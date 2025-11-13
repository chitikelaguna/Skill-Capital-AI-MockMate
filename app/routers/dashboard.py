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
        
        # Get all answers for all sessions
        session_ids = [s["id"] for s in sessions]
        all_answers = []
        
        for session_id in session_ids:
            try:
                answers_response = supabase.table("interview_answers").select("*").eq("session_id", session_id).execute()
                if answers_response.data:
                    all_answers.extend(answers_response.data)
            except Exception as db_err:
                print(f"[WARNING] Failed to fetch answers for session {session_id}: {str(db_err)}")
                continue
        
        # Calculate average score
        total_score = 0
        score_count = 0
        recent_interviews_list = []
        
        for session in sessions[:10]:  # Get last 10 interviews
            # Get answers for this session
            session_answers = [a for a in all_answers if a["session_id"] == session["id"]]
            
            if session_answers:
                # Calculate average score for this session
                session_scores = [a.get("overall_score", 0) for a in session_answers if a.get("overall_score")]
                if session_scores:
                    session_avg = sum(session_scores) / len(session_scores)
                    total_score += session_avg
                    score_count += 1
                    
                    # Get completion time (use latest answer time or session updated_at)
                    completed_at = session.get("updated_at") or session.get("created_at")
                    if session_answers:
                        latest_answer = max(session_answers, key=lambda x: x.get("answered_at", ""))
                        if latest_answer.get("answered_at"):
                            completed_at = latest_answer["answered_at"]
                    
                    # Get question counts
                    try:
                        questions_response = supabase.table("interview_questions").select("id", count="exact").eq("session_id", session["id"]).execute()
                        total_questions = questions_response.count if hasattr(questions_response, 'count') else len(session_answers)
                    except Exception:
                        total_questions = len(session_answers)
                    
                    recent_interviews_list.append(InterviewSummary(
                        session_id=session["id"],
                        role=session.get("role", "Unknown"),
                        experience_level=session.get("experience_level", "Unknown"),
                        overall_score=round(session_avg, 2),
                        total_questions=total_questions,
                        answered_questions=len(session_answers),
                        completed_at=datetime.fromisoformat(completed_at.replace('Z', '+00:00')) if isinstance(completed_at, str) else datetime.now(),
                        session_status=session.get("session_status", "completed")
                    ))
        
        average_score = total_score / score_count if score_count > 0 else 0.0
        
        # Calculate completion rate
        total_questions_all = 0
        answered_questions_all = 0
        for session in sessions:
            try:
                questions_response = supabase.table("interview_questions").select("id", count="exact").eq("session_id", session["id"]).execute()
                total_q = questions_response.count if hasattr(questions_response, 'count') else 0
                total_questions_all += total_q
                
                session_answers = [a for a in all_answers if a["session_id"] == session["id"]]
                answered_questions_all += len(session_answers)
            except Exception:
                continue
        
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
        
        # Get all answers grouped by session
        trend_data = []
        score_progression = {
            "clarity": [],
            "accuracy": [],
            "confidence": [],
            "communication": []
        }
        
        for session in sessions:
            try:
                answers_response = supabase.table("interview_answers").select("*").eq("session_id", session["id"]).execute()
            except Exception as db_err:
                print(f"[WARNING] Failed to fetch answers for session {session['id']}: {str(db_err)}")
                continue
            
            if answers_response.data and len(answers_response.data) > 0:
                answers = answers_response.data
                
                # Calculate average score for this session
                session_scores = [a.get("overall_score", 0) for a in answers if a.get("overall_score")]
                if session_scores:
                    avg_score = sum(session_scores) / len(session_scores)
                    
                    # Get date
                    completed_at = session.get("updated_at") or session.get("created_at")
                    if answers:
                        latest_answer = max(answers, key=lambda x: x.get("answered_at", ""))
                        if latest_answer.get("answered_at"):
                            completed_at = latest_answer["answered_at"]
                    
                    # Format date
                    if isinstance(completed_at, str):
                        date_str = completed_at.split('T')[0]  # Get YYYY-MM-DD
                    else:
                        date_str = completed_at.strftime('%Y-%m-%d')
                    
                    trend_data.append(TrendDataPoint(
                        date=date_str,
                        score=round(avg_score, 2),
                        session_id=session["id"]
                    ))
                    
                    # Calculate category averages for this session
                    clarity_scores = [a.get("relevance_score", 0) for a in answers]
                    accuracy_scores = [a.get("technical_accuracy_score", 0) for a in answers]
                    confidence_scores = [a.get("confidence_score", 0) for a in answers]
                    communication_scores = [a.get("communication_score", 0) for a in answers]
                    
                    if clarity_scores:
                        score_progression["clarity"].append({
                            "date": date_str,
                            "score": sum(clarity_scores) / len(clarity_scores)
                        })
                    if accuracy_scores:
                        score_progression["accuracy"].append({
                            "date": date_str,
                            "score": sum(accuracy_scores) / len(accuracy_scores)
                        })
                    if confidence_scores:
                        score_progression["confidence"].append({
                            "date": date_str,
                            "score": sum(confidence_scores) / len(confidence_scores)
                        })
                    if communication_scores:
                        score_progression["communication"].append({
                            "date": date_str,
                            "score": sum(communication_scores) / len(communication_scores)
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
    """Analyze skills from interview answers to identify strengths and weaknesses"""
    
    if not all_answers:
        return SkillAnalysis(strong_skills=[], weak_areas=[])
    
    # Analyze by question type and scores
    type_scores = {}
    for answer in all_answers:
        q_type = answer.get("question_type", "Unknown")
        score = answer.get("overall_score", 0)
        
        if q_type not in type_scores:
            type_scores[q_type] = []
        type_scores[q_type].append(score)
    
    # Calculate averages by type
    type_averages = {}
    for q_type, scores in type_scores.items():
        if scores:
            type_averages[q_type] = sum(scores) / len(scores)
    
    # Identify strong and weak areas
    sorted_types = sorted(type_averages.items(), key=lambda x: x[1], reverse=True)
    
    strong_skills = [t[0] for t in sorted_types[:3] if t[1] >= 70]
    weak_areas = [t[0] for t in sorted_types[-3:] if t[1] < 70]
    
    # If we don't have enough, use generic categories
    if len(strong_skills) < 3:
        strong_skills.extend(["Technical Knowledge", "Problem Solving", "Communication"][:3-len(strong_skills)])
    
    if len(weak_areas) < 3:
        weak_areas.extend(["Time Management", "Answer Structure", "Technical Depth"][:3-len(weak_areas)])
    
    return SkillAnalysis(
        strong_skills=strong_skills[:3],
        weak_areas=weak_areas[:3]
    )

