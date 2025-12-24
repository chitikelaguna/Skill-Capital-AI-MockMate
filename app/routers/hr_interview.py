"""
HR Interview Routes
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Body
from fastapi.responses import JSONResponse
from typing import Any, Dict, List
from supabase import Client
from app.db.client import get_supabase_client
from app.routers.interview_utils import (
    test_supabase_connection,
    build_resume_context_from_profile,
    log_interview_transcript,
    HR_WARMUP_QUESTIONS,
    HR_WARMUP_COUNT
)
from app.utils.url_utils import get_api_base_url
from app.utils.exceptions import ValidationError, NotFoundError, DatabaseError
from app.config.settings import settings
from app.services.question_generator import question_generator
from app.services.answer_evaluator import answer_evaluator
from app.services.technical_interview_engine import technical_interview_engine
from app.schemas.interview import (
    HRInterviewStartResponse,
    HRSubmitAnswerResponse,
    HRNextQuestionResponse,
    HRFeedbackResponse,
    InterviewEndResponse,
    AnswerScore
)
from app.utils.rate_limiter import check_rate_limit, rate_limit_by_session_id
from app.utils.request_validator import validate_request_size
from fastapi import Request
from openai import OpenAI, APIError, RateLimitError
from datetime import datetime
import urllib.parse
import json
import logging
import traceback
import re

logger = logging.getLogger("hr_interview")

router = APIRouter(prefix="/hr", tags=["hr-interview"])


@router.post("/start", response_model=HRInterviewStartResponse)
async def start_hr_interview(
    http_request: Request,
    request_body: Dict[str, Any] = Body(...),
    supabase: Client = Depends(get_supabase_client),
    _: None = Depends(validate_request_size)
):
    """
    Start a new HR interview session
    Returns the first HR question based on resume
    """
    try:
        # Guard check: Validate Supabase configuration before database calls
        if not settings.supabase_service_key and not settings.supabase_key:
            logger.error("[HR][START] Supabase keys missing: VERCEL env may be unset")
            logger.error("[HR][START] SUPABASE_SERVICE_KEY: Missing")
            logger.error("[HR][START] SUPABASE_KEY (anon): Missing")
            logger.error("[HR][START] This will cause database operations to fail")
            return JSONResponse(
                status_code=500,
                content={
                    "error": "supabase_misconfigured",
                    "detail": "Supabase configuration missing. Please check environment variables."
                }
            )
        
        # Log Supabase user context (service role vs anon)
        if settings.supabase_service_key:
            logger.debug("[HR][START] Using Supabase service role client (bypasses RLS)")
        elif settings.supabase_key:
            logger.debug("[HR][START] Using Supabase anon key client (respects RLS)")
        
        # FIX 12: Test database connection at the start
        if not test_supabase_connection(supabase):
            raise HTTPException(
                status_code=503,
                detail="Database connection unavailable. Please try again shortly."
            )
        # Input validation
        user_id = request_body.get("user_id")
        
        if not user_id:
            logger.warning("[HR][START] Missing user_id in request body")
            raise ValidationError("Missing required information in the request. Please ensure all fields are provided.")
        
        if not isinstance(user_id, str) or not user_id.strip():
            logger.warning(f"[HR][START] Invalid user_id format: {user_id}")
            raise ValidationError("Invalid request format. Please check your input and try again.")
        
        # Validate user_id format: alphanumeric, hyphen, underscore only
        if not re.match(r'^[a-zA-Z0-9_-]+$', user_id):
            raise ValidationError("Invalid user_id format")
        
        # Check rate limit
        check_rate_limit(user_id)
        
        logger.info(f"[HR][START] Starting HR interview for user_id: {user_id}")
        
        # user_id is now TEXT (slugified name), not UUID - no validation needed
        
        # Get user profile (required)
        try:
            profile_response = supabase.table("user_profiles").select("*").eq("user_id", user_id).execute()
            profile = profile_response.data[0] if profile_response.data else None
        except Exception as db_error:
            # Log detailed error information for debugging
            logger.error(
                f"[HR][START] Database error fetching user profile for user_id: {user_id}. Error: {str(db_error)}\n{traceback.format_exc()}", 
                exc_info=True
            )
            
            # Raise DatabaseError for structured error handling
            raise DatabaseError(f"Failed to start interview due to a server error. Please try again.")
        
        if not profile:
            raise NotFoundError("User profile", user_id)
        
        # Build resume context
        resume_context = build_resume_context_from_profile(profile, supabase)
        
        # Create session in database
        db_session_data = {
            "user_id": user_id,  # TEXT (slugified name)
            "interview_type": "hr",
            "role": "HR Interview",
            "experience_level": profile.get("experience_level", "Intermediate"),
            "skills": resume_context.get("skills", []),
            "session_status": "active"
        }
        
        try:
            session_response = supabase.table("interview_sessions").insert(db_session_data).execute()
            if not session_response.data or len(session_response.data) == 0:
                logger.error("[HR][START] Failed to create interview session - no data returned")
                raise DatabaseError("A server error occurred while processing your request. Please try again.")
            session_id = session_response.data[0]["id"]
        except ValidationError:
            # Re-raise ValidationError as-is (from foreign key constraint check)
            raise
        except Exception as db_error:
            error_str = str(db_error)
            logger.error(f"[HR][START] Database error creating session: {str(db_error)}\n{traceback.format_exc()}", exc_info=True)
            if "foreign key constraint" in error_str.lower():
                raise ValidationError("User profile not found. Please upload a resume first to create your profile.")
            raise DatabaseError("A server error occurred while processing your request. Please try again.")
        
        # ✅ WARM-UP STAGE: Always start with first warm-up question (question_number = 1)
        # Warm-up questions help students and freshers feel relaxed and confident
        question_text = HR_WARMUP_QUESTIONS[0]  # "Tell me about yourself."
        logger.info(f"[HR][START] ✅ Starting with warm-up question 1/3: {question_text}")
        
        # Generate audio URL for the question BEFORE storing (same as technical interview)
        audio_url = None
        try:
            if question_text:
                encoded_text = urllib.parse.quote(question_text)
                # ✅ CRITICAL FIX: Use TECH_BACKEND_URL if set, otherwise use request-based URL detection
                # This ensures correct domain resolution on Vercel (matches Technical Interview pattern)
                base_url = settings.tech_backend_url or get_api_base_url(http_request)
                # Ensure base_url doesn't end with slash
                base_url = base_url.rstrip('/')
                audio_url = f"{base_url}/api/interview/text-to-speech?text={encoded_text}"
                logger.info(f"[HR][INTERVIEW] ✅ Generated audio_url: {audio_url}")
                logger.info(f"[HR][INTERVIEW] Base URL: {base_url}, Question text length: {len(question_text)}")
                logger.info(f"[HR][INTERVIEW] Question text preview: {question_text[:50]}...")
            else:
                logger.error(f"[HR][INTERVIEW] ❌ question_text is empty, cannot generate audio_url")
                audio_url = None  # FIX 18: Explicitly set to None
        except Exception as e:
            # FIX 18: Log error and explicitly set audio_url to None to guarantee endpoint continues
            logger.error(f"[HR][INTERVIEW] ❌ Could not generate audio URL for HR question: {str(e)}", exc_info=True)
            audio_url = None  # Explicitly set to None to ensure endpoint continues
        
        # Store first question in hr_round table (question_number = 1, supports up to 10 questions)
        question_db_data = {
            "user_id": str(user_id),
            "session_id": session_id,
            "question_number": 1,  # First question
            "question_text": question_text,
            "question_category": "HR",
            "user_answer": "",  # Initialize with empty answer
            "communication_score": None,
            "cultural_fit_score": None,
            "motivation_score": None,
            "clarity_score": None,
            "overall_score": None,
            "ai_feedback": None,
            "response_time": None
        }
        
        # ✅ FIX 1: Make question saving mandatory - fail fast if save fails
        try:
            insert_response = supabase.table("hr_round").insert(question_db_data).execute()
            if not insert_response.data or len(insert_response.data) == 0:
                logger.error("[HR][START] Failed to store HR question - no data returned from insert")
                raise DatabaseError("Failed to save interview question. Please try again.")
            # ✅ FIX 1: Verify question_number is correctly saved
            saved_question = insert_response.data[0] if insert_response.data else None
            if saved_question:
                saved_question_number = saved_question.get('question_number')
                logger.info(f"[HR][START] ✅ Stored first HR question in database (question_number={saved_question_number})")
                logger.info(f"[HR][START] Saved row ID: {saved_question.get('id')}, session_id: {saved_question.get('session_id')}")
                if saved_question_number != 1:
                    logger.warning(f"[HR][START] ⚠️ Expected question_number=1, but got {saved_question_number}")
            else:
                logger.warning(f"[HR][START] ⚠️ Insert succeeded but no data returned")
        except (ValidationError, NotFoundError, DatabaseError):
            # Re-raise custom exceptions as-is
            raise
        except Exception as e:
            logger.error(f"[HR][START] Failed to store HR question: {str(e)}\n{traceback.format_exc()}", exc_info=True)
            # ✅ FIX 1: Do NOT continue if storage fails - raise error immediately
            raise DatabaseError("Failed to save interview question. Please try again.")
        
        # Harmonize response shape with Technical interview endpoint
        # Core fields matching Technical: session_id, question, audio_url
        # Additional HR-specific fields preserved for backwards compatibility
        # ✅ CRITICAL: Ensure all required keys are always present (set to None if missing)
        response_data = {
            "session_id": session_id if session_id else None,
            "question": question_text if question_text else None,  # Primary key matching Technical
            "first_question": question_text if question_text else None,  # Alias for frontend compatibility (always present)
            "question_type": "HR",
            "question_number": 1,
            "total_questions": HR_WARMUP_COUNT + 7,  # 3 warm-up + 7 resume-based = 10 total
            "interview_completed": False,  # First question, interview not completed
            "is_warmup": True,  # Indicate this is a warm-up question (HR-specific)
            "user_id": user_id,
            "audio_url": audio_url if audio_url else None  # Ensure audio_url is always present (null if not available)
        }
        
        # ✅ CRITICAL: Verify required keys are present (fail-fast if missing)
        if response_data["session_id"] is None:
            logger.error("[HR][START] ❌ session_id is None in response_data")
        if response_data["first_question"] is None:
            logger.warning("[HR][START] ⚠️ first_question is None in response_data")
        if response_data["audio_url"] is None:
            logger.warning("[HR][START] ⚠️ audio_url is None in response_data")
        
        # ✅ CRITICAL: Debug log (matches Technical Interview pattern)
        print("HR start response:", response_data)
        logger.debug(f"[HR][START] Response payload: {response_data}")
        logger.info(f"[HR][START] ✅ Returning response with session_id: {response_data['session_id'] is not None}, first_question: {response_data['first_question'] is not None}, audio_url: {response_data['audio_url'] is not None}")
        logger.info(f"[HR][START] Response keys (harmonized with Technical): {list(response_data.keys())}")
        
        return response_data
        
    except ValidationError as e:
        logger.warning("HR start validation error: %s", str(e))
        return JSONResponse(
            status_code=400,
            content={"error": "validation", "detail": str(e)}
        )
    except NotFoundError as e:
        logger.warning("HR start not found: %s", str(e))
        return JSONResponse(
            status_code=404,
            content={"error": "not_found", "detail": str(e)}
        )
    except DatabaseError as e:
        tb = traceback.format_exc()
        logger.error("HR start db error: %s\n%s", str(e), tb)
        return JSONResponse(
            status_code=500,
            content={"error": "db_error", "detail": "internal"}
        )
    except HTTPException:
        # Re-raise HTTPException as-is (for 503 database connection errors, etc.)
        raise
    except Exception as e:
        tb = traceback.format_exc()
        logger.exception("HR start unexpected error: %s", str(e))
        return JSONResponse(
            status_code=500,
            content={"error": "unexpected", "detail": str(e), "trace": tb}
        )


@router.post("/{session_id}/next-question", response_model=HRNextQuestionResponse)
async def get_next_hr_question(
    session_id: str,
    http_request: Request,
    request_body: Dict[str, Any] = Body(...),
    supabase: Client = Depends(get_supabase_client),
    _: None = Depends(validate_request_size)
):
    """
    Get the next HR question for the interview
    Accepts user_answer in request body, saves it first, then generates context-aware next question
    Uses conversation history from database to enable context-aware follow-up questions
    """
    # FIX 12: Test database connection at the start
    if not test_supabase_connection(supabase):
        raise HTTPException(
            status_code=503,
            detail="Database connection unavailable. Please try again shortly."
        )
    
    try:
        # Input validation
        if not session_id or not isinstance(session_id, str) or not session_id.strip():
            logger.error(f"[HR][NEXT-QUESTION] Invalid session_id: {session_id}")
            raise HTTPException(status_code=400, detail="Invalid request format. Please check your input and try again.")
        
        logger.info(f"[HR][NEXT-QUESTION] Request for session_id: {session_id}")
        logger.debug(f"[HR][NEXT-QUESTION] Request body keys: {list(request_body.keys())}")
        
        # Get session
        try:
            session_response = supabase.table("interview_sessions").select("*").eq("id", session_id).execute()
        except Exception as db_error:
            logger.error(f"[HR][NEXT-QUESTION] Database error fetching session: {str(db_error)}", exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to retrieve interview session. Please try again.")
        
        if not session_response.data or len(session_response.data) == 0:
            logger.warning(f"[HR][NEXT-QUESTION] Session not found: {session_id}")
            raise HTTPException(status_code=404, detail="Interview session not found. Please start a new interview.")
        
        session = session_response.data[0]
        
        # FIX 19: Check if session is already completed
        session_status = session.get("session_status", "").lower()
        if session_status == "completed":
            logger.warning(f"[HR][NEXT-QUESTION] Session already completed: {session_id}")
            raise HTTPException(
                status_code=400,
                detail="This interview session has already been completed. Please start a new interview."
            )
        
        # Validate session is HR type
        session_type = session.get("interview_type", "").lower()
        if session_type != "hr":
            logger.error(f"[HR][NEXT-QUESTION] Wrong session type: {session_type} (expected: hr)")
            raise HTTPException(
                status_code=400, 
                detail="This endpoint is for HR interviews only. Please use the correct interview type."
            )
        
        # Step 1: Save current answer if provided in request
        # FIX: Retrieve the answer using common keys
        user_answer = request_body.get("user_answer") or request_body.get("answer")
        
        # FIX: Implement type validation
        if user_answer is not None:
            # Validate user_answer type
            if not isinstance(user_answer, str):
                logger.warning(f"[HR][NEXT-QUESTION] Invalid user_answer type received: {type(user_answer)}. Attempting conversion.")
                
                # Attempt to convert to string if not None; otherwise, set to None
                try:
                    user_answer = str(user_answer) 
                except Exception:
                    user_answer = None
                    
            # ✅ FIX: Reject empty answers - NO random/auto-answers allowed
            if user_answer and user_answer.strip():
                # The answer is valid and non-empty. Proceed with saving and processing.
                # FIX 13 & 17: Save answer before building conversation history (transaction pattern)
                try:
                    # Get the last question for this session to update with the answer
                    last_question_response = supabase.table("hr_round").select("*").eq("session_id", session_id).order("question_number", desc=True).limit(1).execute()
                    
                    if last_question_response.data and len(last_question_response.data) > 0:
                        last_question = last_question_response.data[0]
                        question_number = last_question.get("question_number")
                        
                        # Update the last question with the user's answer
                        update_data = {
                            "user_answer": user_answer
                        }
                        
                        supabase.table("hr_round").update(update_data).eq("session_id", session_id).eq("question_number", question_number).execute()
                        logger.info(f"[HR][NEXT-QUESTION] ✅ Saved user answer for question {question_number}")
                    else:
                        logger.warning("[HR][NEXT-QUESTION] No question found to update with answer")
                except Exception as e:
                    # FIX 13: Log error and raise HTTPException to maintain data consistency
                    logger.error(f"[HR][NEXT-QUESTION] Failed to save user answer: {str(e)}", exc_info=True)
                    raise HTTPException(
                        status_code=500,
                        detail="Failed to save interview data. Please try again."
                    )
            else:
                # ✅ FIX: Reject empty answers - do NOT allow unanswered questions to move forward
                logger.warning("[HR][NEXT-QUESTION] Empty answer provided - rejecting request")
                raise HTTPException(
                    status_code=400,
                    detail="I could not hear your answer. Please speak again."
                )
        
        # FIX 17: Step 2: Retrieve full conversation history from hr_round table AFTER saving answer
        hr_round_response = supabase.table("hr_round").select(
            "question_text, question_number, user_answer"
        ).eq("session_id", session_id).order("question_number").execute()
        
        # Step 3: Build conversation history array in exact format for LLM
        conversation_history = []
        questions_asked = []
        answers_received = []
        
        for row in (hr_round_response.data or []):
            question_text = row.get("question_text", "")
            user_answer_text = row.get("user_answer", "")
            
            # Add question to conversation history
            if question_text:
                conversation_history.append({"role": "ai", "content": question_text})
                questions_asked.append(question_text)
            
            # Add answer to conversation history (only if not empty)
            if user_answer_text and user_answer_text.strip():
                conversation_history.append({"role": "user", "content": user_answer_text})
                answers_received.append(user_answer_text)
        
        # Check if interview should end (max 10 questions for HR)
        HR_MAX_QUESTIONS = 10
        current_question_count = len(questions_asked)
        
        # If we already have 10 questions, don't generate another one
        if current_question_count >= HR_MAX_QUESTIONS:
            logger.info(f"[HR][NEXT-QUESTION] Interview completed: {current_question_count} questions already asked (max: {HR_MAX_QUESTIONS})")
            return {
                "interview_completed": True,
                "message": "Interview completed. Maximum questions reached."
            }
        
        # ✅ WARM-UP STAGE: Check if we're still in warm-up questions (1-3)
        # Questions 1, 2, 3 are always warm-up questions
        next_question_number = current_question_count + 1
        
        if next_question_number <= HR_WARMUP_COUNT:
            # We're still in warm-up stage - return the next warm-up question
            warmup_index = next_question_number - 1  # Convert to 0-based index
            question_text = HR_WARMUP_QUESTIONS[warmup_index]
            logger.info(f"[HR][NEXT-QUESTION] ✅ Warm-up question {next_question_number}/{HR_WARMUP_COUNT}: {question_text}")
        else:
            # ✅ RESUME-BASED STAGE: After warm-up, switch to AI-generated questions
            logger.info(f"[HR][NEXT-QUESTION] ✅ Warm-up complete, generating resume-based AI question (question {next_question_number})")
            
            # Get user profile for resume context
        user_id = session.get("user_id")
        profile_response = supabase.table("user_profiles").select("*").eq("user_id", user_id).execute()
        profile = profile_response.data[0] if profile_response.data else None
        
        resume_context = {}
        experience_level = "Intermediate"
        skills = []
        
        if profile:
            resume_context = build_resume_context_from_profile(profile, supabase)
            experience_level = profile.get("experience_level", "Intermediate")
            skills = resume_context.get("skills", [])
        
        # Generate next HR question using OpenAI with conversation history
        question_text = None
        try:
            # Check if API key is available
            if not settings.openai_api_key:
                logger.error("[HR][NEXT-QUESTION] OpenAI API key is missing.")
                raise HTTPException(status_code=503, detail="AI service temporarily unavailable. API key not set.")
            
            client = OpenAI(api_key=settings.openai_api_key)
            
            # Build context for HR question generation
            skills_context = ", ".join(skills[:10]) if skills else "general skills"
            
            # Build conversation context
            conversation_context = ""
            if conversation_history:
                # Include last 30 messages to maintain context while staying within token limits
                recent_messages = conversation_history[-30:] if len(conversation_history) > 30 else conversation_history
                conversation_context = "\n".join([
                    f"{msg.get('role', 'unknown').upper()}: {msg.get('content', '')[:300]}"
                    for msg in recent_messages
                ])
            
            # Build list of previously asked questions
            questions_list = ""
            if questions_asked:
                questions_list = "\n".join([f"{i+1}. {q[:150]}" for i, q in enumerate(questions_asked)])
            
            # HR-focused system prompt
            system_prompt = """You are an experienced, friendly HR interviewer conducting a natural, conversational voice-based interview.

Your interview style:
- Speak naturally and conversationally, as if talking to a colleague
- Build on previous answers - ask follow-up questions when appropriate
- Show genuine interest in the candidate's responses
- Focus on behavioral, cultural fit, communication, and motivation questions
- Reference what the candidate mentioned in previous answers
- Avoid awkward pauses - keep the conversation flowing smoothly
- Never repeat questions that have already been asked

Question guidelines:
- Keep questions concise (1-2 sentences) for voice interaction
- Make questions feel natural and conversational
- Build on previous answers to create a cohesive interview flow
- Focus on HR topics: teamwork, problem-solving, motivation, cultural fit, communication
- Reference specific experiences from their resume when relevant"""

            user_prompt = f"""Generate the next HR interview question for a smooth, natural conversation flow.

CANDIDATE'S BACKGROUND (from resume):
Skills: {skills_context}
Experience Level: {experience_level}

CONVERSATION HISTORY (full context):
{conversation_context if conversation_context else "This is the first question. Start with a friendly introduction and a foundational HR question."}

PREVIOUSLY ASKED QUESTIONS (do NOT repeat these):
{questions_list if questions_list else "None - this is the first question"}

INTERVIEW PROGRESS:
- Questions asked so far: {len(questions_asked)}
- Answers received: {len(answers_received)}

Generate ONE natural, conversational HR question that:
1. Flows naturally from the conversation (builds on previous answers if any)
2. Is relevant to HR topics: behavioral, cultural fit, communication, motivation, teamwork
3. Has NOT been asked before (check the list above)
4. Feels like a natural next question in a human HR interview
5. Is appropriate for voice interaction (concise, clear)
6. References specific experiences from their resume when relevant

IMPORTANT:
- If this is early in the interview, start with foundational HR questions (e.g., "Tell me about yourself")
- If the candidate mentioned something interesting, ask a follow-up
- Make it feel like a real conversation, not a scripted Q&A
- Focus on understanding the candidate's personality, work style, and cultural fit

Return ONLY the question text, nothing else. Make it sound natural and conversational."""

            # Build messages with conversation history
            messages = [
                {"role": "system", "content": system_prompt}
            ]
            
            # Step 4: Add conversation history as context messages for context-aware generation
            # CRITICAL: This enables the AI to reference previous answers and build natural follow-ups
            if conversation_history and len(conversation_history) > 0:
                # Include last 30 messages to maintain context while staying within token limits
                history_messages = conversation_history[-30:] if len(conversation_history) > 30 else conversation_history
                for msg in history_messages:
                    role = msg.get("role", "user")
                    content = msg.get("content", "")
                    if role == "ai" or role == "assistant":
                        messages.append({"role": "assistant", "content": content[:500]})  # Limit length
                    elif role == "user":
                        messages.append({"role": "user", "content": content[:500]})  # Limit length
                logger.info(f"[HR][NEXT-QUESTION] ✅ Added {len(history_messages)} conversation history messages for context-aware question generation")
            
            # Add the current prompt
            messages.append({"role": "user", "content": user_prompt})
            
            # Generate question with timeout for better control over network latency
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=messages,
                temperature=0.7,
                max_tokens=150,
                timeout=30  # FIX: ADD TIMEOUT for better control over network latency
            )
            
            question_text = response.choices[0].message.content.strip()
            logger.info(f"[HR][INTERVIEW] Generated next question: {question_text[:50]}...")
            
        except RateLimitError as e:
            # FIX: Catch specific RateLimitError (HTTP 429)
            logger.error(f"[HR][NEXT-QUESTION] OpenAI rate limit exceeded: {str(e)}")
            # Handle the failure by raising a 503 error, suggesting retry
            raise HTTPException(
                status_code=503, 
                detail="The AI service is currently experiencing high demand. Please try again shortly."
            )
            
        except APIError as e:
            # FIX: Catch general APIError (e.g., invalid key, bad request, server side)
            logger.error(f"[HR][NEXT-QUESTION] OpenAI API error occurred: {str(e)}", exc_info=True)
            # Generic failure for external API issue
            raise HTTPException(
                status_code=500, 
                detail="An external service error occurred during question generation. Please try again."
            )
            
        except Exception as e:
            # Catch all other unexpected errors (network, parsing, etc.)
            logger.error(f"[HR][NEXT-QUESTION] Unexpected error during AI question generation: {str(e)}", exc_info=True)
            # Use fallback for unexpected errors to ensure interview can continue
            logger.warning("[HR][NEXT-QUESTION] Using fallback question generator due to unexpected error")
            question_text = None  # Will trigger fallback
        
        # Fallback to question_generator if OpenAI failed
        if not question_text:
            try:
                questions = question_generator.generate_questions(
                    role="HR Interview",
                    experience_level=experience_level,
                    skills=skills,
                    resume_context=resume_context
                )
                hr_questions = [q for q in questions if q.type.lower() == "hr"]
                if hr_questions:
                    question_text = hr_questions[0].question if hasattr(hr_questions[0], 'question') else hr_questions[0].get("question", "")
                else:
                    # Final fallback
                    fallback_questions = [
                        "Tell me about yourself.",
                        "Why are you interested in this position?",
                        "How do you handle stress and pressure?",
                        "What are your career goals?",
                        "Tell me about a time when you worked in a team."
                    ]
                    question_text = fallback_questions[len(questions_asked) % len(fallback_questions)]
            except Exception as fallback_error:
                logger.error(f"[HR][INTERVIEW] Fallback question generation failed: {str(fallback_error)}")
                # Final fallback
                fallback_questions = [
                    "Tell me about yourself.",
                    "Why are you interested in this position?",
                    "How do you handle stress and pressure?",
                    "What are your career goals?",
                    "Tell me about a time when you worked in a team."
                ]
                question_text = fallback_questions[len(questions_asked) % len(fallback_questions)]
        
        if not question_text:
            logger.error("[HR][NEXT-QUESTION] Failed to generate question - question_text is empty after all fallbacks")
            raise HTTPException(status_code=500, detail="A server error occurred while processing your request. Please try again.")
        
        # FIX 13: Step 5: Save new question in hr_round table (transaction pattern)
        # Calculate next question number (should be current count + 1)
        HR_MAX_QUESTIONS = 10  # Maximum questions for HR interview
        question_number = len(questions_asked) + 1
        
        # Double-check we're not exceeding max questions
        if question_number > HR_MAX_QUESTIONS:
            logger.warning(f"[HR][NEXT-QUESTION] Attempted to generate question {question_number} but max is {HR_MAX_QUESTIONS}")
            return {
                "interview_completed": True,
                "message": "Interview completed. Maximum questions reached."
            }
        user_id = str(session.get("user_id", "")) if session else ""
        
        question_db_data = {
            "user_id": user_id,
            "session_id": session_id,
            "question_number": question_number,
            "question_text": question_text,
            "question_category": "HR",
            "user_answer": "",  # Placeholder - will be updated when user submits answer
            "communication_score": None,
            "cultural_fit_score": None,
            "motivation_score": None,
            "clarity_score": None,
            "overall_score": None,
            "ai_feedback": None,
            "response_time": None
        }
        
        try:
            insert_response = supabase.table("hr_round").insert(question_db_data).execute()
            # ✅ FIX 1: Verify question_number is correctly saved
            if insert_response.data and len(insert_response.data) > 0:
                saved_question = insert_response.data[0]
                saved_question_number = saved_question.get('question_number')
                logger.info(f"[HR][NEXT-QUESTION] ✅ Saved new question {saved_question_number} to hr_round table")
                logger.info(f"[HR][NEXT-QUESTION] Saved row ID: {saved_question.get('id')}, session_id: {saved_question.get('session_id')}")
                if saved_question_number != question_number:
                    logger.warning(f"[HR][NEXT-QUESTION] ⚠️ Expected question_number={question_number}, but got {saved_question_number}")
            else:
                logger.error(f"[HR][NEXT-QUESTION] ❌ Insert succeeded but no data returned")
                raise HTTPException(
                    status_code=500,
                    detail="Failed to save interview data. Please try again."
                )
        except HTTPException:
            raise
        except Exception as e:
            # FIX 13: Log error and raise HTTPException to maintain data consistency
            logger.error(f"[HR][NEXT-QUESTION] Failed to store HR question: {str(e)}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail="Failed to save interview data. Please try again."
            )
        
        # ✅ FIX: Generate audio URL for EVERY question (warm-up and follow-up) - MUST always return audio_url
        # ✅ DEBUG: Log audio URL generation process
        logger.debug(f"[HR][DEBUG Q2+] ========== GENERATING AUDIO URL FOR Q{question_number} ==========")
        logger.debug(f"[HR][DEBUG Q2+] question_text length: {len(question_text) if question_text else 0}")
        logger.debug(f"[HR][DEBUG Q2+] question_text preview: {question_text[:100] if question_text else 'EMPTY'}...")
        
        audio_url = None
        try:
            if question_text:
                encoded_text = urllib.parse.quote(question_text)
                # ✅ CRITICAL FIX: Use TECH_BACKEND_URL if set, otherwise use request-based URL detection
                # This ensures correct domain resolution on Vercel (matches Technical Interview pattern)
                base_url = settings.tech_backend_url or get_api_base_url(http_request)
                # Ensure base_url doesn't end with slash
                base_url = base_url.rstrip('/')
                audio_url = f"{base_url}/api/interview/text-to-speech?text={encoded_text}"
                logger.info(f"[HR][NEXT-QUESTION] ✅ Generated audio_url for question {question_number}: {audio_url}")
                logger.debug(f"[HR][DEBUG Q2+] ✅ audio_url generated successfully: {audio_url}")
            else:
                logger.error(f"[HR][NEXT-QUESTION] ❌ question_text is empty, cannot generate audio_url")
                logger.debug(f"[HR][DEBUG Q2+] ❌ question_text is empty - using fallback")
                # Fallback: generate a basic TTS URL even if question_text is empty (shouldn't happen)
                # ✅ CRITICAL FIX: Use request-based URL detection for fallback too
                base_url = settings.tech_backend_url or get_api_base_url(http_request)
                base_url = base_url.rstrip('/')
                audio_url = f"{base_url}/api/interview/text-to-speech?text="
                logger.debug(f"[HR][DEBUG Q2+] Fallback audio_url (empty text): {audio_url}")
        except Exception as e:
            # ✅ FIX: Always provide a fallback audio_url instead of None
            logger.error(f"[HR][NEXT-QUESTION] ❌ Could not generate audio URL: {str(e)}", exc_info=True)
            logger.debug(f"[HR][DEBUG Q2+] Exception during audio_url generation: {str(e)}")
            try:
                # Fallback: generate basic TTS URL with request-based URL detection
                # ✅ CRITICAL FIX: Use request-based URL detection for fallback too
                base_url = settings.tech_backend_url or get_api_base_url(http_request)
                base_url = base_url.rstrip('/')
                if question_text:
                    encoded_text = urllib.parse.quote(question_text)
                    audio_url = f"{base_url}/api/interview/text-to-speech?text={encoded_text}"
                else:
                    audio_url = f"{base_url}/api/interview/text-to-speech?text="
                logger.warning(f"[HR][NEXT-QUESTION] ⚠️ Using fallback audio_url: {audio_url}")
                logger.debug(f"[HR][DEBUG Q2+] Fallback audio_url: {audio_url}")
            except Exception as fallback_error:
                # Last resort: return a basic TTS endpoint URL
                logger.error(f"[HR][NEXT-QUESTION] ❌ Fallback audio URL generation also failed: {str(fallback_error)}")
                logger.debug(f"[HR][DEBUG Q2+] Last resort audio_url (relative): /api/interview/text-to-speech?text=")
                audio_url = "/api/interview/text-to-speech?text="  # Relative URL as last resort
        
        logger.debug(f"[HR][DEBUG Q2+] Final audio_url value: {audio_url}")
        logger.debug(f"[HR][DEBUG Q2+] audio_url is None: {audio_url is None}")
        logger.debug(f"[HR][DEBUG Q2+] ====================================================")
        
        # Determine if interview is completed (question_number > 10)
        interview_completed = question_number > 10
        
        # ✅ Determine if this is a warm-up question
        is_warmup = question_number <= HR_WARMUP_COUNT
        
        response_data = {
            "question": question_text,
            "question_type": "HR",
            "question_number": question_number,
            "total_questions": 10,  # HR interviews support up to 10 questions
            "audio_url": audio_url,
            "interview_completed": interview_completed,
            "is_warmup": is_warmup,  # Indicate if this is a warm-up question
            "session_id": session_id
        }
        
        # ✅ DEBUG: Log response data before returning
        logger.debug(f"[HR][DEBUG Q2+] ========== RETURNING RESPONSE FOR Q{question_number} ==========")
        logger.debug(f"[HR][DEBUG Q2+] response_data keys: {list(response_data.keys())}")
        logger.debug(f"[HR][DEBUG Q2+] response_data['question']: {response_data.get('question', 'MISSING')[:100] if response_data.get('question') else 'MISSING'}...")
        logger.debug(f"[HR][DEBUG Q2+] response_data['audio_url']: {response_data.get('audio_url', 'MISSING')}")
        logger.debug(f"[HR][DEBUG Q2+] response_data['audio_url'] is None: {response_data.get('audio_url') is None}")
        logger.debug(f"[HR][DEBUG Q2+] ==============================================================")
        
        return response_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[HR][NEXT-QUESTION] Unexpected error getting next HR question: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate next question. Please try again.")


@router.post("/{session_id}/submit-answer", response_model=HRSubmitAnswerResponse)
async def submit_hr_answer(
    session_id: str,
    http_request: Request,
    request_body: Dict[str, Any] = Body(...),
    supabase: Client = Depends(get_supabase_client),
    _: None = Depends(validate_request_size)
):
    """
    Submit an answer to the current HR question
    Uses HR-specific evaluation and stores in hr_round table
    """
    # FIX 12: Test database connection at the start
    if not test_supabase_connection(supabase):
        raise HTTPException(
            status_code=503,
            detail="Database connection unavailable. Please try again shortly."
        )
    
    try:
        # Input validation
        if not session_id or not isinstance(session_id, str) or not session_id.strip():
            logger.error(f"[HR][SUBMIT-ANSWER] Invalid session_id: {session_id}")
            raise HTTPException(status_code=400, detail="Invalid request format. Please check your input and try again.")
        
        question = request_body.get("question") or request_body.get("question_text")
        answer = request_body.get("answer") or request_body.get("user_answer")
        
        # ✅ FIX: Accept "No Answer" as valid answer, reject only truly empty answers
        if not answer or not isinstance(answer, str):
            logger.error(f"[HR][SUBMIT-ANSWER] Empty or invalid answer in request - rejecting")
            raise HTTPException(status_code=400, detail="I could not hear your answer. Please speak again.")
        
        # Allow "No Answer" exactly as-is (case-sensitive check)
        if answer.strip() == "" and answer != "No Answer":
            logger.error(f"[HR][SUBMIT-ANSWER] Empty or whitespace-only answer - rejecting")
            raise HTTPException(status_code=400, detail="I could not hear your answer. Please speak again.")
        
        # Log "No Answer" cases for debugging
        if answer == "No Answer":
            logger.debug(f"[HR][SUBMIT-ANSWER] No Answer detected for session_id={session_id}, question_number will be determined from DB")
        
        logger.info(f"[HR][SUBMIT-ANSWER] Submitting answer for session_id: {session_id}")
        logger.debug(f"[HR][SUBMIT-ANSWER] Answer length: {len(answer)} characters")
        
        # Get session
        try:
            session_response = supabase.table("interview_sessions").select("*").eq("id", session_id).execute()
        except Exception as db_error:
            logger.error(f"[HR][SUBMIT-ANSWER] Database error fetching session: {str(db_error)}", exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to retrieve interview session. Please try again.")
        
        if not session_response.data or len(session_response.data) == 0:
            logger.warning(f"[HR][SUBMIT-ANSWER] Session not found: {session_id}")
            raise HTTPException(status_code=404, detail="Interview session not found. Please start a new interview.")
        
        session = session_response.data[0]
        
        # FIX 19: Check if session is already completed
        session_status = session.get("session_status", "").lower()
        if session_status == "completed":
            logger.warning(f"[HR][SUBMIT-ANSWER] Session already completed: {session_id}")
            raise HTTPException(
                status_code=400,
                detail="This interview session has already been completed. Please start a new interview."
            )
        
        # Validate session is HR type
        session_type = session.get("interview_type", "").lower()
        if session_type != "hr":
            logger.error(f"[HR][SUBMIT-ANSWER] Wrong session type: {session_type} (expected: hr)")
            raise HTTPException(
                status_code=400, 
                detail="This endpoint is for HR interviews only. Please use the correct interview type."
            )
        
        # Get current question from hr_round table
        try:
            questions_response = supabase.table("hr_round").select("*").eq("session_id", session_id).order("question_number", desc=True).limit(1).execute()
        except Exception as db_error:
            # Log detailed error information
            logger.error(
                f"[HR][SUBMIT-ANSWER] Database error fetching question for session_id: {session_id}. Error: {str(db_error)}", 
                exc_info=True
            )
            
            # Raise HTTPException with 500 status and user-friendly message
            raise HTTPException(
                status_code=500, 
                detail="Failed to submit answer due to a server error. Please try again."
            )
        
        # Logic to check if data was retrieved (Handle 404 case)
        if not questions_response.data or len(questions_response.data) == 0:
            # This block correctly handles the 404 case if the query succeeded but returned no data
            logger.warning(f"[HR][SUBMIT-ANSWER] No question found in hr_round for session_id={session_id}")
            raise HTTPException(
                status_code=404, 
                detail="No current question found for this session. Please start a new interview."
            )
        
        current_question_db = questions_response.data[0]
        question_number = current_question_db["question_number"]
        question_text = current_question_db.get("question_text", question)
        
        # ✅ Log "No Answer" cases with question_number and session_id
        if answer == "No Answer":
            logger.debug(f"[HR][SUBMIT-ANSWER] No Answer detected - session_id={session_id}, question_number={question_number}, reason=classified_by_frontend")
        
        # ✅ FIX 2: Safety fallback - if question_text is empty in DB, use question from request
        if not question_text or not question_text.strip():
            question_text = question
            if not question_text or not question_text.strip():
                logger.error(f"[HR][SUBMIT-ANSWER] Both DB and request have empty question text for question_number={question_number}")
                raise HTTPException(
                    status_code=400,
                    detail="Question text is missing. Please start a new interview."
                )
            logger.warning(f"[HR][SUBMIT-ANSWER] Question text missing from DB (question_number={question_number}), using question from request body as fallback")
        
        # Get conversation history from hr_round table
        round_data_response = supabase.table("hr_round").select("question_text, question_number, user_answer").eq("session_id", session_id).order("question_number").execute()
        
        conversation_history = []
        questions_asked_list = []
        answers_received_list = []
        
        for row in (round_data_response.data or []):
            q_text = row.get("question_text", "")
            user_ans = row.get("user_answer", "")
            if q_text:
                conversation_history.append({"role": "ai", "content": q_text})
                questions_asked_list.append(q_text)
            if user_ans:  # Only add answer if it's not empty
                conversation_history.append({"role": "user", "content": user_ans})
                answers_received_list.append(user_ans)
        
        # Get experience level for evaluation
        experience_level = session.get("experience_level", "Intermediate")
        response_time = request_body.get("response_time")
        
        # ✅ FIX: For "No Answer", set all scores to 0
        if answer == "No Answer":
            logger.debug(f"[HR][SUBMIT-ANSWER] Setting all scores to 0 for 'No Answer' - session_id={session_id}, question_number={question_number}")
            scores = AnswerScore(
                relevance=0,
                confidence=0,
                technical_accuracy=0,
                communication=0,
                overall=0,
                feedback="No answer provided."
            )
        else:
            # Evaluate answer using HR-specific evaluation
            # Use answer_evaluator with question_type="HR" for HR-specific scoring
            scores = answer_evaluator.evaluate_answer(
                question=question_text,
                question_type="HR",
                answer=answer,
                experience_level=experience_level,
                response_time=response_time
            )
        
        logger.info(f"[HR][SUBMIT-ANSWER] Answer evaluated - Communication: {scores.communication}, Overall: {scores.overall}")
        
        # ✅ FIX: Skip AI response generation for "No Answer" - just move to next question
        ai_response = None
        if answer == "No Answer":
            logger.debug(f"[HR][SUBMIT-ANSWER] Skipping AI response generation for 'No Answer' - session_id={session_id}, question_number={question_number}")
            ai_response = "Let's continue with the next question."
        elif technical_interview_engine.openai_available and technical_interview_engine.client is not None:
            try:
                system_prompt = """You are an experienced HR interviewer providing feedback on candidate answers.
Provide brief, encouraging, and constructive feedback (1-2 sentences) that:
- Acknowledges what the candidate said
- Provides gentle guidance if needed
- Maintains a positive, professional tone
- Is appropriate for HR/behavioral interview context"""

                user_prompt = f"""Question: {question_text}
Candidate Answer: {answer}
Communication Score: {scores.communication}/100
Overall Score: {scores.overall}/100

Provide brief, encouraging feedback for this HR interview answer."""

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
                logger.info(f"[HR][SUBMIT-ANSWER] AI response generated: {ai_response[:50]}...")
                
            except Exception as e:
                logger.warning(f"[HR][SUBMIT-ANSWER] Could not generate AI response: {str(e)}")
                ai_response = "Thank you for your answer. Let's continue with the next question."
        else:
            ai_response = "Thank you for your answer. Let's continue with the next question."
        
        # Generate audio URL for AI response
        ai_response_audio_url = None
        if ai_response:
            try:
                encoded_text = urllib.parse.quote(ai_response)
                # ✅ CRITICAL FIX: Use TECH_BACKEND_URL if set, otherwise use request-based URL detection
                # This ensures correct domain resolution on Vercel (matches Technical Interview pattern)
                base_url = settings.tech_backend_url or get_api_base_url(http_request)
                # Ensure base_url doesn't end with slash
                base_url = base_url.rstrip('/')
                ai_response_audio_url = f"{base_url}/api/interview/text-to-speech?text={encoded_text}"
                logger.info(f"[HR][SUBMIT-ANSWER] Generated AI response audio URL: {ai_response_audio_url}")
            except Exception as e:
                logger.warning(f"[HR][SUBMIT-ANSWER] Could not generate audio URL: {str(e)}")
        
        # Update the existing question row in hr_round table with the answer and evaluation
        user_id = str(session.get("user_id", "")) if session else ""
        
        # Get user's answer audio_url from request (if provided)
        user_answer_audio_url = request_body.get("audio_url")
        
        # FIX 15: Map scores to HR-specific fields with standardized mapping
        # For HR, we use:
        # - communication_score: from scores.communication (direct mapping)
        # - cultural_fit_score: from scores.relevance (how well answer fits company culture/job fit)
        # - motivation_score: from scores.relevance (consistent mapping - relevance indicates motivation)
        # - clarity_score: from scores.communication (clarity is part of communication)
        # - overall_score: from scores.overall (direct mapping)
        
        # FIX 15: Standardize score mapping with safe attribute access
        communication_score = getattr(scores, 'communication', 0)
        relevance_score = getattr(scores, 'relevance', 0)
        overall_score = getattr(scores, 'overall', 0)
        feedback_text = getattr(scores, 'feedback', '')
        
        # ✅ FIX 4: Use ai_response instead of scores.feedback for ai_feedback field
        # ai_response is the generated AI feedback from OpenAI, which is more detailed and contextual
        ai_feedback_to_save = ai_response if ai_response else feedback_text
        
        update_data = {
            "user_answer": answer,
            "audio_url": user_answer_audio_url,  # User's answer audio URL
            "communication_score": communication_score,
            "cultural_fit_score": relevance_score,  # Map relevance to cultural fit (job fit)
            "motivation_score": relevance_score,  # Use relevance as motivation indicator (consistent mapping)
            "clarity_score": communication_score,  # Clarity is part of communication
            "overall_score": overall_score,
            "ai_feedback": ai_feedback_to_save,  # ✅ FIX 4: Use ai_response (generated AI feedback) instead of scores.feedback
            "response_time": response_time
        }
        
        # ✅ FIX 5: Add detailed logging for debugging
        logger.info(f"[HR][SUBMIT-ANSWER] ========== UPDATE DATA ==========")
        logger.info(f"[HR][SUBMIT-ANSWER] session_id: {session_id} (type: {type(session_id)})")
        logger.info(f"[HR][SUBMIT-ANSWER] question_number: {question_number} (type: {type(question_number)})")
        logger.info(f"[HR][SUBMIT-ANSWER] Update data: {update_data}")
        logger.info(f"[HR][SUBMIT-ANSWER] Scores - Communication: {communication_score}, Relevance: {relevance_score}, Overall: {overall_score}")
        logger.info(f"[HR][SUBMIT-ANSWER] AI Feedback length: {len(ai_feedback_to_save) if ai_feedback_to_save else 0} characters")
        logger.info(f"[HR][SUBMIT-ANSWER] ==================================")
        
        # ✅ FIX 2 & 3: Verify the row exists before updating, with fallback to create if missing
        try:
            verify_response = supabase.table("hr_round").select("id, session_id, question_number, question_text").eq("session_id", str(session_id)).eq("question_number", int(question_number)).execute()
        except Exception as verify_error:
            logger.error(f"[HR][SUBMIT-ANSWER] Database error verifying question row: {str(verify_error)}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail="Failed to verify question. Please try again."
            )
        
        # ✅ FIX 3: Fallback logic - if row doesn't exist, create it instead of failing
        if not verify_response.data or len(verify_response.data) == 0:
            logger.warning(f"[HR][SUBMIT-ANSWER] ⚠️ Row not found for session_id={session_id}, question_number={question_number}. Creating new row...")
            
            # Create the row with all necessary data
            insert_data = {
                "user_id": user_id,
                "session_id": str(session_id),
                "question_number": int(question_number),
                "question_text": question_text,  # Use question_text from DB query or request
                "question_category": "HR",
                **update_data  # Include all update_data fields (user_answer, scores, etc.)
            }
            
            try:
                insert_response = supabase.table("hr_round").insert(insert_data).execute()
                if not insert_response.data or len(insert_response.data) == 0:
                    logger.error(f"[HR][SUBMIT-ANSWER] ❌ Failed to create row - insert returned no data")
                    raise HTTPException(
                        status_code=500,
                        detail="Failed to save answer to database. Please try again."
                    )
                logger.info(f"[HR][SUBMIT-ANSWER] ✅ Created new row with ID: {insert_response.data[0].get('id')}")
                answer_response = insert_response  # Use insert response for validation
            except HTTPException:
                raise
            except Exception as insert_error:
                logger.error(f"[HR][SUBMIT-ANSWER] Database error creating row: {str(insert_error)}", exc_info=True)
                raise HTTPException(
                    status_code=500,
                    detail="Failed to save answer to database. Please try again."
                )
        else:
            # Row exists - proceed with update
            existing_row_id = verify_response.data[0].get('id')
            logger.info(f"[HR][SUBMIT-ANSWER] ✓ Row found. Existing row ID: {existing_row_id}")
            logger.info(f"[HR][SUBMIT-ANSWER] Existing row data - question_text: {verify_response.data[0].get('question_text', 'N/A')[:50]}...")
            
            # ✅ FIX 2: Update the row for this question_number and session_id
            try:
                answer_response = supabase.table("hr_round").update(update_data).eq("session_id", str(session_id)).eq("question_number", int(question_number)).execute()
            except Exception as update_error:
                logger.error(f"[HR][SUBMIT-ANSWER] Database error updating answer: {str(update_error)}", exc_info=True)
                logger.error(f"[HR][SUBMIT-ANSWER] Update query details - session_id: {str(session_id)}, question_number: {int(question_number)}")
                raise HTTPException(
                    status_code=500,
                    detail="Failed to save answer to database. Please try again."
                )
        
        # ✅ FIX 5: Validate that the update/insert actually succeeded with detailed logging
        if not answer_response.data or len(answer_response.data) == 0:
            # Determine operation type safely
            operation_type = "UNKNOWN"
            if 'verify_response' in locals() and verify_response and verify_response.data and len(verify_response.data) > 0:
                operation_type = "UPDATE"
            else:
                operation_type = "INSERT"
            
            logger.error(f"[HR][SUBMIT-ANSWER] ❌ Database operation returned no rows!")
            logger.error(f"[HR][SUBMIT-ANSWER] Operation: {operation_type}")
            logger.error(f"[HR][SUBMIT-ANSWER] Query params - session_id: {str(session_id)}, question_number: {int(question_number)}")
            logger.error(f"[HR][SUBMIT-ANSWER] Update data keys: {list(update_data.keys())}")
            logger.error(f"[HR][SUBMIT-ANSWER] ⚠️ POSSIBLE CAUSES:")
            logger.error(f"[HR][SUBMIT-ANSWER]   1. RLS policy blocking update/insert")
            logger.error(f"[HR][SUBMIT-ANSWER]   2. Service role key not configured correctly")
            logger.error(f"[HR][SUBMIT-ANSWER]   3. Row not found (session_id/question_number mismatch)")
            logger.error(f"[HR][SUBMIT-ANSWER]   4. Column type mismatch")
            raise HTTPException(status_code=500, detail="Failed to save answer to database. Please try again.")
        
        # ✅ FIX 5: Log the saved data for verification
        saved_row = answer_response.data[0]
        logger.info(f"[HR][SUBMIT-ANSWER] ✅ Answer saved successfully to hr_round table")
        logger.info(f"[HR][SUBMIT-ANSWER] ========== SAVED DATA VERIFICATION ==========")
        logger.info(f"[HR][SUBMIT-ANSWER] Row ID: {saved_row.get('id')}")
        logger.info(f"[HR][SUBMIT-ANSWER] session_id: {saved_row.get('session_id')}")
        logger.info(f"[HR][SUBMIT-ANSWER] question_number: {saved_row.get('question_number')}")
        logger.info(f"[HR][SUBMIT-ANSWER] user_answer: {saved_row.get('user_answer', '')[:50]}..." if saved_row.get('user_answer') else "user_answer: (empty)")
        logger.info(f"[HR][SUBMIT-ANSWER] communication_score: {saved_row.get('communication_score')}")
        logger.info(f"[HR][SUBMIT-ANSWER] cultural_fit_score: {saved_row.get('cultural_fit_score')}")
        logger.info(f"[HR][SUBMIT-ANSWER] motivation_score: {saved_row.get('motivation_score')}")
        logger.info(f"[HR][SUBMIT-ANSWER] clarity_score: {saved_row.get('clarity_score')}")
        logger.info(f"[HR][SUBMIT-ANSWER] overall_score: {saved_row.get('overall_score')}")
        logger.info(f"[HR][SUBMIT-ANSWER] ai_feedback: {saved_row.get('ai_feedback', '')[:50]}..." if saved_row.get('ai_feedback') else "ai_feedback: (empty)")
        logger.info(f"[HR][SUBMIT-ANSWER] ============================================")
        
        # Log interview transcript
        await log_interview_transcript(
            supabase,
            session_id,
            "hr",  # Use "hr" instead of "technical"
            question_text,
            answer
        )
        
        # Check if interview should be completed (max 10 questions for HR)
        HR_MAX_QUESTIONS = 10
        total_questions = len(questions_asked_list)
        interview_completed = total_questions >= HR_MAX_QUESTIONS
        
        # FIX: Update the main interview_sessions table status if interview is completed
        # Use atomic update with row-level locking: only update if status is not already "completed"
        if interview_completed:
            try:
                # Atomic update: only update if session_status is not already "completed" (prevents race conditions)
                update_response = supabase.table("interview_sessions").update({
                    "session_status": "completed"
                }).eq("id", session_id).neq("session_status", "completed").execute()
                
                if update_response.data and len(update_response.data) > 0:
                    logger.info(f"[HR][SUBMIT-ANSWER] ✅ Session marked as completed for session_id: {session_id}")
                else:
                    logger.info(f"[HR][SUBMIT-ANSWER] Session already completed for session_id: {session_id}")
                
            except Exception as e:
                # Log error but allow the request to finish successfully, as the answer was saved.
                logger.warning(
                    f"[HR][SUBMIT-ANSWER] Could not update session status to completed for session_id: {session_id}. Error: {str(e)}", 
                    exc_info=True
                )
        
        # Get created_at timestamp from response
        created_at_str = answer_response.data[0].get("created_at")
        if isinstance(created_at_str, str):
            created_at_str = created_at_str.replace('Z', '+00:00')
            try:
                answered_at = datetime.fromisoformat(created_at_str)
            except ValueError:
                answered_at = datetime.now()
        else:
            answered_at = datetime.now()
        
        # Return HR-specific response
        return {
            "answer_id": answer_response.data[0].get("id"),
            "session_id": session_id,
            "question_number": question_number,
            "scores": {
                "communication": scores.communication,
                "cultural_fit": scores.relevance,
                "motivation": scores.confidence if hasattr(scores, 'confidence') else scores.communication,
                "clarity": scores.communication,
                "overall": scores.overall
            },
            "ai_response": ai_response,
            "audio_url": ai_response_audio_url,  # Audio URL for AI response
            "feedback": scores.feedback,
            "interview_completed": interview_completed,
            "response_time": response_time,
            "answered_at": answered_at.isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[HR][SUBMIT-ANSWER] Unexpected error submitting HR answer: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to submit answer. Please try again.")


@router.get("/{session_id}/feedback", response_model=HRFeedbackResponse)
async def get_hr_interview_feedback(
    session_id: str,
    supabase: Client = Depends(get_supabase_client),
    _: None = Depends(rate_limit_by_session_id)
):
    """
    Get final feedback for completed HR interview
    Returns HR-specific feedback with communication, cultural fit, motivation, and clarity scores
    """
    try:
        # Input validation
        if not session_id or not isinstance(session_id, str) or not session_id.strip():
            logger.error(f"[HR][FEEDBACK] Invalid session_id: {session_id}")
            raise HTTPException(status_code=400, detail="Invalid request format. Please check your input and try again.")
        
        logger.info(f"[HR][FEEDBACK] Requesting feedback for session_id: {session_id}")
        
        # Get session
        try:
            session_response = supabase.table("interview_sessions").select("*").eq("id", session_id).execute()
        except Exception as db_error:
            logger.error(f"[HR][FEEDBACK] Database error fetching session: {str(db_error)}", exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to retrieve interview session. Please try again.")
        
        if not session_response.data or len(session_response.data) == 0:
            logger.warning(f"[HR][FEEDBACK] Session not found: {session_id}")
            raise HTTPException(status_code=404, detail="Interview session not found. Please start a new interview.")
        
        session = session_response.data[0]
        
        # Validate session is HR type
        session_type = session.get("interview_type", "").lower()
        if session_type != "hr":
            logger.error(f"[HR][FEEDBACK] Wrong session type: {session_type} (expected: hr)")
            raise HTTPException(
                status_code=400, 
                detail="This endpoint is for HR interviews only. Please use the correct interview type."
            )
        
        # Get all answers from hr_round table
        try:
            answers_response = supabase.table("hr_round").select("*").eq("session_id", session_id).order("question_number").execute()
            answers = answers_response.data if answers_response.data else []
        except Exception as db_error:
            logger.error(f"[HR][FEEDBACK] Database error fetching answers: {str(db_error)}", exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to retrieve interview answers. Please try again.")
        
        if not answers:
            logger.warning(f"[HR][FEEDBACK] No answers found for session: {session_id}")
            raise HTTPException(status_code=400, detail="No answers found for this interview. Please complete the interview first.")
        
        # Validate that answers are actually saved (not empty)
        answers_with_data = []
        missing_data_rows = []
        
        for idx, row in enumerate(answers, 1):
            user_answer = row.get("user_answer", "")
            communication_score = row.get("communication_score")
            cultural_fit_score = row.get("cultural_fit_score")
            motivation_score = row.get("motivation_score")
            clarity_score = row.get("clarity_score")
            overall_score = row.get("overall_score")
            
            # ✅ FIX: "No Answer" is a valid answer and should be included in feedback (with 0 scores)
            # Check if this row has been properly saved
            if not user_answer or (user_answer.strip() == "" and user_answer != "No Answer"):
                missing_data_rows.append(f"Question {row.get('question_number', idx)}: user_answer is empty")
            elif communication_score is None and cultural_fit_score is None and motivation_score is None and clarity_score is None:
                missing_data_rows.append(f"Question {row.get('question_number', idx)}: scores are NULL")
            else:
                # Include "No Answer" cases in feedback (they have 0 scores)
                answers_with_data.append(row)
        
        # If NO rows have data, return error
        if len(answers_with_data) == 0:
            logger.error(f"[HR][FEEDBACK] ❌ Cannot generate feedback: No complete answers found. Missing data in: {', '.join(missing_data_rows)}")
            raise HTTPException(
                status_code=400, 
                detail="No complete answers found for this interview. Please ensure all answers are submitted before viewing feedback."
            )
        
        # If some rows are missing data but we have at least one complete answer, log warning but continue
        if missing_data_rows and len(answers_with_data) > 0:
            logger.warning(f"[HR][FEEDBACK] ⚠️  Some answers incomplete: {', '.join(missing_data_rows)}. Generating feedback with {len(answers_with_data)} complete answers.")
        
        # Use only rows with complete data
        answers = answers_with_data
        
        # ✅ FIX: Detect empty/very short answers (< 3-5 meaningful words)
        def is_valid_answer(answer_text: str) -> bool:
            """Check if answer is valid (not empty, not 'No Answer', and has at least 3 meaningful words)"""
            if not answer_text or not isinstance(answer_text, str):
                return False
            answer_text = answer_text.strip()
            if answer_text == "" or answer_text == "No Answer":
                return False
            # Count meaningful words (exclude very short words like "a", "an", "the", "I", "is", etc.)
            words = [w for w in answer_text.split() if len(w) > 2]
            return len(words) >= 3
        
        # Check if ALL answers are empty/No Answer/too short
        valid_answers = []
        empty_answers = []
        for row in answers:
            user_answer = row.get("user_answer", "")
            if is_valid_answer(user_answer):
                valid_answers.append(row)
            else:
                empty_answers.append(row)
        
        # If NO valid answers exist, return 0 scores with appropriate feedback
        if len(valid_answers) == 0:
            logger.warning(f"[HR][FEEDBACK] ⚠️  No valid answers found - all {len(answers)} answers are empty/No Answer/too short")
            return {
                "overall_score": 0.0,
                "communication_score": 0.0,
                "cultural_fit_score": 0.0,
                "motivation_score": 0.0,
                "clarity_score": 0.0,
                "feedback_summary": "Interview ended early with no valid responses.",
                "strengths": ["No valid response detected."],
                "areas_for_improvement": ["Please provide spoken answers to receive accurate feedback."],
                "recommendations": ["Try answering all HR questions with clear, structured responses."],
                "question_count": len(answers),
            }
        
        # If some answers are valid but some are empty, log warning but continue with valid ones
        if len(empty_answers) > 0:
            logger.warning(f"[HR][FEEDBACK] ⚠️  {len(empty_answers)} empty/too short answers detected, using {len(valid_answers)} valid answers for feedback")
        
        # Use only valid answers for scoring and feedback
        answers = valid_answers
        
        # Get conversation history from hr_round table
        conversation_history = []
        questions_asked = []
        answers_received = []
        
        for row in answers:
            question_text = row.get("question_text", "")
            user_answer = row.get("user_answer", "")
            if question_text:
                conversation_history.append({"role": "ai", "content": question_text})
                questions_asked.append(question_text)
            # ✅ FIX: Include "No Answer" in conversation history for feedback
            if user_answer and (user_answer.strip() or user_answer == "No Answer"):
                conversation_history.append({"role": "user", "content": user_answer})
                answers_received.append(user_answer)
        
        # Calculate HR-specific scores
        all_communication_scores = []
        all_cultural_fit_scores = []
        all_motivation_scores = []
        all_clarity_scores = []
        all_overall_scores = []
        
        for answer in answers:
            comm_score = answer.get("communication_score")
            cultural_score = answer.get("cultural_fit_score")
            motivation_score = answer.get("motivation_score")
            clarity_score = answer.get("clarity_score")
            overall_score = answer.get("overall_score")
            
            if comm_score is not None:
                all_communication_scores.append(comm_score)
            if cultural_score is not None:
                all_cultural_fit_scores.append(cultural_score)
            if motivation_score is not None:
                all_motivation_scores.append(motivation_score)
            if clarity_score is not None:
                all_clarity_scores.append(clarity_score)
            if overall_score is not None:
                all_overall_scores.append(overall_score)
        
        # Calculate averages
        avg_communication = sum(all_communication_scores) / len(all_communication_scores) if all_communication_scores else 0
        avg_cultural_fit = sum(all_cultural_fit_scores) / len(all_cultural_fit_scores) if all_cultural_fit_scores else 0
        avg_motivation = sum(all_motivation_scores) / len(all_motivation_scores) if all_motivation_scores else 0
        avg_clarity = sum(all_clarity_scores) / len(all_clarity_scores) if all_clarity_scores else 0
        avg_overall = sum(all_overall_scores) / len(all_overall_scores) if all_overall_scores else 0
        
        # --- Generate HR-specific feedback using AI (fully personalized) ---
        feedback_summary: str = ""
        strengths: List[str] = []
        areas_for_improvement: List[str] = []
        recommendations: List[str] = []

        # Build a rich but compact per-question summary for the LLM so it can
        # base feedback STRICTLY on the candidate's actual answers.
        qa_summaries: List[str] = []
        for idx, row in enumerate(answers, 1):
            q_text = (row.get("question_text") or "").strip()
            a_text = (row.get("user_answer") or "").strip()
            qa_scores = {
                "communication": row.get("communication_score"),
                "cultural_fit": row.get("cultural_fit_score"),
                "motivation": row.get("motivation_score"),
                "clarity": row.get("clarity_score"),
                "overall": row.get("overall_score"),
            }
            score_str = ", ".join(
                f"{name}={value:.1f}"
                for name, value in qa_scores.items()
                if isinstance(value, (int, float))
            )
            qa_summaries.append(
                f"Q{idx}: {q_text}\nA{idx}: {a_text or 'No Answer'}\nScores: {score_str or 'n/a'}"
            )

        qa_block = "\n\n".join(qa_summaries)

        # Prefer LLM-based feedback when OpenAI is available
        if technical_interview_engine.openai_available and technical_interview_engine.client is not None:
            try:
                system_prompt = """
You are an experienced HR interviewer and assessment specialist.
You will receive a full HR interview transcript with question-by-question scores.
Your job is to produce a SHORT, CLEAR, and FULLY PERSONALIZED evaluation.

STRICT RULES:
- Base everything ONLY on the candidate's actual answers and scores.
- Avoid generic boilerplate; reference what the candidate actually did well or poorly.
- Keep language professional, constructive, and easy to understand.

EVALUATION DIMENSIONS (scores are 0–100):
- Communication clarity & structure
- Cultural fit & values alignment
- Motivation & ownership mindset
- Behavioral skills (teamwork, conflict resolution, leadership)
"""

                # ✅ FIX: Check if all answers are empty/No Answer/too short for LLM prompt
                all_empty = all(
                    not is_valid_answer(row.get("user_answer", ""))
                    for row in answers
                )
                
                if all_empty:
                    # Special prompt for empty answers case
                    user_prompt = f"""
HR INTERVIEW SESSION SUMMARY
-----------------------------
CRITICAL: All answers provided were empty, "No Answer", or too short (< 3 meaningful words).

Overall averages (0–100):
- Overall: {avg_overall:.1f}
- Communication: {avg_communication:.1f}
- Cultural Fit: {avg_cultural_fit:.1f}
- Motivation: {avg_motivation:.1f}
- Clarity / Structure: {avg_clarity:.1f}

Total questions asked: {len(answers)}
Valid answers provided: 0

Per-question detail:
{qa_block}

TASK:
Since NO valid answers were provided, generate a JSON object with the following shape:
{{
  "strengths": ["No valid response detected."],
  "areas_for_improvement": ["Please provide spoken answers to receive accurate feedback."],
  "recommendations": ["Try answering all HR questions with clear, structured responses."],
  "summary": "Interview ended early with no valid responses."
}}
"""
                else:
                    user_prompt = f"""
HR INTERVIEW SESSION SUMMARY
-----------------------------
Overall averages (0–100):
- Overall: {avg_overall:.1f}
- Communication: {avg_communication:.1f}
- Cultural Fit: {avg_cultural_fit:.1f}
- Motivation: {avg_motivation:.1f}
- Clarity / Structure: {avg_clarity:.1f}

Total questions answered: {len(answers)}

Conversation History (chronological):
{chr(10).join([f"{msg.get('role', 'unknown').upper()}: {msg.get('content', '')[:300]}" for msg in conversation_history])}

Per-question detail with scores:
{qa_block}

TASK:
Using ONLY this information, generate a JSON object with the following shape:
{{
  "strengths": [
    "2–5 bullet points highlighting concrete strengths based on their answers"
  ],
  "areas_for_improvement": [
    "2–5 bullet points pointing out where answers were weak, vague, shallow or off-topic"
  ],
  "recommendations": [
    "2–5 specific practice recommendations (e.g., use STAR format, add metrics, give clearer examples)"
  ],
  "summary": "3–5 sentences summarising their HR performance, tone, and behavioral fit in natural language"
}}

CONSTRAINTS:
- Every bullet must be specific to THIS candidate's answers (no generic phrases like 'work on your skills').
- Mention communication, examples, structure (STAR), teamwork/conflict and motivation where relevant.
- The summary should read like a real HR interview report.
"""

                response = technical_interview_engine.client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": system_prompt.strip()},
                        {"role": "user", "content": user_prompt.strip()},
                    ],
                    temperature=0.5,
                    max_tokens=600,
                    timeout=30
                )

                raw_content = response.choices[0].message.content.strip()

                # Robust JSON parsing: handle optional markdown fences
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
                        logger.warning(
                            "[HR][FEEDBACK] AI returned non-JSON content, falling back to rule-based text"
                        )
                        feedback_data = {}

                strengths = feedback_data.get("strengths") or []
                areas_for_improvement = feedback_data.get("areas_for_improvement") or []
                recommendations = feedback_data.get("recommendations") or []
                feedback_summary = feedback_data.get("summary") or ""

                logger.info("[HR][FEEDBACK] ✅ AI HR feedback (strengths/improvements/recommendations/summary) generated")
                
            except Exception as e:
                logger.warning(f"[HR][FEEDBACK] Could not generate AI feedback: {str(e)}", exc_info=True)
                # If AI fails, we'll fall back to a simple deterministic text below.

        # Fallback when OpenAI is not available OR AI parsing failed.
        if not feedback_summary or not (strengths or areas_for_improvement or recommendations):
            # ✅ FIX: Check if all answers are empty/No Answer/too short
            all_empty_fallback = all(
                not is_valid_answer(row.get("user_answer", ""))
                for row in answers
            )
            
            if all_empty_fallback or avg_overall == 0:
                # All answers are empty - return appropriate feedback
                feedback_summary = "Interview ended early with no valid responses."
                strengths = ["No valid response detected."]
                areas_for_improvement = ["Please provide spoken answers to receive accurate feedback."]
                recommendations = ["Try answering all HR questions with clear, structured responses."]
        else:
            # Lightweight rule-based summary that is still driven by the real scores.
            feedback_summary = f"Overall HR interview performance score: {avg_overall:.1f}/100. "
            if avg_communication >= 75:
                strengths.append("You communicated clearly and structured your answers well.")
            elif avg_communication < 60:
                areas_for_improvement.append("Your communication was sometimes unclear or unstructured.")

            if avg_cultural_fit >= 75:
                strengths.append("Your values and working style seem strongly aligned with the company culture.")
            elif avg_cultural_fit < 60:
                areas_for_improvement.append("You could show stronger alignment with the company's values and culture.")

            if avg_motivation >= 75:
                strengths.append("You demonstrated strong motivation and enthusiasm for the role.")
            elif avg_motivation < 60:
                areas_for_improvement.append("Your motivation for this role was not always clear or convincing.")

            if avg_clarity >= 75:
                strengths.append("Your answers were clear, well‑structured, and easy to follow.")
            elif avg_clarity < 60:
                areas_for_improvement.append("Your answers would benefit from clearer structure and more focused messaging.")

            if strengths:
                feedback_summary += f"Key strengths: {', '.join(strengths[:2])}. "
            if areas_for_improvement:
                feedback_summary += f"Key areas to improve: {', '.join(areas_for_improvement[:2])}."
        
        if not recommendations:
            recommendations.append(
                "Practice answering HR questions using the STAR (Situation–Task–Action–Result) format with concrete examples."
            )
        
        # Update session status with atomic update (row-level locking)
        supabase.table("interview_sessions").update({"session_status": "completed"}).eq("id", session_id).neq("session_status", "completed").execute()
        
        logger.info(f"[HR][FEEDBACK] ✅ Feedback generated successfully for session {session_id}")
        
        return {
            "overall_score": round(avg_overall, 2),
            "communication_score": round(avg_communication, 2),
            "cultural_fit_score": round(avg_cultural_fit, 2),
            "motivation_score": round(avg_motivation, 2),
            "clarity_score": round(avg_clarity, 2),
            "feedback_summary": feedback_summary,
            "strengths": strengths[:5],
            "areas_for_improvement": areas_for_improvement[:5],
            "recommendations": recommendations[:5],
            "question_count": len(answers),
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[HR][FEEDBACK] Unexpected error generating HR feedback: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate feedback. Please try again.")


@router.put("/{session_id}/end", response_model=InterviewEndResponse)
async def end_hr_interview(
    session_id: str,
    supabase: Client = Depends(get_supabase_client)
):
    """
    End the HR interview session
    Updates session status to completed
    """
    try:
        # Input validation
        if not session_id or not isinstance(session_id, str) or not session_id.strip():
            logger.error(f"[HR][END] Invalid session_id: {session_id}")
            raise HTTPException(status_code=400, detail="Invalid request format. Please check your input and try again.")
        
        logger.info(f"[HR][END] Ending HR interview session: {session_id}")
        
        # Verify session exists and is HR type
        try:
            session_response = supabase.table("interview_sessions").select("*").eq("id", session_id).execute()
        except Exception as db_error:
            logger.error(f"[HR][END] Database error fetching session: {str(db_error)}", exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to retrieve interview session. Please try again.")
        
        if not session_response.data or len(session_response.data) == 0:
            logger.warning(f"[HR][END] Session not found: {session_id}")
            raise HTTPException(status_code=404, detail="Interview session not found. Please start a new interview.")
        
        session = session_response.data[0]
        
        # Validate session is HR type
        session_type = session.get("interview_type", "").lower()
        if session_type != "hr":
            logger.error(f"[HR][END] Wrong session type: {session_type} (expected: hr)")
            raise HTTPException(
                status_code=400, 
                detail="This endpoint is for HR interviews only. Please use the correct interview type."
            )
        
        # Update session status to completed
        # Use atomic update with row-level locking: only update if status is not already "completed"
        try:
            update_response = supabase.table("interview_sessions").update({
                "session_status": "completed"
            }).eq("id", session_id).neq("session_status", "completed").execute()
            
            if not update_response.data or len(update_response.data) == 0:
                logger.info(f"[HR][END] Session already completed for session_id: {session_id}")
            else:
                logger.info(f"[HR][END] ✅ HR interview session ended successfully: {session_id}")
        except Exception as db_error:
            logger.error(f"[HR][END] Database error updating session status: {str(db_error)}", exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to update session status. Please try again.")
        
        return {
            "message": "HR interview ended successfully",
            "session_id": session_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[HR][END] Unexpected error ending HR interview: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to end interview. Please try again.")

