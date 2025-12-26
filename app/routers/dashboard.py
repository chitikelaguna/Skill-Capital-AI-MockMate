"""
Dashboard routes for performance analytics
"""

from fastapi import APIRouter, HTTPException, Depends, Query
from supabase import Client
from app.db.client import get_supabase_client
from app.schemas.dashboard import (
    PerformanceDashboardResponse,
    TrendsDashboardResponse,
    InterviewSummary,
    SkillAnalysis,
    TrendDataPoint
)
from app.utils.exceptions import NotFoundError, DatabaseError
from app.utils.rate_limiter import rate_limit_by_user_id
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import logging
import re

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

@router.get("/performance/{user_id}", response_model=PerformanceDashboardResponse)
async def get_performance_dashboard(
    user_id: str,
    page: Optional[int] = Query(None, description="Page number for pagination (1-indexed)"),
    limit: Optional[int] = Query(None, description="Number of items per page"),
    supabase: Client = Depends(get_supabase_client),
    _: None = Depends(rate_limit_by_user_id)
):
    # CRITICAL FIX: Strictly require non-empty user_id
    if not user_id or not user_id.strip():
        logger.error(f"[DASHBOARD] ❌ SECURITY: Empty user_id provided")
        raise HTTPException(
            status_code=400,
            detail="user_id is required and cannot be empty. Please provide a valid user_id."
        )
    
    # Validate user_id format: alphanumeric, hyphen, underscore only
    if not re.match(r'^[a-zA-Z0-9_-]+$', user_id):
        logger.error(f"[DASHBOARD] ❌ Invalid user_id format: {user_id}")
        raise HTTPException(status_code=400, detail="Invalid user_id format")
    
    # Validate pagination parameters if provided
    if page is not None and page < 1:
        raise HTTPException(status_code=400, detail="page must be >= 1")
    if limit is not None and limit < 1:
        raise HTTPException(status_code=400, detail="limit must be >= 1")
    
    """Get performance dashboard data for a user"""
    try:
        # Get all interview sessions for user
        try:
            sessions_response = supabase.table("interview_sessions").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
            sessions = sessions_response.data if sessions_response.data else []
        except Exception as db_err:
            # If table doesn't exist or query fails, return empty dashboard
            logger.warning(f"[DASHBOARD][PERFORMANCE] Failed to fetch interview sessions: {str(db_err)}")
            sessions = []
        
        if not sessions:
            # Return empty dashboard
            return PerformanceDashboardResponse(
                user_id=user_id,
                total_interviews=0,
                average_score=0.0,
                completion_rate=0.0,
                recent_interviews=[],
                skill_analysis=SkillAnalysis(strong_skills=[], weak_areas=[]),
                resume_summary=None
            )
        
        # Get all answers from round tables based on session type (new schema)
        # Time Complexity: O(n) where n = number of sessions
        # Space Complexity: O(m) where m = total answers
        session_ids = [s["id"] for s in sessions]
        all_answers = []
        
        if session_ids:
            try:
                # Fetch from all round tables based on session interview_type
                for session in sessions:
                    session_id = session["id"]
                    session_type = session.get("interview_type", "technical")
                    
                    # Determine which round table to use
                    if session_type == "coding":
                        round_table = "coding_round"
                    elif session_type == "hr":
                        round_table = "hr_round"
                    elif session_type == "star":
                        round_table = "star_round"
                    else:
                        round_table = "technical_round"
                    
                    try:
                        answers_response = supabase.table(round_table).select("*").eq("session_id", session_id).execute()
                        if answers_response.data:
                            # Map to common format for dashboard
                            for row in answers_response.data:
                                # Include rows that have scores OR user_answer (for coding, check final_score)
                                # This ensures we capture all evaluated answers, even if user_answer is empty
                                has_score = row.get("overall_score") is not None
                                has_coding_score = (round_table == "coding_round" and row.get("final_score") is not None)
                                has_user_answer = row.get("user_answer") and row.get("user_answer").strip() not in ["", "No Answer"]
                                
                                if has_score or has_coding_score or has_user_answer:
                                    # For coding interviews, use final_score as overall_score
                                    overall_score = row.get("overall_score")
                                    if round_table == "coding_round" and overall_score is None:
                                        overall_score = row.get("final_score", 0)
                                    
                                    mapped_answer = {
                                        "session_id": session_id,
                                        "question_number": row.get("question_number", 0),
                                        "question_type": row.get("question_type") or row.get("question_category") or session_type.title(),
                                        "overall_score": overall_score if overall_score is not None else 0,
                                        "relevance_score": row.get("relevance_score"),
                                        "technical_accuracy_score": row.get("technical_accuracy_score"),
                                        "communication_score": row.get("communication_score"),
                                        "created_at": row.get("created_at")  # Use created_at instead of answered_at
                                    }
                                    all_answers.append(mapped_answer)
                    except Exception as round_err:
                        logger.warning(f"[DASHBOARD][PERFORMANCE] Failed to fetch from {round_table} for session {session_id}: {str(round_err)}")
                        continue
            except Exception as db_err:
                logger.warning(f"[DASHBOARD][PERFORMANCE] Failed to batch fetch answers: {str(db_err)}")
        
        # Create answer lookup dictionary for O(1) access instead of O(n) filtering
        # Time Complexity: O(n) to build, O(1) to access
        # Space Complexity: O(n)
        answers_by_session = {}
        for answer in all_answers:
            session_id = answer.get("session_id")
            if session_id:
                if session_id not in answers_by_session:
                    answers_by_session[session_id] = []
                answers_by_session[session_id].append(answer)
        
        # Count questions from round tables (new schema)
        # Questions are stored in round tables with question_text
        question_counts = {}
        if session_ids:
            try:
                # Count questions per session from round tables
                for session in sessions:
                    session_id = session["id"]
                    session_type = session.get("interview_type", "technical")
                    
                    # Determine which round table to use
                    if session_type == "coding":
                        round_table = "coding_round"
                    elif session_type == "hr":
                        round_table = "hr_round"
                    elif session_type == "star":
                        round_table = "star_round"
                    else:
                        round_table = "technical_round"
                    
                    try:
                        # Count all questions asked for this session
                        # Each row in the round table represents a question that was asked
                        questions_response = supabase.table(round_table).select("question_number, question_text").eq("session_id", session_id).execute()
                        # Count unique question_numbers (each question_number represents one question asked)
                        unique_questions = set()
                        for row in (questions_response.data or []):

                            question_number = row.get("question_number")
                            # Include all rows with valid question_number (questions were asked)
                            if question_number is not None:
                                unique_questions.add(question_number)
                        question_counts[session_id] = len(unique_questions) if unique_questions else 0
                    except Exception:
                        # Fallback: use answer counts as approximation
                        question_counts[session_id] = len(answers_by_session.get(session_id, []))
            except Exception:
                # Fallback: use answer counts as approximation
                for sid in session_ids:
                    question_counts[sid] = len(answers_by_session.get(sid, []))
        
        # Calculate average score across ALL sessions (not just last 10)
        # Time Complexity: O(n) where n = number of sessions
        # Space Complexity: O(1) - only storing aggregates
        total_score = 0
        score_count = 0
        recent_interviews_list = []
        
        # Process all sessions for average calculation
        # Build complete list first, then paginate if needed
        for session in sessions:
            session_id = session["id"]
            # Use dictionary lookup instead of filtering (O(1) vs O(n))
            session_answers = answers_by_session.get(session_id, [])
            
            if session_answers:
                # Optimize score calculation: single pass instead of list comprehension + sum
                # Time Complexity: O(m) where m = answers per session
                # Space Complexity: O(1) - calculating sum directly
                score_sum = 0
                score_count_session = 0
                latest_answered_at = None
                
                for answer in session_answers:
                    score = answer.get("overall_score")
                    # Include scores that are 0 (valid scores) - only exclude None
                    if score is not None:
                        score_sum += score
                        score_count_session += 1
                    # Track latest answer time in same loop (use created_at from new schema)
                    created_at = answer.get("created_at")
                    if created_at and (not latest_answered_at or created_at > latest_answered_at):
                        latest_answered_at = created_at
                
                if score_count_session > 0:
                    session_avg = score_sum / score_count_session
                    total_score += session_avg
                    score_count += 1
                    
                    # Get completion time (use latest answer time or session updated_at)
                    completed_at = latest_answered_at or session.get("updated_at") or session.get("created_at")
                    
                    # Get question count from pre-fetched dictionary
                    total_questions = question_counts.get(session_id, len(session_answers))
                    
                    # Add all sessions to list (will paginate later if needed)
                    recent_interviews_list.append(InterviewSummary(
                        session_id=session_id,
                        role=session.get("role", "Unknown"),
                        experience_level=session.get("experience_level", "Unknown"),
                        overall_score=round(session_avg, 2),
                        total_questions=total_questions,
                        answered_questions=len(session_answers),
                        completed_at=datetime.fromisoformat(completed_at.replace('Z', '+00:00')) if isinstance(completed_at, str) else datetime.now(),
                        session_status=session.get("session_status", "completed")
                    ))
        
        # Apply pagination if parameters are provided, otherwise return last 10 (current behavior)
        if page is not None and limit is not None:
            # Calculate pagination
            start_index = (page - 1) * limit
            end_index = start_index + limit
            recent_interviews_list = recent_interviews_list[start_index:end_index]
        elif page is not None or limit is not None:
            # If only one parameter is provided, raise error
            raise HTTPException(status_code=400, detail="Both page and limit must be provided together for pagination")
        else:
            # No pagination: return last 10 (original behavior)
            recent_interviews_list = recent_interviews_list[:10]
        
        # Calculate average across ALL sessions with scores
        average_score = total_score / score_count if score_count > 0 else 0.0
        
        # Calculate completion rate using pre-fetched data
        # Time Complexity: O(n) where n = number of sessions
        # Space Complexity: O(1)
        total_questions_all = sum(question_counts.get(s["id"], 0) for s in sessions)
        answered_questions_all = sum(len(answers_by_session.get(s["id"], [])) for s in sessions)
        
        completion_rate = (answered_questions_all / total_questions_all * 100) if total_questions_all > 0 else 0.0
        
        # Analyze skills from answers
        skill_analysis = analyze_skills(all_answers, sessions)
        
        # Get resume summary from profile
        resume_summary = None
        try:
            profile_response = supabase.table("user_profiles").select("*").eq("user_id", user_id).execute()
            if profile_response.data and len(profile_response.data) > 0:
                profile = profile_response.data[0]
                resume_summary = {
                    "name": profile.get("name"),
                    "email": profile.get("email"),
                    "skills": profile.get("skills", []),
                    "experience_level": profile.get("experience_level"),
                    "has_resume": bool(profile.get("resume_url"))
                }
        except Exception as db_err:
            logger.warning(f"[DASHBOARD][PERFORMANCE] Failed to fetch user profile: {str(db_err)}")
            resume_summary = None
        
        # BUG FIX #2: Create response with Cache-Control headers
        from fastapi.responses import JSONResponse
        response_data = PerformanceDashboardResponse(
            user_id=user_id,
            total_interviews=len(sessions),
            average_score=round(average_score, 2),
            completion_rate=round(completion_rate, 1),
            recent_interviews=recent_interviews_list,
            skill_analysis=skill_analysis,
            resume_summary=resume_summary
        )
        # FIX: Use model_dump(mode='json') to properly serialize datetime objects to ISO strings
        # This ensures all datetime fields are converted to JSON-safe ISO 8601 strings
        response = JSONResponse(content=response_data.model_dump(mode='json'))
        # BUG FIX #2: Set cache headers to prevent Vercel/CDN caching
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response
        
    except HTTPException:
        raise
    except (NotFoundError, DatabaseError) as e:
        # Convert custom exceptions to HTTPException
        status_code = e.status_code if hasattr(e, 'status_code') else 500
        raise HTTPException(status_code=status_code, detail=str(e))
    except Exception as e:
        logger.exception("[DASHBOARD][PERFORMANCE] Performance dashboard error")
        raise HTTPException(status_code=500, detail=f"Error fetching performance dashboard: {str(e)}")

@router.get("/trends/{user_id}", response_model=TrendsDashboardResponse)
async def get_trends_dashboard(
    user_id: str,
    supabase: Client = Depends(get_supabase_client),
    _: None = Depends(rate_limit_by_user_id)
):
    # Validate user_id format: alphanumeric, hyphen, underscore only
    if not re.match(r'^[a-zA-Z0-9_-]+$', user_id):
        raise HTTPException(status_code=400, detail="Invalid user_id format")
    
    """Get trends dashboard data for a user"""
    try:
        # Get all interview sessions for user
        try:
            sessions_response = supabase.table("interview_sessions").select("*").eq("user_id", user_id).order("created_at", desc=False).execute()
            sessions = sessions_response.data if sessions_response.data else []
        except Exception as db_err:
            logger.warning(f"[DASHBOARD][TRENDS] Failed to fetch interview sessions: {str(db_err)}")
            sessions = []
        
        if not sessions:
            return TrendsDashboardResponse(
                user_id=user_id,
                trend_data=[],
                score_progression={}
            )
        
        # Get all answers from round tables based on session type (new schema)
        session_ids = [s["id"] for s in sessions]
        all_answers_trends = []
        
        if session_ids:
            try:
                # Fetch from all round tables based on session interview_type
                for session in sessions:
                    session_id = session["id"]
                    session_type = session.get("interview_type", "technical")
                    
                    # Determine which round table to use
                    if session_type == "coding":
                        round_table = "coding_round"
                    elif session_type == "hr":
                        round_table = "hr_round"
                    elif session_type == "star":
                        round_table = "star_round"
                    else:
                        round_table = "technical_round"
                    
                    try:
                        answers_response = supabase.table(round_table).select("*").eq("session_id", session_id).execute()
                        if answers_response.data:
                            # Map to common format for trends
                            for row in answers_response.data:
                                if row.get("user_answer"):
                                    mapped_answer = {
                                        "session_id": session_id,
                                        "question_number": row.get("question_number", 0),
                                        "question_type": row.get("question_type") or row.get("question_category") or "Technical",
                                        "overall_score": row.get("overall_score", 0),
                                        "relevance_score": row.get("relevance_score"),
                                        "technical_accuracy_score": row.get("technical_accuracy_score"),
                                        "communication_score": row.get("communication_score"),
                                        "created_at": row.get("created_at")  # Use created_at instead of answered_at
                                    }
                                    all_answers_trends.append(mapped_answer)
                    except Exception as round_err:
                        logger.warning(f"[DASHBOARD][TRENDS] Failed to fetch from {round_table} for trends: {str(round_err)}")
                        continue
            except Exception as db_err:
                logger.warning(f"[DASHBOARD][TRENDS] Failed to batch fetch answers for trends: {str(db_err)}")
        
        # Create answer lookup dictionary for O(1) access
        # Time Complexity: O(n) to build, O(1) to access
        # Space Complexity: O(n)
        answers_by_session_trends = {}
        for answer in all_answers_trends:
            session_id = answer.get("session_id")
            if session_id:
                if session_id not in answers_by_session_trends:
                    answers_by_session_trends[session_id] = []
                answers_by_session_trends[session_id].append(answer)
        
        # Process trends data
        # Time Complexity: O(n*m) where n = sessions, m = avg answers per session
        # Space Complexity: O(n)
        trend_data = []
        score_progression = {
            "clarity": [],
            "accuracy": [],
            "confidence": [],
            "communication": []
        }
        
        for session in sessions:
            session_id = session["id"]
            answers = answers_by_session_trends.get(session_id, [])
            
            if answers:
                # Optimize: single pass through answers to calculate all metrics
                # Time Complexity: O(m) where m = answers per session
                # Space Complexity: O(1) - calculating sums directly
                score_sum = 0
                score_count = 0
                clarity_sum = 0
                clarity_count = 0
                accuracy_sum = 0
                accuracy_count = 0
                confidence_sum = 0
                confidence_count = 0
                communication_sum = 0
                communication_count = 0
                latest_answered_at = None
                
                for answer in answers:
                    # Overall score
                    overall = answer.get("overall_score")
                    if overall:
                        score_sum += overall
                        score_count += 1
                    
                    # Category scores
                    relevance = answer.get("relevance_score")
                    if relevance:
                        clarity_sum += relevance
                        clarity_count += 1
                    
                    technical = answer.get("technical_accuracy_score")
                    if technical:
                        accuracy_sum += technical
                        accuracy_count += 1
                    
                    # Note: confidence_score doesn't exist in new schema, skip it
                    # Use communication_score as alternative if needed
                    
                    comm = answer.get("communication_score")
                    if comm:
                        communication_sum += comm
                        communication_count += 1
                    
                    # Track latest answer time (use created_at from new schema)
                    created_at = answer.get("created_at")
                    if created_at and (not latest_answered_at or created_at > latest_answered_at):
                        latest_answered_at = created_at
                
                if score_count > 0:
                    avg_score = score_sum / score_count
                    
                    # Get date
                    completed_at = latest_answered_at or session.get("updated_at") or session.get("created_at")
                    
                    # Format date (optimized: single operation)
                    if isinstance(completed_at, str):
                        date_str = completed_at[:10] if len(completed_at) >= 10 else completed_at.split('T')[0]
                    else:
                        date_str = completed_at.strftime('%Y-%m-%d')
                    
                    trend_data.append(TrendDataPoint(
                        date=date_str,
                        score=round(avg_score, 2),
                        session_id=session_id
                    ))
                    
                    # Add category averages
                    if clarity_count > 0:
                        score_progression["clarity"].append({
                            "date": date_str,
                            "score": round(clarity_sum / clarity_count, 2)
                        })
                    if accuracy_count > 0:
                        score_progression["accuracy"].append({
                            "date": date_str,
                            "score": round(accuracy_sum / accuracy_count, 2)
                        })
                    # Note: confidence_score removed - using communication_score instead
                    # Keep confidence array for API compatibility but use communication data
                    if communication_count > 0:
                        score_progression["confidence"].append({
                            "date": date_str,
                            "score": round(communication_sum / communication_count, 2)
                        })
                    if communication_count > 0:
                        score_progression["communication"].append({
                            "date": date_str,
                            "score": round(communication_sum / communication_count, 2)
                        })
        
        return TrendsDashboardResponse(
            user_id=user_id,
            trend_data=trend_data,
            score_progression=score_progression
        )
        
    except HTTPException:
        raise
    except (NotFoundError, DatabaseError) as e:
        # Convert custom exceptions to HTTPException
        status_code = e.status_code if hasattr(e, 'status_code') else 500
        raise HTTPException(status_code=status_code, detail=str(e))
    except Exception as e:
        logger.exception("[DASHBOARD][TRENDS] Trends dashboard error")
        raise HTTPException(status_code=500, detail=f"Error fetching trends dashboard: {str(e)}")

def analyze_skills(all_answers: List[Dict], sessions: List[Dict]) -> SkillAnalysis:
    """
    Analyze skills from interview answers to identify strengths and weaknesses
    Time Complexity: O(n) where n = number of answers (single pass)
    Space Complexity: O(k) where k = number of unique question types
    Optimization: Single pass through answers, calculating sums and counts directly
    """
    if not all_answers:
        return SkillAnalysis(strong_skills=[], weak_areas=[])
    
    # Analyze by question type and scores in a single pass
    # Use dictionaries to store sum and count for O(1) updates
    # Time Complexity: O(n) - single pass
    # Space Complexity: O(k) where k = unique question types
    type_sums = {}
    type_counts = {}
    
    for answer in all_answers:
        q_type = answer.get("question_type", "Unknown")
        score = answer.get("overall_score")
        
        # Include all scores (including 0) - only exclude None
        if score is not None:
            if q_type not in type_sums:
                type_sums[q_type] = 0
                type_counts[q_type] = 0
            type_sums[q_type] += score
            type_counts[q_type] += 1
    
    # Calculate averages by type
    # Time Complexity: O(k) where k = unique question types
    # Space Complexity: O(k)
    type_averages = {
        q_type: type_sums[q_type] / type_counts[q_type]
        for q_type in type_sums
        if type_counts[q_type] > 0
    }
    
    if not type_averages:
        # Fallback to generic categories if no data
        return SkillAnalysis(
            strong_skills=["Technical Knowledge", "Problem Solving", "Communication"],
            weak_areas=["Time Management", "Answer Structure", "Technical Depth"]
        )
    
    # Identify strong and weak areas
    # Time Complexity: O(k log k) for sorting
    # Space Complexity: O(k)
    sorted_types = sorted(type_averages.items(), key=lambda x: x[1], reverse=True)
    
    # Extract strong skills and weak areas in single pass
    # Time Complexity: O(k)
    # Space Complexity: O(1) - max 3 items
    strong_skills = [t[0] for t in sorted_types if t[1] >= 70][:3]
    weak_areas = [t[0] for t in reversed(sorted_types) if t[1] < 70][:3]
    
    # If we don't have enough, use generic categories
    generic_strong = ["Technical Knowledge", "Problem Solving", "Communication"]
    generic_weak = ["Time Management", "Answer Structure", "Technical Depth"]
    
    if len(strong_skills) < 3:
        strong_skills.extend([s for s in generic_strong if s not in strong_skills][:3-len(strong_skills)])
    
    if len(weak_areas) < 3:
        weak_areas.extend([w for w in generic_weak if w not in weak_areas][:3-len(weak_areas)])
    
    return SkillAnalysis(
        strong_skills=strong_skills[:3],
        weak_areas=weak_areas[:3]
    )

