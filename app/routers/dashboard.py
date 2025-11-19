"""
Dashboard routes for performance analytics
"""

from fastapi import APIRouter, HTTPException, Depends
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
from typing import List, Dict, Optional
from datetime import datetime, timedelta

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

@router.get("/performance/{user_id}", response_model=PerformanceDashboardResponse)
async def get_performance_dashboard(
    user_id: str,
    supabase: Client = Depends(get_supabase_client)
):
    """Get performance dashboard data for a user"""
    try:
        # Get all interview sessions for user
        try:
            sessions_response = supabase.table("interview_sessions").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
            sessions = sessions_response.data if sessions_response.data else []
        except Exception as db_err:
            # If table doesn't exist or query fails, return empty dashboard
            print(f"[WARNING] Failed to fetch interview sessions: {str(db_err)}")
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
        
        # Get all answers for all sessions in a single query (optimized: O(1) instead of O(n))
        # Time Complexity: O(1) - Single query with IN clause
        # Space Complexity: O(n) where n = total answers
        session_ids = [s["id"] for s in sessions]
        all_answers = []
        
        if session_ids:
            try:
                # Batch fetch all answers for all sessions at once
                # Supabase supports IN queries for better performance
                answers_response = supabase.table("interview_answers").select("*").in_("session_id", session_ids).execute()
                if answers_response.data:
                    all_answers = answers_response.data
            except Exception as db_err:
                print(f"[WARNING] Failed to batch fetch answers: {str(db_err)}")
                # Fallback to individual queries only if batch fails
                for session_id in session_ids:
                    try:
                        answers_response = supabase.table("interview_answers").select("*").eq("session_id", session_id).execute()
                        if answers_response.data:
                            all_answers.extend(answers_response.data)
                    except Exception:
                        continue
        
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
        
        # Batch fetch question counts for all sessions (optimized: O(1) instead of O(n))
        # Time Complexity: O(1) - Single query with IN clause
        # Space Complexity: O(n) where n = number of sessions
        question_counts = {}
        if session_ids:
            try:
                questions_response = supabase.table("interview_questions").select("session_id,id").in_("session_id", session_ids).execute()
                if questions_response.data:
                    # Count questions per session
                    for q in questions_response.data:
                        sid = q.get("session_id")
                        if sid:
                            question_counts[sid] = question_counts.get(sid, 0) + 1
            except Exception:
                # Fallback: use answer counts as approximation
                for sid in session_ids:
                    question_counts[sid] = len(answers_by_session.get(sid, []))
        
        # Calculate average score
        # Time Complexity: O(n) where n = number of recent sessions (max 10)
        # Space Complexity: O(1) - only storing aggregates
        total_score = 0
        score_count = 0
        recent_interviews_list = []
        
        for session in sessions[:10]:  # Get last 10 interviews
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
                    if score:
                        score_sum += score
                        score_count_session += 1
                    # Track latest answer time in same loop
                    answered_at = answer.get("answered_at")
                    if answered_at and (not latest_answered_at or answered_at > latest_answered_at):
                        latest_answered_at = answered_at
                
                if score_count_session > 0:
                    session_avg = score_sum / score_count_session
                    total_score += session_avg
                    score_count += 1
                    
                    # Get completion time (use latest answer time or session updated_at)
                    completed_at = latest_answered_at or session.get("updated_at") or session.get("created_at")
                    
                    # Get question count from pre-fetched dictionary
                    total_questions = question_counts.get(session_id, len(session_answers))
                    
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
            print(f"[WARNING] Failed to fetch user profile: {str(db_err)}")
            resume_summary = None
        
        return PerformanceDashboardResponse(
            user_id=user_id,
            total_interviews=len(sessions),
            average_score=round(average_score, 2),
            completion_rate=round(completion_rate, 1),
            recent_interviews=recent_interviews_list,
            skill_analysis=skill_analysis,
            resume_summary=resume_summary
        )
        
    except HTTPException:
        raise
    except (NotFoundError, DatabaseError) as e:
        # Convert custom exceptions to HTTPException
        status_code = e.status_code if hasattr(e, 'status_code') else 500
        raise HTTPException(status_code=status_code, detail=str(e))
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"[ERROR] Performance dashboard error: {str(e)}")
        print(f"[ERROR] Traceback: {error_details}")
        raise HTTPException(status_code=500, detail=f"Error fetching performance dashboard: {str(e)}")

@router.get("/trends/{user_id}", response_model=TrendsDashboardResponse)
async def get_trends_dashboard(
    user_id: str,
    supabase: Client = Depends(get_supabase_client)
):
    """Get trends dashboard data for a user"""
    try:
        # Get all interview sessions for user
        try:
            sessions_response = supabase.table("interview_sessions").select("*").eq("user_id", user_id).order("created_at", desc=False).execute()
            sessions = sessions_response.data if sessions_response.data else []
        except Exception as db_err:
            print(f"[WARNING] Failed to fetch interview sessions: {str(db_err)}")
            sessions = []
        
        if not sessions:
            return TrendsDashboardResponse(
                user_id=user_id,
                trend_data=[],
                score_progression={}
            )
        
        # Batch fetch all answers for all sessions (optimized: O(1) instead of O(n))
        # Time Complexity: O(1) - Single query with IN clause
        # Space Complexity: O(n) where n = total answers
        session_ids = [s["id"] for s in sessions]
        all_answers_trends = []
        
        if session_ids:
            try:
                answers_response = supabase.table("interview_answers").select("*").in_("session_id", session_ids).execute()
                if answers_response.data:
                    all_answers_trends = answers_response.data
            except Exception as db_err:
                print(f"[WARNING] Failed to batch fetch answers for trends: {str(db_err)}")
        
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
                    
                    confidence = answer.get("confidence_score")
                    if confidence:
                        confidence_sum += confidence
                        confidence_count += 1
                    
                    comm = answer.get("communication_score")
                    if comm:
                        communication_sum += comm
                        communication_count += 1
                    
                    # Track latest answer time
                    answered_at = answer.get("answered_at")
                    if answered_at and (not latest_answered_at or answered_at > latest_answered_at):
                        latest_answered_at = answered_at
                
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
                    if confidence_count > 0:
                        score_progression["confidence"].append({
                            "date": date_str,
                            "score": round(confidence_sum / confidence_count, 2)
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
        import traceback
        error_details = traceback.format_exc()
        print(f"[ERROR] Trends dashboard error: {str(e)}")
        print(f"[ERROR] Traceback: {error_details}")
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
        score = answer.get("overall_score", 0)
        
        if score > 0:  # Only count non-zero scores
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

