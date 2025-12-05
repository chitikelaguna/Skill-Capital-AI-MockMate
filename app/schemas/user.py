"""
User profile schemas
Pydantic models for request/response validation
"""

from pydantic import BaseModel, EmailStr
from typing import Optional, List, Dict, Any


class UserProfileCreate(BaseModel):
    """
    Schema for creating a user profile
    Time Complexity: O(1) - Model validation
    Space Complexity: O(1) - Constant space
    """
    user_id: str
    name: Optional[str] = None
    email: EmailStr
    skills: Optional[List[str]] = []
    experience_level: Optional[str] = None
    resume_url: Optional[str] = None


class UserProfileUpdate(BaseModel):
    """
    Schema for updating a user profile
    Time Complexity: O(1)
    Space Complexity: O(1)
    """
    name: Optional[str] = None
    skills: Optional[List[str]] = None
    experience_level: Optional[str] = None
    resume_url: Optional[str] = None


class UserProfileResponse(BaseModel):
    """
    Schema for user profile response
    Time Complexity: O(1)
    Space Complexity: O(1)
    """
    id: str
    user_id: str
    name: Optional[str] = None
    email: str
    skills: Optional[List[str]] = []  # Default to empty list if null from DB
    experience_level: Optional[str] = None
    resume_url: Optional[str] = None
    access_role: Optional[str] = None  # No default - use None if not present
    created_at: Optional[str] = None  # ISO format string for JSON serialization
    updated_at: Optional[str] = None  # ISO format string for JSON serialization
    
    class Config:
        """Pydantic configuration"""
        # Allow population by field name or alias
        populate_by_name = True
        # Validate assignment
        validate_assignment = True
        # Allow extra fields from database that aren't in schema
        extra = "ignore"


class ResumeAnalysisResponse(BaseModel):
    """
    Schema for resume analysis response
    Time Complexity: O(1)
    Space Complexity: O(1)
    """
    success: Optional[bool] = None
    error: Optional[str] = None
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    name: Optional[str] = None
    email: Optional[str] = None
    skills: Optional[List[str]] = []
    experience_level: Optional[str] = None
    keywords: Optional[Dict[str, Any]] = {}
    text_length: Optional[int] = 0
    summary: Optional[Dict[str, Any]] = None
    interview_modules: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None
    
    class Config:
        """Pydantic configuration"""
        populate_by_name = True
        validate_assignment = True
        extra = "allow"  # Allow extra fields that may exist in cache


class ResumeUploadResponse(BaseModel):
    """
    Schema for resume upload response
    Time Complexity: O(1)
    Space Complexity: O(1)
    """
    success: bool
    message: str
    session_id: str
    interview_session_id: Optional[str] = None
    user_id: Optional[str] = None
    name: Optional[str] = None
    email: Optional[str] = None
    skills: Optional[List[str]] = []
    experience_level: Optional[str] = None
    keywords: Optional[Dict[str, Any]] = {}
    text_length: Optional[int] = 0
    summary: Optional[Dict[str, Any]] = None
    interview_modules: Optional[Dict[str, Any]] = None
    resume_url: Optional[str] = None


class ExperienceUpdateResponse(BaseModel):
    """
    Schema for experience update response
    Time Complexity: O(1)
    Space Complexity: O(1)
    """
    status: str
    success: bool
    message: str
    experience_level: str
    session_id: str
