"""
User profile and authentication schemas
Pydantic models for request/response validation
"""

from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime


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
    name: Optional[str]
    email: str
    skills: List[str]
    experience_level: Optional[str]
    resume_url: Optional[str]
    access_role: Optional[str] = "Student"  # Default to "Student"
    created_at: datetime
    updated_at: datetime


class AuthRequest(BaseModel):
    """
    Schema for authentication requests
    Time Complexity: O(1)
    Space Complexity: O(1)
    """
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    """
    Schema for authentication response
    Time Complexity: O(1)
    Space Complexity: O(1)
    """
    access_token: str
    refresh_token: Optional[str] = None
    user: dict
    message: str

