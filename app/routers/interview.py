"""
Interview routes
"""

from fastapi import APIRouter, HTTPException, Depends
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
    InterviewEvaluationResponse
)
from app.services.topic_generator import topic_generator
from app.services.question_generator import question_generator
from app.services.answer_evaluator import answer_evaluator
from app.services.interview_evaluator import interview_evaluator
from app.services.resume_parser import resume_parser
from app.utils.database import (
    get_user_profile,
    get_interview_session,
    get_question_by_number,
    get_all_answers_for_session,
    batch_insert_questions
)
from app.utils.datetime_utils import parse_datetime, get_current_timestamp
from app.utils.exceptions import NotFoundError, ValidationError, DatabaseError
from typing import Optional
from datetime import datetime
import uuid
import tempfile
import os

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

