"""
Coding Interview Routes
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Body
from typing import Any, Dict, List, Optional
from supabase import Client
from app.db.client import get_supabase_client
from app.routers.interview_utils import (
    build_resume_context_from_profile,
    build_context_from_cache,
    merge_resume_context,
    log_interview_transcript
)
from app.services.coding_interview_engine import coding_interview_engine
from app.config.settings import settings
from app.schemas.interview import (
    CodingInterviewStartResponse,
    CodingNextQuestionResponse,
    CodingResultsResponse,
    CodeRunResponse,
    InterviewEndResponse
)
from app.utils.rate_limiter import check_rate_limit, rate_limit_by_session_id
from app.utils.request_validator import validate_request_size
from fastapi import Request
import logging
import json
import subprocess
import tempfile
import time
import shutil
import re
import sqlite3
import sys
import os
import ast
import httpx

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/coding", tags=["coding-interview"])



@router.post("/start", response_model=CodingInterviewStartResponse)
async def start_coding_interview(
    http_request: Request,
    request_body: Dict[str, Any] = Body(...),
    supabase: Client = Depends(get_supabase_client),
    _: None = Depends(validate_request_size)
):
    """
    Start a new coding interview session
    Returns the first coding question based on resume skills
    """
    try:
        user_id = request_body.get("user_id")
        
        if not user_id:
            raise HTTPException(status_code=400, detail="user_id is required")
        
        # Validate user_id format: alphanumeric, hyphen, underscore only
        if not re.match(r'^[a-zA-Z0-9_-]+$', user_id):
            raise HTTPException(status_code=400, detail="Invalid user_id format")
        
        # Check rate limit
        check_rate_limit(user_id)
        
        # Build resume-aware context
        resume_skills: List[str] = []
        resume_context: Dict[str, Any] = {
            "skills": [],
            "projects": [],
            "experience_level": None,
            "keywords": {},
            "domains": []
        }
        profile_response = None
        
        # user_id is now TEXT (slugified name), not UUID - no validation needed
        
        # Get user profile (required)
        profile = None
        try:
            profile_response = supabase.table("user_profiles").select("*").eq("user_id", user_id).execute()
            profile = profile_response.data[0] if profile_response.data else None
            if not profile:
                raise HTTPException(
                    status_code=404,
                    detail=f"User profile not found for user_id: {user_id}. Please ensure the user exists in user_profiles table."
                )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Error fetching user profile: {str(e)}"
            )
        
        if profile:
            profile_context = build_resume_context_from_profile(profile, supabase)
            resume_context = merge_resume_context(resume_context, profile_context)
            resume_skills = resume_context.get("skills", []) or []
        else:
            try:
                from app.routers.profile import resume_analysis_cache
                cached_data = None
                for cached_info in resume_analysis_cache.values():
                    if cached_info.get("user_id") == user_id:
                        cached_data = cached_info
                        break
                if cached_data:
                    cache_context = build_context_from_cache(cached_data)
                    resume_context = merge_resume_context(resume_context, cache_context)
                    resume_skills = resume_context.get("skills", []) or []
            except Exception:
                pass
        
        if not resume_skills:
            resume_skills = resume_context.get("skills", []) or []
            if not resume_skills:
                resume_skills = []
        
        # If no skills found, require user to upload resume
        if not resume_skills or len(resume_skills) == 0:
            raise HTTPException(
                status_code=400,
                detail="No skills found in resume. Please upload a resume with technical skills first."
            )
        
        # Fetch past performance for adaptive difficulty
        past_performance = None
        if user_id:
            try:
                past_results = supabase.table("coding_round").select("*").eq("user_id", user_id).order("created_at", desc=True).limit(20).execute()
                if past_results.data and len(past_results.data) > 0:
                    total_past = len(past_results.data)
                    correct_past = sum(1 for r in past_results.data if r.get("correctness", False))
                    total_score_past = sum(r.get("final_score", 0) for r in past_results.data)
                    past_performance = {
                        "accuracy": (correct_past / total_past * 100) if total_past > 0 else 0,
                        "average_score": (total_score_past / total_past) if total_past > 0 else 0,
                        "total_sessions": total_past
                    }
            except Exception as e:
                logger.warning(f"[CODING][START] Could not fetch past performance: {str(e)}")
        
        # Initialize coding session
        session_data = coding_interview_engine.start_coding_session(
            user_id=user_id,
            resume_skills=resume_skills,
            resume_context=resume_context,
            experience_level=resume_context.get("experience_level") or (profile.get("experience_level") if profile else None)
        )
        
        # Add past performance to session data for adaptive difficulty
        if past_performance:
            session_data["past_performance"] = past_performance
        
        # Generate first coding question
        first_question = coding_interview_engine.generate_coding_question(
            session_data,
            []
        )
        
        # Create session in database
        session_id = None
        try:
            db_session_data = {
                "user_id": user_id,  # TEXT (slugified name)
                "interview_type": "coding",  # New schema: use interview_type
                "role": "Coding Interview",  # Keep for backward compatibility
                "experience_level": (profile.get("experience_level", "Intermediate") if profile else "Intermediate"),
                "skills": resume_skills,
                "session_status": "active"
            }
            session_response = supabase.table("interview_sessions").insert(db_session_data).execute()
            if session_response.data and len(session_response.data) > 0:
                session_id = session_response.data[0]["id"]
            else:
                raise HTTPException(status_code=500, detail="Failed to create interview session")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Error creating interview session: {str(e)}"
            )

        # Store first coding question in coding_round table (new schema)
        question_text = first_question.get("problem") or first_question.get("question") or ""
        if session_id:
            try:
                question_db_data = {
                    "user_id": user_id,
                    "session_id": session_id,
                    "question_number": 1,
                    "question_text": question_text,
                    "difficulty_level": first_question.get("difficulty", "Medium"),
                    "programming_language": "python",  # Default, can be changed by user
                    "user_code": "",  # Placeholder - will be updated when user submits solution
                    "execution_output": None,
                    "execution_time": None,
                    "test_cases_passed": 0,
                    "total_test_cases": 0,
                    "correct_solution": None,
                    "correctness": False,
                    "final_score": 0,
                    "ai_feedback": None
                }
                supabase.table("coding_round").insert(question_db_data).execute()
            except Exception as e:
                logger.warning(f"[CODING][START] Could not store first question: {str(e)}")

        await log_interview_transcript(
            supabase,
            session_id,
            "coding",
            question_text,
            None
        )

        # Add question_number to question object
        first_question["question_number"] = 1
        
        CODING_TOTAL_QUESTIONS = 5  # Constant for coding interview total questions
        
        return {
            "session_id": session_id,
            "question": first_question,
            "question_number": 1,
            "total_questions": CODING_TOTAL_QUESTIONS,
            "skills": resume_skills,
            "interview_completed": False,
            "user_id": user_id  # Include user_id in response
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error starting coding interview: {str(e)}")


async def store_coding_result(
    supabase: Client,
    user_id: str,
    session_id: str,
    question_number: int,
    question_text: str,
    user_code: str,
    programming_language: str,
    difficulty_level: Optional[str] = None,
    execution_output: Optional[str] = None,
    correctness: bool = False,
    ai_feedback: Optional[str] = None,
    final_score: int = 0,
    execution_time: Optional[float] = None,
    test_cases_passed: int = 0,
    total_test_cases: int = 0,
    correct_solution: Optional[str] = None
) -> None:
    """
    Store coding interview result in Supabase
    """
    if not supabase:
        return
    
    try:
        # Validate required fields before storing
        if not user_id or not user_id.strip():
            raise ValueError("user_id is required and cannot be empty")
        if not session_id or not session_id.strip():
            raise ValueError("session_id is required and cannot be empty")
        if question_number is None or question_number < 1:
            raise ValueError(f"question_number must be a positive integer, got: {question_number}")
        if not question_text or not question_text.strip():
            raise ValueError("question_text is required and cannot be empty")
        if not user_code or not user_code.strip():
            raise ValueError("user_code is required and cannot be empty")
        
        # Ensure None values are converted to empty strings for text fields
        # This prevents database issues and ensures frontend receives consistent data
        result_data = {
            "user_id": str(user_id).strip(),
            "session_id": str(session_id).strip(),
            "question_number": int(question_number),
            "question_text": str(question_text).strip() if question_text else "",
            "user_code": str(user_code).strip() if user_code else "",
            "programming_language": str(programming_language).strip() if programming_language else "python",
            "difficulty_level": str(difficulty_level).strip() if difficulty_level else None,
            "execution_output": str(execution_output).strip() if execution_output is not None else "",
            "correctness": bool(correctness),
            "ai_feedback": str(ai_feedback).strip() if ai_feedback is not None else "",
            "final_score": int(final_score) if final_score is not None else 0,
            "execution_time": float(execution_time) if execution_time is not None else None,
            "test_cases_passed": int(test_cases_passed) if test_cases_passed is not None else 0,
            "total_test_cases": int(total_test_cases) if total_test_cases is not None else 0,
            "correct_solution": str(correct_solution).strip() if correct_solution is not None else ""
        }
        
        # Validate data types and constraints
        if result_data["final_score"] < 0 or result_data["final_score"] > 100:
            logger.warning(f"[CODING][STORE] final_score out of range (0-100): {result_data['final_score']}, clamping to valid range")
            result_data["final_score"] = max(0, min(100, result_data["final_score"]))
        
        if result_data["test_cases_passed"] < 0:
            result_data["test_cases_passed"] = 0
        if result_data["total_test_cases"] < 0:
            result_data["total_test_cases"] = 0
        if result_data["test_cases_passed"] > result_data["total_test_cases"]:
            logger.warning(f"[CODING][STORE] test_cases_passed ({result_data['test_cases_passed']}) > total_test_cases ({result_data['total_test_cases']}), clamping")
            result_data["test_cases_passed"] = result_data["total_test_cases"]
        
        # Log what we're storing for debugging
        logger.info(f"[CODING][STORE] ========== Preparing to Store Coding Result ==========")
        logger.info(f"[CODING][STORE] Session ID: {session_id}")
        logger.info(f"[CODING][STORE] Question Number: {question_number}")
        logger.info(f"[CODING][STORE] User ID: {user_id}")
        logger.info(f"[CODING][STORE] User code length: {len(result_data['user_code'])} chars")
        logger.info(f"[CODING][STORE] Execution output length: {len(result_data['execution_output'])} chars")
        logger.info(f"[CODING][STORE] AI feedback length: {len(result_data['ai_feedback'])} chars")
        logger.info(f"[CODING][STORE] Correct solution length: {len(result_data['correct_solution'])} chars")
        logger.info(f"[CODING][STORE] Correctness: {result_data['correctness']}")
        logger.info(f"[CODING][STORE] Final score: {result_data['final_score']}")
        logger.info(f"[CODING][STORE] Test cases: {result_data['test_cases_passed']}/{result_data['total_test_cases']}")
        
        # Check if row already exists (question was stored when it was asked)
        logger.info(f"[CODING][STORE] Checking for existing row: session_id={session_id}, question_number={question_number}")
        existing_row = supabase.table("coding_round").select("id, user_code, execution_output, ai_feedback, correctness").eq("session_id", session_id).eq("question_number", question_number).execute()
        
        if existing_row.data and len(existing_row.data) > 0:
            # Update existing row with user's solution and evaluation
            existing_data = existing_row.data[0]
            logger.info(f"[CODING][STORE] Found existing row (id: {existing_data.get('id')}) - Current: user_code={bool(existing_data.get('user_code'))}, execution_output={bool(existing_data.get('execution_output'))}, ai_feedback={bool(existing_data.get('ai_feedback'))}, correctness={existing_data.get('correctness')}")
            logger.info(f"[CODING][STORE] Updating with: user_code length={len(result_data.get('user_code', ''))}, execution_output length={len(result_data.get('execution_output', ''))}, ai_feedback length={len(result_data.get('ai_feedback', ''))}, correctness={result_data.get('correctness')}")
            
            # Use update with explicit error handling
            logger.info(f"[CODING][STORE] Executing UPDATE query for session {session_id}, question {question_number}")
            logger.info(f"[CODING][STORE] Update data keys: {list(result_data.keys())}")
            logger.info(f"[CODING][STORE] Update data preview: user_id={result_data.get('user_id')}, session_id={result_data.get('session_id')}, question_number={result_data.get('question_number')}, user_code_len={len(result_data.get('user_code', ''))}, execution_output_len={len(result_data.get('execution_output', ''))}, ai_feedback_len={len(result_data.get('ai_feedback', ''))}, correctness={result_data.get('correctness')}")
            
            try:
                update_response = supabase.table("coding_round").update(result_data).eq("session_id", session_id).eq("question_number", question_number).execute()
            except Exception as update_error:
                error_msg = f"Update query failed for session {session_id}, question {question_number}: {str(update_error)}"
                logger.error(f"[CODING][STORE] ✗ {error_msg}")
                logger.error(f"[CODING][STORE] Error type: {type(update_error).__name__}")
                import traceback
                logger.error(f"[CODING][STORE] Traceback: {traceback.format_exc()}")
                # Try insert as fallback
                logger.info(f"[CODING][STORE] Attempting fallback INSERT...")
                try:
                    insert_response = supabase.table("coding_round").insert(result_data).execute()
                    if not insert_response.data:
                        raise Exception(f"Both update and insert failed. Update error: {error_msg}, Insert returned no data")
                    else:
                        inserted_id = insert_response.data[0].get('id', 'unknown')
                        logger.info(f"[CODING][STORE] ✓ Fallback insert succeeded with id: {inserted_id}")
                        return  # Success via insert
                except Exception as insert_error:
                    combined_error = f"Both update and insert failed. Update: {error_msg}, Insert: {str(insert_error)}"
                    logger.error(f"[CODING][STORE] ✗ {combined_error}")
                    raise Exception(combined_error) from insert_error
            
            # Check if update returned data
            if not update_response.data:
                error_msg = f"Update returned no data for session {session_id}, question {question_number}"
                logger.error(f"[CODING][STORE] ✗ {error_msg}")
                logger.error(f"[CODING][STORE] Attempting fallback INSERT...")
                # Try insert as fallback
                try:
                    insert_response = supabase.table("coding_round").insert(result_data).execute()
                    if not insert_response.data:
                        raise Exception(f"Both update and insert failed. Update: {error_msg}, Insert returned no data")
                    else:
                        inserted_id = insert_response.data[0].get('id', 'unknown')
                        logger.info(f"[CODING][STORE] ✓ Fallback insert succeeded with id: {inserted_id}")
                        return  # Success via insert
                except Exception as insert_error:
                    combined_error = f"Both update and insert failed. Update: {error_msg}, Insert: {str(insert_error)}"
                    logger.error(f"[CODING][STORE] ✗ {combined_error}")
                    raise Exception(combined_error) from insert_error
            
            # Update succeeded - get the updated row ID
            updated_id = update_response.data[0].get('id') if update_response.data else None
            logger.info(f"[CODING][STORE] ✓ Update query returned data (id: {updated_id})")
            
            # CRITICAL: Verify the update actually persisted
            # Use a simpler verification approach - check that row exists and has key fields
            try:
                logger.info(f"[CODING][STORE] Verifying update persistence...")
                # First, verify row exists
                if updated_id:
                    verify_response = supabase.table("coding_round").select("*").eq("id", updated_id).execute()
                else:
                    verify_response = supabase.table("coding_round").select("*").eq("session_id", session_id).eq("question_number", question_number).execute()
                
                if verify_response.data and len(verify_response.data) > 0:
                    verified = verify_response.data[0]
                    
                    # Verify critical required fields (these should never be NULL)
                    validation_errors = []
                    
                    # Check required fields
                    if not verified.get('user_id'):
                        validation_errors.append("user_id is NULL or empty")
                    if not verified.get('session_id'):
                        validation_errors.append("session_id is NULL or empty")
                    if verified.get('question_number') is None:
                        validation_errors.append("question_number is NULL")
                    if not verified.get('question_text'):
                        validation_errors.append("question_text is NULL or empty")
                    if not verified.get('user_code'):
                        validation_errors.append("user_code is NULL or empty")
                    if verified.get('correctness') is None:
                        validation_errors.append("correctness is NULL")
                    if verified.get('final_score') is None:
                        validation_errors.append("final_score is NULL")
                    if verified.get('test_cases_passed') is None:
                        validation_errors.append("test_cases_passed is NULL")
                    if verified.get('total_test_cases') is None:
                        validation_errors.append("total_test_cases is NULL")
                    if not verified.get('created_at'):
                        validation_errors.append("created_at is NULL")
                    
                    if validation_errors:
                        # Log what we actually got for debugging
                        logger.error(f"[CODING][STORE] ✗ Validation failed. Retrieved row keys: {list(verified.keys())}")
                        logger.error(f"[CODING][STORE] ✗ Retrieved values: user_id={verified.get('user_id')}, session_id={verified.get('session_id')}, question_number={verified.get('question_number')}, user_code_len={len(str(verified.get('user_code', '')))}, correctness={verified.get('correctness')}")
                        error_msg = f"Validation failed after update: {', '.join(validation_errors)}"
                        logger.error(f"[CODING][STORE] ✗ {error_msg}")
                        # Don't raise - this might be an RLS issue, log and continue
                        logger.warning(f"[CODING][STORE] ⚠️ Continuing despite validation errors - may be RLS field filtering issue")
                    else:
                        logger.info(f"[CODING][STORE] ✓ Verification successful - all required fields present")
                        logger.info(f"[CODING][STORE]   user_id: {verified.get('user_id')}")
                        logger.info(f"[CODING][STORE]   session_id: {verified.get('session_id')}")
                        logger.info(f"[CODING][STORE]   question_number: {verified.get('question_number')}")
                        logger.info(f"[CODING][STORE]   question_text length: {len(str(verified.get('question_text', '')))}")
                        logger.info(f"[CODING][STORE]   user_code length: {len(str(verified.get('user_code', '')))}")
                        logger.info(f"[CODING][STORE]   execution_output length: {len(str(verified.get('execution_output', '')))}")
                        logger.info(f"[CODING][STORE]   ai_feedback length: {len(str(verified.get('ai_feedback', '')))}")
                        logger.info(f"[CODING][STORE]   correctness: {verified.get('correctness')}")
                        logger.info(f"[CODING][STORE]   final_score: {verified.get('final_score')}")
                        logger.info(f"[CODING][STORE]   created_at: {verified.get('created_at')}")
                    
                    # Warn about optional fields that are empty (but not required)
                    if not verified.get('execution_output'):
                        logger.warning(f"[CODING][STORE] ⚠️ WARNING: execution_output is empty (optional field)")
                    if not verified.get('ai_feedback'):
                        logger.warning(f"[CODING][STORE] ⚠️ WARNING: ai_feedback is empty (should have feedback)")
                    if not verified.get('correct_solution'):
                        logger.warning(f"[CODING][STORE] ⚠️ WARNING: correct_solution is empty (optional field)")
                else:
                    logger.error(f"[CODING][STORE] ✗ Verification failed: Row not found after update!")
                    raise Exception(f"Update verification failed: Row not found for session {session_id}, question {question_number}")
            except ValueError as verify_error:
                # This is our validation error - log but don't fail completely (might be RLS issue)
                logger.warning(f"[CODING][STORE] ⚠️ Validation warning (may be RLS related): {str(verify_error)}")
                # Continue - the update likely succeeded, verification might have RLS issues
            except Exception as verify_error:
                logger.error(f"[CODING][STORE] ✗ Verification query failed: {str(verify_error)}")
                import traceback
                logger.error(f"[CODING][STORE] Verification traceback: {traceback.format_exc()}")
                # Try a simpler check - just verify row exists
                try:
                    simple_check = supabase.table("coding_round").select("id").eq("session_id", session_id).eq("question_number", question_number).execute()
                    if simple_check.data:
                        logger.warning(f"[CODING][STORE] ⚠️ Row exists but detailed verification failed. This may be an RLS issue. Update likely succeeded.")
                        # Continue - row exists, update probably succeeded
                    else:
                        raise Exception(f"Update verification failed: Row not found. Error: {str(verify_error)}") from verify_error
                except Exception:
                    # If even simple check fails, log warning but continue
                    logger.warning(f"[CODING][STORE] ⚠️ Could not verify update, but update query succeeded. Continuing.")
        else:
            # Insert new row if question wasn't stored earlier (fallback)
            logger.info(f"[CODING][STORE] No existing row found - Inserting new coding result for session {session_id}, question {question_number}")
            logger.info(f"[CODING][STORE] Insert data: user_code length={len(result_data.get('user_code', ''))}, execution_output length={len(result_data.get('execution_output', ''))}, ai_feedback length={len(result_data.get('ai_feedback', ''))}, correctness={result_data.get('correctness')}")
            
            try:
                insert_response = supabase.table("coding_round").insert(result_data).execute()
            except Exception as insert_error:
                error_msg = f"Insert query failed for session {session_id}, question {question_number}: {str(insert_error)}"
                logger.error(f"[CODING][STORE] ✗ {error_msg}")
                logger.error(f"[CODING][STORE] Error type: {type(insert_error).__name__}")
                import traceback
                logger.error(f"[CODING][STORE] Traceback: {traceback.format_exc()}")
                logger.error(f"[CODING][STORE] Result data keys: {list(result_data.keys())}")
                logger.error(f"[CODING][STORE] Result data sample: user_id={result_data.get('user_id')}, session_id={result_data.get('session_id')}, question_number={result_data.get('question_number')}")
                raise Exception(error_msg) from insert_error
            
            if not insert_response.data:
                error_msg = f"Insert returned no data for session {session_id}, question {question_number}"
                logger.error(f"[CODING][STORE] ✗ {error_msg}")
                logger.error(f"[CODING][STORE] Result data keys: {list(result_data.keys())}")
                logger.error(f"[CODING][STORE] Result data sample: user_id={result_data.get('user_id')}, session_id={result_data.get('session_id')}, question_number={result_data.get('question_number')}")
                raise Exception(error_msg)
            else:
                inserted_id = insert_response.data[0].get('id', 'unknown')
                inserted_data = insert_response.data[0]
                logger.info(f"[CODING][STORE] ✓ Successfully stored coding result with id: {inserted_id}")
                logger.info(f"[CODING][STORE] Inserted values: user_code={bool(inserted_data.get('user_code'))}, execution_output={bool(inserted_data.get('execution_output'))}, ai_feedback={bool(inserted_data.get('ai_feedback'))}, correctness={inserted_data.get('correctness')}")
                
                # Verify the insert actually persisted - check ALL fields
                try:
                    logger.info(f"[CODING][STORE] Verifying insert persistence...")
                    verify_response = supabase.table("coding_round").select("user_id, session_id, question_number, question_text, user_code, execution_output, ai_feedback, correctness, final_score, execution_time, test_cases_passed, total_test_cases, correct_solution, created_at").eq("id", inserted_id).execute()
                    if verify_response.data and len(verify_response.data) > 0:
                        verified = verify_response.data[0]
                        
                        # Verify all fields
                        validation_errors = []
                        if not verified.get('user_id'):
                            validation_errors.append("user_id is NULL or empty")
                        if not verified.get('session_id'):
                            validation_errors.append("session_id is NULL or empty")
                        if not verified.get('question_number'):
                            validation_errors.append("question_number is NULL")
                        if not verified.get('question_text'):
                            validation_errors.append("question_text is NULL or empty")
                        if not verified.get('user_code'):
                            validation_errors.append("user_code is NULL or empty")
                        if verified.get('correctness') is None:
                            validation_errors.append("correctness is NULL")
                        if verified.get('final_score') is None:
                            validation_errors.append("final_score is NULL")
                        if verified.get('test_cases_passed') is None:
                            validation_errors.append("test_cases_passed is NULL")
                        if verified.get('total_test_cases') is None:
                            validation_errors.append("total_test_cases is NULL")
                        if not verified.get('created_at'):
                            validation_errors.append("created_at is NULL")
                        
                        if validation_errors:
                            error_msg = f"Validation failed after insert: {', '.join(validation_errors)}"
                            logger.error(f"[CODING][STORE] ✗ {error_msg}")
                            raise ValueError(error_msg)
                        
                        logger.info(f"[CODING][STORE] ✓ Insert verification successful:")
                        logger.info(f"[CODING][STORE]   user_id: {verified.get('user_id')}")
                        logger.info(f"[CODING][STORE]   session_id: {verified.get('session_id')}")
                        logger.info(f"[CODING][STORE]   question_number: {verified.get('question_number')}")
                        logger.info(f"[CODING][STORE]   question_text length: {len(verified.get('question_text', '') or '')}")
                        logger.info(f"[CODING][STORE]   user_code length: {len(verified.get('user_code', '') or '')}")
                        logger.info(f"[CODING][STORE]   execution_output length: {len(verified.get('execution_output', '') or '')}")
                        logger.info(f"[CODING][STORE]   ai_feedback length: {len(verified.get('ai_feedback', '') or '')}")
                        logger.info(f"[CODING][STORE]   correctness: {verified.get('correctness')}")
                        logger.info(f"[CODING][STORE]   final_score: {verified.get('final_score')}")
                        logger.info(f"[CODING][STORE]   created_at: {verified.get('created_at')}")
                    else:
                        logger.error(f"[CODING][STORE] ✗ Insert verification failed: Row not found after insert!")
                except Exception as verify_error:
                    logger.error(f"[CODING][STORE] ✗ Insert verification query failed: {str(verify_error)}")
                    import traceback
                    logger.error(f"[CODING][STORE] Insert verification traceback: {traceback.format_exc()}")
                    # CRITICAL: If verification fails, we can't confirm data was saved
                    # Raise exception to ensure caller knows storage may have failed
                    raise Exception(f"Insert verification failed: Could not confirm data persistence. Error: {str(verify_error)}") from verify_error
            
    except Exception as e:
        # Log error with full details
        import logging
        import traceback
        error_details = {
            "error": str(e),
            "error_type": type(e).__name__,
            "traceback": traceback.format_exc(),
            "session_id": session_id,
            "question_number": question_number,
            "user_id": user_id,
            "result_data_keys": list(result_data.keys()) if 'result_data' in locals() else 'N/A'
        }
        logger.error(f"✗ ERROR storing coding result: {error_details}")
        
        # Try to provide helpful error message
        error_str = str(e).lower()
        if "permission" in error_str or "policy" in error_str or "rls" in error_str:
            logger.error("This looks like an RLS (Row Level Security) policy issue. Check Supabase policies.")
            logger.error("Ensure the service role key is being used for database operations.")
        elif "column" in error_str and "does not exist" in error_str:
            logger.error("This looks like a schema mismatch. Verify table structure in Supabase.")
        elif "violates" in error_str and "constraint" in error_str:
            logger.error("This looks like a constraint violation. Check data types and constraints.")
        
        # CRITICAL: Re-raise the exception so calling code knows storage failed
        logger.error("Re-raising exception to prevent silent failure...")
        raise  # Re-raise to let calling code handle it


def wrap_python_function_code(user_code: str, test_input: str) -> str:
    """
    Automatically wrap Python function definitions with a test harness.
    
    Detects if user code defines functions and wraps it to:
    1. Parse test_input appropriately
    2. Call the main function with parsed input
    3. Print the result
    
    Returns wrapped code if functions detected, original code otherwise.
    """
    if not user_code or not user_code.strip():
        return user_code
    
    try:
        # Parse the code to detect function definitions
        tree = ast.parse(user_code)
        
        # Find all top-level function definitions (only check tree.body, not nested)
        functions = []
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                # Extract argument names (ignore 'self' for class methods)
                args = [arg.arg for arg in node.args.args if arg.arg != 'self']
                functions.append({
                    'name': node.name,
                    'args': args,
                    'line': node.lineno,
                    'arg_count': len(args)
                })
        
        # If no functions found, return original code (script-style)
        if not functions:
            return user_code
        
        # Select the main function:
        # 1. Prefer functions that are not private (don't start with _)
        # 2. Prefer the first function if all are private
        # 3. Use the first public function found (most likely to be the main solution)
        main_function = None
        public_functions = [f for f in functions if not f['name'].startswith('_')]
        
        if public_functions:
            # Use the first public function (first defined in code)
            main_function = public_functions[0]
        else:
            # All functions are private, use the first one
            main_function = functions[0]
        
        if not main_function:
            return user_code
        
        func_name = main_function['name']
        func_args = main_function['args']
        
        # Generate test harness code
        # Parse test_input intelligently
        harness_code = f"""
# Auto-generated test harness
import sys
import json
import ast as ast_module

# Read test input from stdin
test_input_str = sys.stdin.read().strip()

# Parse test input based on function parameters
# Try multiple parsing strategies to handle different input formats
parsed_input = None

# Strategy 1: Try JSON parsing (handles arrays, objects, strings, numbers)
try:
    parsed_input = json.loads(test_input_str)
except json.JSONDecodeError:
    pass

# Strategy 2: Try Python literal_eval (handles lists, tuples, dicts, numbers, strings)
if parsed_input is None:
    try:
        parsed_input = ast_module.literal_eval(test_input_str)
    except (ValueError, SyntaxError):
        pass

# Strategy 3: Try parsing as space/comma-separated values
if parsed_input is None and test_input_str:
    # Remove brackets if present and split
    cleaned = test_input_str.strip()
    if cleaned.startswith('[') and cleaned.endswith(']'):
        cleaned = cleaned[1:-1].strip()
    elif cleaned.startswith('(') and cleaned.endswith(')'):
        cleaned = cleaned[1:-1].strip()
    
    # Split by comma or space
    parts = [p.strip() for p in cleaned.replace(',', ' ').split() if p.strip()]
    
    if len(parts) == 1:
        # Single value - try to convert to number
        try:
            parsed_input = int(parts[0])
        except ValueError:
            try:
                parsed_input = float(parts[0])
            except ValueError:
                parsed_input = parts[0]
    elif len(parts) > 1:
        # Multiple values - try to convert to list of numbers
        try:
            parsed_input = [int(x) for x in parts]
        except ValueError:
            try:
                parsed_input = [float(x) for x in parts]
            except ValueError:
                parsed_input = parts

# Strategy 4: Fallback to string
if parsed_input is None:
    parsed_input = test_input_str

# Call the user's function
# Handle different function signatures
"""
        
        # Generate function call based on number of parameters
        if len(func_args) == 0:
            # No parameters
            harness_code += f"result = {func_name}()\n"
        elif len(func_args) == 1:
            # Single parameter - pass parsed_input directly
            harness_code += f"result = {func_name}(parsed_input)\n"
        else:
            # Multiple parameters - try to unpack if parsed_input is iterable
            harness_code += f"""# Multiple parameters detected
if isinstance(parsed_input, (list, tuple)) and len(parsed_input) == {len(func_args)}:
    result = {func_name}(*parsed_input)
elif isinstance(parsed_input, dict) and len(parsed_input) == {len(func_args)}:
    result = {func_name}(**parsed_input)
else:
    # Fallback: pass as first argument
    result = {func_name}(parsed_input)
"""
        
        harness_code += """
# Print the result
print(result)
"""
        
        # Combine user code with harness
        wrapped_code = user_code + "\n" + harness_code
        
        logger.info(f"[WRAP] ✅ Detected function '{func_name}' with args {func_args}")
        logger.info(f"[WRAP] Test input: {repr(test_input)}")
        logger.info(f"[WRAP] Generated harness code:\n{harness_code}")
        logger.info(f"[WRAP] Full wrapped code length: {len(wrapped_code)} chars")
        logger.debug(f"[WRAP] Full wrapped code:\n{wrapped_code}")
        return wrapped_code
        
    except SyntaxError as e:
        # Code has syntax errors, can't parse - return original
        logger.warning(f"[WRAP] Could not parse code for function detection: {str(e)}")
        return user_code
    except Exception as e:
        # Any other error - return original code
        logger.warning(f"[WRAP] Error detecting functions: {str(e)}")
        return user_code


async def evaluate_coding_solution(
    question_text: str,
    user_code: str,
    programming_language: str,
    difficulty_level: Optional[str] = None,
    question_data: Optional[Dict[str, Any]] = None,
    sql_setup: Optional[str] = None
) -> Dict[str, Any]:
    """
    Evaluate a coding solution using LLM-based evaluation
    Uses GPT-4o for comprehensive code analysis and correctness determination
    """
    result = {
        "correctness": False,
        "score": 0,
        "feedback": "",
        "execution_output": "",
        "execution_time": None,
        "test_cases_passed": 0,
        "total_test_cases": 0,
        "correct_solution": ""
    }
    
    # Extract test cases and examples from question_data
    test_cases = []
    examples = []
    if question_data:
        test_cases = question_data.get("test_cases", []) or []
        examples = question_data.get("examples", []) or []
        if not test_cases and examples:
            test_cases = examples
    
    # Execute the code to get real output
    execution_result = None
    execution_outputs = []
    
    try:
        # First, try executing without input to see if code runs
        execution_result = await execute_code_safely(
            user_code, 
            programming_language.lower(), 
            "",
            sql_setup if programming_language.lower() == "sql" else ""
        )
        
        # Format execution output
        if execution_result.get("error"):
            error_msg = execution_result.get('error', 'Unknown error')
            result["execution_output"] = f"Execution Error:\n{error_msg}"
            execution_outputs.append(f"Error: {error_msg}")
            # Only mark as incorrect for actual syntax/compilation errors, not for missing compilers
            error_lower = error_msg.lower()
            # Check if it's a compiler not found error (should use fallback, but if fallback also fails, don't penalize)
            is_compiler_not_found = any(keyword in error_lower for keyword in ["not found", "compiler not found", "runtime not found", "jdk", "gcc", "g++"])
            # Only mark as incorrect for actual code errors, not infrastructure issues
            if any(keyword in error_lower for keyword in ["syntax", "compile", "parse", "indentation", "invalid syntax"]) and not is_compiler_not_found:
                result["correctness"] = False
                result["score"] = 0
            # If compiler not found and fallback also failed, let LLM evaluate the code logic instead
            elif is_compiler_not_found:
                logger.info("[EVAL] Compiler not found - will rely on LLM-based code analysis for evaluation")
                execution_outputs.append("Note: Code execution unavailable, using AI-based analysis")
        else:
            output = execution_result.get("output", "")
            if output:
                result["execution_output"] = output
                execution_outputs.append(f"Output: {output}")
            else:
                result["execution_output"] = "Code executed successfully but produced no output.\nThis is normal for function definitions that don't print anything."
                execution_outputs.append("No output (code defines functions/classes)")
        
        result["execution_time"] = execution_result.get("execution_time")
        
    except Exception as e:
        logger.warning(f"Error executing code for evaluation: {str(e)}")
        result["execution_output"] = f"Execution error: {str(e)}"
        execution_outputs.append(f"Execution error: {str(e)}")
    
    # Run test cases and collect outputs for LLM analysis
    test_results = []
    if test_cases:
        for i, test_case in enumerate(test_cases):
            # Get test input - ensure it's a string for stdin
            raw_test_input = test_case.get("input", "")
            # Convert to string if it's not already (handles list/dict inputs)
            if isinstance(raw_test_input, (list, dict)):
                import json
                test_input = json.dumps(raw_test_input)
            else:
                test_input = str(raw_test_input)
            
            expected_output = str(test_case.get("output", "")).strip()
            
            logger.info(f"[EVAL] Test case {i+1} raw input: {repr(raw_test_input)}, stringified: {repr(test_input)}")
            
            try:
                # ✅ FIX: Auto-wrap function definitions for Python code
                code_to_execute = user_code
                was_wrapped = False
                if programming_language.lower() == "python":
                    original_code = user_code
                    code_to_execute = wrap_python_function_code(user_code, test_input)
                    was_wrapped = (code_to_execute != original_code)
                    logger.info(f"[EVAL] Test case {i+1}: {'✅ USING WRAPPED CODE' if was_wrapped else '⚠️ Using original code (no functions detected)'}")
                    if was_wrapped:
                        logger.info(f"[EVAL] Wrapped code preview (first 500 chars):\n{code_to_execute[:500]}...")
                
                # Execute with test input
                logger.info(f"[EVAL] Executing test case {i+1} with input: {repr(test_input)}")
                test_execution = await execute_code_safely(
                    code_to_execute,
                    programming_language.lower(),
                    test_input,
                    sql_setup if programming_language.lower() == "sql" else ""
                )
                
                # Enhanced output capture and normalization
                raw_output = test_execution.get("output", "")
                raw_error = test_execution.get("error", "")
                return_code = test_execution.get("exit_code", 0)
                
                logger.info(f"[EVAL] Test case {i+1} execution result:")
                logger.info(f"[EVAL]   Return code: {return_code}")
                logger.info(f"[EVAL]   Raw stdout (bytes): {repr(raw_output.encode('utf-8') if raw_output else b'')}")
                logger.info(f"[EVAL]   Raw stdout (string): {repr(raw_output)}")
                logger.info(f"[EVAL]   Raw stderr: {repr(raw_error)}")
                
                actual_output = ""
                if raw_error:
                    actual_output = f"Error: {raw_error}"
                    logger.warning(f"[EVAL] Test case {i+1} had execution error: {raw_error}")
                else:
                    # Enhanced normalization: strip whitespace, handle newlines, normalize for C/C++ output
                    actual_output = str(raw_output).strip() if raw_output else ""
                    # Remove trailing newlines and whitespace
                    actual_output = actual_output.rstrip('\n\r').rstrip()
                    # Normalize multiple consecutive spaces/tabs to single space (preserve newlines for multi-line output)
                    actual_output = re.sub(r'[ \t]+', ' ', actual_output)  # Multiple spaces/tabs to single space
                    # Normalize multiple consecutive newlines to single newline
                    actual_output = re.sub(r'\n\s*\n+', '\n', actual_output)
                    actual_output = actual_output.strip()
                    logger.info(f"[EVAL]   Normalized actual_output: {repr(actual_output)}")
                
                # Enhanced comparison with normalization
                expected_normalized = str(expected_output).strip().rstrip('\n\r').rstrip()
                # Normalize expected output similarly (remove extra whitespace but preserve structure)
                expected_normalized = re.sub(r'[ \t]+', ' ', expected_normalized)  # Multiple spaces/tabs to single space
                expected_normalized = re.sub(r'\n\s*\n+', '\n', expected_normalized)  # Multiple newlines to single
                expected_normalized = expected_normalized.strip()
                actual_normalized = actual_output
                
                # Try numeric comparison if both look numeric
                is_match = False
                match_reason = ""
                
                # Exact string match
                if actual_normalized == expected_normalized:
                    is_match = True
                    match_reason = "exact string match"
                else:
                    # Try numeric comparison
                    try:
                        actual_num = float(actual_normalized)
                        expected_num = float(expected_normalized)
                        if abs(actual_num - expected_num) < 1e-9:  # Float tolerance
                            is_match = True
                            match_reason = f"numeric match ({actual_num} == {expected_num})"
                    except (ValueError, TypeError):
                        pass
                    
                    # Try JSON/literal comparison for structured data
                    if not is_match:
                        try:
                            import json
                            actual_parsed = json.loads(actual_normalized)
                            expected_parsed = json.loads(expected_normalized)
                            if actual_parsed == expected_parsed:
                                is_match = True
                                match_reason = "JSON parsed match"
                        except (json.JSONDecodeError, ValueError, TypeError):
                            try:
                                actual_parsed = ast.literal_eval(actual_normalized)
                                expected_parsed = ast.literal_eval(expected_normalized)
                                if actual_parsed == expected_parsed:
                                    is_match = True
                                    match_reason = "Python literal parsed match"
                            except (ValueError, SyntaxError):
                                pass
                
                logger.info(f"[EVAL] Test case {i+1} comparison:")
                logger.info(f"[EVAL]   Expected: {repr(expected_normalized)}")
                logger.info(f"[EVAL]   Actual:   {repr(actual_normalized)}")
                logger.info(f"[EVAL]   Match:    {is_match} ({match_reason if is_match else 'NO MATCH'})")
                
                test_results.append({
                    "test_case": i + 1,
                    "input": test_input,
                    "expected": expected_output,
                    "actual": actual_output,
                    "passed": is_match  # Use actual comparison result
                })
                execution_outputs.append(f"Test {i+1} - Input: {test_input}, Expected: {expected_output}, Got: {actual_output}, Passed: {is_match}")
                
            except Exception as e:
                logger.warning(f"Error running test case {i+1}: {str(e)}")
                test_results.append({
                    "test_case": i + 1,
                    "input": test_input,
                    "expected": expected_output,
                    "actual": f"Error: {str(e)}",
                    "passed": False
                })
                execution_outputs.append(f"Test {i+1} - Error: {str(e)}")
    
    # Build comprehensive execution summary
    execution_summary = "\n".join(execution_outputs) if execution_outputs else "No execution data available"
    
    # Use LLM for comprehensive evaluation (primary judge)
    try:
        if settings.openai_api_key:
            from openai import OpenAI
            client = OpenAI(api_key=settings.openai_api_key)
            
            # Try GPT-4o first, fallback to GPT-4, then GPT-3.5
            model = "gpt-4o"
            try:
                # Test if model is available
                client.models.list()
            except:
                model = "gpt-4"
            try:
                if model == "gpt-4":
                    client.models.list()
            except:
                model = "gpt-3.5-turbo"
            
            # Build test case summary
            test_summary = ""
            if test_results:
                test_summary = "\n\nTest Case Execution Results:\n"
                for tr in test_results:
                    test_summary += f"Test Case {tr['test_case']}:\n"
                    test_summary += f"  Input: {tr.get('input', 'N/A')}\n"
                    test_summary += f"  Expected Output: {tr.get('expected', 'N/A')}\n"
                    test_summary += f"  Actual Output: {tr.get('actual', 'N/A')}\n\n"
            
            system_prompt = """You are an expert coding interview evaluator. Your task is to provide SHORT, CLEAN, and PRECISE feedback.

CRITICAL FEEDBACK REQUIREMENTS:
- Keep feedback SHORT and CONCISE (1-3 sentences per section, NOT long paragraphs)
- NO repetition or duplicate explanations
- NO redundant blocks or repeated suggestions
- Be clear, helpful, and user-friendly
- Focus on the most important points only

EVALUATION RULES:
- A solution is CORRECT if it implements the right algorithm/logic, even if output formatting differs
- Be generous with correctness - if the solution works, mark it as TRUE
- For SQL: Check if query logic is correct, not just exact output match

FEEDBACK STRUCTURE (KEEP IT SHORT):
1. Brief correctness explanation (1-2 sentences)
2. 2-3 clear improvement points (one sentence each)
3. One simple logic-building tip (1 sentence)
4. Short motivation message (1-2 sentences)

DO NOT generate:
- Long paragraphs or essays
- Repeated improvement suggestions
- Redundant logic explanations
- Duplicate motivation messages
- Complex analysis sections"""
            
            user_prompt = f"""Evaluate this coding solution and provide SHORT, CLEAN feedback:

QUESTION:
{question_text}

CANDIDATE'S SOLUTION ({programming_language}):
```{programming_language}
{user_code}
```

EXECUTION RESULTS:
{execution_summary}
{test_summary}

DIFFICULTY LEVEL: {difficulty_level or "Medium"}

Provide evaluation in JSON format with SHORT, CONCISE feedback:
{{
  "correctness": true/false,  // TRUE if solution is logically correct, FALSE only if significant errors
  "score": 0-100,  // Score based on correctness, quality, efficiency
  "feedback": "SHORT feedback with ONLY these 4 sections (1-2 sentences each, NO long paragraphs):\n\n✅ CORRECTNESS:\n[1-2 sentences: Brief explanation of whether solution works correctly]\n\n💡 IMPROVEMENTS:\n[2-3 bullet points: Specific, actionable improvements - one sentence each]\n\n🧠 LOGIC TIP:\n[1 sentence: Simple tip for approaching similar problems]\n\n💪 MOTIVATION:\n[1-2 sentences: Encouraging message - celebrate if correct, support if incorrect]",
  "correct_solution": "Complete, clean solution code in {programming_language} with brief comments",
  "test_cases_passed": number,
  "total_test_cases": {len(test_results) if test_results else 0},
  "time_complexity": "O(...) - brief",
  "space_complexity": "O(...) - brief",
  "improvements": ["improvement 1", "improvement 2", "improvement 3"],  // MAX 3 improvements, one sentence each
  "motivation_message": "Short encouraging message (1-2 sentences max)"
}}

CRITICAL: Keep ALL feedback SHORT:
- Feedback field: MAX 10-15 lines total
- Each improvement: ONE sentence only
- Motivation: 1-2 sentences max
- NO long paragraphs, NO repetition, NO duplicate sections"""
            
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3,  # Lower temperature for more consistent evaluation
                response_format={"type": "json_object"},
                timeout=30
            )
            
            ai_response = json.loads(response.choices[0].message.content)
            
            # Parse correctness - handle both boolean and string values
            correctness_value = ai_response.get("correctness", False)
            if isinstance(correctness_value, str):
                # Handle string "true"/"false" from LLM
                correctness_value = correctness_value.lower() in ["true", "1", "yes", "correct"]
            elif isinstance(correctness_value, bool):
                correctness_value = correctness_value
            else:
                # Default to False if unexpected type
                correctness_value = False
            
            # Override correctness if there was a syntax/compilation error (but not for compiler not found errors)
            execution_output_lower = result.get("execution_output", "").lower()
            is_compiler_error = any(keyword in execution_output_lower for keyword in ["not found", "compiler not found", "runtime not found"])
            if execution_output_lower and any(keyword in execution_output_lower for keyword in ["syntax", "compile", "parse", "indentation", "invalid syntax"]) and not is_compiler_error:
                correctness_value = False
                if result.get("score", 0) > 0:
                    result["score"] = 0
            
            # ✅ FIX: Override LLM verdict with actual test case results if test cases are available
            # Test case results are more reliable than LLM opinion
            if test_results and len(test_results) > 0:
                # Count how many test cases actually passed (use the passed field we set during execution)
                passed_count = sum(1 for tr in test_results if tr.get("passed", False))
                total_test_count = len(test_results)
                
                logger.info(f"[EVAL] Test case results summary:")
                for tr in test_results:
                    logger.info(f"[EVAL]   Test {tr['test_case']}: {'✅ PASSED' if tr.get('passed') else '❌ FAILED'} - Expected: {repr(tr.get('expected'))}, Got: {repr(tr.get('actual'))}")
                
                # If ALL test cases pass, solution is definitely correct (override LLM)
                if passed_count == total_test_count and total_test_count > 0:
                    logger.info(f"[EVAL] ✅ All {total_test_count} test cases passed - overriding LLM verdict to CORRECT")
                    correctness_value = True
                    # Also update score if LLM gave low score for correct solution
                    if result.get("score", 0) < 80:
                        result["score"] = 85  # Good score for passing all tests
                # If most test cases pass (>= 80%), also mark as correct
                elif passed_count >= total_test_count * 0.8 and total_test_count > 0:
                    logger.info(f"[EVAL] ✅ {passed_count}/{total_test_count} test cases passed (>=80%) - overriding LLM verdict to CORRECT")
                    correctness_value = True
                    if result.get("score", 0) < 70:
                        result["score"] = int(70 + (passed_count / total_test_count) * 15)  # Score based on pass rate
                # If few test cases pass, trust LLM's verdict (might be logic issues)
                else:
                    logger.info(f"[EVAL] ⚠️ Only {passed_count}/{total_test_count} test cases passed - using LLM verdict")
            else:
                # No test cases available - rely on LLM evaluation
                logger.info(f"[EVAL] No test cases available - using LLM-based evaluation")
                # If LLM says it's correct and there's no execution error (or only compiler not found), trust it
                if correctness_value and not result.get("execution_output", "").startswith("Execution Error"):
                    logger.info(f"[EVAL] LLM marked as correct with no execution errors - accepting verdict")
            
            # Use final correctness value (may have been overridden by test cases)
            result["correctness"] = correctness_value
            
            # Parse score - ensure it's an integer (do this BEFORE score adjustment)
            score_value = ai_response.get("score", 0)
            if isinstance(score_value, (int, float)):
                result["score"] = int(score_value)
            else:
                # Try to parse string score
                try:
                    result["score"] = int(float(str(score_value)))
                except (ValueError, TypeError):
                    # Default score based on correctness
                    result["score"] = 85 if correctness_value else 40
            
            # Ensure score is reasonable based on correctness (do this AFTER parsing)
            if result["correctness"] and result.get("score", 0) < 70:
                # If marked as correct but score is too low, boost it
                logger.info(f"[EVAL] Correctness is True but score is {result.get('score')} - boosting to at least 75")
                result["score"] = max(75, result.get("score", 0))
            elif not result["correctness"] and result.get("score", 0) > 50:
                # If marked as incorrect but score is too high, reduce it
                logger.info(f"[EVAL] Correctness is False but score is {result.get('score')} - reducing to at most 50")
                result["score"] = min(50, result.get("score", 0))
            
            # ✅ FIX: Build SHORT, CLEAN feedback (avoid duplication)
            # Use LLM feedback as primary source (it should already contain all sections)
            llm_feedback = ai_response.get("feedback", "")
            
            # Only add execution status if there's an error (success is implied in feedback)
            if result["execution_output"] and "Error" in result["execution_output"]:
                # Prepend brief error info only if critical
                error_msg = result['execution_output'].split('\n')[0]  # First line only
                result["feedback"] = f"❌ Execution Error: {error_msg}\n\n{llm_feedback}" if llm_feedback else f"❌ Execution Error: {error_msg}"
            else:
                # Use LLM feedback directly (it's already structured and short)
                result["feedback"] = llm_feedback
            
            # Limit improvements to max 3 (already handled in prompt, but ensure here too)
            improvements = ai_response.get("improvements", [])[:3]  # Max 3 improvements
            
            # Get motivation (should be short from prompt)
            motivation = ai_response.get("motivation_message", "")
            
            # Store additional fields for display (keep minimal)
            result["errors_found"] = ai_response.get("errors_found", [])[:2]  # Max 2 errors
            result["bugs_explained"] = ai_response.get("bugs_explained", [])[:2]  # Max 2 bugs
            result["time_complexity"] = ai_response.get("time_complexity", "")
            result["space_complexity"] = ai_response.get("space_complexity", "")
            
            # ✅ FIX: Ensure feedback is never empty (keep it short)
            if not result["feedback"] or result["feedback"].strip() == "":
                if correctness_value:
                    result["feedback"] = "✅ CORRECTNESS:\nYour solution works correctly and handles the main requirement efficiently.\n\n💪 MOTIVATION:\nGreat job! Keep practicing to improve consistency."
                else:
                    result["feedback"] = "✅ CORRECTNESS:\nYour solution needs some adjustments. Review the execution output for details.\n\n💡 IMPROVEMENTS:\n• Check the error messages carefully\n• Verify your logic handles all test cases\n\n💪 MOTIVATION:\nKeep practicing! Mistakes are learning opportunities."
            
            result["correct_solution"] = ai_response.get("correct_solution", "")
            if not result["correct_solution"] or result["correct_solution"].strip() == "":
                result["correct_solution"] = "# Correct solution will be generated based on the problem requirements."
            
            # ✅ FIX: Use actual test case results (more reliable than LLM's count)
            if test_results and len(test_results) > 0:
                # Use the test_results we just calculated above
                result["test_cases_passed"] = len([t for t in test_results if t.get("passed", False)])
                result["total_test_cases"] = len(test_results)
            else:
                # Fallback to LLM's count if no test cases were run
                test_cases_passed = ai_response.get("test_cases_passed")
                if isinstance(test_cases_passed, (int, float)):
                    result["test_cases_passed"] = int(test_cases_passed)
                else:
                    result["test_cases_passed"] = 0
                
                total_test_cases = ai_response.get("total_test_cases")
                if isinstance(total_test_cases, (int, float)):
                    result["total_test_cases"] = int(total_test_cases)
                else:
                    result["total_test_cases"] = 0
            
            # ✅ FIX: Store additional fields for display (already defined above)
            result["improvements"] = improvements
            result["motivation_message"] = motivation
            result["code_quality_score"] = ai_response.get("code_quality_score", 0)
            result["edge_cases_handled"] = ai_response.get("edge_cases_handled", False)
            result["missing_concepts"] = ai_response.get("missing_concepts", [])
            
            logger.info(f"[EVAL] LLM Evaluation Complete - Model: {model}")
            logger.info(f"[EVAL] Correctness: {result['correctness']}")
            logger.info(f"[EVAL] Score: {result['score']}")
            logger.info(f"[EVAL] Feedback length: {len(result.get('feedback', ''))} chars")
            logger.info(f"[EVAL] Correct solution length: {len(result.get('correct_solution', ''))} chars")
            logger.info(f"[EVAL] Test cases passed: {result.get('test_cases_passed', 0)}/{result.get('total_test_cases', 0)}")
            
    except Exception as e:
        logger.error(f"Could not generate AI feedback: {str(e)}")
        import traceback
        logger.error(f"LLM Error traceback: {traceback.format_exc()}")
        
        # ✅ FIX: Provide SHORT fallback feedback
        if result.get("execution_output") and "Error" in result["execution_output"]:
            error_msg = result['execution_output'].split('\n')[0]  # First line only
            result["feedback"] = f"""✅ CORRECTNESS:
Your code encountered an execution error: {error_msg}

💡 IMPROVEMENTS:
• Check syntax errors (missing brackets, colons, parentheses)
• Verify all variables are defined before use
• Test with simple inputs first

🧠 LOGIC TIP:
Read error messages carefully - they usually point to the exact issue.

💪 MOTIVATION:
Don't worry! Errors are part of learning. Review the error and try again."""
            
            result["errors_found"] = [error_msg]
            result["bugs_explained"] = [f"Runtime error: {error_msg}"]
            result["improvements"] = ["Fix syntax errors", "Check variable definitions", "Verify logic flow"]
            result["motivation_message"] = "Keep practicing! Every programmer faces errors - the key is learning from them."
        elif test_results:
            # More lenient matching - check if outputs are logically equivalent
            passed = 0
            for tr in test_results:
                actual = str(tr.get("actual", "")).strip()
                expected = str(tr.get("expected", "")).strip()
                # Exact match
                if actual == expected:
                    passed += 1
                    tr["passed"] = True
                # Numeric equivalence (for cases where output format differs)
                elif actual.replace(".", "").replace("-", "").isdigit() and expected.replace(".", "").replace("-", "").isdigit():
                    try:
                        if float(actual) == float(expected):
                            passed += 1
                            tr["passed"] = True
                        else:
                            tr["passed"] = False
                    except ValueError:
                        tr["passed"] = False
                else:
                    tr["passed"] = False
            
            total = len(test_results)
            result["test_cases_passed"] = passed
            result["total_test_cases"] = total
            # Mark as correct if all test cases pass OR if most pass (>= 80%)
            result["correctness"] = (passed == total and total > 0) or (passed >= total * 0.8 and total > 0)
            
            result["feedback"] = f"""Test Case Analysis:

Your solution passed {passed} out of {total} test cases.

Test Case Details:"""
            for tr in test_results:
                match = tr.get("actual", "").strip() == tr.get("expected", "").strip()
                result["feedback"] += f"\n\nTest {tr['test_case']}: {'✓ PASSED' if match else '✗ FAILED'}"
                result["feedback"] += f"\n  Input: {tr.get('input', 'N/A')}"
                result["feedback"] += f"\n  Expected: {tr.get('expected', 'N/A')}"
                result["feedback"] += f"\n  Got: {tr.get('actual', 'N/A')}"
            
            if result["correctness"]:
                result["feedback"] += "\n\n🎉 Great job! Your solution passed all test cases."
                result["score"] = 85  # Good score for passing all tests
                result["motivation_message"] = "Excellent work! You've successfully solved this problem. Your solution demonstrates good problem-solving skills. Keep practicing to master even more challenging problems! 🌟"
            else:
                result["feedback"] += "\n\nPlease review your logic and ensure all test cases pass."
                result["score"] = int((passed / total) * 60)  # Partial credit
                result["motivation_message"] = f"You passed {passed} out of {total} test cases. Review the failed cases, understand why they failed, and refine your solution. You're making progress! 💪"
        else:
            result["feedback"] = """Code Execution Analysis:

Your code executed successfully. However, comprehensive evaluation requires test cases or AI analysis.

To improve your solution:
1. Review the problem requirements carefully
2. Test with the provided examples
3. Consider edge cases
4. Optimize time and space complexity"""
            result["score"] = 50  # Neutral score without evaluation
        
        # Generate a helpful correct solution template
        result["correct_solution"] = f"""# Correct Solution for: {question_text[:80]}...

# Approach:
# 1. Understand the problem requirements
# 2. Identify the optimal algorithm/data structure
# 3. Handle edge cases
# 4. Optimize for time and space complexity

# Note: Full AI-generated solution is temporarily unavailable.
# Please refer to the problem statement, examples, and feedback above for guidance.

# Example structure:
def solve():
    # Your implementation here
    pass"""
    
    # Ensure we always have meaningful output
    if not result["execution_output"]:
        result["execution_output"] = "Code evaluation completed. See feedback section for detailed analysis."
    
    if not result["feedback"]:
        result["feedback"] = "Evaluation completed. Please review your solution."
    
    if not result["correct_solution"]:
        result["correct_solution"] = "# Correct solution generation in progress..."
    
    return result


@router.post("/{session_id}/next-question", response_model=CodingNextQuestionResponse)
async def get_next_coding_question(
    session_id: str,
    http_request: Request,
    request_body: Dict[str, Any] = Body(...),
    supabase: Client = Depends(get_supabase_client),
    _: None = Depends(validate_request_size)
):
    """
    Get the next coding question after submitting a solution
    """
    try:
        # Log incoming request for debugging
        logger.info(f"[CODING/NEXT] Received request: session_id={request_body.get('session_id')}, has_solution={bool(request_body.get('solution'))}, solution_length={len(request_body.get('solution', ''))}")
        
        session_id = request_body.get("session_id")
        previous_question = request_body.get("previous_question", {})
        solution = request_body.get("solution", "")
        
        if not session_id:
            raise HTTPException(status_code=400, detail="session_id is required")
        
        if not solution or not solution.strip():
            logger.warning(f"[CODING/NEXT] No solution provided in request for session {session_id}")
            raise HTTPException(status_code=400, detail="solution is required. Please submit your code.")
        
        # Prepare transcript logging
        if isinstance(previous_question, dict):
            question_text_for_answer = (
                previous_question.get("problem")
                or previous_question.get("question")
                or json.dumps(previous_question)
            )
        else:
            question_text_for_answer = previous_question or ""

        # Get session data
        session = None
        skills = []
        questions = []
        session_experience = None
        session_projects: List[str] = []
        session_domains: List[str] = []
        
        try:
            session_response = supabase.table("interview_sessions").select("*").eq("id", session_id).execute()
            if session_response.data and len(session_response.data) > 0:
                session = session_response.data[0]
                skills = session.get("skills", []) or []
                session_experience = session.get("experience_level")
                session_user_id = session.get("user_id")
                if session_user_id:
                    try:
                        profile_resp = (
                            supabase.table("user_profiles")
                            .select("*")
                            .eq("user_id", session_user_id)
                            .limit(1)
                            .execute()
                        )
                        profile_row = profile_resp.data[0] if profile_resp.data else None
                        if profile_row:
                            profile_context = build_resume_context_from_profile(profile_row, supabase)
                            session_projects = profile_context.get("projects", [])
                            session_domains = profile_context.get("domains", [])
                            if profile_context.get("experience_level"):
                                session_experience = profile_context.get("experience_level")
                    except Exception as profile_err:
                        logger.warning(f"Could not refresh resume context for coding session {session_id}: {profile_err}")
                
                # Get previous questions from coding_round table (new schema)
                try:
                    round_data_response = supabase.table("coding_round").select("question_text, question_number, user_code").eq("session_id", session_id).order("question_number").execute()
                    questions = []
                    for row in (round_data_response.data or []):
                        question_text = row.get("question_text", "")
                        if question_text:
                            questions.append({
                                "question": question_text,
                                "question_number": row.get("question_number", 0)
                            })
                except Exception as e:
                    logger.warning(f"Could not fetch questions: {str(e)}")
                    questions = []
        except Exception as e:
            logger.warning(f"Session not found in database: {str(e)}")
            skills = ["Python", "Data Structures", "Algorithms"]
        
        # Log the submitted solution
        await log_interview_transcript(
            supabase,
            session_id,
            "coding",
            question_text_for_answer,
            solution
        )

        # Get user_id and language from request
        # Priority: session user_id (if exists) > request user_id > try to get from user_profiles
        user_id = None
        if session and session.get("user_id"):
            user_id = session.get("user_id")
            logger.info(f"Using user_id from session: {user_id}")
        else:
            user_id = request_body.get("user_id")
            if user_id and not re.match(r'^[a-zA-Z0-9_-]+$', user_id):
                raise HTTPException(status_code=400, detail="Invalid user_id format")
            if not user_id:
                # Try to get user_id from user_profiles if we have session_user_id
                if session_user_id:
                    user_id = session_user_id
                    logger.info(f"Using user_id from session_user_id: {user_id}")
                else:
                    # Last resort: try to find any user in user_profiles
                    try:
                        users_response = supabase.table("user_profiles").select("user_id").limit(1).execute()
                        if users_response.data and len(users_response.data) > 0:
                            user_id = users_response.data[0].get("user_id")
                            logger.info(f"Using first user from user_profiles: {user_id}")
                        else:
                            user_id = "unknown"
                            logger.warning("No user found in user_profiles, using 'unknown'")
                    except Exception as e:
                        logger.warning(f"Could not get user from user_profiles: {str(e)}")
                        user_id = "unknown"
        
        # Validate user_id exists in user_profiles
        if user_id and user_id != "unknown":
            try:
                user_check = supabase.table("user_profiles").select("user_id").eq("user_id", user_id).limit(1).execute()
                if not user_check.data:
                    logger.warning(f"User {user_id} not found in user_profiles, but continuing anyway")
            except Exception as e:
                logger.warning(f"Could not validate user_id: {str(e)}")
        programming_language = request_body.get("programming_language", "python")
        difficulty_level = previous_question.get("difficulty") if isinstance(previous_question, dict) else None
        
        # Get question data (test cases, table setup for SQL, etc.)
        question_data = None
        sql_setup = None
        if isinstance(previous_question, dict):
            question_data = previous_question
            sql_setup = previous_question.get("table_setup")
        else:
            # Try to parse if it's a JSON string
            try:
                if isinstance(previous_question, str):
                    question_data = json.loads(previous_question)
                    sql_setup = question_data.get("table_setup") if question_data else None
            except (json.JSONDecodeError, TypeError):
                pass
        
        # Evaluate the solution and generate feedback
        logger.info(f"[CODING/NEXT] ========== Starting Code Evaluation ==========")
        logger.info(f"[CODING/NEXT] Session ID: {session_id}")
        logger.info(f"[CODING/NEXT] Solution length: {len(solution)} chars")
        logger.info(f"[CODING/NEXT] Programming language: {programming_language}")
        logger.info(f"[CODING/NEXT] Question text length: {len(question_text_for_answer)} chars")
        logger.info(f"[CODING/NEXT] Has question_data: {bool(question_data)}")
        logger.info(f"[CODING/NEXT] Has test_cases: {bool(question_data and question_data.get('test_cases')) if question_data else False}")
        
        try:
            evaluation_result = await evaluate_coding_solution(
                question_text_for_answer,
                solution,
                programming_language,
                difficulty_level,
                question_data=question_data,
                sql_setup=sql_setup
            )
        except Exception as eval_error:
            import traceback
            logger.error(f"✗ CRITICAL: Code evaluation failed: {str(eval_error)}")
            logger.error(f"  Traceback: {traceback.format_exc()}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to evaluate code: {str(eval_error)}"
            )
        
        logger.info(f"[CODING/NEXT] ========== Evaluation Complete ==========")
        logger.info(f"[CODING/NEXT] Correctness: {evaluation_result.get('correctness')}")
        logger.info(f"[CODING/NEXT] Score: {evaluation_result.get('score')}")
        logger.info(f"[CODING/NEXT] Execution output length: {len(evaluation_result.get('execution_output') or '')} chars")
        logger.info(f"[CODING/NEXT] AI feedback length: {len(evaluation_result.get('feedback') or '')} chars")
        logger.info(f"[CODING/NEXT] Correct solution length: {len(evaluation_result.get('correct_solution') or '')} chars")
        logger.info(f"[CODING/NEXT] Test cases passed: {evaluation_result.get('test_cases_passed', 0)}/{evaluation_result.get('total_test_cases', 0)}")
        
        # Validate evaluation result has required fields
        if not evaluation_result:
            raise HTTPException(status_code=500, detail="Code evaluation returned no result")
        
        if "correctness" not in evaluation_result:
            logger.warning(f"[CODING/NEXT] Evaluation result missing 'correctness' field, defaulting to False")
            evaluation_result["correctness"] = False
        
        # Store coding result
        # Get the question number from the previous question (the one user just answered)
        if isinstance(previous_question, dict) and previous_question.get("question_number"):
            current_question_number = previous_question.get("question_number")
            logger.info(f"[CODING/NEXT] Using question_number from previous_question: {current_question_number}")
        else:
            # Try to get from existing questions in coding_round
            try:
                existing_questions = supabase.table("coding_round").select("question_number").eq("session_id", session_id).order("question_number", desc=True).limit(1).execute()
                if existing_questions.data and len(existing_questions.data) > 0:
                    current_question_number = existing_questions.data[0].get("question_number", 1)
                    logger.info(f"[CODING/NEXT] Using question_number from existing questions: {current_question_number}")
                else:
                    current_question_number = len(questions) if questions else 1
                    logger.info(f"[CODING/NEXT] No existing questions found, using calculated: {current_question_number}")
            except Exception as e:
                logger.warning(f"Could not determine question number: {str(e)}")
                current_question_number = len(questions) if questions else 1
                logger.info(f"[CODING/NEXT] Fallback question_number: {current_question_number}")
        
        logger.info(f"[CODING/NEXT] Final question_number for storage: {current_question_number}")
        
        # Store result in database
        # Ensure we have actual values, not None or empty strings for critical fields
        execution_output = evaluation_result.get("execution_output") or ""
        ai_feedback = evaluation_result.get("feedback") or ""
        correct_solution = evaluation_result.get("correct_solution") or ""
        
        # Log evaluation results for debugging
        logger.info(f"Evaluation results - Correctness: {evaluation_result.get('correctness')}, Score: {evaluation_result.get('score')}")
        logger.info(f"Feedback length: {len(ai_feedback)}, Solution length: {len(correct_solution)}, Output length: {len(execution_output)}")
        
        # Log for debugging
        logger.info(f"Storing coding result for session {session_id}, question {current_question_number}")
        logger.info(f"Execution output length: {len(execution_output)}, Feedback length: {len(ai_feedback)}, Solution length: {len(correct_solution)}")
        
        # Store the result - CRITICAL: This must succeed
        # Get question_text from existing row if available, otherwise use question_text_for_answer
        stored_question_text = question_text_for_answer
        try:
            existing_question_row = supabase.table("coding_round").select("question_text").eq("session_id", session_id).eq("question_number", current_question_number).execute()
            if existing_question_row.data and len(existing_question_row.data) > 0:
                stored_question_text = existing_question_row.data[0].get("question_text", question_text_for_answer)
        except Exception as e:
            logger.warning(f"Could not fetch existing question text: {str(e)}")
        
        # CRITICAL: Storage must succeed - don't continue if it fails
        logger.info(f"[CODING/NEXT] Attempting to store result for session {session_id}, question {current_question_number}")
        logger.info(f"[CODING/NEXT] Storage data: user_code length={len(solution)}, execution_output length={len(execution_output)}, ai_feedback length={len(ai_feedback)}, correctness={evaluation_result.get('correctness', False)}")
        
        try:
            await store_coding_result(
                supabase=supabase,
                user_id=user_id,
                session_id=session_id,
                question_number=current_question_number,
                question_text=stored_question_text,
                user_code=solution,
                programming_language=programming_language,
                difficulty_level=difficulty_level,
                execution_output=execution_output,
                correctness=evaluation_result.get("correctness", False),
                ai_feedback=ai_feedback,
                final_score=evaluation_result.get("score", 0),
                execution_time=evaluation_result.get("execution_time"),
                test_cases_passed=evaluation_result.get("test_cases_passed", 0),
                total_test_cases=evaluation_result.get("total_test_cases", 0),
                correct_solution=correct_solution
            )
            logger.info(f"✓ Successfully stored coding result for session {session_id}, question {current_question_number}")
        except Exception as e:
            # CRITICAL: Storage failure must stop execution - don't silently continue
            import traceback
            error_msg = f"CRITICAL: Failed to store coding result: {str(e)}"
            logger.error(f"✗ {error_msg}")
            logger.error(f"  Session: {session_id}, Question: {current_question_number}, User: {user_id}")
            logger.error(f"  Full traceback: {traceback.format_exc()}")
            logger.error(f"  This will cause results page to show no data!")
            logger.error(f"  Stopping interview flow to prevent data loss.")
            
            # Re-raise as HTTPException so frontend gets proper error
            raise HTTPException(
                status_code=500,
                detail=f"Failed to save coding result. Please try again. Error: {str(e)}"
            )
        
        # Check completion based on ANSWERED questions (rows with user_code)
        # Count how many questions have been answered (have user_code) for this session
        CODING_TOTAL_QUESTIONS = 5  # Constant for coding interview total questions
        
        try:
            # Count only answered questions (those with user_code)
            answered_questions_response = supabase.table("coding_round").select("question_number").eq("session_id", session_id).not_.is_("user_code", "null").neq("user_code", "").execute()
            answered_count = len(answered_questions_response.data or [])
            logger.info(f"Total answered questions for session {session_id}: {answered_count}")
        except Exception as e:
            logger.warning(f"Could not count answered questions: {str(e)}")
            # Fallback: count all questions (less accurate but works)
            try:
                all_questions_response = supabase.table("coding_round").select("question_number").eq("session_id", session_id).execute()
                answered_count = len(all_questions_response.data or [])
            except Exception:
                answered_count = len(questions)
        
        # If we've answered 5 questions, mark as completed
        if answered_count >= CODING_TOTAL_QUESTIONS:
            logger.info(f"Interview completed - {answered_count} questions answered")
            return {
                "interview_completed": True,
                "message": "Coding interview completed! Thank you for your solutions.",
                "session_id": session_id
            }
        
        # Calculate next question number (1-5)
        # Next question number is answered_count + 1 (since we just answered current question)
        next_question_number = answered_count + 1
        
        # Ensure we don't exceed total questions
        if next_question_number > CODING_TOTAL_QUESTIONS:
            logger.warning(f"Next question number {next_question_number} exceeds total {CODING_TOTAL_QUESTIONS}, marking as completed")
            return {
                "interview_completed": True,
                "message": "Coding interview completed! Thank you for your solutions.",
                "session_id": session_id
            }
        
        # Generate next question
        # ✅ FIX: Build comprehensive list of all previous questions to prevent duplicates
        previous_questions_text = []
        previous_questions_normalized = set()  # Use set for O(1) lookup
        
        try:
            # Get all questions (answered and unanswered) to prevent duplicates
            all_questions_response = supabase.table("coding_round").select("question_text, question_number").eq("session_id", session_id).order("question_number").execute()
            for row in (all_questions_response.data or []):
                question_text = row.get("question_text", "")
                if question_text and question_text.strip():
                    # Normalize question text for duplicate detection
                    normalized = question_text.strip().lower()
                    # Remove extra whitespace and normalize
                    normalized = " ".join(normalized.split())
                    previous_questions_text.append(question_text)
                    previous_questions_normalized.add(normalized)
            
            logger.info(f"[CODING/NEXT] Found {len(previous_questions_text)} previous questions in database")
            for i, q in enumerate(previous_questions_text[:5], 1):
                logger.info(f"[CODING/NEXT]   Q{i}: {q[:80]}...")
                
        except Exception as e:
            logger.warning(f"Could not fetch previous questions for duplicate check: {str(e)}")
            # Fallback: use questions from memory
            previous_questions_text = [q.get("question", "") for q in questions if q.get("question")]
            for q_text in previous_questions_text:
                if q_text:
                    normalized = q_text.strip().lower()
                    normalized = " ".join(normalized.split())
                    previous_questions_normalized.add(normalized)
        
        session_data = {
            "session_id": session_id,
            "coding_skills": skills,
            "current_question_index": answered_count,
            "questions_asked": previous_questions_text,  # All previous questions to prevent duplicates
            "questions_asked_normalized": previous_questions_normalized,  # Normalized set for fast duplicate check
            "solutions_submitted": [],
            "experience_level": session_experience,
            "resume_projects": session_projects,
            "domains": session_domains
        }
        
        # Generate next question - ensure this always succeeds
        try:
            next_question = coding_interview_engine.generate_coding_question(
                session_data,
                previous_questions_text
            )
            
            # Validate question was generated
            if not next_question:
                logger.error("Failed to generate next question - got None")
                raise Exception("Failed to generate next question")
            
            # Ensure question has required fields
            if not next_question.get("problem") and not next_question.get("question"):
                logger.error(f"Generated question missing problem field: {next_question}")
                # Try to get fallback question
                next_question = coding_interview_engine._get_fallback_coding_question(session_data, previous_questions_text)
            
            logger.info(f"✓ Generated next question (number {next_question_number}): {next_question.get('problem', next_question.get('question', 'N/A'))[:100]}")
            
        except Exception as gen_error:
            logger.error(f"✗ Error generating next question: {str(gen_error)}")
            # Use fallback question to ensure we always return something
            try:
                next_question = coding_interview_engine._get_fallback_coding_question(session_data, previous_questions_text)
                logger.info("✓ Using fallback question")
            except Exception as fallback_error:
                logger.error(f"✗ Fallback question generation also failed: {str(fallback_error)}")
                # Last resort: return a simple question
                next_question = {
                    "problem": "Write a function to solve a coding problem. Show your problem-solving approach.",
                    "difficulty": "Medium",
                    "examples": [],
                    "constraints": "",
                    "topics": ["Algorithms", "Problem Solving"]
                }
        
        # Store question in coding_round table if session exists (new schema)
        if session:
            try:
                user_id = str(session.get("user_id", "")) if session else ""
                question_text = next_question.get("problem") or next_question.get("question") or json.dumps(next_question)
                question_db_data = {
                    "user_id": user_id,
                    "session_id": session_id,
                    "question_number": next_question_number,
                    "question_text": question_text,
                    "difficulty_level": next_question.get("difficulty", "Medium"),
                    "programming_language": request_body.get("programming_language", "python"),
                    "user_code": "",  # Placeholder - will be updated when user submits solution
                    "execution_output": None,
                    "execution_time": None,
                    "test_cases_passed": 0,
                    "total_test_cases": 0,
                    "correct_solution": None,
                    "correctness": False,
                    "final_score": 0,
                    "ai_feedback": None
                }
                supabase.table("coding_round").insert(question_db_data).execute()
            except Exception as e:
                logger.warning(f"Could not store question: {str(e)}")

        await log_interview_transcript(
            supabase,
            session_id,
            "coding",
            next_question.get("problem") or next_question.get("question") or "",
            None
        )
        
        # Add question_number to question object
        next_question["question_number"] = next_question_number
        
        # Log what we're returning
        logger.info(f"📤 Returning next question: number={next_question_number}, has_problem={bool(next_question.get('problem'))}, has_question={bool(next_question.get('question'))}")
        
        # Get user_id from session
        user_id = None
        if session and session.get("user_id"):
            user_id = session.get("user_id")
        
        CODING_TOTAL_QUESTIONS = 5  # Constant for coding interview total questions
        
        return {
            "question": next_question,
            "question_number": next_question_number,
            "total_questions": CODING_TOTAL_QUESTIONS,
            "interview_completed": False,
            "session_id": session_id,  # Include session_id for frontend
            "user_id": user_id  # Include user_id for frontend
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting next coding question: {str(e)}")





# ==================== Coding Helper Functions ====================

# Removed unused library checking functions - not needed for coding interview evaluation


async def execute_code_with_piston_api(code: str, language: str, test_input: str) -> Dict[str, Any]:
    """
    Execute code using Piston API (free online code execution service) as fallback
    when local compilers are not available.
    
    Piston API supports: python, java, javascript, c, cpp, and many other languages.
    """
    try:
        import httpx
        
        # Map language names to Piston API language identifiers
        piston_language_map = {
            "python": "python",
            "java": "java",
            "javascript": "javascript",
            "js": "javascript",
            "c": "c",
            "cpp": "cpp",
            "c++": "cpp"
        }
        
        piston_lang = piston_language_map.get(language.lower())
        if not piston_lang:
            return {
                "output": "",
                "error": f"Language {language} not supported by Piston API fallback",
                "execution_time": 0,
                "exit_code": 1
            }
        
        # Piston API endpoint (public, no API key required)
        piston_url = "https://emkc.org/api/v2/piston/execute"
        
        # Prepare request payload
        payload = {
            "language": piston_lang,
            "version": "*",  # Use latest version
            "files": [
                {
                    "content": code
                }
            ],
            "stdin": test_input if test_input else ""
        }
        
        logger.info(f"[PISTON] Executing {language} code via Piston API (fallback)")
        logger.debug(f"[PISTON] Code length: {len(code)} chars, Input: {repr(test_input)}")
        
        # Execute with timeout
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(piston_url, json=payload)
            response.raise_for_status()
            result = response.json()
        
        # Parse Piston API response
        run_result = result.get("run", {})
        compile_result = result.get("compile", {})
        
        # Check for compilation errors
        if compile_result.get("stderr"):
            return {
                "output": "",
                "error": compile_result.get("stderr", "Compilation error"),
                "execution_time": 0,
                "exit_code": 1
            }
        
        # Get execution output
        stdout = run_result.get("stdout", "").strip()
        stderr = run_result.get("stderr", "").strip()
        
        # Combine stdout and stderr (stderr might contain warnings)
        output = stdout
        if stderr and not stdout:
            output = stderr
        elif stderr:
            output = f"{stdout}\n{stderr}"
        
        execution_time = run_result.get("time", 0)
        exit_code = run_result.get("code", 0)
        
        logger.info(f"[PISTON] Execution successful: output length={len(output)}, time={execution_time}s, exit_code={exit_code}")
        
        return {
            "output": output,
            "error": "" if exit_code == 0 else stderr,
            "execution_time": execution_time,
            "exit_code": exit_code
        }
        
    except httpx.TimeoutException:
        logger.warning("[PISTON] Request timeout")
        return {
            "output": "",
            "error": "Code execution timeout. Please try again or simplify your code.",
            "execution_time": 0,
            "exit_code": 1
        }
    except httpx.HTTPStatusError as e:
        logger.warning(f"[PISTON] HTTP error: {e.response.status_code}")
        return {
            "output": "",
            "error": f"Code execution service unavailable (HTTP {e.response.status_code}). Please try again later.",
            "execution_time": 0,
            "exit_code": 1
        }
    except Exception as e:
        logger.warning(f"[PISTON] Error using Piston API: {str(e)}")
        return {
            "output": "",
            "error": f"Code execution service error: {str(e)}",
            "execution_time": 0,
            "exit_code": 1
        }


async def execute_code_safely(code: str, language: str, test_input: str, sql_setup: str = "") -> Dict[str, Any]:
    """
    Execute code safely using subprocess with timeout and resource limits
    Handles Windows and Unix systems properly
    
    Supported languages:
    - Python (with data science libraries: pandas, numpy, matplotlib, seaborn, scikit-learn)
    - Java (requires JDK)
    - JavaScript (requires Node.js)
    - C/C++ (requires GCC/G++)
    - SQL (uses sqlite3 via Python)
    """
    
    tmp_file_path = None
    output_file = None
    class_file = None
    temp_dir = None
    
    try:
        # Create temporary file for code
        file_extension = {
            "python": ".py",
            "java": ".java",
            "javascript": ".js",
            "c": ".c",
            "cpp": ".cpp",
            "c++": ".cpp",
            "sql": ".sql"
        }.get(language, ".txt")
        
        # Create temp file in a temporary directory
        temp_dir = tempfile.mkdtemp()
        
        # For Java, extract class name and use it as filename
        if language == "java":
            class_match = re.search(r'public\s+class\s+(\w+)', code)
            if class_match:
                class_name = class_match.group(1)
                tmp_file_path = os.path.join(temp_dir, f"{class_name}{file_extension}")
            else:
                # Fallback: try to find any class declaration
                class_match = re.search(r'class\s+(\w+)', code)
                if class_match:
                    class_name = class_match.group(1)
                    tmp_file_path = os.path.join(temp_dir, f"{class_name}{file_extension}")
                else:
                    # Default to "code"
                    tmp_file_path = os.path.join(temp_dir, f"code{file_extension}")
        else:
            tmp_file_path = os.path.join(temp_dir, f"code{file_extension}")
        
        with open(tmp_file_path, 'w', encoding='utf-8') as tmp_file:
            tmp_file.write(code)
        
        # Log file contents for debugging
        logger.info(f"[EXEC] Writing code to temp file: {tmp_file_path}")
        logger.info(f"[EXEC] Code length: {len(code)} chars")
        logger.info(f"[EXEC] Test input: {repr(test_input)}")
        logger.debug(f"[EXEC] Full code to execute:\n{code}")
        
        try:
            start_time = time.time()
            
            # Execute based on language
            if language == "python":
                # Find python executable - prioritize venv Python which has data science libraries
                python_cmd = None
                
                # Get the project root directory (where venv should be)
                current_file = os.path.abspath(__file__)
                # Navigate from app/routers/coding_interview.py to project root
                project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_file)))
                
                # Try to use venv Python first (has pandas, numpy, etc.)
                if os.name == 'nt':  # Windows
                    venv_python = os.path.join(project_root, "venv", "Scripts", "python.exe")
                else:  # Unix/Linux/Mac
                    venv_python = os.path.join(project_root, "venv", "bin", "python")
                
                if os.path.exists(venv_python):
                    python_cmd = venv_python
                else:
                    # Fallback to system Python (may not have data science libraries)
                    python_cmd = shutil.which("python") or shutil.which("python3") or "python"
                
                # Supported data science libraries
                supported_libraries = {
                    'pandas': 'pandas',
                    'numpy': 'numpy',
                    'matplotlib': 'matplotlib',
                    'seaborn': 'seaborn',
                    'sklearn': 'scikit-learn',
                    'scikit-learn': 'scikit-learn'
                }
                
                # Log execution command
                logger.info(f"[EXEC] Executing: {python_cmd} {tmp_file_path}")
                logger.info(f"[EXEC] Working directory: {temp_dir}")
                logger.info(f"[EXEC] Input (stdin): {repr(test_input)}")
                
                process = subprocess.run(
                    [python_cmd, tmp_file_path],
                    input=test_input,
                    capture_output=True,
                    text=True,
                    timeout=10,  # Increased timeout for data science operations
                    cwd=temp_dir,
                    shell=False
                )
                
                # Log execution results
                logger.info(f"[EXEC] Execution completed:")
                logger.info(f"[EXEC]   Return code: {process.returncode}")
                logger.info(f"[EXEC]   Stdout (raw): {repr(process.stdout)}")
                logger.info(f"[EXEC]   Stderr (raw): {repr(process.stderr)}")
                logger.info(f"[EXEC]   Stdout length: {len(process.stdout) if process.stdout else 0} chars")
                
                # Check for ModuleNotFoundError in stderr and provide helpful message
                if process.returncode != 0 and process.stderr:
                    stderr_lower = process.stderr.lower()
                    if 'modulenotfounderror' in stderr_lower or 'no module named' in stderr_lower:
                        # Extract module name from error
                        module_match = re.search(r"no module named ['\"]([^'\"]+)['\"]", stderr_lower, re.IGNORECASE)
                        if module_match:
                            module_name = module_match.group(1)
                            # Handle missing module error
                            if module_name in supported_libraries:
                                return {
                                    "output": process.stdout,
                                    "error": f"ModuleNotFoundError: '{module_name}' is not available in the execution environment. Please use Python standard library only.",
                                    "execution_time": round(time.time() - start_time, 3),
                                    "exit_code": process.returncode
                                }
                            else:
                                return {
                                    "output": process.stdout,
                                    "error": f"ModuleNotFoundError: '{module_name}' is not available. Please use only Python standard library modules.",
                                    "execution_time": round(time.time() - start_time, 3),
                                    "exit_code": process.returncode
                                }
                
                # If execution succeeded, return result
                execution_time = time.time() - start_time
                return {
                    "output": process.stdout,
                    "error": process.stderr if process.returncode != 0 else "",
                    "execution_time": round(execution_time, 3),
                    "exit_code": process.returncode
                }
            elif language == "java":
                # Find javac and java executables
                javac_cmd = shutil.which("javac")
                java_cmd = shutil.which("java")
                
                if not javac_cmd or not java_cmd:
                    # Fallback to Piston API when local Java compiler is not available
                    logger.info("[EXEC] Java compiler not found locally, using Piston API fallback")
                    return await execute_code_with_piston_api(code, language, test_input)
                
                # Compile first
                compile_process = subprocess.run(
                    [javac_cmd, tmp_file_path],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    cwd=temp_dir,
                    shell=False
                )
                
                if compile_process.returncode != 0:
                    return {
                        "output": "",
                        "error": compile_process.stderr or compile_process.stdout or "Compilation failed",
                        "execution_time": 0
                    }
                
                # Get class name from filename (file was already named based on class)
                class_name = os.path.basename(tmp_file_path).replace(".java", "")
                class_file = os.path.join(temp_dir, f"{class_name}.class")
                
                # Check if class file was created
                if not os.path.exists(class_file):
                    # Try to find any .class file in the directory
                    class_files = [f for f in os.listdir(temp_dir) if f.endswith('.class')]
                    if class_files:
                        class_name = class_files[0].replace('.class', '')
                        class_file = os.path.join(temp_dir, f"{class_name}.class")
                    else:
                        return {
                            "output": "",
                            "error": "Compilation succeeded but class file not found. Ensure the class name matches the file name or use 'public class ClassName'.",
                            "execution_time": 0
                        }
                
                # Run compiled class
                process = subprocess.run(
                    [java_cmd, "-cp", temp_dir, class_name],
                    input=test_input,
                    capture_output=True,
                    text=True,
                    timeout=5,
                    cwd=temp_dir,
                    shell=False
                )
            elif language in ["javascript", "js"]:
                # Find node executable
                node_cmd = shutil.which("node")
                if not node_cmd:
                    return {
                        "output": "",
                        "error": "Node.js not found. Please ensure Node.js is installed and added to PATH.",
                        "execution_time": 0
                    }
                
                process = subprocess.run(
                    [node_cmd, tmp_file_path],
                    input=test_input,
                    capture_output=True,
                    text=True,
                    timeout=5,
                    cwd=temp_dir,
                    shell=False
                )
            elif language in ["c", "cpp", "c++"]:
                # Find compiler executable
                compiler = "g++" if language in ["cpp", "c++"] else "gcc"
                compiler_cmd = shutil.which(compiler)
                
                if not compiler_cmd:
                    # Fallback to Piston API when local compiler is not available
                    compiler_name = "G++" if language in ["cpp", "c++"] else "GCC"
                    logger.info(f"[EXEC] {compiler_name} compiler not found locally, using Piston API fallback")
                    return await execute_code_with_piston_api(code, language, test_input)
                
                # Compile first - use proper output file path
                if os.name == 'nt':  # Windows
                    output_file = os.path.join(temp_dir, "a.exe")
                else:  # Unix/Linux/Mac
                    output_file = os.path.join(temp_dir, "a.out")
                
                compile_process = subprocess.run(
                    [compiler_cmd, tmp_file_path, "-o", output_file],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    cwd=temp_dir,
                    shell=False
                )
                
                if compile_process.returncode != 0:
                    return {
                        "output": "",
                        "error": compile_process.stderr or compile_process.stdout or "Compilation failed",
                        "execution_time": 0
                    }
                
                # Check if executable was created
                if not os.path.exists(output_file):
                    return {
                        "output": "",
                        "error": "Compilation succeeded but executable not found.",
                        "execution_time": 0
                    }
                
                # Run compiled executable
                # On Windows, use the full path; on Unix, use ./ prefix
                if os.name == 'nt':
                    exec_cmd = output_file
                else:
                    exec_cmd = f"./{os.path.basename(output_file)}"
                
                process = subprocess.run(
                    [exec_cmd] if os.name == 'nt' else exec_cmd.split(),
                    input=test_input,
                    capture_output=True,
                    text=True,
                    timeout=5,
                    cwd=temp_dir,
                    shell=False
                )
            elif language == "sql":
                # SQL execution using sqlite3 (lightweight, no setup required)
                # Create a Python wrapper to execute SQL safely
                # Escape backslashes in file path for Windows
                escaped_path = tmp_file_path.replace('\\', '\\\\')
                # Escape setup SQL properly for Python raw string (r''')
                if sql_setup:
                    # Escape single quotes
                    escaped_setup = sql_setup.replace("'", "\\'")
                    # Escape backslashes
                    escaped_setup = escaped_setup.replace('\\', '\\\\')
                else:
                    escaped_setup = ""
                
                sql_wrapper = f"""import sqlite3
import sys
import json
import os
import re

# Blocked SQL keywords for security (prevent file access, external DBs, schema changes, etc.)
# Note: INSERT, UPDATE, DELETE are allowed as they're legitimate SQL operations for interviews
BLOCKED_KEYWORDS = [
    'ATTACH', 'DETACH', 'PRAGMA', '.read', '.import', '.output', '.dump',
    'CREATE TABLE', 'CREATE TRIGGER', 'CREATE VIEW', 'CREATE INDEX', 
    'DROP', 'ALTER', 'TRUNCATE', 'VACUUM', 'ANALYZE', 'EXPLAIN QUERY PLAN'
]

def is_safe_sql(statement):
    '''Check if SQL statement is safe to execute'''
    stmt_upper = statement.upper().strip()
    for keyword in BLOCKED_KEYWORDS:
        if keyword in stmt_upper:
            return False, f"Unsafe SQL keyword detected: {{keyword}}"
    return True, None

try:
    # Read SQL from file
    sql_file = r'{escaped_path}'
    with open(sql_file, 'r', encoding='utf-8') as f:
        sql_code = f.read()
    
    # Create in-memory database
    conn = sqlite3.connect(':memory:')
    cursor = conn.cursor()
    
    # Execute setup SQL first (table creation and sample data)
    setup_sql = r'''{escaped_setup}'''
    if setup_sql.strip():
        # Split setup SQL by semicolon, handling multi-line statements
        normalized_setup = setup_sql
        # Split by semicolon - this works even with newlines
        setup_statements = []
        parts = normalized_setup.split(';')
        for part in parts:
            # Clean up: remove leading/trailing whitespace and newlines
            stmt = ' '.join(part.split())
            if stmt:
                setup_statements.append(stmt)
        
        # Execute each setup statement
        for setup_stmt in setup_statements:
            if not setup_stmt:
                continue
            try:
                cursor.execute(setup_stmt)
                conn.commit()
            except Exception as e:
                # Setup errors are logged but don't stop execution
                print(f"Setup warning: {{str(e)}}", file=sys.stderr)
                # Continue with next statement
    
    # Split user SQL into individual statements
    user_statements = [s.strip() for s in sql_code.split(';') if s.strip()]
    
    if not user_statements:
        print(json.dumps([{{'error': 'No SQL statements found'}}], indent=2))
        conn.close()
        sys.exit(1)
    
    results = []
    for statement in user_statements:
        if not statement:
            continue
        
        # Check if statement is safe
        is_safe, error_msg = is_safe_sql(statement)
        if not is_safe:
            results.append({{
                'error': error_msg,
                'statement': statement[:100]
            }})
            continue
        
        try:
            cursor.execute(statement)
            
            # Try to fetch results if it's a SELECT
            if statement.strip().upper().startswith('SELECT'):
                rows = cursor.fetchall()
                columns = [desc[0] for desc in cursor.description] if cursor.description else []
                # Convert rows to list format for JSON serialization
                rows_list = [list(row) for row in rows]
                results.append({{
                    'columns': columns,
                    'rows': rows_list,
                    'row_count': len(rows_list)
                }})
            else:
                conn.commit()
                results.append({{
                    'message': 'Statement executed successfully',
                    'rows_affected': cursor.rowcount
                }})
        except Exception as e:
            results.append({{
                'error': str(e),
                'statement': statement[:100] if len(statement) > 100 else statement
            }})
    
    # Output results as JSON
    print(json.dumps(results, indent=2))
    conn.close()
except Exception as e:
    # Output error as JSON to stdout (not stderr) so it's captured
    print(json.dumps([{{'error': f"Execution error: {{str(e)}}"}}], indent=2))
    sys.exit(1)
"""
                # Write SQL wrapper
                wrapper_path = os.path.join(temp_dir, "sql_executor.py")
                with open(wrapper_path, 'w', encoding='utf-8') as f:
                    f.write(sql_wrapper)
                
                # Find python executable (use same logic as Python execution)
                current_file = os.path.abspath(__file__)
                project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_file)))
                
                if os.name == 'nt':  # Windows
                    venv_python = os.path.join(project_root, "venv", "Scripts", "python.exe")
                else:  # Unix/Linux/Mac
                    venv_python = os.path.join(project_root, "venv", "bin", "python")
                
                if os.path.exists(venv_python):
                    python_cmd = venv_python
                else:
                    python_cmd = shutil.which("python") or shutil.which("python3") or "python"
                
                process = subprocess.run(
                    [python_cmd, wrapper_path],
                    input=test_input,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    cwd=temp_dir,
                    shell=False,
                    encoding='utf-8',
                    errors='replace'
                )
            else:
                return {
                    "output": "",
                    "error": f"Language '{language}' execution not implemented. Supported languages: Python, Java, JavaScript, C, C++, SQL.",
                    "execution_time": 0,
                    "exit_code": 1
                }
            
            execution_time = time.time() - start_time
            
            # Format output and error messages
            output = process.stdout
            error = process.stderr if process.returncode != 0 else ""
            
            # For SQL execution, check both stdout and stderr for output
            # The SQL wrapper outputs JSON to stdout, but if there's an error, it might be in stderr
            if language == "sql":
                # Debug: Log what we got
                if not output:
                    logger.warning(f"[SQL] No stdout output. Return code: {process.returncode}, stderr: {process.stderr[:200] if process.stderr else 'None'}")
                
                if not output and process.stderr:
                    # Check if stderr contains JSON (our error format)
                    stderr_content = process.stderr.strip()
                    if stderr_content.startswith('[') or stderr_content.startswith('{'):
                        output = stderr_content
                        error = ""
                    else:
                        # If stderr has content but not JSON, it's a real error
                        error = stderr_content
                        # Also try to get output from stderr if it looks like JSON
                        if stderr_content and (stderr_content.startswith('[') or stderr_content.startswith('{')):
                            output = stderr_content
                            error = ""
            
            # Improve error messages for better user experience
            if error:
                error_lower = error.lower()
                # Make error messages more user-friendly
                if "compilation" in error_lower or "compile" in error_lower:
                    if language == "java":
                        error = f"Java Compilation Error:\n{error}\n\nTip: Ensure your class name matches the filename and all syntax is correct."
                    elif language in ["c", "cpp", "c++"]:
                        error = f"C/C++ Compilation Error:\n{error}\n\nTip: Check for syntax errors, missing includes, or undefined references."
                elif "timeout" in error_lower:
                    error = f"Execution Timeout: Your code took longer than the allowed time limit.\n\nTip: Optimize your algorithm or check for infinite loops."
                elif "not found" in error_lower or "cannot find" in error_lower:
                    if language == "java":
                        error = f"Java Runtime Error:\n{error}\n\nTip: Ensure Java JDK is installed and javac/java are in your PATH."
                    elif language in ["c", "cpp", "c++"]:
                        error = f"Compiler Error:\n{error}\n\nTip: Ensure GCC/G++ is installed. On Windows, install MinGW or Visual Studio Build Tools."
                    elif language in ["javascript", "js"]:
                        error = f"Node.js Error:\n{error}\n\nTip: Ensure Node.js is installed and 'node' is in your PATH."
            
            return {
                "output": output,
                "error": error,
                "execution_time": round(execution_time, 3),
                "exit_code": process.returncode
            }
            
        finally:
            # Clean up temp files and directory
            try:
                if temp_dir and os.path.exists(temp_dir):
                    # Clean up all files in temp directory
                    for file in os.listdir(temp_dir):
                        file_path = os.path.join(temp_dir, file)
                        try:
                            if os.path.isfile(file_path):
                                os.unlink(file_path)
                        except Exception:
                            pass
                    # Remove temp directory
                    try:
                        os.rmdir(temp_dir)
                    except Exception:
                        pass
            except Exception as cleanup_error:
                logger.warning(f"Error cleaning up temp files: {cleanup_error}")
        
    except subprocess.TimeoutExpired:
        timeout_limit = 10 if language == "python" or language == "sql" else 5
        return {
            "output": "",
            "error": f"Execution timeout ({timeout_limit} seconds exceeded). Your code took too long to execute.\n\nTip: Check for infinite loops, optimize your algorithm, or reduce input size.",
            "execution_time": float(timeout_limit),
            "exit_code": 124
        }
    except FileNotFoundError as e:
        # Provide helpful messages based on language
        tool_messages = {
            "python": "Python interpreter not found. Please ensure Python is installed and in your PATH.",
            "java": "Java compiler (javac) or runtime (java) not found. Please install Java JDK and add it to your PATH.",
            "javascript": "Node.js not found. Please install Node.js from https://nodejs.org/ and add it to your PATH.",
            "c": "GCC compiler not found. On Windows, install MinGW or Visual Studio Build Tools. On Linux/Mac, install gcc via package manager.",
            "cpp": "G++ compiler not found. On Windows, install MinGW or Visual Studio Build Tools. On Linux/Mac, install g++ via package manager.",
            "sql": "Python interpreter not found (required for SQL execution). Please ensure Python is installed."
        }
        error_msg = tool_messages.get(language, f"Required tool not found: {str(e)}. Please ensure the necessary compilers/runtimes are installed and in your PATH.")
        return {
            "output": "",
            "error": error_msg,
            "execution_time": 0,
            "exit_code": 127
        }
    except Exception as e:
        # Provide a friendly error message
        error_msg = f"Execution error: {str(e)}\n\n"
        if "permission" in str(e).lower():
            error_msg += "Tip: This might be a permissions issue. Please contact support."
        elif "memory" in str(e).lower():
            error_msg += "Tip: Your code might be using too much memory. Try optimizing your solution."
        else:
            error_msg += "Tip: Check your code for syntax errors or logical issues."
        return {
            "output": "",
            "error": error_msg,
            "execution_time": 0,
            "exit_code": 1
        }


@router.post("/run", response_model=CodeRunResponse)
async def run_code(
    http_request: Request,
    request_body: Dict[str, Any] = Body(...),
    supabase: Client = Depends(get_supabase_client),
    _: None = Depends(validate_request_size)
):
    """
    Execute code safely in a sandboxed environment
    Accepts: {code, language, input, sql_setup, session_id} (sql_setup is optional, for SQL questions with table definitions)
    Returns: {output, error, execution_time}
    """
    try:
        # Extract and validate session_id
        session_id = request_body.get("session_id")
        if not session_id or not isinstance(session_id, str) or not session_id.strip():
            raise HTTPException(
                status_code=400,
                detail="session_id is required and must be a valid string"
            )
        
        # Validate session exists in database
        try:
            session_response = supabase.table("interview_sessions").select("id, interview_type").eq("id", session_id).execute()
            if not session_response.data or len(session_response.data) == 0:
                raise HTTPException(
                    status_code=404,
                    detail="Invalid session_id. Interview session not found. Please start a new coding interview."
                )
            
            # Verify session is a coding interview
            session = session_response.data[0]
            session_type = session.get("interview_type", "").lower()
            if session_type != "coding":
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid session type. This endpoint is for coding interviews only. Session type: {session_type}"
                )
        except HTTPException:
            raise
        except Exception as db_error:
            logger.error(f"[CODING RUN] Database error validating session: {str(db_error)}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail="Failed to validate interview session. Please try again."
            )
        
        code = request_body.get("code", "")
        language = request_body.get("language", "python")
        test_input = request_body.get("input", "")
        sql_setup = request_body.get("sql_setup", "")  # Table definitions and sample data for SQL questions
        
        if not code:
            raise HTTPException(status_code=400, detail="code is required")
        
        if not language:
            raise HTTPException(status_code=400, detail="language is required")
        
        # Validate language
        supported_languages = ["python", "java", "javascript", "c", "cpp", "c++", "sql"]
        language_lower = language.lower()
        if language_lower not in supported_languages:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported language. Supported: {', '.join(supported_languages)}"
            )
        
        # Execute code based on language
        result = await execute_code_safely(code, language_lower, test_input, sql_setup)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error executing code: {str(e)}")


@router.put("/{session_id}/end", response_model=InterviewEndResponse)
async def end_coding_interview(
    session_id: str,
    supabase: Client = Depends(get_supabase_client)
):
    """
    End the coding interview session
    Updates session status to completed
    """
    try:
        # Input validation
        if not session_id or not isinstance(session_id, str) or not session_id.strip():
            logger.error(f"[CODING][END] Invalid session_id: {session_id}")
            raise HTTPException(status_code=400, detail="Invalid request format. Please check your input and try again.")
        
        logger.info(f"[CODING][END] Ending coding interview session: {session_id}")
        
        # Verify session exists and is coding type
        try:
            session_response = supabase.table("interview_sessions").select("*").eq("id", session_id).execute()
        except Exception as db_error:
            logger.error(f"[CODING][END] Database error fetching session: {str(db_error)}", exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to retrieve interview session. Please try again.")
        
        if not session_response.data or len(session_response.data) == 0:
            logger.warning(f"[CODING][END] Session not found: {session_id}")
            raise HTTPException(status_code=404, detail="Interview session not found. Please start a new interview.")
        
        session = session_response.data[0]
        
        # Validate session is coding type
        session_type = session.get("interview_type", "").lower()
        if session_type != "coding":
            logger.error(f"[CODING][END] Wrong session type: {session_type} (expected: coding)")
            raise HTTPException(
                status_code=400, 
                detail="This endpoint is for coding interviews only. Please use the correct interview type."
            )
        
        # Update session status to completed
        # Use atomic update with row-level locking: only update if status is not already "completed"
        try:
            update_response = supabase.table("interview_sessions").update({
                "session_status": "completed"
            }).eq("id", session_id).neq("session_status", "completed").execute()
            
            if not update_response.data or len(update_response.data) == 0:
                logger.info(f"[CODING][END] Session already completed for session_id: {session_id}")
            else:
                logger.info(f"[CODING][END] ✅ Coding interview session ended successfully: {session_id}")
        except Exception as db_error:
            logger.error(f"[CODING][END] Database error updating session status: {str(db_error)}", exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to update session status. Please try again.")
        
        return {
            "message": "Coding interview ended successfully",
            "session_id": session_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[CODING][END] Unexpected error ending coding interview: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to end interview. Please try again.")

