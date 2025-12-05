"""
Database utility functions for optimized queries
"""

import json
import logging
from typing import Optional, List, Dict, Any
from supabase import Client
from datetime import datetime
from app.utils.exceptions import NotFoundError, DatabaseError
from app.utils.profile_normalizer import prepare_profile_for_pydantic

logger = logging.getLogger(__name__)


def sanitize_user_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sanitize user profile data from database
    Converts None values to appropriate defaults for list/array fields
    Ensures all fields are present with consistent types
    Normalizes JSONB fields that might be stored as strings
    
    Time Complexity: O(1) - Constant time field updates
    Space Complexity: O(1) - In-place updates
    
    Args:
        profile: Raw user profile dictionary from database
        
    Returns:
        Sanitized profile dictionary with consistent field types
    """
    if not profile:
        return profile
    
    # Use the profile normalizer to handle JSONB fields and prepare for Pydantic
    sanitized = prepare_profile_for_pydantic(profile)
    
    logger.debug(f"[SANITIZE] Sanitized profile for user_id: {sanitized.get('user_id')}")
    
    return sanitized


def _check_supabase_response_for_html_error(response: Any) -> Optional[str]:
    """
    Check if Supabase response contains HTML error content.
    PostgREST sometimes returns HTML error pages instead of JSON.
    
    Args:
        response: Supabase response object
    
    Returns:
        Error message if HTML detected, None otherwise
    """
    try:
        # Check response data for HTML content
        if hasattr(response, 'data'):
            if response.data is not None:
                # If data is a string and looks like HTML, it's an error
                if isinstance(response.data, str):
                    if response.data.strip().startswith('<'):
                        return "Supabase returned HTML error response"
        
        # Check response text/body if available
        if hasattr(response, 'text'):
            text = response.text
            if text and isinstance(text, str) and text.strip().startswith('<'):
                return "Supabase returned HTML error response"
        
        # Check for error messages in response
        if hasattr(response, 'error'):
            error = response.error
            if error:
                error_str = str(error)
                if '<html' in error_str.lower() or '<body' in error_str.lower():
                    return f"Supabase HTML error: {error_str[:200]}"
        
        return None
    except Exception as e:
        logger.debug(f"[CHECK-HTML] Error checking response: {str(e)}")
        return None


async def get_user_profile(supabase: Client, user_id: str) -> Optional[Dict[str, Any]]:
    """
    Get user profile by user_id
    Time Complexity: O(1) - Single indexed query
    Space Complexity: O(1) - Returns single record
    Optimization: Uses indexed query on user_id
    """
    try:
        response = supabase.table("user_profiles").select("*").eq("user_id", user_id).limit(1).execute()
        
        # Check for HTML error responses
        html_error = _check_supabase_response_for_html_error(response)
        if html_error:
            logger.error(f"[GET-PROFILE] HTML error detected in Supabase response: {html_error}")
            raise DatabaseError(f"Database returned HTML error instead of JSON. This may indicate a PostgREST serialization failure. Original error: {html_error}")
        
        if response.data and len(response.data) > 0:
            return sanitize_user_profile(response.data[0])
        return None
    except DatabaseError:
        raise
    except Exception as e:
        error_msg = str(e)
        # Check if error message contains HTML indicators
        if '<html' in error_msg.lower() or '<body' in error_msg.lower() or '\\r\\n' in error_msg:
            logger.error(f"[GET-PROFILE] HTML error in exception: {error_msg[:200]}")
            raise DatabaseError(f"Database returned HTML error instead of JSON. This may indicate a PostgREST serialization failure or RLS policy issue. Original error: {error_msg[:500]}")
        raise DatabaseError(f"Error fetching user profile: {error_msg}")


async def get_authenticated_user(supabase: Client, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Get authenticated user from user_profiles table
    If user_id is provided, fetch that specific user
    Otherwise, get the first user (for development/testing)
    Time Complexity: O(1) - Single query
    Space Complexity: O(1) - Returns single record
    """
    try:
        if user_id:
            # Get specific user by user_id
            response = supabase.table("user_profiles").select("*").eq("user_id", user_id).limit(1).execute()
            
            # Check for HTML error responses
            html_error = _check_supabase_response_for_html_error(response)
            if html_error:
                logger.error(f"[GET-AUTH-USER] HTML error detected: {html_error}")
                raise DatabaseError(f"Database returned HTML error instead of JSON. Original error: {html_error}")
            
            if response.data and len(response.data) > 0:
                return sanitize_user_profile(response.data[0])
        else:
            # Get first user from user_profiles (for development)
            response = supabase.table("user_profiles").select("*").limit(1).execute()
            
            # Check for HTML error responses
            html_error = _check_supabase_response_for_html_error(response)
            if html_error:
                logger.error(f"[GET-AUTH-USER] HTML error detected: {html_error}")
                raise DatabaseError(f"Database returned HTML error instead of JSON. Original error: {html_error}")
            
            if response.data and len(response.data) > 0:
                return sanitize_user_profile(response.data[0])
        return None
    except DatabaseError:
        raise
    except Exception as e:
        error_msg = str(e)
        if '<html' in error_msg.lower() or '<body' in error_msg.lower() or '\\r\\n' in error_msg:
            logger.error(f"[GET-AUTH-USER] HTML error in exception: {error_msg[:200]}")
            raise DatabaseError(f"Database returned HTML error instead of JSON. Original error: {error_msg[:500]}")
        raise DatabaseError(f"Error fetching authenticated user: {error_msg}")


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
    question_number: int,
    round_table: str = "technical_round"
) -> Optional[Dict[str, Any]]:
    """
    Get question by session_id and question_number from round table
    Time Complexity: O(1) - Single indexed query
    Space Complexity: O(1) - Returns single record
    Optimization: Uses composite index on (session_id, question_number)
    """
    try:
        response = (
            supabase.table(round_table)
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
    session_id: str,
    round_table: str = "technical_round"
) -> List[Dict[str, Any]]:
    """
    Get all answers for a session from round table, ordered by question_number
    Time Complexity: O(n) where n = number of answers
    Space Complexity: O(n) - Returns list of answers
    Optimization: Single query with ordering, avoids N+1 queries
    """
    try:
        response = (
            supabase.table(round_table)
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
    questions: List[Dict[str, Any]],
    round_table: str = "technical_round",
    user_id: str = ""
) -> bool:
    """
    Batch insert questions for a session into round table
    Time Complexity: O(n) where n = number of questions
    Space Complexity: O(n) - Stores all questions in memory
    Optimization: Single batch insert instead of multiple individual inserts
    """
    try:
        if not questions:
            return False
        
        # Prepare questions data for round table
        questions_data = []
        for idx, question in enumerate(questions, start=1):
            questions_data.append({
                "user_id": user_id,
                "session_id": session_id,
                "question_number": idx,
                "question_text": question.get("question", ""),
                "question_type": question.get("type", "Technical"),
                "user_answer": ""  # Initialize with empty answer
            })
        
        # Batch insert
        response = supabase.table(round_table).insert(questions_data).execute()
        return response.data is not None and len(response.data) > 0
    except Exception as e:
        raise DatabaseError(f"Error inserting questions: {str(e)}")


async def get_total_questions_count(supabase: Client, session_id: str, round_table: str = "technical_round") -> int:
    """
    Get total questions count for a session from round table
    Time Complexity: O(1) - Count query with index
    Space Complexity: O(1) - Returns integer
    Optimization: Uses COUNT query instead of fetching all records
    """
    try:
        response = (
            supabase.table(round_table)
            .select("id", count="exact")
            .eq("session_id", session_id)
            .execute()
        )
        return response.count if hasattr(response, 'count') else 0
    except Exception as e:
        raise DatabaseError(f"Error counting questions: {str(e)}")

