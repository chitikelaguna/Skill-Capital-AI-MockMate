"""
Admin routes for managing students, questions, and analytics
"""

from fastapi import APIRouter, HTTPException, Depends
from supabase import Client
from app.db.client import get_supabase_client
from app.schemas.admin import (
    StudentInterviewResult,
    QuestionTemplate,
    QuestionTemplateCreate,
    QuestionTemplateUpdate,
    AnalyticsData
)
from typing import List, Dict
from datetime import datetime
import uuid

router = APIRouter(prefix="/api/admin", tags=["admin"])

def check_admin_access(supabase: Client) -> bool:
    """Check if current user has admin access (simplified - in production, use proper auth)"""
    # For now, we'll allow access. In production, check user role from auth token
    # This is a placeholder - implement proper admin authentication
    return True

@router.get("/students", response_model=List[StudentInterviewResult])
async def get_all_students(
    supabase: Client = Depends(get_supabase_client)
):
    """Get all students' interview results"""
    try:
        # Check admin access (placeholder)
        if not check_admin_access(supabase):
            raise HTTPException(status_code=403, detail="Admin access required")
        
        # Get all interview sessions with user info
        sessions_response = supabase.table("interview_sessions").select("*").order("created_at", desc=True).execute()
        
        sessions = sessions_response.data if sessions_response.data else []
        
        if not sessions:
            return []
        
        # Get user profiles
        user_ids = list(set([s["user_id"] for s in sessions]))
        user_profiles = {}
        
        for user_id in user_ids:
            profile_response = supabase.table("user_profiles").select("*").eq("user_id", user_id).execute()
            if profile_response.data and len(profile_response.data) > 0:
                profile = profile_response.data[0]
                user_profiles[user_id] = {
                    "name": profile.get("name", "Unknown"),
                    "email": profile.get("email", "Unknown")
                }
            else:
                user_profiles[user_id] = {
                    "name": "Unknown",
                    "email": "Unknown"
                }
        
        # Get answers for each session to calculate scores
        results = []
        for session in sessions:
            user_id = session["user_id"]
            user_info = user_profiles.get(user_id, {"name": "Unknown", "email": "Unknown"})
            
            # Get answers for this session
            answers_response = supabase.table("interview_answers").select("*").eq("session_id", session["id"]).execute()
            answers = answers_response.data if answers_response.data else []
            
            if answers:
                # Calculate average score
                scores = [a.get("overall_score", 0) for a in answers if a.get("overall_score")]
                avg_score = sum(scores) / len(scores) if scores else 0
                
                # Get completion time
                completed_at = session.get("updated_at") or session.get("created_at")
                if answers:
                    latest_answer = max(answers, key=lambda x: x.get("answered_at", ""))
                    if latest_answer.get("answered_at"):
                        completed_at = latest_answer["answered_at"]
                
                # Get question count
                questions_response = supabase.table("interview_questions").select("id", count="exact").eq("session_id", session["id"]).execute()
                total_questions = questions_response.count if hasattr(questions_response, 'count') else len(answers)
                
                results.append(StudentInterviewResult(
                    user_id=user_id,
                    user_name=user_info["name"],
                    user_email=user_info["email"],
                    session_id=session["id"],
                    role=session.get("role", "Unknown"),
                    experience_level=session.get("experience_level", "Unknown"),
                    overall_score=round(avg_score, 2),
                    total_questions=total_questions,
                    answered_questions=len(answers),
                    completed_at=datetime.fromisoformat(completed_at.replace('Z', '+00:00')) if isinstance(completed_at, str) else datetime.now(),
                    session_status=session.get("session_status", "completed")
                ))
        
        return results
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching students: {str(e)}")

@router.get("/questions", response_model=List[QuestionTemplate])
async def get_question_templates(
    supabase: Client = Depends(get_supabase_client)
):
    """Get all question templates"""
    try:
        if not check_admin_access(supabase):
            raise HTTPException(status_code=403, detail="Admin access required")
        
        response = supabase.table("question_templates").select("*").order("created_at", desc=True).execute()
        
        templates = []
        for item in (response.data if response.data else []):
            templates.append(QuestionTemplate(
                id=item["id"],
                question_text=item["question_text"],
                question_type=item["question_type"],
                role=item.get("role"),
                experience_level=item.get("experience_level"),
                category=item.get("category"),
                created_at=datetime.fromisoformat(item["created_at"].replace('Z', '+00:00')) if isinstance(item.get("created_at"), str) else None,
                updated_at=datetime.fromisoformat(item["updated_at"].replace('Z', '+00:00')) if isinstance(item.get("updated_at"), str) else None
            ))
        
        return templates
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching question templates: {str(e)}")

@router.post("/questions", response_model=QuestionTemplate)
async def create_question_template(
    template: QuestionTemplateCreate,
    supabase: Client = Depends(get_supabase_client)
):
    """Create a new question template"""
    try:
        if not check_admin_access(supabase):
            raise HTTPException(status_code=403, detail="Admin access required")
        
        template_data = {
            "question_text": template.question_text,
            "question_type": template.question_type,
            "role": template.role,
            "experience_level": template.experience_level,
            "category": template.category
        }
        
        response = supabase.table("question_templates").insert(template_data).execute()
        
        if not response.data or len(response.data) == 0:
            raise HTTPException(status_code=500, detail="Failed to create question template")
        
        item = response.data[0]
        return QuestionTemplate(
            id=item["id"],
            question_text=item["question_text"],
            question_type=item["question_type"],
            role=item.get("role"),
            experience_level=item.get("experience_level"),
            category=item.get("category"),
            created_at=datetime.fromisoformat(item["created_at"].replace('Z', '+00:00')) if isinstance(item.get("created_at"), str) else datetime.now(),
            updated_at=datetime.fromisoformat(item["updated_at"].replace('Z', '+00:00')) if isinstance(item.get("updated_at"), str) else datetime.now()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating question template: {str(e)}")

@router.put("/questions/{template_id}", response_model=QuestionTemplate)
async def update_question_template(
    template_id: str,
    template: QuestionTemplateUpdate,
    supabase: Client = Depends(get_supabase_client)
):
    """Update a question template"""
    try:
        if not check_admin_access(supabase):
            raise HTTPException(status_code=403, detail="Admin access required")
        
        update_data = {}
        if template.question_text is not None:
            update_data["question_text"] = template.question_text
        if template.question_type is not None:
            update_data["question_type"] = template.question_type
        if template.role is not None:
            update_data["role"] = template.role
        if template.experience_level is not None:
            update_data["experience_level"] = template.experience_level
        if template.category is not None:
            update_data["category"] = template.category
        
        if not update_data:
            raise HTTPException(status_code=400, detail="No fields to update")
        
        response = supabase.table("question_templates").update(update_data).eq("id", template_id).execute()
        
        if not response.data or len(response.data) == 0:
            raise HTTPException(status_code=404, detail="Question template not found")
        
        item = response.data[0]
        return QuestionTemplate(
            id=item["id"],
            question_text=item["question_text"],
            question_type=item["question_type"],
            role=item.get("role"),
            experience_level=item.get("experience_level"),
            category=item.get("category"),
            created_at=datetime.fromisoformat(item["created_at"].replace('Z', '+00:00')) if isinstance(item.get("created_at"), str) else None,
            updated_at=datetime.fromisoformat(item["updated_at"].replace('Z', '+00:00')) if isinstance(item.get("updated_at"), str) else None
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating question template: {str(e)}")

@router.delete("/questions/{template_id}")
async def delete_question_template(
    template_id: str,
    supabase: Client = Depends(get_supabase_client)
):
    """Delete a question template"""
    try:
        if not check_admin_access(supabase):
            raise HTTPException(status_code=403, detail="Admin access required")
        
        response = supabase.table("question_templates").delete().eq("id", template_id).execute()
        
        return {"success": True, "message": "Question template deleted"}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting question template: {str(e)}")

@router.get("/analytics", response_model=AnalyticsData)
async def get_analytics(
    supabase: Client = Depends(get_supabase_client)
):
    """Get analytics data"""
    try:
        if not check_admin_access(supabase):
            raise HTTPException(status_code=403, detail="Admin access required")
        
        # Get all sessions
        sessions_response = supabase.table("interview_sessions").select("*").execute()
        sessions = sessions_response.data if sessions_response.data else []
        
        # Get all answers
        all_answers = []
        for session in sessions:
            answers_response = supabase.table("interview_answers").select("*").eq("session_id", session["id"]).execute()
            if answers_response.data:
                all_answers.extend(answers_response.data)
        
        # Get unique students
        unique_user_ids = list(set([s["user_id"] for s in sessions]))
        total_students = len(unique_user_ids)
        total_interviews = len(sessions)
        
        # Calculate average score
        scores = [a.get("overall_score", 0) for a in all_answers if a.get("overall_score")]
        average_score = sum(scores) / len(scores) if scores else 0
        
        # Calculate completion rate
        total_questions = 0
        total_answered = len(all_answers)
        for session in sessions:
            questions_response = supabase.table("interview_questions").select("id", count="exact").eq("session_id", session["id"]).execute()
            count = questions_response.count if hasattr(questions_response, 'count') else 0
            total_questions += count
        
        completion_rate = (total_answered / total_questions * 100) if total_questions > 0 else 0
        
        # Analyze weaknesses
        weakness_counts = {}
        for answer in all_answers:
            q_type = answer.get("question_type", "Unknown")
            score = answer.get("overall_score", 0)
            if score < 70:  # Weak performance
                weakness_counts[q_type] = weakness_counts.get(q_type, 0) + 1
        
        most_common_weaknesses = [
            {"weakness": k, "count": v}
            for k, v in sorted(weakness_counts.items(), key=lambda x: x[1], reverse=True)
        ][:5]
        
        # Score distribution
        score_distribution = {
            "0-50": 0,
            "50-70": 0,
            "70-90": 0,
            "90-100": 0
        }
        for score in scores:
            if score < 50:
                score_distribution["0-50"] += 1
            elif score < 70:
                score_distribution["50-70"] += 1
            elif score < 90:
                score_distribution["70-90"] += 1
            else:
                score_distribution["90-100"] += 1
        
        # Role statistics
        role_stats = {}
        for session in sessions:
            role = session.get("role", "Unknown")
            if role not in role_stats:
                role_stats[role] = {"count": 0, "scores": []}
            
            role_stats[role]["count"] += 1
            
            # Get scores for this session
            session_answers = [a for a in all_answers if a["session_id"] == session["id"]]
            session_scores = [a.get("overall_score", 0) for a in session_answers if a.get("overall_score")]
            if session_scores:
                role_stats[role]["scores"].extend(session_scores)
        
        role_statistics = []
        for role, data in role_stats.items():
            avg_score = sum(data["scores"]) / len(data["scores"]) if data["scores"] else 0
            role_statistics.append({
                "role": role,
                "count": data["count"],
                "avg_score": round(avg_score, 2)
            })
        
        return AnalyticsData(
            total_students=total_students,
            total_interviews=total_interviews,
            average_score=round(average_score, 2),
            completion_rate=round(completion_rate, 2),
            most_common_weaknesses=most_common_weaknesses,
            score_distribution=score_distribution,
            role_statistics=role_statistics
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching analytics: {str(e)}")

