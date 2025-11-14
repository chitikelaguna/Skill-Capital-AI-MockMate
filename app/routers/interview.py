"""
Interview routes
"""

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form, Request, Body
from fastapi.responses import StreamingResponse
from supabase import Client
from app.db.client import get_supabase_client
from app.schemas.interview import (
    InterviewSetupRequest, 
    InterviewSetupResponse,
    InterviewGenerateRequest,
    InterviewGenerateResponse,
    InterviewQuestion,
    StartInterviewRequest,
    StartInterviewResponse,
    SubmitAnswerRequest,
    SubmitAnswerResponse,
    InterviewEvaluationRequest,
    InterviewEvaluationResponse,
    TechnicalInterviewStartRequest,
    TechnicalInterviewStartResponse
)
from app.services.topic_generator import topic_generator
from app.services.question_generator import question_generator
from app.services.answer_evaluator import answer_evaluator
from app.services.interview_evaluator import interview_evaluator
from app.services.resume_parser import resume_parser
from app.services.technical_interview_engine import technical_interview_engine
from app.utils.database import (
    get_user_profile,
    get_interview_session,
    get_question_by_number,
    get_all_answers_for_session,
    batch_insert_questions
)
from app.utils.datetime_utils import parse_datetime, get_current_timestamp
from app.utils.exceptions import NotFoundError, ValidationError, DatabaseError
from typing import Optional, Dict, Any, List
from datetime import datetime
import uuid
import tempfile
import os
import json
import io
import base64
import urllib.parse

router = APIRouter(prefix="/api/interview", tags=["interview"])

@router.post("/setup", response_model=InterviewSetupResponse)
async def setup_interview(
    setup_request: InterviewSetupRequest,
    supabase: Client = Depends(get_supabase_client)
):
    """
    Setup interview based on role and experience level.
    Generates interview topics based on user's skills from profile.
    """
    try:
        # Get user profile to fetch skills
        profile_response = supabase.table("user_profiles").select("*").eq("user_id", setup_request.user_id).execute()
        
        user_skills: Optional[list] = []
        if profile_response.data and len(profile_response.data) > 0:
            user_skills = profile_response.data[0].get("skills", [])
        
        # Generate topics based on role, experience, and user skills
        topics = topic_generator.generate_topics(
            role=setup_request.role,
            experience_level=setup_request.experience_level,
            user_skills=user_skills if user_skills else None
        )
        
        # Get suggested skills
        suggested_skills = topic_generator.get_suggested_skills(
            role=setup_request.role,
            user_skills=user_skills if user_skills else []
        )
        
        return InterviewSetupResponse(
            user_id=setup_request.user_id,
            role=setup_request.role,
            experience_level=setup_request.experience_level,
            topics=topics,
            suggested_skills=suggested_skills,
            total_topics=len(topics)
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error setting up interview: {str(e)}")

@router.get("/roles")
async def get_available_roles():
    """Get list of available roles"""
    roles = [
        "Python Developer",
        "ServiceNow Engineer",
        "DevOps",
        "Fresher",
        "Full Stack Developer",
        "Data Engineer"
    ]
    return {"roles": roles}

@router.get("/experience-levels")
async def get_experience_levels():
    """Get list of available experience levels"""
    levels = [
        "Fresher",
        "1yrs",
        "2yrs",
        "3yrs",
        "4yrs",
        "5yrs",
        "5yrs+"
    ]
    return {"experience_levels": levels}

@router.post("/generate", response_model=InterviewGenerateResponse)
async def generate_interview_questions(
    generate_request: InterviewGenerateRequest,
    supabase: Client = Depends(get_supabase_client)
):
    """
    Generate interview questions using OpenAI.
    Creates a session and stores questions in the database.
    If resume is uploaded, uses resume context for personalized questions.
    """
    try:
        # Try to fetch resume context if available
        resume_context = None
        try:
            # Get user profile to check for resume
            profile_response = supabase.table("user_profiles").select("*").eq("user_id", generate_request.user_id).execute()
            
            if profile_response.data and len(profile_response.data) > 0:
                profile = profile_response.data[0]
                resume_url = profile.get("resume_url")
                
                if resume_url:
                    # Download resume from Supabase storage
                    # Extract bucket and file path from URL
                    # Format: https://[project].supabase.co/storage/v1/object/public/[bucket]/[path]
                    try:
                        # Parse the resume URL to get file path
                        if "storage/v1/object/public/" in resume_url:
                            path_part = resume_url.split("storage/v1/object/public/")[1]
                            bucket_name = path_part.split("/")[0]
                            file_path = "/".join(path_part.split("/")[1:])
                            
                            # Download file from storage
                            file_response = supabase.storage.from_(bucket_name).download(file_path)
                            
                            if file_response:
                                # Save to temporary file
                                file_extension = os.path.splitext(file_path)[1]
                                with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as tmp_file:
                                    tmp_file.write(file_response)
                                    tmp_file_path = tmp_file.name
                                
                                try:
                                    # Parse resume to extract keywords
                                    parsed_resume = resume_parser.parse_resume(tmp_file_path, file_extension)
                                    
                                    # Extract keywords for context
                                    resume_context = {
                                        "keywords": parsed_resume.get("keywords", {}),
                                        "skills": parsed_resume.get("skills", [])
                                    }
                                finally:
                                    # Clean up temporary file
                                    if os.path.exists(tmp_file_path):
                                        os.unlink(tmp_file_path)
                    except Exception as e:
                        # If resume parsing fails, continue without resume context
                        print(f"Warning: Could not parse resume for context: {str(e)}")
                        resume_context = None
        except Exception as e:
            # If fetching resume fails, continue without resume context
            print(f"Warning: Could not fetch resume context: {str(e)}")
            resume_context = None
        
        # Generate questions using AI (with resume context if available)
        questions = question_generator.generate_questions(
            role=generate_request.role,
            experience_level=generate_request.experience_level,
            skills=generate_request.skills,
            resume_context=resume_context
        )
        
        # Create interview session
        session_data = {
            "user_id": generate_request.user_id,
            "role": generate_request.role,
            "experience_level": generate_request.experience_level,
            "skills": generate_request.skills,
            "session_status": "active"
        }
        
        session_response = supabase.table("interview_sessions").insert(session_data).execute()
        
        if not session_response.data or len(session_response.data) == 0:
            raise HTTPException(status_code=500, detail="Failed to create interview session")
        
        session_id = session_response.data[0]["id"]
        
        # Store questions in database
        questions_data = []
        for idx, question in enumerate(questions, start=1):
            question_data = {
                "session_id": session_id,
                "question_type": question.type,
                "question": question.question,
                "question_number": idx
            }
            questions_data.append(question_data)
        
        # Insert all questions
        if questions_data:
            supabase.table("interview_questions").insert(questions_data).execute()
        
        return InterviewGenerateResponse(
            session_id=session_id,
            user_id=generate_request.user_id,
            role=generate_request.role,
            experience_level=generate_request.experience_level,
            questions=questions,
            total_questions=len(questions),
            created_at=datetime.now()
        )
        
    except ValueError as e:
        # If OpenAI key is not set, return fallback questions
        if "OpenAI API key" in str(e):
            # Use fallback questions
            questions = question_generator._get_fallback_questions(
                role=generate_request.role,
                experience_level=generate_request.experience_level,
                skills=generate_request.skills
            )
            
            # Still create session and store questions
            session_data = {
                "user_id": generate_request.user_id,
                "role": generate_request.role,
                "experience_level": generate_request.experience_level,
                "skills": generate_request.skills,
                "session_status": "active"
            }
            
            session_response = supabase.table("interview_sessions").insert(session_data).execute()
            session_id = session_response.data[0]["id"] if session_response.data else str(uuid.uuid4())
            
            questions_data = []
            for idx, question in enumerate(questions, start=1):
                question_data = {
                    "session_id": session_id,
                    "question_type": question.type,
                    "question": question.question,
                    "question_number": idx
                }
                questions_data.append(question_data)
            
            if questions_data:
                supabase.table("interview_questions").insert(questions_data).execute()
            
            return InterviewGenerateResponse(
                session_id=session_id,
                user_id=generate_request.user_id,
                role=generate_request.role,
                experience_level=generate_request.experience_level,
                questions=questions,
                total_questions=len(questions),
                created_at=datetime.now()
            )
        else:
            raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating interview questions: {str(e)}")

@router.get("/session/{session_id}/questions")
async def get_session_questions(
    session_id: str,
    supabase: Client = Depends(get_supabase_client)
):
    """Get all questions for a specific interview session"""
    try:
        # Get session
        session_response = supabase.table("interview_sessions").select("*").eq("id", session_id).execute()
        
        if not session_response.data or len(session_response.data) == 0:
            raise HTTPException(status_code=404, detail="Session not found")
        
        # Get questions
        questions_response = supabase.table("interview_questions").select("*").eq("session_id", session_id).order("question_number").execute()
        
        questions = []
        if questions_response.data:
            for q in questions_response.data:
                questions.append(InterviewQuestion(
                    type=q["question_type"],
                    question=q["question"]
                ))
        
        return {
            "session_id": session_id,
            "session": session_response.data[0],
            "questions": questions,
            "total_questions": len(questions)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching session questions: {str(e)}")

@router.post("/start", response_model=StartInterviewResponse)
async def start_interview(
    start_request: StartInterviewRequest,
    supabase: Client = Depends(get_supabase_client)
):
    """Start an interview session - get the first question"""
    try:
        # Get session
        session_response = supabase.table("interview_sessions").select("*").eq("id", start_request.session_id).execute()
        
        if not session_response.data or len(session_response.data) == 0:
            raise HTTPException(status_code=404, detail="Session not found")
        
        session = session_response.data[0]
        
        # Get first question
        questions_response = supabase.table("interview_questions").select("*").eq("session_id", start_request.session_id).order("question_number").limit(1).execute()
        
        if not questions_response.data or len(questions_response.data) == 0:
            raise HTTPException(status_code=404, detail="No questions found for this session")
        
        first_question = questions_response.data[0]
        
        # Get total question count
        total_response = supabase.table("interview_questions").select("id", count="exact").eq("session_id", start_request.session_id).execute()
        total_questions = total_response.count if hasattr(total_response, 'count') else len(questions_response.data)
        
        # Update session status to active if needed
        if session.get("session_status") != "active":
            supabase.table("interview_sessions").update({"session_status": "active"}).eq("id", start_request.session_id).execute()
        
        return StartInterviewResponse(
            session_id=start_request.session_id,
            current_question=InterviewQuestion(
                type=first_question["question_type"],
                question=first_question["question"]
            ),
            question_number=first_question["question_number"],
            total_questions=total_questions,
            interview_started=True,
            time_limit=60  # 60 seconds per question
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error starting interview: {str(e)}")

@router.get("/session/{session_id}/question/{question_number}")
async def get_question(
    session_id: str,
    question_number: int,
    supabase: Client = Depends(get_supabase_client)
):
    """Get a specific question by number"""
    try:
        questions_response = supabase.table("interview_questions").select("*").eq("session_id", session_id).eq("question_number", question_number).execute()
        
        if not questions_response.data or len(questions_response.data) == 0:
            raise HTTPException(status_code=404, detail="Question not found")
        
        question = questions_response.data[0]
        
        return {
            "question_id": question["id"],
            "question_number": question["question_number"],
            "question_type": question["question_type"],
            "question": question["question"]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching question: {str(e)}")

@router.post("/submit-answer", response_model=SubmitAnswerResponse)
async def submit_answer(
    answer_request: SubmitAnswerRequest,
    supabase: Client = Depends(get_supabase_client)
):
    """Submit an answer and get AI evaluation"""
    try:
        # Get session to get experience level
        session_response = supabase.table("interview_sessions").select("*").eq("id", answer_request.session_id).execute()
        
        if not session_response.data or len(session_response.data) == 0:
            raise HTTPException(status_code=404, detail="Session not found")
        
        session = session_response.data[0]
        experience_level = session.get("experience_level", "Fresher")
        
        # Evaluate answer using AI (include response time in evaluation)
        scores = answer_evaluator.evaluate_answer(
            question=answer_request.question_text,
            question_type=answer_request.question_type,
            answer=answer_request.user_answer,
            experience_level=experience_level,
            response_time=answer_request.response_time
        )
        
        # Store answer in database
        answer_data = {
            "session_id": answer_request.session_id,
            "question_id": answer_request.question_id,
            "question_number": answer_request.question_number,
            "question_text": answer_request.question_text,
            "question_type": answer_request.question_type,
            "user_answer": answer_request.user_answer,
            "relevance_score": scores.relevance,
            "confidence_score": scores.confidence,
            "technical_accuracy_score": scores.technical_accuracy,
            "communication_score": scores.communication,
            "overall_score": scores.overall,
            "ai_feedback": scores.feedback,
            "response_time": answer_request.response_time,
            "evaluated_at": datetime.now().isoformat()
        }
        
        answer_response = supabase.table("interview_answers").insert(answer_data).execute()
        
        if not answer_response.data or len(answer_response.data) == 0:
            raise HTTPException(status_code=500, detail="Failed to save answer")
        
        answer_id = answer_response.data[0]["id"]
        # Parse timestamp - handle different formats
        answered_at_str = answer_response.data[0]["answered_at"]
        if isinstance(answered_at_str, str):
            answered_at_str = answered_at_str.replace('Z', '+00:00')
            try:
                answered_at = datetime.fromisoformat(answered_at_str)
            except ValueError:
                answered_at = datetime.now()
        else:
            answered_at = datetime.now()
        evaluated_at = datetime.now()
        
        return SubmitAnswerResponse(
            answer_id=answer_id,
            session_id=answer_request.session_id,
            question_id=answer_request.question_id,
            scores=scores,
            response_time=answer_request.response_time,
            answered_at=answered_at,
            evaluated_at=evaluated_at
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error submitting answer: {str(e)}")

@router.get("/session/{session_id}/next-question/{current_question_number}")
async def get_next_question(
    session_id: str,
    current_question_number: int,
    supabase: Client = Depends(get_supabase_client)
):
    """Get the next question after current one"""
    try:
        # Get next question
        questions_response = supabase.table("interview_questions").select("*").eq("session_id", session_id).gt("question_number", current_question_number).order("question_number").limit(1).execute()
        
        if not questions_response.data or len(questions_response.data) == 0:
            # No more questions
            # Mark session as completed
            supabase.table("interview_sessions").update({"session_status": "completed"}).eq("id", session_id).execute()
            return {
                "has_next": False,
                "message": "Interview completed! No more questions."
            }
        
        question = questions_response.data[0]
        
        return {
            "has_next": True,
            "question_id": question["id"],
            "question_number": question["question_number"],
            "question_type": question["question_type"],
            "question": question["question"]
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching next question: {str(e)}")

@router.post("/evaluate", response_model=InterviewEvaluationResponse)
async def evaluate_interview(
    evaluation_request: InterviewEvaluationRequest,
    supabase: Client = Depends(get_supabase_client)
):
    """Evaluate complete interview session and generate feedback report"""
    try:
        # Get session
        session_response = supabase.table("interview_sessions").select("*").eq("id", evaluation_request.session_id).execute()
        
        if not session_response.data or len(session_response.data) == 0:
            raise HTTPException(status_code=404, detail="Session not found")
        
        session = session_response.data[0]
        role = session.get("role", "Unknown")
        experience_level = session.get("experience_level", "Fresher")
        
        # Get all answers for this session
        answers_response = supabase.table("interview_answers").select("*").eq("session_id", evaluation_request.session_id).order("question_number").execute()
        
        answers = answers_response.data if answers_response.data else []
        
        if not answers:
            raise HTTPException(status_code=400, detail="No answers found for this session. Please complete the interview first.")
        
        # Get total questions count
        questions_response = supabase.table("interview_questions").select("id", count="exact").eq("session_id", evaluation_request.session_id).execute()
        total_questions = questions_response.count if hasattr(questions_response, 'count') else len(answers)
        
        # Evaluate interview
        evaluation_result = interview_evaluator.evaluate_interview(
            role=role,
            experience_level=experience_level,
            answers=answers,
            total_questions=total_questions
        )
        
        return InterviewEvaluationResponse(
            session_id=evaluation_request.session_id,
            overall_score=evaluation_result["overall_score"],
            category_scores=evaluation_result["category_scores"],
            total_questions=total_questions,
            answered_questions=len(answers),
            feedback_summary=evaluation_result["feedback_summary"],
            recommendations=evaluation_result["recommendations"],
            strengths=evaluation_result["strengths"],
            areas_for_improvement=evaluation_result["areas_for_improvement"],
            generated_at=datetime.now()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error evaluating interview: {str(e)}")

# ==================== Technical Interview Endpoints ====================

@router.post("/technical", response_model=TechnicalInterviewStartResponse)
async def start_technical_interview(
    request: TechnicalInterviewStartRequest,
    supabase: Client = Depends(get_supabase_client)
):
    """
    Start a new technical interview session based on user's resume
    """
    try:
        user_id = request.user_id
        
        # Get user profile to extract resume skills
        profile_response = supabase.table("user_profiles").select("*").eq("user_id", user_id).execute()
        
        resume_skills = []
        resume_context = None
        
        if profile_response.data and len(profile_response.data) > 0:
            profile = profile_response.data[0]
            resume_skills = profile.get("skills", [])
            resume_url = profile.get("resume_url")
            
            # Try to parse resume if available
            if resume_url:
                try:
                    if "storage/v1/object/public/" in resume_url:
                        path_part = resume_url.split("storage/v1/object/public/")[1]
                        bucket_name = path_part.split("/")[0]
                        file_path = "/".join(path_part.split("/")[1:])
                        
                        file_response = supabase.storage.from_(bucket_name).download(file_path)
                        
                        if file_response:
                            file_extension = os.path.splitext(file_path)[1]
                            with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as tmp_file:
                                tmp_file.write(file_response)
                                tmp_file_path = tmp_file.name
                            
                            try:
                                parsed_resume = resume_parser.parse_resume(tmp_file_path, file_extension)
                                resume_context = {
                                    "keywords": parsed_resume.get("keywords", {}),
                                    "skills": parsed_resume.get("skills", [])
                                }
                            finally:
                                if os.path.exists(tmp_file_path):
                                    os.unlink(tmp_file_path)
                except Exception as e:
                    print(f"Warning: Could not parse resume for technical interview: {str(e)}")
        
        # Initialize interview session using engine
        session_data = technical_interview_engine.start_interview_session(
            user_id=user_id,
            resume_skills=resume_skills,
            resume_context=resume_context
        )
        
        # Create session in database
        db_session_data = {
            "user_id": user_id,
            "role": "Technical Interview",
            "experience_level": profile_response.data[0].get("experience_level", "Intermediate") if profile_response.data else "Intermediate",
            "skills": session_data["technical_skills"],
            "session_status": "active"
        }
        
        session_response = supabase.table("interview_sessions").insert(db_session_data).execute()
        
        if not session_response.data or len(session_response.data) == 0:
            raise HTTPException(status_code=500, detail="Failed to create interview session")
        
        session_id = session_response.data[0]["id"]
        session_data["session_id"] = session_id
        
        # Store session metadata (conversation history) in a JSON field
        # We'll use a metadata field or store in session notes
        # For now, we'll store conversation history in session metadata
        metadata = {
            "conversation_history": session_data["conversation_history"],
            "current_question_index": 0,
            "questions_asked": [],
            "answers_received": [],
            "all_scores": []
        }
        
        # Update session with metadata (store as JSON in a text field or use a metadata column)
        # Since we don't have a metadata column, we'll manage this in memory and store in answers/questions
        
        return TechnicalInterviewStartResponse(
            session_id=session_id,
            conversation_history=session_data["conversation_history"],
            technical_skills=session_data["technical_skills"]
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error starting technical interview: {str(e)}")

@router.post("/technical/{session_id}/next-question")
async def get_next_technical_question(
    session_id: str,
    supabase: Client = Depends(get_supabase_client)
):
    """
    Get the next technical question for the interview
    """
    try:
        # Get session
        session_response = supabase.table("interview_sessions").select("*").eq("id", session_id).execute()
        
        if not session_response.data or len(session_response.data) == 0:
            raise HTTPException(status_code=404, detail="Session not found")
        
        session = session_response.data[0]
        
        # Get conversation history from stored questions and answers
        questions_response = supabase.table("interview_questions").select("*").eq("session_id", session_id).order("question_number").execute()
        answers_response = supabase.table("interview_answers").select("*").eq("session_id", session_id).order("question_number").execute()
        
        # Build conversation history
        conversation_history = []
        questions_asked = []
        answers_received = []
        
        # Add questions and answers to conversation
        questions = questions_response.data if questions_response.data else []
        answers = answers_response.data if answers_response.data else []
        
        for q in questions:
            conversation_history.append({"role": "ai", "content": q["question"]})
            questions_asked.append(q["question"])
        
        for a in answers:
            conversation_history.append({"role": "user", "content": a["user_answer"]})
            answers_received.append(a["user_answer"])
        
        # Prepare session data
        session_data = {
            "session_id": session_id,
            "technical_skills": session.get("skills", []),
            "conversation_history": conversation_history,
            "current_question_index": len(questions),
            "questions_asked": questions_asked,
            "answers_received": answers_received
        }
        
        # Check if interview should end (max 10 questions)
        if len(questions_asked) >= 10:
            return {
                "interview_completed": True,
                "message": "Interview completed. Maximum questions reached."
            }
        
        # Generate next question
        question_data = technical_interview_engine.generate_next_question(session_data, conversation_history)
        
        # Store question in database
        question_number = len(questions) + 1
        question_db_data = {
            "session_id": session_id,
            "question_type": question_data.get("question_type", "Technical"),
            "question": question_data["question"],
            "question_number": question_number
        }
        
        supabase.table("interview_questions").insert(question_db_data).execute()
        
        # Generate audio URL using TTS
        audio_url = None
        try:
            # We'll generate audio on-demand via the TTS endpoint
            import urllib.parse
            encoded_text = urllib.parse.quote(question_data['question'])
            audio_url = f"/api/interview/text-to-speech?text={encoded_text}"
        except Exception as e:
            print(f"Warning: Could not generate audio URL: {str(e)}")
        
        return {
            "question": question_data["question"],
            "question_type": question_data.get("question_type", "Technical"),
            "audio_url": audio_url,
            "interview_completed": False
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting next question: {str(e)}")

@router.post("/technical/{session_id}/submit-answer")
async def submit_technical_answer(
    session_id: str,
    request: Dict[str, Any],
    supabase: Client = Depends(get_supabase_client)
):
    """
    Submit an answer to the current technical question
    """
    try:
        question = request.get("question")
        answer = request.get("answer")
        
        if not question or not answer:
            raise HTTPException(status_code=400, detail="question and answer are required")
        
        # Get session
        session_response = supabase.table("interview_sessions").select("*").eq("id", session_id).execute()
        
        if not session_response.data or len(session_response.data) == 0:
            raise HTTPException(status_code=404, detail="Session not found")
        
        session = session_response.data[0]
        
        # Get current question from database
        questions_response = supabase.table("interview_questions").select("*").eq("session_id", session_id).order("question_number", desc=True).limit(1).execute()
        
        if not questions_response.data or len(questions_response.data) == 0:
            raise HTTPException(status_code=404, detail="No current question found")
        
        current_question_db = questions_response.data[0]
        question_id = current_question_db["id"]
        question_number = current_question_db["question_number"]
        
        # Get conversation history
        questions_list = supabase.table("interview_questions").select("*").eq("session_id", session_id).order("question_number").execute()
        answers_list = supabase.table("interview_answers").select("*").eq("session_id", session_id).order("question_number").execute()
        
        conversation_history = []
        for q in (questions_list.data or []):
            conversation_history.append({"role": "ai", "content": q["question"]})
        for a in (answers_list.data or []):
            conversation_history.append({"role": "user", "content": a["user_answer"]})
        
        # Prepare session data
        session_data = {
            "session_id": session_id,
            "technical_skills": session.get("skills", []),
            "conversation_history": conversation_history,
            "current_question_index": len(questions_list.data or []),
            "questions_asked": [q["question"] for q in (questions_list.data or [])],
            "answers_received": [a["user_answer"] for a in (answers_list.data or [])]
        }
        
        # Evaluate answer
        evaluation = technical_interview_engine.evaluate_answer(
            question=question,
            answer=answer,
            session_data=session_data,
            conversation_history=conversation_history
        )
        
        # Store answer in database
        answer_data = {
            "session_id": session_id,
            "question_id": question_id,
            "question_number": question_number,
            "question_text": question,
            "question_type": current_question_db.get("question_type", "Technical"),
            "user_answer": answer,
            "relevance_score": evaluation["scores"]["relevance"],
            "confidence_score": 0,  # Not used in technical interview
            "technical_accuracy_score": evaluation["scores"]["technical_accuracy"],
            "communication_score": evaluation["scores"]["communication"],
            "overall_score": evaluation["scores"]["overall"],
            "ai_feedback": evaluation.get("ai_response", ""),
            "response_time": None,
            "evaluated_at": datetime.now().isoformat()
        }
        
        answer_response = supabase.table("interview_answers").insert(answer_data).execute()
        
        # Generate audio URL for AI response
        audio_url = None
        if evaluation.get("ai_response"):
            try:
                import urllib.parse
                encoded_text = urllib.parse.quote(evaluation['ai_response'])
                audio_url = f"/api/interview/text-to-speech?text={encoded_text}"
            except Exception as e:
                print(f"Warning: Could not generate audio URL: {str(e)}")
        
        # Check if interview should continue (max 10 questions)
        total_questions = len(questions_list.data or [])
        if total_questions >= 10:
            return {
                "ai_response": evaluation.get("ai_response", "Thank you for your answer."),
                "audio_url": audio_url,
                "scores": evaluation["scores"],
                "interview_completed": True
            }
        
        return {
            "ai_response": evaluation.get("ai_response", "Thank you for your answer."),
            "audio_url": audio_url,
            "scores": evaluation["scores"],
            "interview_completed": False
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error submitting answer: {str(e)}")

@router.get("/technical/{session_id}/feedback")
async def get_technical_interview_feedback(
    session_id: str,
    supabase: Client = Depends(get_supabase_client)
):
    """
    Get final feedback for completed technical interview
    """
    try:
        # Get session
        session_response = supabase.table("interview_sessions").select("*").eq("id", session_id).execute()
        
        if not session_response.data or len(session_response.data) == 0:
            raise HTTPException(status_code=404, detail="Session not found")
        
        session = session_response.data[0]
        
        # Get all answers
        answers_response = supabase.table("interview_answers").select("*").eq("session_id", session_id).order("question_number").execute()
        answers = answers_response.data if answers_response.data else []
        
        if not answers:
            raise HTTPException(status_code=400, detail="No answers found for this session")
        
        # Get conversation history
        questions_response = supabase.table("interview_questions").select("*").eq("session_id", session_id).order("question_number").execute()
        
        conversation_history = []
        for q in (questions_response.data or []):
            conversation_history.append({"role": "ai", "content": q["question"]})
        for a in answers:
            conversation_history.append({"role": "user", "content": a["user_answer"]})
        
        # Prepare session data
        session_data = {
            "session_id": session_id,
            "technical_skills": session.get("skills", []),
            "conversation_history": conversation_history,
            "current_question_index": len(questions_response.data or []),
            "questions_asked": [q["question"] for q in (questions_response.data or [])],
            "answers_received": [a["user_answer"] for a in answers]
        }
        
        # Get all scores
        all_scores = []
        for answer in answers:
            all_scores.append({
                "relevance": answer.get("relevance_score", 0),
                "technical_accuracy": answer.get("technical_accuracy_score", 0),
                "communication": answer.get("communication_score", 0),
                "overall": answer.get("overall_score", 0)
            })
        
        # Generate feedback
        feedback = technical_interview_engine.generate_final_feedback(
            session_data=session_data,
            conversation_history=conversation_history,
            all_scores=all_scores
        )
        
        # Update session status
        supabase.table("interview_sessions").update({"session_status": "completed"}).eq("id", session_id).execute()
        
        return feedback
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating feedback: {str(e)}")

@router.post("/technical/{session_id}/end")
async def end_technical_interview(
    session_id: str,
    supabase: Client = Depends(get_supabase_client)
):
    """
    End the technical interview session
    """
    try:
        # Update session status
        supabase.table("interview_sessions").update({"session_status": "completed"}).eq("id", session_id).execute()
        
        return {"message": "Interview ended successfully", "session_id": session_id}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error ending interview: {str(e)}")

@router.post("/speech-to-text")
async def speech_to_text(
    audio: UploadFile = File(...),
    supabase: Client = Depends(get_supabase_client)
):
    """
    Convert speech audio to text using OpenAI Whisper
    """
    try:
        # Check if OpenAI is available
        if not technical_interview_engine.openai_available or technical_interview_engine.client is None:
            raise HTTPException(status_code=503, detail="Speech-to-text service is not available. OpenAI API key is required.")
        
        # Save uploaded audio to temporary file
        file_extension = os.path.splitext(audio.filename)[1] if audio.filename else ".webm"
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as tmp_file:
            content = await audio.read()
            tmp_file.write(content)
            tmp_file_path = tmp_file.name
        
        try:
            # Transcribe using OpenAI Whisper
            with open(tmp_file_path, "rb") as audio_file:
                transcript = technical_interview_engine.client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    language="en"
                )
            
            text = transcript.text
            
            return {"text": text, "language": "en"}
            
        finally:
            # Clean up temporary file
            if os.path.exists(tmp_file_path):
                os.unlink(tmp_file_path)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error converting speech to text: {str(e)}")

@router.get("/text-to-speech")
async def text_to_speech(
    text: str,
    supabase: Client = Depends(get_supabase_client)
):
    """
    Convert text to speech using OpenAI TTS
    Returns audio file as streaming response
    """
    try:
        # Check if OpenAI is available
        if not technical_interview_engine.openai_available or technical_interview_engine.client is None:
            raise HTTPException(status_code=503, detail="Text-to-speech service is not available. OpenAI API key is required.")
        
        if not text:
            raise HTTPException(status_code=400, detail="text parameter is required")
        
        # Generate speech using OpenAI TTS
        response = technical_interview_engine.client.audio.speech.create(
            model="tts-1",
            voice="alloy",  # Options: alloy, echo, fable, onyx, nova, shimmer
            input=text[:500]  # Limit text length
        )
        
        # Return audio as streaming response
        audio_data = response.content
        
        return StreamingResponse(
            io.BytesIO(audio_data),
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "inline; filename=speech.mp3"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error converting text to speech: {str(e)}")

