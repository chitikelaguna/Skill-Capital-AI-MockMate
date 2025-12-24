"""
STAR Interview endpoints
Contains all STAR (behavioral) interview flow endpoints
"""

from fastapi import APIRouter, HTTPException, Depends, Body
from supabase import Client
from app.db.client import get_supabase_client
from app.routers.interview_utils import build_resume_context_from_profile
from app.services.question_generator import question_generator
from app.services.answer_evaluator import answer_evaluator
from app.services.technical_interview_engine import technical_interview_engine
from typing import Dict, Any, List
import json
import logging
import urllib.parse
import re
from app.utils.url_utils import get_api_base_url
from app.config.settings import settings
from app.schemas.interview import (
    STARInterviewStartResponse,
    STARSubmitAnswerResponse,
    STARNextQuestionResponse,
    STARFeedbackResponse,
    InterviewEndResponse
)
from app.utils.rate_limiter import check_rate_limit, rate_limit_by_session_id
from app.utils.request_validator import validate_request_size
from fastapi import Request
from openai import OpenAI, APIError, RateLimitError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["star-interview"])



@router.post("/star/start", response_model=STARInterviewStartResponse)
async def start_star_interview(
    http_request: Request,
    request_body: Dict[str, Any] = Body(...),
    supabase: Client = Depends(get_supabase_client),
    _: None = Depends(validate_request_size)
):
    """
    Start a new STAR (behavioral) interview session
    Returns the first STAR question based on resume
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
        
        # user_id is now TEXT (slugified name), not UUID - no validation needed
        
        # Get user profile (required)
        profile_response = supabase.table("user_profiles").select("*").eq("user_id", user_id).execute()
        profile = profile_response.data[0] if profile_response.data else None
        
        if not profile:
            raise HTTPException(
                status_code=404,
                detail=f"User profile not found for user_id: {user_id}. Please upload a resume first to create your profile."
            )
        
        # Build resume context
        resume_context = build_resume_context_from_profile(profile, supabase)
        
        # Create session in database
        db_session_data = {
            "user_id": user_id,  # TEXT (slugified name)
            "interview_type": "star",
            "role": "STAR Interview",
            "experience_level": profile.get("experience_level", "Intermediate"),
            "skills": resume_context.get("skills", []),
            "session_status": "active"
        }
        
        try:
            session_response = supabase.table("interview_sessions").insert(db_session_data).execute()
            if not session_response.data or len(session_response.data) == 0:
                raise HTTPException(status_code=500, detail="Failed to create interview session")
            session_id = session_response.data[0]["id"]
        except Exception as db_error:
            error_str = str(db_error)
            if "foreign key constraint" in error_str.lower():
                raise HTTPException(
                    status_code=400,
                    detail=f"User profile not found. Please ensure user_id {user_id} exists in user_profiles table."
                )
            raise HTTPException(status_code=500, detail=f"Error creating interview session: {error_str}")
        
        # Generate first STAR question using question generator
        questions = question_generator.generate_questions(
            role="Behavioral Interview",
            experience_level=profile.get("experience_level", "Intermediate"),
            skills=resume_context.get("skills", []),
            resume_context=resume_context
        )
        
        # Filter for behavioral/STAR questions - InterviewQuestion is a Pydantic model, access attributes directly
        star_questions = [q for q in questions if q.type.lower() in ["hr", "behavioral", "star"]]
        if not star_questions:
            # Fallback STAR question - create InterviewQuestion object for consistency
            from app.schemas.interview import InterviewQuestion
            star_questions = [InterviewQuestion(type="STAR", question="Tell me about a time when you had to work under pressure.")]
        
        first_question = star_questions[0]
        
        # Extract question text - handle both InterviewQuestion objects and dicts
        question_text = first_question.question if hasattr(first_question, 'question') else first_question.get("question", "")
        
        # Store first question in star_round table
        question_db_data = {
            "user_id": str(user_id),
            "session_id": session_id,
            "question_number": 1,
            "question_text": question_text,
            "user_answer": "",  # Initialize with empty answer
            "star_structure_score": None,
            "situation_score": None,
            "task_score": None,
            "action_score": None,
            "result_score": None,
            "overall_score": None,
            "ai_feedback": None,
            "star_guidance": None,
            "improvement_suggestions": None,
            "response_time": None
        }
        
        try:
            supabase.table("star_round").insert(question_db_data).execute()
        except Exception as e:
            logger.warning(f"Failed to store STAR question: {str(e)}")
        
        # Generate audio URL for the question (same as HR interview)
        audio_url = None
        try:
            if question_text:
                encoded_text = urllib.parse.quote(question_text)
                base_url = get_api_base_url()
                audio_url = f"{base_url}/api/interview/text-to-speech?text={encoded_text}"
                logger.info(f"[STAR][INTERVIEW] ✅ Generated audio_url: {audio_url}")
            else:
                logger.error(f"[STAR][INTERVIEW] ❌ question_text is empty, cannot generate audio_url")
                audio_url = None
        except Exception as e:
            logger.error(f"[STAR][INTERVIEW] ❌ Could not generate audio URL: {str(e)}", exc_info=True)
            audio_url = None
        
        return {
            "session_id": session_id,
            "question": question_text,
            "question_type": "STAR",
            "question_number": 1,
            "total_questions": 10,  # STAR interviews support up to 10 questions
            "user_id": user_id,
            "audio_url": audio_url  # Include audio URL for TTS playback
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting STAR interview: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error starting STAR interview: {str(e)}")


@router.post("/star/{session_id}/submit-answer", response_model=STARSubmitAnswerResponse)
async def submit_star_answer(
    session_id: str,
    http_request: Request,
    request_body: Dict[str, Any] = Body(...),
    supabase: Client = Depends(get_supabase_client),
    _: None = Depends(validate_request_size)
):
    """
    Submit an answer to the current STAR question
    Uses STAR-specific evaluation and stores in star_round table
    """
    try:
        # Input validation
        if not session_id or not isinstance(session_id, str) or not session_id.strip():
            logger.error(f"[STAR][SUBMIT-ANSWER] Invalid session_id: {session_id}")
            raise HTTPException(status_code=400, detail="Invalid request format. Please check your input and try again.")
        
        question = request_body.get("question") or request_body.get("question_text")
        answer = request_body.get("answer") or request_body.get("user_answer")
        
        # Accept "No Answer" as valid answer, reject only truly empty answers
        if not answer or not isinstance(answer, str):
            logger.error(f"[STAR][SUBMIT-ANSWER] Empty or invalid answer in request - rejecting")
            raise HTTPException(status_code=400, detail="I could not hear your answer. Please speak again.")
        
        # Allow "No Answer" exactly as-is (case-sensitive check)
        if answer.strip() == "" and answer != "No Answer":
            logger.error(f"[STAR][SUBMIT-ANSWER] Empty or whitespace-only answer - rejecting")
            raise HTTPException(status_code=400, detail="I could not hear your answer. Please speak again.")
        
        logger.info(f"[STAR][SUBMIT-ANSWER] Submitting answer for session_id: {session_id}")
        
        # Get session
        try:
            session_response = supabase.table("interview_sessions").select("*").eq("id", session_id).execute()
        except Exception as db_error:
            logger.error(f"[STAR][SUBMIT-ANSWER] Database error fetching session: {str(db_error)}", exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to retrieve interview session. Please try again.")
        
        if not session_response.data or len(session_response.data) == 0:
            logger.warning(f"[STAR][SUBMIT-ANSWER] Session not found: {session_id}")
            raise HTTPException(status_code=404, detail="Interview session not found. Please start a new interview.")
        
        session = session_response.data[0]
        
        # Validate session is STAR type
        session_type = session.get("interview_type", "").lower()
        if session_type != "star":
            logger.error(f"[STAR][SUBMIT-ANSWER] Wrong session type: {session_type} (expected: star)")
            raise HTTPException(
                status_code=400, 
                detail="This endpoint is for STAR interviews only. Please use the correct interview type."
            )
        
        # Get current question from star_round table
        try:
            questions_response = supabase.table("star_round").select("*").eq("session_id", session_id).order("question_number", desc=True).limit(1).execute()
        except Exception as db_error:
            logger.error(f"[STAR][SUBMIT-ANSWER] Database error fetching question: {str(db_error)}", exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to submit answer due to a server error. Please try again.")
        
        if not questions_response.data or len(questions_response.data) == 0:
            logger.warning(f"[STAR][SUBMIT-ANSWER] No question found in star_round for session_id={session_id}")
            raise HTTPException(
                status_code=404, 
                detail="No current question found for this session. Please start a new interview."
            )
        
        current_question_db = questions_response.data[0]
        question_number = current_question_db["question_number"]
        question_text = current_question_db.get("question_text", question)
        
        if not question_text or not question_text.strip():
            question_text = question
            if not question_text or not question_text.strip():
                logger.error(f"[STAR][SUBMIT-ANSWER] Both DB and request have empty question text")
                raise HTTPException(
                    status_code=400,
                    detail="Question text is missing. Please start a new interview."
                )
        
        # Get experience level for evaluation
        experience_level = session.get("experience_level", "Intermediate")
        response_time = request_body.get("response_time")
        
        # For "No Answer", set all scores to 0
        if answer == "No Answer":
            logger.debug(f"[STAR][SUBMIT-ANSWER] Setting all scores to 0 for 'No Answer'")
            from app.schemas.interview import AnswerScore
            scores = AnswerScore(
                relevance=0,
                confidence=0,
                technical_accuracy=0,
                communication=0,
                overall=0,
                feedback="No answer provided."
            )
        else:
            # Evaluate answer using STAR-specific evaluation
            scores = answer_evaluator.evaluate_answer(
                question=question_text,
                question_type="STAR",
                answer=answer,
                experience_level=experience_level,
                response_time=response_time
            )
        
        logger.info(f"[STAR][SUBMIT-ANSWER] Answer evaluated - Overall: {scores.overall}")
        
        # Generate AI response
        ai_response = None
        if answer == "No Answer":
            ai_response = "Let's continue with the next question."
        else:
            # Use OpenAI to generate STAR-specific feedback
            if technical_interview_engine.openai_available and technical_interview_engine.client is not None:
                try:
                    system_prompt = """You are an experienced behavioral interviewer providing feedback on STAR method answers.
Provide brief, encouraging, and constructive feedback (1-2 sentences) that:
- Acknowledges what the candidate said
- Provides gentle guidance on STAR structure if needed
- Maintains a positive, professional tone
- Focuses on Situation, Task, Action, Result structure"""
                    
                    user_prompt = f"""Question: {question_text}
Candidate Answer: {answer}
Overall Score: {scores.overall}/100
                    
Provide brief, encouraging feedback for this STAR interview answer."""
                    
                    response = technical_interview_engine.client.chat.completions.create(
                        model="gpt-3.5-turbo",
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        temperature=0.7,
                        max_tokens=150,
                        timeout=30
                    )
                    
                    ai_response = response.choices[0].message.content.strip()
                    logger.info(f"[STAR][SUBMIT-ANSWER] AI response generated: {ai_response[:50]}...")
                    
                except Exception as e:
                    logger.warning(f"[STAR][SUBMIT-ANSWER] Could not generate AI response: {str(e)}")
                    ai_response = "Thank you for your answer. Let's continue with the next question."
            else:
                ai_response = "Thank you for your answer. Let's continue with the next question."
        
        # Generate audio URL for AI response
        ai_response_audio_url = None
        if ai_response:
            try:
                encoded_text = urllib.parse.quote(ai_response)
                base_url = get_api_base_url()
                ai_response_audio_url = f"{base_url}/api/interview/text-to-speech?text={encoded_text}"
                logger.info(f"[STAR][SUBMIT-ANSWER] Generated AI response audio URL")
            except Exception as e:
                logger.warning(f"[STAR][SUBMIT-ANSWER] Could not generate audio URL: {str(e)}")
        
        # Update the existing question row in star_round table
        user_id = str(session.get("user_id", "")) if session else ""
        
        # Map scores to STAR-specific fields
        # For STAR, we evaluate: structure, situation, task, action, result
        # Map from answer_evaluator scores to STAR scores
        star_structure_score = scores.overall  # Overall structure adherence
        situation_score = scores.relevance  # How well situation was described
        task_score = scores.communication  # How well task was explained
        action_score = scores.technical_accuracy  # How well actions were described
        result_score = scores.overall  # How well results were presented
        overall_score = scores.overall
        
        update_data = {
            "user_answer": answer,
            "star_structure_score": star_structure_score,
            "situation_score": situation_score,
            "task_score": task_score,
            "action_score": action_score,
            "result_score": result_score,
            "overall_score": overall_score,
            "ai_feedback": ai_response if ai_response else scores.feedback,
            "response_time": response_time
        }
        
        try:
            answer_response = supabase.table("star_round").update(update_data).eq("session_id", str(session_id)).eq("question_number", int(question_number)).execute()
            
            if not answer_response.data or len(answer_response.data) == 0:
                logger.error(f"[STAR][SUBMIT-ANSWER] ❌ Update returned no rows")
                raise HTTPException(status_code=500, detail="Failed to save answer to database. Please try again.")
            
            logger.info(f"[STAR][SUBMIT-ANSWER] ✅ Answer saved successfully")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[STAR][SUBMIT-ANSWER] Database error updating answer: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to save answer to database. Please try again.")
        
        # Check if interview should be completed (max 10 questions for STAR)
        STAR_MAX_QUESTIONS = 10
        questions_response = supabase.table("star_round").select("question_number").eq("session_id", session_id).execute()
        total_questions = len(questions_response.data) if questions_response.data else 0
        interview_completed = total_questions >= STAR_MAX_QUESTIONS
        
        # Update session status if completed
        # Use atomic update with row-level locking: only update if status is not already "completed"
        if interview_completed:
            try:
                update_response = supabase.table("interview_sessions").update({
                    "session_status": "completed"
                }).eq("id", session_id).neq("session_status", "completed").execute()
                
                if update_response.data and len(update_response.data) > 0:
                    logger.info(f"[STAR][SUBMIT-ANSWER] ✅ Session marked as completed")
                else:
                    logger.info(f"[STAR][SUBMIT-ANSWER] Session already completed")
            except Exception as e:
                logger.warning(f"[STAR][SUBMIT-ANSWER] Could not update session status: {str(e)}")
        
        return {
            "answer_id": answer_response.data[0].get("id"),
            "session_id": session_id,
            "question_number": question_number,
            "scores": {
                "star_structure": star_structure_score,
                "situation": situation_score,
                "task": task_score,
                "action": action_score,
                "result": result_score,
                "overall": overall_score
            },
            "ai_response": ai_response,
            "audio_url": ai_response_audio_url,
            "feedback": scores.feedback,
            "interview_completed": interview_completed,
            "response_time": response_time
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[STAR][SUBMIT-ANSWER] Unexpected error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to submit answer. Please try again.")


@router.post("/star/{session_id}/next-question", response_model=STARNextQuestionResponse)
async def get_next_star_question(
    session_id: str,
    http_request: Request,
    request_body: Dict[str, Any] = Body(...),
    supabase: Client = Depends(get_supabase_client),
    _: None = Depends(validate_request_size)
):
    """
    Get the next STAR question for the interview
    Accepts user_answer in request body, saves it first, then generates context-aware next question
    """
    try:
        # Input validation
        if not session_id or not isinstance(session_id, str) or not session_id.strip():
            logger.error(f"[STAR][NEXT-QUESTION] Invalid session_id: {session_id}")
            raise HTTPException(status_code=400, detail="Invalid request format. Please check your input and try again.")
        
        logger.info(f"[STAR][NEXT-QUESTION] Request for session_id: {session_id}")
        
        # Get session
        try:
            session_response = supabase.table("interview_sessions").select("*").eq("id", session_id).execute()
        except Exception as db_error:
            logger.error(f"[STAR][NEXT-QUESTION] Database error fetching session: {str(db_error)}", exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to retrieve interview session. Please try again.")
        
        if not session_response.data or len(session_response.data) == 0:
            logger.warning(f"[STAR][NEXT-QUESTION] Session not found: {session_id}")
            raise HTTPException(status_code=404, detail="Interview session not found. Please start a new interview.")
        
        session = session_response.data[0]
        
        # Validate session is STAR type
        session_type = session.get("interview_type", "").lower()
        if session_type != "star":
            logger.error(f"[STAR][NEXT-QUESTION] Wrong session type: {session_type} (expected: star)")
            raise HTTPException(
                status_code=400, 
                detail="This endpoint is for STAR interviews only. Please use the correct interview type."
            )
        
        # Save current answer if provided
        user_answer = request_body.get("user_answer") or request_body.get("answer")
        if user_answer and user_answer.strip() and user_answer != "No Answer":
            try:
                last_question_response = supabase.table("star_round").select("*").eq("session_id", session_id).order("question_number", desc=True).limit(1).execute()
                
                if last_question_response.data and len(last_question_response.data) > 0:
                    last_question = last_question_response.data[0]
                    question_number = last_question.get("question_number")
                    
                    update_data = {"user_answer": user_answer}
                    supabase.table("star_round").update(update_data).eq("session_id", session_id).eq("question_number", question_number).execute()
                    logger.info(f"[STAR][NEXT-QUESTION] ✅ Saved user answer for question {question_number}")
            except Exception as e:
                logger.warning(f"[STAR][NEXT-QUESTION] Failed to save user answer: {str(e)}")
        
        # Retrieve conversation history
        star_round_response = supabase.table("star_round").select(
            "question_text, question_number, user_answer"
        ).eq("session_id", session_id).order("question_number").execute()
        
        conversation_history = []
        questions_asked = []
        
        for row in (star_round_response.data or []):
            question_text = row.get("question_text", "")
            user_answer_text = row.get("user_answer", "")
            
            if question_text:
                conversation_history.append({"role": "ai", "content": question_text})
                questions_asked.append(question_text)
            
            if user_answer_text and user_answer_text.strip() and user_answer_text != "No Answer":
                conversation_history.append({"role": "user", "content": user_answer_text})
        
        # Check if interview should end (max 10 questions for STAR)
        STAR_MAX_QUESTIONS = 10
        current_question_count = len(questions_asked)
        
        if current_question_count >= STAR_MAX_QUESTIONS:
            logger.info(f"[STAR][NEXT-QUESTION] Interview completed: {current_question_count} questions already asked")
            return {
                "interview_completed": True,
                "message": "Interview completed. Maximum questions reached."
            }
        
        # Generate next STAR question
        next_question_number = current_question_count + 1
        user_id = session.get("user_id")
        
        # Get user profile for resume context
        profile_response = supabase.table("user_profiles").select("*").eq("user_id", user_id).execute()
        profile = profile_response.data[0] if profile_response.data else None
        
        resume_context = {}
        experience_level = "Intermediate"
        skills = []
        
        if profile:
            resume_context = build_resume_context_from_profile(profile, supabase)
            experience_level = profile.get("experience_level", "Intermediate")
            skills = resume_context.get("skills", [])
        
        # Generate next STAR question using OpenAI
        question_text = None
        try:
            if not settings.openai_api_key:
                logger.error("[STAR][NEXT-QUESTION] OpenAI API key is missing.")
                raise HTTPException(status_code=503, detail="AI service temporarily unavailable. API key not set.")
            
            client = OpenAI(api_key=settings.openai_api_key)
            
            skills_context = ", ".join(skills[:10]) if skills else "general skills"
            
            conversation_context = ""
            if conversation_history:
                recent_messages = conversation_history[-30:] if len(conversation_history) > 30 else conversation_history
                conversation_context = "\n".join([
                    f"{msg.get('role', 'unknown').upper()}: {msg.get('content', '')[:300]}"
                    for msg in recent_messages
                ])
            
            questions_list = ""
            if questions_asked:
                questions_list = "\n".join([f"{i+1}. {q[:150]}" for i, q in enumerate(questions_asked)])
            
            system_prompt = """You are an experienced behavioral interviewer conducting STAR method interviews.
Your interview style:
- Ask behavioral questions that require STAR method answers
- Focus on Situation, Task, Action, Result structure
- Build on previous answers when appropriate
- Reference the candidate's resume and experiences
- Keep questions concise (1-2 sentences) for voice interaction
- Never repeat questions that have already been asked"""
            
            user_prompt = f"""Generate the next STAR interview question for a behavioral interview.
            
CANDIDATE'S BACKGROUND (from resume):
Skills: {skills_context}
Experience Level: {experience_level}
            
CONVERSATION HISTORY:
{conversation_context if conversation_context else "This is the first question. Start with a foundational behavioral question."}
            
PREVIOUSLY ASKED QUESTIONS (do NOT repeat these):
{questions_list if questions_list else "None - this is the first question"}
            
INTERVIEW PROGRESS:
- Questions asked so far: {len(questions_asked)}
            
Generate ONE behavioral question that:
1. Requires a STAR method answer (Situation, Task, Action, Result)
2. Is relevant to behavioral interview topics
3. Has NOT been asked before
4. References the candidate's resume when relevant
5. Is appropriate for voice interaction (concise, clear)
            
Return ONLY the question text, nothing else."""
            
            messages = [{"role": "system", "content": system_prompt}]
            
            if conversation_history and len(conversation_history) > 0:
                history_messages = conversation_history[-30:] if len(conversation_history) > 30 else conversation_history
                for msg in history_messages:
                    role = msg.get("role", "user")
                    content = msg.get("content", "")
                    if role == "ai" or role == "assistant":
                        messages.append({"role": "assistant", "content": content[:500]})
                    elif role == "user":
                        messages.append({"role": "user", "content": content[:500]})
            
            messages.append({"role": "user", "content": user_prompt})
            
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=messages,
                temperature=0.7,
                max_tokens=150,
                timeout=30
            )
            
            question_text = response.choices[0].message.content.strip()
            logger.info(f"[STAR][INTERVIEW] Generated next question: {question_text[:50]}...")
            
        except RateLimitError as e:
            logger.error(f"[STAR][NEXT-QUESTION] OpenAI rate limit exceeded: {str(e)}")
            raise HTTPException(
                status_code=503, 
                detail="The AI service is currently experiencing high demand. Please try again shortly."
            )
        except APIError as e:
            logger.error(f"[STAR][NEXT-QUESTION] OpenAI API error: {str(e)}", exc_info=True)
            raise HTTPException(
                status_code=500, 
                detail="An external service error occurred during question generation. Please try again."
            )
        except Exception as e:
            logger.error(f"[STAR][NEXT-QUESTION] Unexpected error: {str(e)}", exc_info=True)
            question_text = None
        
        # Fallback to question generator if OpenAI failed
        if not question_text:
            try:
                questions = question_generator.generate_questions(
                    role="Behavioral Interview",
                    experience_level=experience_level,
                    skills=skills,
                    resume_context=resume_context
                )
                star_questions = [q for q in questions if q.type.lower() in ["hr", "behavioral", "star"]]
                if star_questions:
                    question_text = star_questions[0].question if hasattr(star_questions[0], 'question') else star_questions[0].get("question", "")
                else:
                    fallback_questions = [
                        "Tell me about a time when you had to work under pressure.",
                        "Describe a situation where you had to solve a difficult problem.",
                        "Give me an example of when you worked effectively in a team.",
                        "Tell me about a time when you had to lead a project.",
                        "Describe a challenging situation you faced at work."
                    ]
                    question_text = fallback_questions[len(questions_asked) % len(fallback_questions)]
            except Exception as fallback_error:
                logger.error(f"[STAR][INTERVIEW] Fallback question generation failed: {str(fallback_error)}")
                question_text = "Tell me about a time when you had to work under pressure."
        
        if not question_text:
            logger.error("[STAR][NEXT-QUESTION] Failed to generate question")
            raise HTTPException(status_code=500, detail="A server error occurred while processing your request. Please try again.")
        
        # Save new question in star_round table
        question_db_data = {
            "user_id": str(user_id),
            "session_id": session_id,
            "question_number": next_question_number,
            "question_text": question_text,
            "user_answer": "",
            "star_structure_score": None,
            "situation_score": None,
            "task_score": None,
            "action_score": None,
            "result_score": None,
            "overall_score": None,
            "ai_feedback": None,
            "star_guidance": None,
            "improvement_suggestions": None,
            "response_time": None
        }
        
        try:
            insert_response = supabase.table("star_round").insert(question_db_data).execute()
            if not insert_response.data or len(insert_response.data) == 0:
                logger.error(f"[STAR][NEXT-QUESTION] Failed to store question")
                raise HTTPException(status_code=500, detail="Failed to save interview data. Please try again.")
            logger.info(f"[STAR][NEXT-QUESTION] ✅ Saved new question {next_question_number}")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[STAR][NEXT-QUESTION] Failed to store question: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to save interview data. Please try again.")
        
        # Generate audio URL for question
        audio_url = None
        try:
            if question_text:
                encoded_text = urllib.parse.quote(question_text)
                base_url = get_api_base_url()
                audio_url = f"{base_url}/api/interview/text-to-speech?text={encoded_text}"
                logger.info(f"[STAR][NEXT-QUESTION] ✅ Generated audio_url for question {next_question_number}")
        except Exception as e:
            logger.error(f"[STAR][NEXT-QUESTION] ❌ Could not generate audio URL: {str(e)}", exc_info=True)
            try:
                base_url = get_api_base_url()
                if question_text:
                    encoded_text = urllib.parse.quote(question_text)
                    audio_url = f"{base_url}/api/interview/text-to-speech?text={encoded_text}"
            except Exception:
                audio_url = "/api/interview/text-to-speech?text="
        
        interview_completed = next_question_number > 10
        
        return {
            "question": question_text,
            "question_type": "STAR",
            "question_number": next_question_number,
            "total_questions": 10,
            "audio_url": audio_url,
            "interview_completed": interview_completed,
            "session_id": session_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[STAR][NEXT-QUESTION] Unexpected error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate next question. Please try again.")


@router.get("/star/{session_id}/feedback", response_model=STARFeedbackResponse)
async def get_star_interview_feedback(
    session_id: str,
    supabase: Client = Depends(get_supabase_client),
    _: None = Depends(rate_limit_by_session_id)
):
    """
    Get final feedback for completed STAR interview
    Returns STAR-specific feedback with structure, situation, task, action, and result scores
    """
    try:
        # Input validation
        if not session_id or not isinstance(session_id, str) or not session_id.strip():
            logger.error(f"[STAR FEEDBACK] Invalid session_id: {session_id}")
            raise HTTPException(status_code=400, detail="Invalid request format. Please check your input and try again.")
        
        logger.info(f"[STAR FEEDBACK] Requesting feedback for session_id: {session_id}")
        
        # Get session
        try:
            session_response = supabase.table("interview_sessions").select("*").eq("id", session_id).execute()
        except Exception as db_error:
            logger.error(f"[STAR FEEDBACK] Database error fetching session: {str(db_error)}", exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to retrieve interview session. Please try again.")
        
        if not session_response.data or len(session_response.data) == 0:
            logger.warning(f"[STAR FEEDBACK] Session not found: {session_id}")
            raise HTTPException(status_code=404, detail="Interview session not found. Please start a new interview.")
        
        session = session_response.data[0]
        
        # Validate session is STAR type
        session_type = session.get("interview_type", "").lower()
        if session_type != "star":
            logger.error(f"[STAR FEEDBACK] Wrong session type: {session_type} (expected: star)")
            raise HTTPException(
                status_code=400, 
                detail="This endpoint is for STAR interviews only. Please use the correct interview type."
            )
        
        # Get all answers from star_round table
        try:
            answers_response = supabase.table("star_round").select("*").eq("session_id", session_id).order("question_number").execute()
        except Exception as db_error:
            logger.error(f"[STAR FEEDBACK] Database error fetching answers: {str(db_error)}", exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to retrieve interview answers. Please try again.")
        
        answers = answers_response.data if answers_response.data else []
        
        if not answers:
            raise HTTPException(status_code=400, detail="No answers found for this session. Please complete the interview first.")
        
        # --- Detect valid vs. empty/too-short answers ---
        def is_valid_answer(answer_text: str) -> bool:
            """A STAR answer is valid if it has at least ~3 meaningful words (not empty/'No Answer')."""
            if not answer_text or not isinstance(answer_text, str):
                return False
            answer_text = answer_text.strip()
            if answer_text == "" or answer_text == "No Answer":
                return False
            words = [w for w in answer_text.split() if len(w) > 2]
            return len(words) >= 3
        
        valid_answers = []
        empty_answers = []
        for row in answers:
            user_answer = row.get("user_answer", "")
            if is_valid_answer(user_answer) and row.get("overall_score") is not None:
                valid_answers.append(row)
            else:
                empty_answers.append(row)
        
        # If NO valid answers at all → score = 0 and fixed feedback
        if len(valid_answers) == 0:
            logger.warning(f"[STAR FEEDBACK] ⚠️  No valid answers found - all {len(answers)} answers are empty/No Answer/too short")
            return {
                "overall_score": 0.0,
                "star_structure_score": 0.0,
                "situation_score": 0.0,
                "task_score": 0.0,
                "action_score": 0.0,
                "result_score": 0.0,
                "feedback_summary": "Interview ended early with no valid responses.",
                "strengths": ["No valid response detected."],
                "areas_for_improvement": ["Please provide spoken answers to receive accurate feedback."],
                "recommendations": ["Try answering all STAR questions with clear Situation, Task, Action, and Result."],
                "question_count": len(answers),
            }
        
        if len(empty_answers) > 0:
            logger.warning(f"[STAR FEEDBACK] ⚠️  {len(empty_answers)} empty/too short answers detected, using {len(valid_answers)} valid answers for feedback")
        
        # Use only valid answers for scoring and feedback
        answers = valid_answers
        
        # Calculate average scores from valid answers only
        total_star_structure = 0.0
        total_situation = 0.0
        total_task = 0.0
        total_action = 0.0
        total_result = 0.0
        total_overall = 0.0
        count = 0
        
        for answer in answers:
            total_star_structure += answer.get("star_structure_score", 0) or 0
            total_situation += answer.get("situation_score", 0) or 0
            total_task += answer.get("task_score", 0) or 0
            total_action += answer.get("action_score", 0) or 0
            total_result += answer.get("result_score", 0) or 0
            total_overall += answer.get("overall_score", 0) or 0
            count += 1
        
        if count == 0:
            # Safety: should not happen because of valid_answers check above
            logger.error("[STAR FEEDBACK] No scored valid answers after filtering")
            return {
                "overall_score": 0.0,
                "star_structure_score": 0.0,
                "situation_score": 0.0,
                "task_score": 0.0,
                "action_score": 0.0,
                "result_score": 0.0,
                "feedback_summary": "Interview ended early with no valid responses.",
                "strengths": ["No valid response detected."],
                "areas_for_improvement": ["Please provide spoken answers to receive accurate feedback."],
                "recommendations": ["Try answering all STAR questions with clear Situation, Task, Action, and Result."],
                "question_count": len(answers),
            }
        
        avg_star_structure = total_star_structure / count
        avg_situation = total_situation / count
        avg_task = total_task / count
        avg_action = total_action / count
        avg_result = total_result / count
        avg_overall = total_overall / count
        
        # Build conversation history & per-question summaries for LLM (personalised feedback)
        conversation_history: List[Dict[str, str]] = []
        qa_summaries: List[str] = []
        for idx, row in enumerate(answers, 1):
            q_text = (row.get("question_text") or "").strip()
            a_text = (row.get("user_answer") or "").strip()
            if q_text:
                conversation_history.append({"role": "ai", "content": q_text})
            if a_text:
                conversation_history.append({"role": "user", "content": a_text})
            scores = {
                "star_structure": row.get("star_structure_score"),
                "situation": row.get("situation_score"),
                "task": row.get("task_score"),
                "action": row.get("action_score"),
                "result": row.get("result_score"),
                "overall": row.get("overall_score"),
            }
            score_str = ", ".join(
                f"{name}={value:.1f}"
                for name, value in scores.items()
                if isinstance(value, (int, float))
            )
            qa_summaries.append(
                f"Q{idx}: {q_text}\nA{idx}: {a_text or 'No Answer'}\nScores: {score_str or 'n/a'}"
            )
        qa_block = "\n\n".join(qa_summaries)
        
        # Generate feedback summary using OpenAI (JSON structure)
        feedback_summary = ""
        strengths: List[str] = []
        areas_for_improvement: List[str] = []
        recommendations: List[str] = []
        
        try:
            if technical_interview_engine.openai_available and technical_interview_engine.client is not None:
                system_prompt = """
You are an expert behavioral interviewer and STAR-method coach.
You will receive the candidate's STAR interview transcript plus per-question STAR scores.
Your job is to produce a SHORT, CLEAR, and FULLY PERSONALIZED evaluation.

FOCUS AREAS (0–100 scores):
- STAR structure completeness (did they cover Situation, Task, Action, Result?)
- Clarity of each STAR component
- Relevance and impact of examples
- Communication and reflection.

YOU MUST output a JSON object only.
"""
                
                user_prompt = f"""
STAR INTERVIEW SESSION SUMMARY
------------------------------
Overall averages (0–100):
- Overall: {avg_overall:.1f}
- STAR Structure: {avg_star_structure:.1f}
- Situation: {avg_situation:.1f}
- Task: {avg_task:.1f}
- Action: {avg_action:.1f}
- Result: {avg_result:.1f}

Total STAR questions answered: {len(answers)}

Conversation History (chronological):
{chr(10).join([f"{msg.get('role', 'unknown').upper()}: {msg.get('content', '')[:300]}" for msg in conversation_history])}

Per-question detail with scores:
{qa_block}

TASK:
Using ONLY this information, return a JSON object with this shape:
{{
  "strengths": [
    "2–5 bullet points describing concrete strengths based on their STAR answers"
  ],
  "areas_for_improvement": [
    "2–5 bullet points pointing out missing/weak STAR components (S/T/A/R), vagueness, or poor examples"
  ],
  "recommendations": [
    "2–5 specific practice recommendations (e.g., add metrics, sharpen Situation, clarify Result, etc.)"
  ],
  "summary": "3–5 sentences summarising their overall STAR interview performance in natural language"
}}

CONSTRAINTS:
- Every bullet must be specific to THIS candidate's answers.
- Call out clearly if they often miss Situation, Task, Action, or Result.
- Mention clarity, relevance, and communication style where appropriate.
"""
                
                response = technical_interview_engine.client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": system_prompt.strip()},
                        {"role": "user", "content": user_prompt.strip()},
                    ],
                    temperature=0.5,
                    max_tokens=650,
                    timeout=30
                )
                
                raw_content = response.choices[0].message.content.strip()
                
                try:
                    feedback_data = json.loads(raw_content)
                except json.JSONDecodeError:
                    try:
                        start = raw_content.find("{")
                        end = raw_content.rfind("}")
                        if start != -1 and end != -1 and end > start:
                            feedback_data = json.loads(raw_content[start : end + 1])
                        else:
                            raise
                    except Exception:
                        logger.warning("[STAR FEEDBACK] AI returned non-JSON content, falling back to rule-based text")
                        feedback_data = {}
                
                strengths = feedback_data.get("strengths") or []
                areas_for_improvement = feedback_data.get("areas_for_improvement") or []
                recommendations = feedback_data.get("recommendations") or []
                feedback_summary = feedback_data.get("summary") or ""
                
        except Exception as e:
            logger.warning(f"[STAR FEEDBACK] Could not generate AI feedback: {str(e)}", exc_info=True)
        
        # Fallback or supplement when OpenAI is not available OR AI parsing failed.
        if not feedback_summary or not (strengths or areas_for_improvement or recommendations):
            # If everything scored extremely low, treat as almost no effective answer
            if avg_overall <= 1:
                feedback_summary = "Interview ended early with no valid responses."
                strengths = ["No valid response detected."]
                areas_for_improvement = ["Please provide spoken answers to receive accurate feedback."]
                recommendations = ["Try answering all STAR questions with clear Situation, Task, Action, and Result."]
            else:
                feedback_summary = f"Overall STAR interview performance score: {avg_overall:.1f}/100. "
                # Simple rule-based analysis of STAR dimensions
                if avg_star_structure >= 75:
                    strengths.append("You generally followed the STAR structure and kept your stories organised.")
                elif avg_star_structure < 60:
                    areas_for_improvement.append("Your answers did not consistently cover all STAR parts (Situation, Task, Action, Result).")
                    recommendations.append("Practice structuring each answer explicitly into Situation, Task, Action, and Result.")
                
                if avg_situation >= 75:
                    strengths.append("You set up the Situation clearly so the listener understood the context.")
                elif avg_situation < 60:
                    areas_for_improvement.append("Situations were sometimes vague or missing important context.")
                
                if avg_task >= 75:
                    strengths.append("You explained your responsibilities and goals in each story well.")
                elif avg_task < 60:
                    areas_for_improvement.append("Tasks or objectives were not always clearly described.")
                
                if avg_action >= 75:
                    strengths.append("You described your Actions in good detail, showing what you personally did.")
                elif avg_action < 60:
                    areas_for_improvement.append("Actions were sometimes high-level; add more specific steps you took.")
                
                if avg_result >= 75:
                    strengths.append("You highlighted strong Results and impact in your examples.")
                elif avg_result < 60:
                    areas_for_improvement.append("Results were often missing or lacked clear outcomes/metrics.")
                
                if strengths:
                    feedback_summary += f"Key strengths: {', '.join(strengths[:2])}. "
                if areas_for_improvement:
                    feedback_summary += f"Key areas to improve: {', '.join(areas_for_improvement[:2])}."
                
                if not recommendations:
                    recommendations.append("Prepare 3–5 STAR stories with clear outcomes and practice saying them out loud.")
        
        return {
            "overall_score": round(avg_overall, 2),
            "star_structure_score": round(avg_star_structure, 2),
            "situation_score": round(avg_situation, 2),
            "task_score": round(avg_task, 2),
            "action_score": round(avg_action, 2),
            "result_score": round(avg_result, 2),
            "feedback_summary": feedback_summary,
            "strengths": strengths[:5],
            "areas_for_improvement": areas_for_improvement[:5],
            "recommendations": recommendations[:5],
            "question_count": len(answers)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[STAR FEEDBACK] Unexpected error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve feedback. Please try again.")


@router.put("/star/{session_id}/end", response_model=InterviewEndResponse)
async def end_star_interview(
    session_id: str,
    supabase: Client = Depends(get_supabase_client)
):
    """
    End the STAR interview session
    Updates session status to completed
    """
    try:
        # Input validation
        if not session_id or not isinstance(session_id, str) or not session_id.strip():
            logger.error(f"[STAR][END] Invalid session_id: {session_id}")
            raise HTTPException(status_code=400, detail="Invalid request format. Please check your input and try again.")
        
        logger.info(f"[STAR][END] Ending STAR interview session: {session_id}")
        
        # Verify session exists and is STAR type
        try:
            session_response = supabase.table("interview_sessions").select("*").eq("id", session_id).execute()
        except Exception as db_error:
            logger.error(f"[STAR][END] Database error fetching session: {str(db_error)}", exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to retrieve interview session. Please try again.")
        
        if not session_response.data or len(session_response.data) == 0:
            logger.warning(f"[STAR][END] Session not found: {session_id}")
            raise HTTPException(status_code=404, detail="Interview session not found. Please start a new interview.")
        
        session = session_response.data[0]
        
        # Validate session is STAR type
        session_type = session.get("interview_type", "").lower()
        if session_type != "star":
            logger.error(f"[STAR][END] Wrong session type: {session_type} (expected: star)")
            raise HTTPException(
                status_code=400, 
                detail="This endpoint is for STAR interviews only. Please use the correct interview type."
            )
        
        # Update session status to completed with atomic update (row-level locking)
        try:
            update_response = supabase.table("interview_sessions").update({
                "session_status": "completed"
            }).eq("id", session_id).neq("session_status", "completed").execute()
            
            if not update_response.data or len(update_response.data) == 0:
                logger.info(f"[STAR][END] Session already completed for session_id: {session_id}")
            else:
                logger.info(f"[STAR][END] ✅ STAR interview session ended successfully: {session_id}")
        except Exception as e:
            logger.error(f"[STAR][END] Error updating session status: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to end interview session. Please try again.")
        
        return {
            "message": "STAR interview session ended successfully",
            "session_id": session_id,
            "status": "completed"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[STAR][END] Unexpected error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to end interview session. Please try again.")

