"""
Technical Interview Routes
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Body
from typing import Any, Dict
from supabase import Client
from app.db.client import get_supabase_client
from app.routers.interview_utils import log_interview_transcript, build_resume_context_from_profile
from app.services.technical_interview_engine import technical_interview_engine
from app.services.resume_parser import resume_parser
from app.utils.url_utils import get_api_base_url
from app.schemas.interview import (
    TechnicalInterviewStartResponse,
    TechnicalSubmitAnswerResponse,
    TechnicalNextQuestionResponse,
    TechnicalFeedbackResponse,
    TechnicalSummaryResponse,
    InterviewEndResponse
)
from app.utils.rate_limiter import check_rate_limit, rate_limit_by_session_id
from app.utils.request_validator import validate_request_size
from fastapi import Request
import os
import tempfile
import urllib.parse
import logging
import re

logger = logging.getLogger(__name__)

# Technical Interview Constants
TECHNICAL_MAX_QUESTIONS = 10

router = APIRouter(prefix="/technical", tags=["technical-interview"])



@router.post("/start", response_model=TechnicalInterviewStartResponse)
async def start_interview_page(
    http_request: Request,
    request_body: Dict[str, Any] = Body(...),
    supabase: Client = Depends(get_supabase_client),
    _: None = Depends(validate_request_size)
):
    """
    Start a new technical interview for the new interview.html page
    Returns the first question based on resume skills
    """
    try:
        user_id = request_body.get("user_id")
        session_id = request_body.get("session_id")  # Optional: can reuse existing session
        
        if not user_id:
            raise HTTPException(
                status_code=400, 
                detail="user_id is required. Please ensure the frontend passes user_id in the request body. This should be fetched from /api/profile/current or stored in the user session."
            )
        
        # Validate user_id format: alphanumeric, hyphen, underscore only
        if not re.match(r'^[a-zA-Z0-9_-]+$', user_id):
            raise HTTPException(status_code=400, detail="Invalid user_id format")
        
        # Check rate limit
        check_rate_limit(user_id)
        
        # user_id is now TEXT (slugified name), not UUID - no validation needed
        
        # Get user profile to extract resume skills (required)
        resume_skills = []
        resume_context = None
        profile_response = None
        
        try:
            profile_response = supabase.table("user_profiles").select("*").eq("user_id", user_id).execute()
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Error fetching user profile: {str(e)}"
            )
        
        # Require profile to exist - if not, raise error (user must upload resume first)
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
            else:
                # No profile found - user must upload resume first
                raise HTTPException(
                    status_code=404,
                    detail=f"User profile not found for user_id: {user_id}. Please upload a resume first to create your profile."
                )
        
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
                    logger.warning(f"Could not parse resume for technical interview: {str(e)}")
        
        # If no skills found, require user to upload resume
        if not resume_skills or len(resume_skills) == 0:
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
            # Ensure user profile exists before creating session (to satisfy foreign key constraint)
            if not profile_response or not profile_response.data or len(profile_response.data) == 0:
                raise HTTPException(
                    status_code=404,
                    detail=f"User profile not found for user_id: {user_id}. Please upload a resume first to create your profile."
                )
            
            # Create new session in database
            db_session_data = {
                "user_id": user_id,  # TEXT (slugified name)
                "interview_type": "technical",  # New schema field
                "role": "Technical Interview",  # Keep for backward compatibility
                "experience_level": (profile_response.data[0].get("experience_level", "Intermediate") if profile_response and profile_response.data else "Intermediate"),
                "skills": resume_skills,
                "session_status": "active"
            }
            
            try:
                session_response = supabase.table("interview_sessions").insert(db_session_data).execute()
                
                if not session_response.data or len(session_response.data) == 0:
                    raise HTTPException(status_code=500, detail="Failed to create interview session")
                
                session_id = session_response.data[0]["id"]
            except HTTPException:
                raise
            except Exception as db_error:
                error_str = str(db_error)
                # Check if it's a foreign key constraint error
                if "foreign key constraint" in error_str.lower() or "not present in table" in error_str.lower():
                    raise HTTPException(
                        status_code=400,
                        detail=f"User profile not found. Please ensure user_id {user_id} exists in user_profiles table. Error: {error_str}"
                    )
                raise HTTPException(
                    status_code=500,
                    detail=f"Error creating interview session: {error_str}"
                )
        
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
        
        # Generate audio URL for the question BEFORE storing
        audio_url = None
        try:
            question_text = first_question_data.get("question", "")
            if question_text:
                encoded_text = urllib.parse.quote(question_text)
                # Use TECH_BACKEND_URL if set, otherwise use request-based URL detection
                from app.config.settings import settings
                base_url = settings.tech_backend_url or get_api_base_url(http_request)
                # Ensure base_url doesn't end with slash
                base_url = base_url.rstrip('/')
                audio_url = f"{base_url}/api/interview/text-to-speech?text={encoded_text}"
                logger.info(f"[START INTERVIEW] Generated audio_url: {audio_url}")
        except Exception as e:
            logger.warning(f"Could not generate audio URL for first question: {str(e)}")
        
        # Store first question in technical_round table
        if session_id:
            try:
                # Check if session exists in DB before storing question
                session_check = supabase.table("interview_sessions").select("id, user_id").eq("id", session_id).limit(1).execute()
                if session_check.data and len(session_check.data) > 0:
                    session_user_id = str(session_check.data[0].get("user_id", user_id))
                    question_db_data = {
                        "user_id": session_user_id,
                        "session_id": session_id,
                        "question_number": 1,
                        "question_text": first_question_data["question"],
                        "question_type": first_question_data.get("question_type", "Technical"),
                        "audio_url": audio_url,  # CRITICAL: Store audio_url when question is created
                        "user_answer": "",  # Placeholder - will be updated when user submits answer
                        "relevance_score": None,
                        "technical_accuracy_score": None,
                        "communication_score": None,
                        "overall_score": None,
                        "ai_feedback": None,
                        "response_time": None
                    }
                    insert_response = supabase.table("technical_round").insert(question_db_data).execute()
                    if not insert_response.data or len(insert_response.data) == 0:
                        logger.error(f"[START INTERVIEW] ❌ Failed to store first question in database")
                        raise HTTPException(status_code=500, detail="Failed to store first question in database")
                    logger.info(f"[START INTERVIEW] ✓ Stored first question with ID: {insert_response.data[0].get('id')}")
            except Exception as e:
                logger.error(f"[START INTERVIEW] ❌ Could not store first question in database: {str(e)}")
                # Error storing question - raise exception
                raise HTTPException(status_code=500, detail=f"Error storing question: {str(e)}")
        
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
            "total_questions": 18,  # Will ask 15-20 questions
            "skills": resume_skills,
            "audio_url": audio_url,
            "interview_completed": False,
            "user_id": user_id  # Include user_id in response
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error starting interview: {str(e)}")


@router.post("/{session_id}/next-question", response_model=TechnicalNextQuestionResponse)
async def get_next_technical_question(
    session_id: str,
    http_request: Request,
    request_body: Dict[str, Any] = Body(...),
    supabase: Client = Depends(get_supabase_client),
    _: None = Depends(validate_request_size)
):
    """
    Get the next technical question for the interview
    Accepts user_answer in request body, saves it first, then generates context-aware next question
    Uses conversation history from database to enable context-aware follow-up questions (like HR/STAR)
    """
    try:
        # Input validation
        if not session_id or not isinstance(session_id, str) or not session_id.strip():
            logger.error(f"[TECHNICAL][NEXT-QUESTION] Invalid session_id: {session_id}")
            raise HTTPException(status_code=400, detail="Invalid request format. Please check your input and try again.")
        
        logger.info(f"[TECHNICAL][NEXT-QUESTION] Request for session_id: {session_id}")
        
        # Get session
        try:
            session_response = supabase.table("interview_sessions").select("*").eq("id", session_id).execute()
        except Exception as db_error:
            logger.error(f"[TECHNICAL][NEXT-QUESTION] Database error fetching session: {str(db_error)}", exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to retrieve interview session. Please try again.")
        
        if not session_response.data or len(session_response.data) == 0:
            logger.warning(f"[TECHNICAL][NEXT-QUESTION] Session not found: {session_id}")
            raise HTTPException(status_code=404, detail="Interview session not found. Please start a new interview.")
        
        session = session_response.data[0]
        
        # Check if session is already completed
        session_status = session.get("session_status", "").lower()
        if session_status == "completed":
            logger.warning(f"[TECHNICAL][NEXT-QUESTION] Session already completed: {session_id}")
            raise HTTPException(
                status_code=400,
                detail="This interview session has already been completed. Please start a new interview."
            )
        
        # Validate session is technical type
        session_type = session.get("interview_type", "").lower()
        if session_type != "technical":
            logger.error(f"[TECHNICAL][NEXT-QUESTION] Wrong session type: {session_type} (expected: technical)")
            raise HTTPException(
                status_code=400, 
                detail="This endpoint is for technical interviews only. Please use the correct interview type."
            )
        
        # Step 1: Save current answer if provided in request (like HR/STAR interviews)
        user_answer = request_body.get("user_answer") or request_body.get("answer")
        
        if user_answer is not None:
            if not isinstance(user_answer, str):
                logger.warning(f"[TECHNICAL][NEXT-QUESTION] Invalid user_answer type received: {type(user_answer)}. Attempting conversion.")
                try:
                    user_answer = str(user_answer) 
                except Exception:
                    user_answer = None
            
            # ✅ Reject empty answers - NO random/auto-answers allowed
            if user_answer and user_answer.strip():
                try:
                    # Get the last question for this session to update with the answer
                    last_question_response = supabase.table("technical_round").select("*").eq("session_id", session_id).order("question_number", desc=True).limit(1).execute()
                    
                    if last_question_response.data and len(last_question_response.data) > 0:
                        last_question = last_question_response.data[0]
                        question_number = last_question.get("question_number")
                        
                        # Update the last question with the user's answer
                        update_data = {
                            "user_answer": user_answer
                        }
                        
                        supabase.table("technical_round").update(update_data).eq("session_id", session_id).eq("question_number", question_number).execute()
                        logger.info(f"[TECHNICAL][NEXT-QUESTION] ✅ Saved user answer for question {question_number}")
                    else:
                        logger.warning("[TECHNICAL][NEXT-QUESTION] No question found to update with answer")
                except Exception as e:
                    logger.error(f"[TECHNICAL][NEXT-QUESTION] Failed to save user answer: {str(e)}", exc_info=True)
                    raise HTTPException(
                        status_code=500,
                        detail="Failed to save interview data. Please try again."
                    )
            else:
                # ✅ Reject empty answers - do NOT allow unanswered questions to move forward
                logger.warning("[TECHNICAL][NEXT-QUESTION] Empty answer provided - rejecting request")
                raise HTTPException(
                    status_code=400,
                    detail="I could not hear your answer. Please speak again."
                )
        
        # Step 2: Retrieve full conversation history from technical_round table AFTER saving answer
        technical_round_response = supabase.table("technical_round").select(
            "question_text, question_number, user_answer"
        ).eq("session_id", session_id).order("question_number").execute()
        
        # Step 3: Build conversation history array in exact format for LLM
        conversation_history = []
        questions_asked = []
        answers_received = []
        
        for row in (technical_round_response.data or []):
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
        
        # Check if interview should end (max 10 questions for Technical - same as HR/STAR)
        current_question_count = len(questions_asked)
        
        # If we already have 10 questions, don't generate another one
        if current_question_count >= TECHNICAL_MAX_QUESTIONS:
            logger.info(f"[TECHNICAL][NEXT-QUESTION] Interview completed: {current_question_count} questions already asked (max: {TECHNICAL_MAX_QUESTIONS})")
            return {
                "interview_completed": True,
                "message": "Interview completed. Maximum questions reached."
            }
        
        # ✅ CONVERSATIONAL FLOW: Generate next question using OpenAI with conversation history (like HR/STAR)
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
        
        # Generate next technical question using OpenAI with conversation history
        question_text = None
        try:
            from openai import OpenAI, APIError, RateLimitError
            from app.config.settings import settings
            
            # Check if API key is available
            if not settings.openai_api_key:
                logger.error("[TECHNICAL][NEXT-QUESTION] OpenAI API key is missing.")
                raise HTTPException(status_code=503, detail="AI service temporarily unavailable. API key not set.")
            
            client = OpenAI(api_key=settings.openai_api_key)
            
            # Build context for technical question generation
            skills_context = ", ".join(skills[:10]) if skills else "general technical skills"
            
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
            
            # Technical-focused system prompt
            system_prompt = """You are an experienced, friendly technical interviewer conducting a natural, conversational voice-based interview.

Your interview style:
- Speak naturally and conversationally, as if talking to a colleague
- Build on previous answers - ask follow-up questions when appropriate
- Show genuine interest in the candidate's responses
- Focus on technical knowledge, problem-solving, and implementation details
- Reference what the candidate mentioned in previous answers
- Avoid awkward pauses - keep the conversation flowing smoothly
- Never repeat questions that have already been asked

Question guidelines:
- Keep questions concise (1-2 sentences) for voice interaction
- Make questions feel natural and conversational
- Build on previous answers to create a cohesive interview flow
- Test technical knowledge progressively (basic → advanced)
- Reference specific technologies/skills from the resume when relevant"""

            user_prompt = f"""Generate the next technical interview question for a smooth, natural conversation flow.

CANDIDATE'S TECHNICAL SKILLS (from resume):
Skills: {skills_context}
Experience Level: {experience_level}

CONVERSATION HISTORY (full context):
{conversation_context if conversation_context else "This is the first question. Start with a friendly introduction and a foundational technical question."}

PREVIOUSLY ASKED QUESTIONS (do NOT repeat these):
{questions_list if questions_list else "None - this is the first question"}

INTERVIEW PROGRESS:
- Questions asked so far: {len(questions_asked)}
- Answers received: {len(answers_received)}

Generate ONE natural, conversational technical question that:
1. Flows naturally from the conversation (builds on previous answers if any)
2. Is relevant to the candidate's skills: {skills_context}
3. Has NOT been asked before (check the list above)
4. Feels like a natural next question in a human interview
5. Is appropriate for voice interaction (concise, clear)
6. Tests technical knowledge at an appropriate level
7. References specific technologies from their resume when relevant

IMPORTANT:
- If this is early in the interview, start with foundational questions
- If the candidate mentioned something interesting, ask a follow-up
- Make it feel like a real conversation, not a scripted Q&A
- Reference specific technologies from their resume when relevant

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
                logger.info(f"[TECHNICAL][NEXT-QUESTION] ✅ Added {len(history_messages)} conversation history messages for context-aware question generation")
            
            messages.append({"role": "user", "content": user_prompt})
            
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=messages,
                temperature=0.7,
                max_tokens=150,
                timeout=30
            )
            
            question_text = response.choices[0].message.content.strip()
            logger.info(f"[TECHNICAL][NEXT-QUESTION] Generated next question: {question_text[:50]}...")
            
        except RateLimitError as e:
            logger.error(f"[TECHNICAL][NEXT-QUESTION] OpenAI rate limit exceeded: {str(e)}")
            raise HTTPException(
                status_code=503, 
                detail="The AI service is currently experiencing high demand. Please try again shortly."
            )
        except APIError as e:
            logger.error(f"[TECHNICAL][NEXT-QUESTION] OpenAI API error: {str(e)}", exc_info=True)
            raise HTTPException(
                status_code=500, 
                detail="An external service error occurred during question generation. Please try again."
            )
        except Exception as e:
            logger.error(f"[TECHNICAL][NEXT-QUESTION] Unexpected error: {str(e)}", exc_info=True)
            question_text = None
        
        # Fallback to technical_interview_engine if OpenAI failed
        if not question_text:
            try:
                session_data = {
                    "session_id": session_id,
                    "technical_skills": skills,
                    "conversation_history": conversation_history,
                    "current_question_index": current_question_count,
                    "questions_asked": questions_asked,
                    "answers_received": answers_received
                }
                question_data = technical_interview_engine.generate_next_question(session_data, conversation_history)
                question_text = question_data.get("question", "")
            except Exception as fallback_error:
                logger.error(f"[TECHNICAL][NEXT-QUESTION] Fallback question generation failed: {str(fallback_error)}")
                # Last resort fallback
                fallback_questions = [
                    f"Can you explain how you would use {skills[0] if skills else 'your technical skills'} in a real-world project?",
                    "What's your approach to debugging complex technical issues?",
                    "How do you stay updated with the latest technologies in your field?",
                    "Can you describe a challenging technical problem you've solved?",
                    "What's your experience with version control and collaboration tools?"
                ]
                question_text = fallback_questions[current_question_count % len(fallback_questions)]
        
        # Store new question in technical_round table
        question_number = current_question_count + 1
        user_id = str(session.get("user_id", "")) if session else ""
        
        question_db_data = {
            "user_id": user_id,
            "session_id": session_id,
            "question_number": question_number,
            "question_text": question_text,
            "question_type": "Technical",
            "user_answer": "",  # Placeholder - will be updated when user submits answer
            "relevance_score": None,
            "technical_accuracy_score": None,
            "communication_score": None,
            "overall_score": None,
            "ai_feedback": None,
            "response_time": None
        }
        
        try:
            insert_response = supabase.table("technical_round").insert(question_db_data).execute()
            if not insert_response.data or len(insert_response.data) == 0:
                logger.error("[TECHNICAL][NEXT-QUESTION] Failed to store technical question - no data returned from insert")
                raise HTTPException(
                    status_code=500,
                    detail="Failed to save interview question. Please try again."
                )
            logger.info(f"[TECHNICAL][NEXT-QUESTION] ✅ Stored question {question_number} in database")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[TECHNICAL][NEXT-QUESTION] Failed to store technical question: {str(e)}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail="Failed to save interview question. Please try again."
            )
        
        # ✅ FIX: Generate audio URL for EVERY question - MUST always return audio_url
        audio_url = None
        try:
            if question_text:
                encoded_text = urllib.parse.quote(question_text)
                # Use TECH_BACKEND_URL if set, otherwise use request-based URL detection
                from app.config.settings import settings
                base_url = settings.tech_backend_url or get_api_base_url(http_request)
                # Ensure base_url doesn't end with slash
                base_url = base_url.rstrip('/')
                audio_url = f"{base_url}/api/interview/text-to-speech?text={encoded_text}"
                logger.info(f"[TECHNICAL][INTERVIEW] ✅ Generated audio_url: {audio_url}")
            else:
                logger.error(f"[TECHNICAL][INTERVIEW] ❌ question_text is empty, cannot generate audio_url")
                audio_url = None
        except Exception as e:
            logger.error(f"[TECHNICAL][INTERVIEW] ❌ Could not generate audio URL for technical question: {str(e)}", exc_info=True)
            audio_url = None
        
        # Determine if interview is completed (question_number > 10)
        interview_completed = question_number > TECHNICAL_MAX_QUESTIONS
        
        return {
            "question": question_text,
            "question_type": "Technical",
            "question_number": question_number,
            "total_questions": 10,  # Technical interviews now have 10 questions (same as HR/STAR)
            "audio_url": audio_url,
            "interview_completed": interview_completed,
            "session_id": session_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[TECHNICAL][NEXT-QUESTION] Unexpected error getting next technical question: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate next question. Please try again.")


@router.post("/{session_id}/submit-answer", response_model=TechnicalSubmitAnswerResponse)
async def submit_technical_answer(
    session_id: str,
    http_request: Request,
    request_body: Dict[str, Any] = Body(...),
    supabase: Client = Depends(get_supabase_client),
    _: None = Depends(validate_request_size)
):
    """
    Submit an answer to the current technical question
    """
    try:
        question = request_body.get("question")
        answer = request_body.get("answer")
        
        if not question or not answer:
            raise HTTPException(status_code=400, detail="question and answer are required")
        
        # Get session
        session_response = supabase.table("interview_sessions").select("*").eq("id", session_id).execute()
        
        if not session_response.data or len(session_response.data) == 0:
            raise HTTPException(status_code=404, detail="Session not found")
        
        session = session_response.data[0]
        
        # Get current question from technical_round table (new schema)
        questions_response = supabase.table("technical_round").select("*").eq("session_id", session_id).order("question_number", desc=True).limit(1).execute()
        
        if not questions_response.data or len(questions_response.data) == 0:
            raise HTTPException(status_code=404, detail="No current question found")
        
        current_question_db = questions_response.data[0]
        question_id = current_question_db["id"]
        question_number = current_question_db["question_number"]
        
        # Get conversation history from technical_round table
        round_data_response = supabase.table("technical_round").select("question_text, question_number, user_answer").eq("session_id", session_id).order("question_number").execute()
        
        conversation_history = []
        questions_asked_list = []
        answers_received_list = []
        
        for row in (round_data_response.data or []):
            question_text = row.get("question_text", "")
            user_answer = row.get("user_answer", "")
            if question_text:
                conversation_history.append({"role": "ai", "content": question_text})
                questions_asked_list.append(question_text)
            if user_answer:  # Only add answer if it's not empty
                conversation_history.append({"role": "user", "content": user_answer})
                answers_received_list.append(user_answer)
        
        # Prepare session data
        session_data = {
            "session_id": session_id,
            "technical_skills": session.get("skills", []),
            "conversation_history": conversation_history,
            "current_question_index": len(questions_asked_list),
            "questions_asked": questions_asked_list,
            "answers_received": answers_received_list
        }
        
        # Evaluate answer (get scores only, feedback will be generated separately)
        evaluation = technical_interview_engine.evaluate_answer(
            question=question,
            answer=answer,
            session_data=session_data,
            conversation_history=conversation_history
        )
        
        # Get scores from evaluation
        scores = evaluation.get("scores", {})
        
        # Generate AI feedback response (same style as HR interview)
        # This replaces the follow-up question approach with proper feedback
        ai_response = None
        question_text = current_question_db.get("question_text", question)
        
        if technical_interview_engine.openai_available and technical_interview_engine.client is not None:
            try:
                system_prompt = """You are an experienced technical interviewer providing feedback on candidate answers.
Provide brief, encouraging, and constructive feedback (1-2 sentences) that:
- Acknowledges what the candidate said
- Provides gentle guidance if needed
- Maintains a positive, professional tone
- Is appropriate for technical interview context"""

                user_prompt = f"""Question: {question_text}
Candidate Answer: {answer}
Technical Accuracy Score: {scores.get('technical_accuracy', 0)}/100
Communication Score: {scores.get('communication', 0)}/100
Overall Score: {scores.get('overall', 0)}/100

Provide brief, encouraging feedback for this technical interview answer."""

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
                logger.info(f"[TECHNICAL][SUBMIT-ANSWER] AI feedback generated: {ai_response[:50]}...")
                
            except Exception as e:
                logger.warning(f"[TECHNICAL][SUBMIT-ANSWER] Could not generate AI feedback: {str(e)}")
                ai_response = "Thank you for your answer. Let's continue with the next question."
        else:
            ai_response = "Thank you for your answer. Let's continue with the next question."
        
        # Generate audio URL for AI response
        ai_response_audio_url = None
        if ai_response:
            try:
                encoded_text = urllib.parse.quote(ai_response)
                # Use TECH_BACKEND_URL if set, otherwise use request-based URL detection
                from app.config.settings import settings
                base_url = settings.tech_backend_url or get_api_base_url(http_request)
                # Ensure base_url doesn't end with slash
                base_url = base_url.rstrip('/')
                ai_response_audio_url = f"{base_url}/api/interview/text-to-speech?text={encoded_text}"
                logger.info(f"[TECHNICAL][SUBMIT-ANSWER] Generated AI feedback audio URL: {ai_response_audio_url}")
            except Exception as e:
                logger.warning(f"[TECHNICAL][SUBMIT-ANSWER] Could not generate audio URL: {str(e)}")
        
        # Update the existing question row in technical_round table with the answer and evaluation
        user_id = str(session.get("user_id", "")) if session else ""
        
        # Get user's answer audio_url from request (if provided)
        user_answer_audio_url = request_body.get("audio_url")  # User's answer audio URL from frontend
        
        # CRITICAL: Log before update with all relevant data
        logger.info(f"[SUBMIT ANSWER] ========== Preparing to Update Technical Round ==========")
        logger.info(f"[SUBMIT ANSWER] session_id: {session_id} (type: {type(session_id).__name__})")
        logger.info(f"[SUBMIT ANSWER] user_id: {user_id}")
        logger.info(f"[SUBMIT ANSWER] question_number: {question_number} (type: {type(question_number).__name__})")
        logger.info(f"[SUBMIT ANSWER] extracted_answer_text: {answer[:100]}..." if len(answer) > 100 else f"[SUBMIT ANSWER] extracted_answer_text: {answer}")
        logger.info(f"[SUBMIT ANSWER] user_answer_audio_url: {user_answer_audio_url}")
        logger.info(f"[SUBMIT ANSWER] ai_response_audio_url: {ai_response_audio_url}")
        logger.info(f"[SUBMIT ANSWER] relevance_score: {scores.get('relevance', 0)}")
        logger.info(f"[SUBMIT ANSWER] technical_accuracy_score: {scores.get('technical_accuracy', 0)}")
        logger.info(f"[SUBMIT ANSWER] communication_score: {scores.get('communication', 0)}")
        logger.info(f"[SUBMIT ANSWER] overall_score: {scores.get('overall', 0)}")
        logger.info(f"[SUBMIT ANSWER] ai_response (feedback): {ai_response[:50] if ai_response else 'None'}...")
        
        # Verify the row exists before updating
        verify_response = supabase.table("technical_round").select("id, session_id, question_number, user_id").eq("session_id", str(session_id)).eq("question_number", int(question_number)).execute()
        
        if not verify_response.data or len(verify_response.data) == 0:
            logger.error(f"[SUBMIT ANSWER] ❌ CRITICAL: Row not found for update!")
            logger.error(f"[SUBMIT ANSWER] Searched for session_id={session_id} (as {type(session_id).__name__}), question_number={question_number} (as {type(question_number).__name__})")
            # Try to find what rows actually exist
            debug_response = supabase.table("technical_round").select("id, session_id, question_number").eq("session_id", str(session_id)).execute()
            logger.error(f"[SUBMIT ANSWER] Debug: Found {len(debug_response.data) if debug_response.data else 0} rows with session_id={session_id}")
            if debug_response.data:
                for row in debug_response.data:
                    logger.error(f"[SUBMIT ANSWER] Debug row: id={row.get('id')}, session_id={row.get('session_id')} (type: {type(row.get('session_id')).__name__}), question_number={row.get('question_number')} (type: {type(row.get('question_number')).__name__})")
            raise HTTPException(status_code=404, detail=f"Question row not found for session_id={session_id}, question_number={question_number}. Cannot update answer.")
        
        logger.info(f"[SUBMIT ANSWER] ✓ Row found. Existing row ID: {verify_response.data[0].get('id')}")
        
        # Get user's answer audio_url from request if provided
        user_answer_audio_url = request_body.get("audio_url")  # User's answer audio URL from frontend
        
        # Update the existing row (the question was already stored when it was asked)
        # Ensure ALL fields are included: user_answer, audio_url (user's answer), scores, and feedback
        update_data = {
            "user_answer": answer,
            "audio_url": user_answer_audio_url,  # CRITICAL: User's answer audio URL (not AI response audio)
            "relevance_score": scores.get("relevance", 0),
            "technical_accuracy_score": scores.get("technical_accuracy", 0),
            "communication_score": scores.get("communication", 0),
            "overall_score": scores.get("overall", 0),
            "ai_feedback": ai_response if ai_response else "",  # AI feedback on the answer (generated above)
            "ai_response": ai_response if ai_response else "",  # AI response/feedback (generated above)
            "response_time": None
        }
        
        # Ensure no None values are stored as None (use empty string for text fields, 0 for scores if needed)
        # But actually, None is acceptable for optional fields per schema, so we keep them as is
        
        logger.info(f"[SUBMIT ANSWER] Update data prepared: {list(update_data.keys())}")
        
        # Update the row for this question_number and session_id
        # CRITICAL: Normalize types to ensure match (session_id as str, question_number as int)
        answer_response = supabase.table("technical_round").update(update_data).eq("session_id", str(session_id)).eq("question_number", int(question_number)).execute()
        
        # CRITICAL FIX: Validate that the update actually succeeded
        if not answer_response.data or len(answer_response.data) == 0:
            logger.error(f"[SUBMIT ANSWER] ❌ CRITICAL: Database update returned no rows!")
            logger.error(f"[SUBMIT ANSWER] Update query: session_id={str(session_id)}, question_number={int(question_number)}")
            logger.error(f"[SUBMIT ANSWER] Update data: {update_data}")
            # Try to get the current row to debug
            debug_response = supabase.table("technical_round").select("*").eq("session_id", str(session_id)).eq("question_number", int(question_number)).execute()
            logger.error(f"[SUBMIT ANSWER] Debug - Current row exists: {debug_response.data is not None and len(debug_response.data) > 0 if debug_response.data else False}")
            if debug_response.data:
                logger.error(f"[SUBMIT ANSWER] Debug - Current row data: {debug_response.data[0]}")
            raise HTTPException(status_code=500, detail=f"Failed to save answer to database. No rows were updated. This may be due to RLS policies or data type mismatches.")
        
        # Log successful update with response details
        updated_row = answer_response.data[0]
        logger.info(f"[SUBMIT ANSWER] ✅ SUCCESS: Database update completed!")
        logger.info(f"[SUBMIT ANSWER] Updated row ID: {updated_row.get('id')}")
        logger.info(f"[SUBMIT ANSWER] Updated user_answer: {updated_row.get('user_answer', '')[:50]}..." if len(updated_row.get('user_answer', '')) > 50 else f"[SUBMIT ANSWER] Updated user_answer: {updated_row.get('user_answer', '')}")
        logger.info(f"[SUBMIT ANSWER] Updated audio_url: {updated_row.get('audio_url')}")
        logger.info(f"[SUBMIT ANSWER] Updated relevance_score: {updated_row.get('relevance_score')}")
        logger.info(f"[SUBMIT ANSWER] Updated technical_accuracy_score: {updated_row.get('technical_accuracy_score')}")
        logger.info(f"[SUBMIT ANSWER] Updated communication_score: {updated_row.get('communication_score')}")
        logger.info(f"[SUBMIT ANSWER] Updated overall_score: {updated_row.get('overall_score')}")
        logger.info(f"[SUBMIT ANSWER] Updated ai_feedback: {updated_row.get('ai_feedback', '')[:50]}..." if len(updated_row.get('ai_feedback', '')) > 50 else f"[SUBMIT ANSWER] Updated ai_feedback: {updated_row.get('ai_feedback', '')}")
        logger.info(f"[SUBMIT ANSWER] Updated ai_response: {updated_row.get('ai_response', '')[:50]}..." if len(updated_row.get('ai_response', '')) > 50 else f"[SUBMIT ANSWER] Updated ai_response: {updated_row.get('ai_response', '')}")
        logger.info(f"[SUBMIT ANSWER] ========== Update Complete ==========")
        
        # Check if interview should continue (max 10 questions for Technical, same as HR/STAR)
        TECHNICAL_MAX_QUESTIONS = 10
        total_questions = len(questions_asked_list)
        interview_completed = total_questions >= TECHNICAL_MAX_QUESTIONS
        
        # Update the main interview_sessions table status if interview is completed
        # Use atomic update with row-level locking: only update if status is not already "completed"
        if interview_completed:
            try:
                update_response = supabase.table("interview_sessions").update({
                    "session_status": "completed"
                }).eq("id", session_id).neq("session_status", "completed").execute()
                
                if update_response.data and len(update_response.data) > 0:
                    logger.info(f"[TECHNICAL][SUBMIT-ANSWER] ✅ Session marked as completed for session_id: {session_id}")
                else:
                    logger.info(f"[TECHNICAL][SUBMIT-ANSWER] Session already completed for session_id: {session_id}")
            except Exception as e:
                logger.warning(f"[TECHNICAL][SUBMIT-ANSWER] Could not update session status to completed: {str(e)}")
        
        # Return response with feedback (same structure as HR interview)
        return {
            "answer_id": answer_response.data[0].get("id"),
            "session_id": session_id,
            "question_number": question_number,
            "scores": {
                "relevance": scores.get("relevance", 0),
                "technical_accuracy": scores.get("technical_accuracy", 0),
                "communication": scores.get("communication", 0),
                "overall": scores.get("overall", 0)
            },
            "ai_response": ai_response,  # AI feedback (generated above)
            "audio_url": ai_response_audio_url,  # Audio URL for AI feedback
            "interview_completed": interview_completed
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error submitting answer: {str(e)}")


@router.get("/{session_id}/feedback", response_model=TechnicalFeedbackResponse)
async def get_technical_interview_feedback(
    session_id: str,
    supabase: Client = Depends(get_supabase_client),
    _: None = Depends(rate_limit_by_session_id)
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
        
        # Get all answers from technical_round table
        answers_response = supabase.table("technical_round").select("*").eq("session_id", session_id).order("question_number").execute()
        answers = answers_response.data if answers_response.data else []
        
        if not answers:
            raise HTTPException(status_code=400, detail="No answers found for this session")
        
        # CRITICAL: Validate that answers are actually saved (not empty)
        # But be lenient - work with whatever data we have
        answers_with_data = []
        missing_data_rows = []
        
        for idx, row in enumerate(answers, 1):
            user_answer = row.get("user_answer", "")
            relevance_score = row.get("relevance_score")
            technical_accuracy_score = row.get("technical_accuracy_score")
            communication_score = row.get("communication_score")
            overall_score = row.get("overall_score")
            
            # Check if this row has been properly saved
            if not user_answer or user_answer.strip() == "":
                missing_data_rows.append(f"Question {row.get('question_number', idx)}: user_answer is empty")
            elif relevance_score is None and technical_accuracy_score is None and communication_score is None:
                missing_data_rows.append(f"Question {row.get('question_number', idx)}: scores are NULL")
            else:
                answers_with_data.append(row)
        
        # If NO rows have data, return error
        if len(answers_with_data) == 0:
            error_detail = f"No complete answers found. Missing data in: {', '.join(missing_data_rows)}. Please ensure all answers are submitted before viewing feedback."
            logger.error(f"[FEEDBACK] ❌ Cannot generate feedback: {error_detail}")
            raise HTTPException(status_code=400, detail=error_detail)
        
        # If some rows are missing data but we have at least one complete answer, log warning but continue
        if missing_data_rows and len(answers_with_data) > 0:
            logger.warning(f"[FEEDBACK] ⚠️  Some answers incomplete: {', '.join(missing_data_rows)}. Generating feedback with {len(answers_with_data)} complete answers.")
        
        # Use only rows with complete data
        answers = answers_with_data
        
        # Get conversation history from technical_round table (new schema)
        # Questions and answers are in the same table
        conversation_history = []
        questions_asked = []
        answers_received = []
        
        for row in answers:
            question_text = row.get("question_text", "")
            user_answer = row.get("user_answer", "")
            if question_text:
                conversation_history.append({"role": "ai", "content": question_text})
                questions_asked.append(question_text)
            if user_answer and user_answer.strip():  # Only add if answer exists and is not empty
                conversation_history.append({"role": "user", "content": user_answer})
                answers_received.append(user_answer)
        
        # Prepare session data
        session_data = {
            "session_id": session_id,
            "technical_skills": session.get("skills", []),
            "conversation_history": conversation_history,
            "current_question_index": len(questions_asked),
            "questions_asked": questions_asked,
            "answers_received": answers_received
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
        
        # Update session status with atomic update (row-level locking)
        supabase.table("interview_sessions").update({"session_status": "completed"}).eq("id", session_id).neq("session_status", "completed").execute()
        
        return feedback
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating feedback: {str(e)}")



@router.put("/{session_id}/end", response_model=InterviewEndResponse)
async def end_technical_interview(
    session_id: str,
    supabase: Client = Depends(get_supabase_client)
):
    """
    End the technical interview session
    """
    try:
        # Update session status with atomic update (row-level locking)
        supabase.table("interview_sessions").update({"session_status": "completed"}).eq("id", session_id).neq("session_status", "completed").execute()
        
        return {"message": "Interview ended successfully", "session_id": session_id}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error ending interview: {str(e)}")

