"""
Interview routes
"""

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form, Request, Body, Query
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
from app.services.coding_interview_engine import coding_interview_engine
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

async def log_interview_transcript(
    supabase: Client,
    session_id: Optional[str],
    interview_type: str,
    question_text: Optional[str],
    user_answer: Optional[str] = None
) -> None:
    """
    Store each question/answer interaction in Supabase for analytics
    """
    if not supabase:
        return
    if not session_id:
        session_id = "unknown_session"

    try:
        transcript_data = {
            "session_id": session_id,
            "interview_type": interview_type,
            "question": question_text or "",
            "user_answer": user_answer,
            "created_at": datetime.utcnow().isoformat()
        }
        supabase.table("interview_transcripts").insert(transcript_data).execute()
    except Exception as e:
        print(f"[TRANSCRIPT] Warning: Could not log interaction: {str(e)}")


async def evaluate_coding_solution(
    question_text: str,
    user_code: str,
    programming_language: str,
    difficulty_level: Optional[str] = None
) -> Dict[str, Any]:
    """
    Evaluate a coding solution and generate feedback
    """
    from app.config.settings import settings
    from openai import OpenAI
    
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
    
    # Try to execute the code to get output
    # Note: execute_code_safely is defined later in this file, but Python allows forward references
    try:
        # Import here to avoid circular dependency
        import subprocess
        import tempfile
        import time
        import shutil
        
        # Simple execution for evaluation (full execution happens in /coding/run endpoint)
        # For now, we'll let AI evaluate based on code structure
        result["execution_output"] = "Code structure analysis in progress"
    except Exception as e:
        result["execution_output"] = f"Execution analysis: {str(e)}"
    
    # Generate AI feedback and correct solution
    try:
        if settings.openai_api_key:
            client = OpenAI(api_key=settings.openai_api_key)
            
            system_prompt = """You are an expert coding interview evaluator. Analyze the candidate's solution and provide:
1. Detailed feedback on what they did correctly
2. What mistakes they made
3. Step-by-step explanation of the correct approach
4. Improvement suggestions
5. Missing concepts
6. Time and space complexity of the optimal solution
7. A correct solution code

Be constructive, educational, and encouraging."""
            
            user_prompt = f"""Question: {question_text}

Candidate's Solution ({programming_language}):
```{programming_language}
{user_code}
```

Execution Output: {result.get("execution_output", "No output")}

Difficulty Level: {difficulty_level or "Medium"}

Provide comprehensive feedback and a correct solution in JSON format:
{{
  "feedback": "Detailed feedback explaining what's correct, what's wrong, and how to improve",
  "correct_solution": "Complete correct solution code",
  "correctness": true/false,
  "score": 0-100,
  "test_cases_passed": 0,
  "total_test_cases": 0,
  "time_complexity": "O(...)",
  "space_complexity": "O(...)",
  "improvements": ["suggestion1", "suggestion2"],
  "missing_concepts": ["concept1", "concept2"]
}}"""
            
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.7,
                response_format={"type": "json_object"}
            )
            
            ai_response = json.loads(response.choices[0].message.content)
            result["feedback"] = ai_response.get("feedback", "")
            result["correct_solution"] = ai_response.get("correct_solution", "")
            result["correctness"] = ai_response.get("correctness", False)
            result["score"] = ai_response.get("score", 0)
            result["test_cases_passed"] = ai_response.get("test_cases_passed", 0)
            result["total_test_cases"] = ai_response.get("total_test_cases", 0)
            
    except Exception as e:
        print(f"Warning: Could not generate AI feedback: {str(e)}")
        result["feedback"] = "Feedback generation unavailable. Please review your solution manually."
        result["correct_solution"] = "Correct solution not available."
    
    return result


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
        result_data = {
            "user_id": user_id,
            "session_id": session_id,
            "question_number": question_number,
            "question_text": question_text,
            "user_code": user_code,
            "programming_language": programming_language,
            "difficulty_level": difficulty_level,
            "execution_output": execution_output,
            "correctness": correctness,
            "ai_feedback": ai_feedback,
            "final_score": final_score,
            "execution_time": execution_time,
            "test_cases_passed": test_cases_passed,
            "total_test_cases": total_test_cases,
            "correct_solution": correct_solution
        }
        supabase.table("coding_results").insert(result_data).execute()
        print(f"[CODING_RESULT] Stored result for session {session_id}, question {question_number}")
    except Exception as e:
        print(f"[CODING_RESULT] Warning: Could not store coding result: {str(e)}")


def _normalize_project_entries(project_entries: Optional[Any]) -> List[str]:
    """Convert parsed project data into human-readable strings"""
    normalized: List[str] = []
    if not project_entries:
        return normalized
    try:
        for entry in project_entries:
            if isinstance(entry, dict):
                name = entry.get("name") or entry.get("title") or entry.get("project")
                description = entry.get("summary") or entry.get("description")
                technologies = entry.get("technologies") or entry.get("tech")
                parts = []
                if name:
                    parts.append(name.strip())
                if description:
                    parts.append(description.strip())
                if technologies and isinstance(technologies, list):
                    parts.append(f"Tech: {', '.join(technologies[:4])}")
                project_text = " - ".join(parts)
                if project_text:
                    normalized.append(project_text)
            elif isinstance(entry, str):
                project_text = entry.strip()
                if project_text:
                    normalized.append(project_text)
    except Exception as err:
        print(f"[RESUME] Warning: Could not normalize projects: {err}")
    return normalized[:5]


def build_resume_context_from_profile(
    profile_row: Optional[Dict[str, Any]],
    supabase: Client
) -> Dict[str, Any]:
    """
    Build a resume-aware context dictionary from the stored profile + resume file
    """
    context: Dict[str, Any] = {
        "skills": [],
        "experience_level": None,
        "projects": [],
        "keywords": {},
        "domains": []
    }
    if not profile_row:
        return context

    context["skills"] = list(profile_row.get("skills", []) or [])
    context["experience_level"] = profile_row.get("experience_level")

    resume_url = profile_row.get("resume_url")
    if resume_url and "storage/v1/object/public/" in resume_url:
        tmp_file_path = None
        try:
            path_part = resume_url.split("storage/v1/object/public/")[1]
            bucket_name = path_part.split("/")[0]
            file_path = "/".join(path_part.split("/")[1:])

            file_response = supabase.storage.from_(bucket_name).download(file_path)
            if file_response:
                file_extension = os.path.splitext(file_path)[1]
                with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as tmp_file:
                    tmp_file.write(file_response)
                    tmp_file_path = tmp_file.name

                parsed_resume = resume_parser.parse_resume(tmp_file_path, file_extension)
                parsed_skills = parsed_resume.get("skills", [])
                if parsed_skills:
                    existing = set(s.lower() for s in context["skills"])
                    for skill in parsed_skills:
                        if skill and skill.lower() not in existing:
                            context["skills"].append(skill)
                            existing.add(skill.lower())
                context["keywords"] = parsed_resume.get("keywords", {})
                summary_block = parsed_resume.get("summary") or {}
                projects_list = summary_block.get("projects_summary") or parsed_resume.get("projects")
                if projects_list:
                    context["projects"] = _normalize_project_entries(projects_list)
                if not context["experience_level"]:
                    context["experience_level"] = parsed_resume.get("experience_level")
                domains = context["keywords"].get("job_titles", []) if context["keywords"] else []
                if domains:
                    context["domains"] = domains
        except Exception as err:
            print(f"[RESUME] Warning: Failed to parse resume for context: {err}")
        finally:
            if tmp_file_path and os.path.exists(tmp_file_path):
                try:
                    os.unlink(tmp_file_path)
                except Exception:
                    pass

    return context


def build_context_from_cache(cache_entry: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not cache_entry:
        return {}
    summary_block = cache_entry.get("summary") or {}
    projects_list = summary_block.get("projects_summary")
    context = {
        "skills": cache_entry.get("skills", []) or [],
        "projects": _normalize_project_entries(projects_list),
        "experience_level": cache_entry.get("experience_level"),
        "keywords": cache_entry.get("keywords", {}),
        "domains": []
    }
    interview_modules = cache_entry.get("interview_modules") or {}
    if not context["projects"]:
        coding_module = interview_modules.get("coding_test") if isinstance(interview_modules, dict) else None
        if coding_module:
            topics = coding_module.get("topics")
            if topics:
                context["projects"] = [f"Coding Topic: {topic}" for topic in topics[:3]]
    return context


def merge_resume_context(base: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    if not extra:
        return base
    merged = {
        "skills": list(dict.fromkeys((base.get("skills") or []) + (extra.get("skills") or []))),
        "projects": list(dict.fromkeys((base.get("projects") or []) + (extra.get("projects") or []))),
        "experience_level": base.get("experience_level") or extra.get("experience_level"),
        "keywords": base.get("keywords") or extra.get("keywords") or {},
        "domains": list(dict.fromkeys((base.get("domains") or []) + (extra.get("domains") or [])))
    }

    # Merge keyword dictionaries if both exist
    if base.get("keywords") and extra.get("keywords"):
        merged["keywords"] = {**extra.get("keywords", {}), **base.get("keywords", {})}
    return merged

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
        profile_response = supabase.table("user_profiles").select("*").eq("user_id", generate_request.user_id).execute()
        profile = profile_response.data[0] if profile_response.data else None

        resume_context: Dict[str, Any] = {
            "skills": list(generate_request.skills),
            "experience_level": generate_request.experience_level,
            "projects": [],
            "keywords": {},
            "domains": []
        }
        if profile:
            resume_context = merge_resume_context(
                resume_context,
                build_resume_context_from_profile(profile, supabase)
            )

        # Try to supplement context from cached resume analysis if available
        try:
            from app.routers.profile import resume_analysis_cache
            cached_entry = None
            for cached_info in resume_analysis_cache.values():
                if cached_info.get("user_id") == generate_request.user_id:
                    cached_entry = cached_info
                    break
            if cached_entry:
                resume_context = merge_resume_context(
                    resume_context,
                    build_context_from_cache(cached_entry)
                )
        except Exception:
            pass

        if not resume_context.get("skills"):
            resume_context["skills"] = list(generate_request.skills)
        
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
            "skills": resume_context.get("skills", generate_request.skills),
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
                skills=generate_request.skills,
                resume_context=resume_context
            )
            
            # Still create session and store questions
            session_data = {
                "user_id": generate_request.user_id,
                "role": generate_request.role,
                "experience_level": generate_request.experience_level,
                "skills": resume_context.get("skills", generate_request.skills),
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
        
        await log_interview_transcript(
            supabase,
            answer_request.session_id,
            "technical",
            answer_request.question_text,
            answer_request.user_answer
        )
        
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
        profile = profile_response.data[0] if profile_response.data else None
        
        resume_context = build_resume_context_from_profile(profile, supabase)
        resume_skills = resume_context.get("skills", [])
        
        # Initialize interview session using engine
        session_data = technical_interview_engine.start_interview_session(
            user_id=user_id,
            resume_skills=resume_skills,
            resume_context=resume_context,
            role="Technical Interview",
            experience_level=resume_context.get("experience_level") or (profile.get("experience_level") if profile else None)
        )
        
        # Create session in database
        db_session_data = {
            "user_id": user_id,
            "role": "Technical Interview",
            "experience_level": resume_context.get("experience_level") or (profile.get("experience_level") if profile else "Intermediate"),
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
        print(f"[STT] Received audio file: {audio.filename}, content_type: {audio.content_type}")
        
        # Check if OpenAI is available
        if not technical_interview_engine.openai_available or technical_interview_engine.client is None:
            raise HTTPException(status_code=503, detail="Speech-to-text service is not available. OpenAI API key is required.")
        
        # Save uploaded audio to temporary file
        file_extension = os.path.splitext(audio.filename)[1] if audio.filename else ".webm"
        tmp_file_path = None
        
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as tmp_file:
                content = await audio.read()
                print(f"[STT] Audio file size: {len(content)} bytes")
                tmp_file.write(content)
                tmp_file_path = tmp_file.name
            
            # Transcribe using OpenAI Whisper
            print(f"[STT] Transcribing audio file: {tmp_file_path}")
            with open(tmp_file_path, "rb") as audio_file:
                transcript = technical_interview_engine.client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    language="en"
                )
            
            text = transcript.text
            print(f"[STT] Transcription result: {text[:100]}...")
            
            return {"text": text, "language": "en"}
            
        finally:
            # Clean up temporary file
            if tmp_file_path and os.path.exists(tmp_file_path):
                try:
                    os.unlink(tmp_file_path)
                except Exception as e:
                    print(f"[STT] Warning: Could not delete temp file: {str(e)}")
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[STT] Error: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error converting speech to text: {str(e)}")

@router.post("/text-to-speech")
async def text_to_speech(
    request: Dict[str, Any],
    supabase: Client = Depends(get_supabase_client)
):
    """
    Convert text to speech using OpenAI TTS
    Accepts: {"text": "question text"}
    Returns audio file as streaming response
    """
    try:
        text = request.get("text", "")
        
        # Check if OpenAI is available
        if not technical_interview_engine.openai_available or technical_interview_engine.client is None:
            raise HTTPException(status_code=503, detail="Text-to-speech service is not available. OpenAI API key is required.")
        
        if not text:
            raise HTTPException(status_code=400, detail="text parameter is required")
        
        print(f"[TTS] Generating speech for text: {text[:100]}...")
        
        # Generate speech using OpenAI TTS
        response = technical_interview_engine.client.audio.speech.create(
            model="tts-1",
            voice="alloy",  # Options: alloy, echo, fable, onyx, nova, shimmer
            input=text[:1000]  # Limit text length to 1000 chars
        )
        
        # Return audio as streaming response
        audio_data = response.content
        
        print(f"[TTS] Generated audio, size: {len(audio_data)} bytes")
        
        return StreamingResponse(
            io.BytesIO(audio_data),
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "inline; filename=speech.mp3",
                "Content-Type": "audio/mpeg",
                "Cache-Control": "no-cache"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[TTS] Error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error converting text to speech: {str(e)}")


@router.get("/text-to-speech")
async def text_to_speech_get(
    text: str = Query(..., description="Text to convert to speech"),
    supabase: Client = Depends(get_supabase_client)
):
    """
    Convert text to speech using OpenAI TTS (GET endpoint for URL-based access)
    Returns audio file as streaming response
    """
    try:
        # Check if OpenAI is available
        if not technical_interview_engine.openai_available or technical_interview_engine.client is None:
            raise HTTPException(status_code=503, detail="Text-to-speech service is not available. OpenAI API key is required.")
        
        if not text:
            raise HTTPException(status_code=400, detail="text parameter is required")
        
        print(f"[TTS] Generating speech for text: {text[:100]}...")
        
        # Generate speech using OpenAI TTS
        response = technical_interview_engine.client.audio.speech.create(
            model="tts-1",
            voice="alloy",
            input=text[:1000]
        )
        
        audio_data = response.content
        
        return StreamingResponse(
            io.BytesIO(audio_data),
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "inline; filename=speech.mp3",
                "Content-Type": "audio/mpeg",
                "Cache-Control": "no-cache"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[TTS] Error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error converting text to speech: {str(e)}")


# ==================== New Interview Page Routes ====================

@router.post("/technical/start")
async def start_interview_page(
    request: Dict[str, Any],
    supabase: Client = Depends(get_supabase_client)
):
    """
    Start a new technical interview for the new interview.html page
    Returns the first question based on resume skills
    """
    try:
        user_id = request.get("user_id")
        session_id = request.get("session_id")  # Optional: can reuse existing session
        
        if not user_id:
            raise HTTPException(status_code=400, detail="user_id is required")
        
        # Get user profile to extract resume skills
        resume_skills = []
        resume_context = None
        profile_response = None
        
        # Check if user_id is a valid UUID before querying database
        import uuid as uuid_lib
        is_valid_uuid = False
        try:
            uuid_lib.UUID(user_id)
            is_valid_uuid = True
        except (ValueError, TypeError):
            is_valid_uuid = False
        
        if is_valid_uuid:
            try:
                profile_response = supabase.table("user_profiles").select("*").eq("user_id", user_id).execute()
            except Exception as e:
                print(f"Warning: Could not fetch profile from database: {str(e)}")
                profile_response = None
        
        # If no profile found in database, try to get skills from sessionStorage/cache
        # For test users, we'll need to get skills from resume analysis cache
        if not profile_response or not profile_response.data or len(profile_response.data) == 0:
            # Try to get skills from resume analysis cache (stored during resume upload)
            # Optimized: O(n) search but breaks early on first match
            # Time Complexity: O(n) worst case, O(1) best case (first item matches)
            # Space Complexity: O(1)
            from app.routers.profile import resume_analysis_cache
            cached_data = None
            # Optimize: iterate and break early on match
            for cached_info in resume_analysis_cache.values():
                if cached_info.get("user_id") == user_id:
                    cached_data = cached_info
                    break
            
            if cached_data:
                resume_skills = cached_data.get("skills", []) or []
                print(f"Using cached resume data for user {user_id}")
        
        if profile_response and profile_response.data and len(profile_response.data) > 0:
            profile = profile_response.data[0]
            resume_skills = profile.get("skills", []) or []
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
                                # Merge parsed skills with profile skills
                                if parsed_resume.get("skills"):
                                    resume_skills.extend(parsed_resume.get("skills", []))
                                    resume_skills = list(dict.fromkeys(resume_skills))  # Remove duplicates
                            finally:
                                if os.path.exists(tmp_file_path):
                                    os.unlink(tmp_file_path)
                except Exception as e:
                    print(f"Warning: Could not parse resume for technical interview: {str(e)}")
        
        # If no skills found, try to use default skills for testing
        if not resume_skills or len(resume_skills) == 0:
            # For test users, provide some default skills to allow testing
            if not is_valid_uuid:
                print(f"Warning: No skills found for test user {user_id}. Using default skills for testing.")
                resume_skills = ["Python", "JavaScript", "SQL", "Web Development"]
            else:
                raise HTTPException(
                    status_code=400, 
                    detail="No technical skills found in resume. Please upload a resume with technical skills first."
                )
        
        # Create or reuse session
        if session_id:
            # Check if session exists
            session_response = supabase.table("interview_sessions").select("*").eq("id", session_id).execute()
            if not session_response.data or len(session_response.data) == 0:
                session_id = None  # Create new session
        
        if not session_id:
            # Check if user_id is a valid UUID
            import uuid as uuid_lib
            is_valid_uuid = False
            try:
                uuid_lib.UUID(user_id)
                is_valid_uuid = True
            except (ValueError, TypeError):
                is_valid_uuid = False
            
            # Create new session
            if is_valid_uuid:
                # Use database for real users
                db_session_data = {
                    "user_id": user_id,
                    "role": "Technical Interview",
                    "experience_level": (profile_response.data[0].get("experience_level", "Intermediate") if profile_response and profile_response.data else "Intermediate"),
                    "skills": resume_skills,
                    "session_status": "active"
                }
                
                try:
                    session_response = supabase.table("interview_sessions").insert(db_session_data).execute()
                    
                    if not session_response.data or len(session_response.data) == 0:
                        raise HTTPException(status_code=500, detail="Failed to create interview session")
                    
                    session_id = session_response.data[0]["id"]
                except Exception as db_error:
                    # If database insert fails, generate a temporary session ID
                    print(f"Warning: Database insert failed for user_id {user_id}: {str(db_error)}")
                    print("Using temporary session ID for testing")
                    session_id = str(uuid_lib.uuid4())
            else:
                # For test users with non-UUID IDs, generate a temporary session ID
                # Store session in memory or use a test-friendly approach
                print(f"Warning: user_id '{user_id}' is not a valid UUID. Using temporary session ID for testing.")
                session_id = str(uuid_lib.uuid4())
        
        # Initialize interview session
        session_data = technical_interview_engine.start_interview_session(
            user_id=user_id,
            resume_skills=resume_skills,
            resume_context=resume_context
        )
        
        # Generate first question based on skills
        conversation_history = session_data.get("conversation_history", [])
        first_question_data = technical_interview_engine.generate_next_question(
            {
                **session_data,
                "session_id": session_id
            },
            conversation_history
        )
        
        # Store first question in database (only if session was created in DB)
        if is_valid_uuid and session_id:
            try:
                # Check if session exists in DB before storing question
                session_check = supabase.table("interview_sessions").select("id").eq("id", session_id).limit(1).execute()
                if session_check.data and len(session_check.data) > 0:
                    question_db_data = {
                        "session_id": session_id,
                        "question_type": first_question_data.get("question_type", "Technical"),
                        "question": first_question_data["question"],
                        "question_number": 1
                    }
                    supabase.table("interview_questions").insert(question_db_data).execute()
            except Exception as e:
                print(f"Warning: Could not store first question in database: {str(e)}")
                # Continue without storing in DB for test sessions
        
        await log_interview_transcript(
            supabase,
            session_id,
            "technical",
            first_question_data.get("question", ""),
            None
        )

        return {
            "session_id": session_id,
            "question": first_question_data["question"],
            "question_type": first_question_data.get("question_type", "Technical"),
            "question_number": 1,
            "total_questions": 10,  # Will ask 8-12 questions
            "skills": resume_skills,
            "interview_completed": False
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error starting interview: {str(e)}")


@router.post("/technical/next")
async def get_next_interview_question(
    request: Dict[str, Any],
    supabase: Client = Depends(get_supabase_client)
):
    """
    Get the next interview question based on user's answer
    Acts like a human interviewer with follow-up questions
    """
    try:
        session_id = request.get("session_id")
        user_answer = request.get("user_answer", "")
        previous_question = request.get("previous_question", "")
        
        if not session_id:
            raise HTTPException(status_code=400, detail="session_id is required")
        
        if not user_answer:
            raise HTTPException(status_code=400, detail="user_answer is required")
        
        # Prepare question text for transcript logging
        if isinstance(previous_question, dict):
            question_text_for_answer = (
                previous_question.get("question")
                or previous_question.get("problem")
                or json.dumps(previous_question)
            )
        else:
            question_text_for_answer = previous_question or ""

        session_experience = None
        session_projects: List[str] = []
        session_domains: List[str] = []

        # Get session data
        session = None
        skills = []
        questions = []
        session_experience = None
        session_projects: List[str] = []
        session_domains: List[str] = []
        answers = []
        session_role = "Technical Interview"
        session_resume_projects: List[str] = []
        session_resume_domains: List[str] = []
        session_experience = None
        
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
                        print(f"Warning: Could not refresh resume context for coding session {session_id}: {profile_err}")
                session_experience = session.get("experience_level", session_experience)
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
                        print(f"Warning: Could not refresh resume context for coding session {session_id}: {profile_err}")
                session_role = session.get("role", session_role)
                session_experience = session.get("experience_level", session_experience)
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
                            session_resume_projects = profile_context.get("projects", [])
                            session_resume_domains = profile_context.get("domains", [])
                            if profile_context.get("experience_level"):
                                session_experience = profile_context.get("experience_level")
                    except Exception as profile_err:
                        print(f"Warning: Could not refresh resume context for session {session_id}: {profile_err}")
                
                # Get all questions for this session
                try:
                    questions_response = supabase.table("interview_questions").select("*").eq("session_id", session_id).order("question_number").execute()
                    questions = questions_response.data or []
                except Exception as e:
                    print(f"Warning: Could not fetch questions from database: {str(e)}")
                    questions = []
                
                # Get all answers
                try:
                    answers_response = supabase.table("interview_answers").select("*").eq("session_id", session_id).order("created_at").execute()
                    answers = answers_response.data or []
                except Exception as e:
                    print(f"Warning: Could not fetch answers from database: {str(e)}")
                    answers = []
                
                # Store user's answer (only if session exists in DB)
                if questions and len(questions) > 0:
                    try:
                        current_question = questions[-1]
                        answer_db_data = {
                            "session_id": session_id,
                            "question_id": current_question["id"],
                            "question_number": current_question.get("question_number", len(questions)),
                            "question_text": previous_question or current_question.get("question", ""),
                            "question_type": current_question.get("question_type", "Technical"),
                            "user_answer": user_answer,
                            "relevance_score": None,  # Will be evaluated later if needed
                            "confidence_score": None,
                            "technical_accuracy_score": None,
                            "communication_score": None,
                            "overall_score": None,
                            "ai_feedback": None,
                            "response_time": None
                        }
                        supabase.table("interview_answers").insert(answer_db_data).execute()
                        print(f"[STORE] Stored answer for question {current_question.get('question_number')}")
                    except Exception as e:
                        print(f"Warning: Could not store answer in database: {str(e)}")
                        # Continue without storing in DB for test sessions
        except Exception as e:
            print(f"Warning: Session {session_id} not found in database (may be test session): {str(e)}")
            # For test sessions, use default skills
            skills = ["Python", "JavaScript", "SQL", "Web Development"]
        
        # Log the user's answer for transcripts
        await log_interview_transcript(
            supabase,
            session_id,
            "technical",
            question_text_for_answer,
            user_answer
        )

        # Build conversation history
        conversation_history = []
        for i, q in enumerate(questions):
            conversation_history.append({
                "role": "ai",
                "content": q["question"]
            })
            if i < len(answers):
                conversation_history.append({
                    "role": "user",
                    "content": answers[i].get("user_answer", "")
                })
        
        # Add current answer
        conversation_history.append({
            "role": "user",
            "content": user_answer
        })
        
        # Check if interview should end (8-12 questions)
        total_questions = len(questions)
        if total_questions >= 12:
            return {
                "interview_completed": True,
                "message": "Interview completed. Thank you for your responses."
            }
        
        # Generate next question (AI acts like human interviewer with follow-ups)
        session_data = {
            "session_id": session_id,
            "technical_skills": skills,
            "conversation_history": conversation_history,
            "current_question_index": total_questions,
            "questions_asked": [q["question"] for q in questions],
            "answers_received": [a.get("user_answer", "") for a in answers] + [user_answer],
            "resume_projects": session_resume_projects,
            "resume_domains": session_resume_domains,
            "experience_level": session_experience,
            "role": session_role
        }
        
        next_question_data = technical_interview_engine.generate_next_question(session_data, conversation_history)
        
        # Store next question (only if session exists in DB)
        question_number = total_questions + 1
        if session:
            try:
                question_db_data = {
                    "session_id": session_id,
                    "question_type": next_question_data.get("question_type", "Technical"),
                    "question": next_question_data["question"],
                    "question_number": question_number
                }
                supabase.table("interview_questions").insert(question_db_data).execute()
            except Exception as e:
                print(f"Warning: Could not store question in database: {str(e)}")
                # Continue without storing in DB for test sessions
        
        await log_interview_transcript(
            supabase,
            session_id,
            "technical",
            next_question_data.get("question", ""),
            None
        )

        return {
            "question": next_question_data["question"],
            "question_type": next_question_data.get("question_type", "Technical"),
            "question_number": question_number,
            "total_questions": 10,
            "interview_completed": False
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting next question: {str(e)}")


@router.get("/technical/{session_id}/summary")
async def get_interview_summary(
    session_id: str,
    supabase: Client = Depends(get_supabase_client)
):
    """
    Get interview summary with scores, strengths, and improvements
    """
    try:
        # Get session
        session_response = supabase.table("interview_sessions").select("*").eq("id", session_id).execute()
        if not session_response.data:
            raise HTTPException(status_code=404, detail="Session not found")
        
        # Get all questions and answers
        questions_response = supabase.table("interview_questions").select("*").eq("session_id", session_id).order("question_number").execute()
        answers_response = supabase.table("interview_answers").select("*").eq("session_id", session_id).order("created_at").execute()
        
        questions = questions_response.data or []
        answers = answers_response.data or []
        
        if len(questions) == 0:
            raise HTTPException(status_code=400, detail="No interview data found")
        
        # Use existing feedback endpoint logic
        feedback_response = await get_technical_interview_feedback(session_id, supabase)
        feedback_data = feedback_response
        
        return {
            "session_id": session_id,
            "total_questions": len(questions),
            "answered_questions": len(answers),
            "overall_score": feedback_data.get("overall_score", 0),
            "strengths": feedback_data.get("strengths", []),
            "weak_areas": feedback_data.get("areas_for_improvement", []),
            "recommendations": feedback_data.get("recommendations", []),
            "summary": feedback_data.get("feedback_summary", "")
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting interview summary: {str(e)}")


# ==================== Coding Interview Routes ====================

@router.post("/coding/start")
async def start_coding_interview(
    request: Dict[str, Any],
    supabase: Client = Depends(get_supabase_client)
):
    """
    Start a new coding interview session
    Returns the first coding question based on resume skills
    """
    try:
        user_id = request.get("user_id")
        
        if not user_id:
            raise HTTPException(status_code=400, detail="user_id is required")
        
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
        
        # Check if user_id is a valid UUID
        import uuid as uuid_lib
        is_valid_uuid = False
        try:
            uuid_lib.UUID(user_id)
            is_valid_uuid = True
        except (ValueError, TypeError):
            is_valid_uuid = False
        
        profile = None
        if is_valid_uuid:
            try:
                profile_response = supabase.table("user_profiles").select("*").eq("user_id", user_id).execute()
                profile = profile_response.data[0] if profile_response.data else None
            except Exception as e:
                print(f"Warning: Could not fetch profile from database: {str(e)}")
                profile_response = None
        
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
        
        # If no skills found, use default
        if not resume_skills or len(resume_skills) == 0:
            if not is_valid_uuid:
                print(f"Warning: No skills found for test user {user_id}. Using default skills.")
                resume_skills = ["Python", "Data Structures", "Algorithms", "Problem Solving"]
            else:
                raise HTTPException(
                    status_code=400,
                    detail="No skills found in resume. Please upload a resume with technical skills first."
                )
        
        # Fetch past performance for adaptive difficulty
        past_performance = None
        if is_valid_uuid:
            try:
                past_results = supabase.table("coding_results").select("*").eq("user_id", user_id).order("created_at", desc=True).limit(20).execute()
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
                print(f"Warning: Could not fetch past performance: {str(e)}")
        
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
        
        # Create or get session ID
        session_id = None
        session_created_in_db = False
        if is_valid_uuid:
            try:
                db_session_data = {
                    "user_id": user_id,
                    "role": "Coding Interview",
                    "experience_level": (profile_response.data[0].get("experience_level", "Intermediate") if profile_response and profile_response.data else "Intermediate"),
                    "skills": resume_skills,
                    "session_status": "active"
                }
                session_response = supabase.table("interview_sessions").insert(db_session_data).execute()
                if session_response.data and len(session_response.data) > 0:
                    session_id = session_response.data[0]["id"]
                    session_created_in_db = True
            except Exception as e:
                print(f"Warning: Could not create session in database: {str(e)}")
                session_id = str(uuid_lib.uuid4())
        else:
            session_id = str(uuid_lib.uuid4())

        # Store first coding question for real sessions
        question_text = first_question.get("problem") or first_question.get("question") or ""
        if session_created_in_db and question_text:
            try:
                supabase.table("interview_questions").insert({
                    "session_id": session_id,
                    "question_type": "Coding",
                    "question": question_text,
                    "question_number": 1
                }).execute()
            except Exception as e:
                print(f"Warning: Could not store first coding question: {str(e)}")

        await log_interview_transcript(
            supabase,
            session_id,
            "coding",
            question_text,
            None
        )

        return {
            "session_id": session_id,
            "question": first_question,
            "question_number": 1,
            "total_questions": 5,  # Coding tests typically have 3-5 questions
            "skills": resume_skills,
            "interview_completed": False
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error starting coding interview: {str(e)}")


@router.post("/coding/next")
async def get_next_coding_question(
    request: Dict[str, Any],
    supabase: Client = Depends(get_supabase_client)
):
    """
    Get the next coding question after submitting a solution
    """
    try:
        session_id = request.get("session_id")
        previous_question = request.get("previous_question", {})
        solution = request.get("solution", "")
        
        if not session_id:
            raise HTTPException(status_code=400, detail="session_id is required")
        
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
                        print(f"Warning: Could not refresh resume context for coding session {session_id}: {profile_err}")
                
                # Get previous questions
                try:
                    questions_response = supabase.table("interview_questions").select("*").eq("session_id", session_id).order("question_number").execute()
                    questions = questions_response.data or []
                except Exception as e:
                    print(f"Warning: Could not fetch questions: {str(e)}")
                    questions = []
        except Exception as e:
            print(f"Warning: Session not found in database: {str(e)}")
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
        user_id = session.get("user_id") if session else request.get("user_id", "unknown")
        programming_language = request.get("programming_language", "python")
        difficulty_level = previous_question.get("difficulty") if isinstance(previous_question, dict) else None
        
        # Evaluate the solution and generate feedback
        evaluation_result = await evaluate_coding_solution(
            question_text_for_answer,
            solution,
            programming_language,
            difficulty_level
        )
        
        # Store coding result
        # The current question number is the last question that was asked (which the user just answered)
        current_question_number = len(questions) if questions else 1
        if session:
            await store_coding_result(
                supabase=supabase,
                user_id=user_id,
                session_id=session_id,
                question_number=current_question_number,
                question_text=question_text_for_answer,
                user_code=solution,
                programming_language=programming_language,
                difficulty_level=difficulty_level,
                execution_output=evaluation_result.get("execution_output"),
                correctness=evaluation_result.get("correctness", False),
                ai_feedback=evaluation_result.get("feedback"),
                final_score=evaluation_result.get("score", 0),
                execution_time=evaluation_result.get("execution_time"),
                test_cases_passed=evaluation_result.get("test_cases_passed", 0),
                total_test_cases=evaluation_result.get("total_test_cases", 0),
                correct_solution=evaluation_result.get("correct_solution")
            )

        # Calculate next question number (1-5, then complete)
        total_questions_in_db = len(questions)
        
        # If we've already answered 5 questions, mark as completed
        if total_questions_in_db >= 5:
            return {
                "interview_completed": True,
                "message": "Coding interview completed! Thank you for your solutions."
            }
        
        # Calculate next question number (1-5)
        next_question_number = total_questions_in_db + 1
        
        # Generate next question
        session_data = {
            "session_id": session_id,
            "coding_skills": skills,
            "current_question_index": total_questions_in_db,
            "questions_asked": [q.get("question", "") for q in questions],
            "solutions_submitted": [],
            "experience_level": session_experience,
            "resume_projects": session_projects,
            "domains": session_domains
        }
        
        previous_questions_text = [q.get("question", "") for q in questions]
        next_question = coding_interview_engine.generate_coding_question(
            session_data,
            previous_questions_text
        )
        
        # Store question if session exists
        if session:
            try:
                question_db_data = {
                    "session_id": session_id,
                    "question_type": "Coding",
                    "question": next_question.get("problem") or next_question.get("question") or json.dumps(next_question),
                    "question_number": next_question_number
                }
                supabase.table("interview_questions").insert(question_db_data).execute()
            except Exception as e:
                print(f"Warning: Could not store question: {str(e)}")

        await log_interview_transcript(
            supabase,
            session_id,
            "coding",
            next_question.get("problem") or next_question.get("question") or "",
            None
        )
        
        return {
            "question": next_question,
            "question_number": next_question_number,
            "total_questions": 5,
            "interview_completed": False
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting next coding question: {str(e)}")


@router.get("/coding/{session_id}/results")
async def get_coding_results(
    session_id: str,
    supabase: Client = Depends(get_supabase_client)
):
    """
    Get all coding interview results for a session
    """
    try:
        results_response = supabase.table("coding_results").select("*").eq("session_id", session_id).order("question_number").execute()
        results = results_response.data or []
        
        # Calculate overall statistics
        total_questions = len(results)
        correct_answers = sum(1 for r in results if r.get("correctness", False))
        total_score = sum(r.get("final_score", 0) for r in results)
        average_score = total_score / total_questions if total_questions > 0 else 0
        
        return {
            "session_id": session_id,
            "results": results,
            "statistics": {
                "total_questions": total_questions,
                "correct_answers": correct_answers,
                "incorrect_answers": total_questions - correct_answers,
                "total_score": total_score,
                "average_score": round(average_score, 2),
                "accuracy": round((correct_answers / total_questions * 100) if total_questions > 0 else 0, 2)
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching coding results: {str(e)}")


@router.post("/coding/run")
async def run_code(
    request: Dict[str, Any],
    supabase: Client = Depends(get_supabase_client)
):
    """
    Execute code safely in a sandboxed environment
    Accepts: {code, language, input}
    Returns: {output, error, execution_time}
    """
    try:
        code = request.get("code", "")
        language = request.get("language", "python")
        test_input = request.get("input", "")
        
        if not code:
            raise HTTPException(status_code=400, detail="code is required")
        
        if not language:
            raise HTTPException(status_code=400, detail="language is required")
        
        # Validate language
        supported_languages = ["python", "java", "javascript", "c", "cpp", "c++"]
        language_lower = language.lower()
        if language_lower not in supported_languages:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported language. Supported: {', '.join(supported_languages)}"
            )
        
        # Execute code based on language
        result = await execute_code_safely(code, language_lower, test_input)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error executing code: {str(e)}")


async def execute_code_safely(code: str, language: str, test_input: str) -> Dict[str, Any]:
    """
    Execute code safely using subprocess with timeout and resource limits
    Handles Windows and Unix systems properly
    """
    import subprocess
    import tempfile
    import time
    import shutil
    
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
            "c++": ".cpp"
        }.get(language, ".txt")
        
        # Create temp file in a temporary directory
        temp_dir = tempfile.mkdtemp()
        
        # For Java, extract class name and use it as filename
        if language == "java":
            import re
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
        
        try:
            start_time = time.time()
            
            # Execute based on language
            if language == "python":
                # Find python executable
                python_cmd = shutil.which("python") or shutil.which("python3") or "python"
                process = subprocess.run(
                    [python_cmd, tmp_file_path],
                    input=test_input,
                    capture_output=True,
                    text=True,
                    timeout=5,
                    cwd=temp_dir,
                    shell=False
                )
            elif language == "java":
                # Find javac and java executables
                javac_cmd = shutil.which("javac")
                java_cmd = shutil.which("java")
                
                if not javac_cmd or not java_cmd:
                    return {
                        "output": "",
                        "error": "Java compiler (javac) or runtime (java) not found. Please ensure Java JDK is installed and added to PATH.",
                        "execution_time": 0
                    }
                
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
                    compiler_name = "G++" if language in ["cpp", "c++"] else "GCC"
                    return {
                        "output": "",
                        "error": f"{compiler_name} compiler not found. Please ensure {compiler_name} is installed and added to PATH. On Windows, you can install MinGW or use Visual Studio Build Tools.",
                        "execution_time": 0
                    }
                
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
            else:
                raise HTTPException(status_code=400, detail=f"Language {language} execution not implemented")
            
            execution_time = time.time() - start_time
            
            return {
                "output": process.stdout,
                "error": process.stderr if process.returncode != 0 else "",
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
                print(f"[WARNING] Error cleaning up temp files: {cleanup_error}")
            
    except subprocess.TimeoutExpired:
        return {
            "output": "",
            "error": "Execution timeout (5 seconds exceeded)",
            "execution_time": 5.0
        }
    except FileNotFoundError as e:
        return {
            "output": "",
            "error": f"Required tool not found: {str(e)}. Please ensure the necessary compilers/runtimes are installed and in your PATH.",
            "execution_time": 0
        }
    except Exception as e:
        return {
            "output": "",
            "error": f"Execution error: {str(e)}",
            "execution_time": 0
        }