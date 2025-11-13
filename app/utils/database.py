"""
Database utility functions for optimized queries
"""

from typing import Optional, List, Dict, Any
from supabase import Client
from datetime import datetime
from app.utils.exceptions import NotFoundError, DatabaseError


async def get_user_profile(supabase: Client, user_id: str) -> Optional[Dict[str, Any]]:
    """
    Get user profile by user_id
    Time Complexity: O(1) - Single indexed query
    Space Complexity: O(1) - Returns single record
    Optimization: Uses indexed query on user_id
    """
    try:
        response = supabase.table("user_profiles").select("*").eq("user_id", user_id).limit(1).execute()
        return response.data[0] if response.data and len(response.data) > 0 else None
    except Exception as e:
        raise DatabaseError(f"Error fetching user profile: {str(e)}")


async def get_interview_session(supabase: Client, session_id: str) -> Dict[str, Any]:
    """
    Get interview session by session_id
    Time Complexity: O(1) - Single indexed query
    Space Complexity: O(1) - Returns single record
    Optimization: Uses indexed query on session_id
    """
    try:
        response = supabase.table("interview_sessions").select("*").eq("id", session_id).limit(1).execute()
        if not response.data or len(response.data) == 0:
            raise NotFoundError("Interview session", session_id)
        return response.data[0]
    except NotFoundError:
        raise
    except Exception as e:
        raise DatabaseError(f"Error fetching interview session: {str(e)}")


async def get_question_by_number(
    supabase: Client, 
    session_id: str, 
    question_number: int
) -> Optional[Dict[str, Any]]:
    """
    Get question by session_id and question_number
    Time Complexity: O(1) - Single indexed query
    Space Complexity: O(1) - Returns single record
    Optimization: Uses composite index on (session_id, question_number)
    """
    try:
        response = (
            supabase.table("interview_questions")
            .select("*")
            .eq("session_id", session_id)
            .eq("question_number", question_number)
            .limit(1)
            .execute()
        )
        return response.data[0] if response.data and len(response.data) > 0 else None
    except Exception as e:
        raise DatabaseError(f"Error fetching question: {str(e)}")


async def get_all_answers_for_session(
    supabase: Client, 
    session_id: str
) -> List[Dict[str, Any]]:
    """
    Get all answers for a session, ordered by question_number
    Time Complexity: O(n) where n = number of answers
    Space Complexity: O(n) - Returns list of answers
    Optimization: Single query with ordering, avoids N+1 queries
    """
    try:
        response = (
            supabase.table("interview_answers")
            .select("*")
            .eq("session_id", session_id)
            .order("question_number")
            .execute()
        )
        return response.data if response.data else []
    except Exception as e:
        raise DatabaseError(f"Error fetching answers: {str(e)}")


async def batch_insert_questions(
    supabase: Client,
    session_id: str,
    questions: List[Dict[str, Any]]
) -> bool:
    """
    Batch insert questions for a session
    Time Complexity: O(n) where n = number of questions
    Space Complexity: O(n) - Stores all questions in memory
    Optimization: Single batch insert instead of multiple individual inserts
    """
    try:
        if not questions:
            return False
        
        # Prepare questions data
        questions_data = []
        for idx, question in enumerate(questions, start=1):
            questions_data.append({
                "session_id": session_id,
                "question_type": question.get("type", "Technical"),
                "question": question.get("question", ""),
                "question_number": idx
            })
        
        # Batch insert
        response = supabase.table("interview_questions").insert(questions_data).execute()
        return response.data is not None and len(response.data) > 0
    except Exception as e:
        raise DatabaseError(f"Error inserting questions: {str(e)}")


async def get_total_questions_count(supabase: Client, session_id: str) -> int:
    """
    Get total questions count for a session
    Time Complexity: O(1) - Count query with index
    Space Complexity: O(1) - Returns integer
    Optimization: Uses COUNT query instead of fetching all records
    """
    try:
        response = (
            supabase.table("interview_questions")
            .select("id", count="exact")
            .eq("session_id", session_id)
            .execute()
        )
        return response.count if hasattr(response, 'count') else 0
    except Exception as e:
        raise DatabaseError(f"Error counting questions: {str(e)}")

