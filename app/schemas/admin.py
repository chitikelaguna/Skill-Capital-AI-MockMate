"""
Admin panel schemas
Pydantic models for admin operations
"""

from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime


class StudentInterviewResult(BaseModel):
    """
    Schema for student interview result
    Time Complexity: O(1)
    Space Complexity: O(1)
    """
    user_id: str
    user_name: str
    user_email: str
    session_id: str
    role: str
    experience_level: str
    overall_score: float
    total_questions: int
    answered_questions: int
    completed_at: datetime
    session_status: str


class QuestionTemplate(BaseModel):
    """
    Schema for question template
    Time Complexity: O(1)
    Space Complexity: O(1)
    """
    id: Optional[str] = None
    question_text: str
    question_type: str  # HR, Technical, Problem-solving
    role: Optional[str] = None  # Specific role or "General"
    experience_level: Optional[str] = None  # Specific level or "All"
    category: Optional[str] = None  # e.g., "Python", "System Design"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class QuestionTemplateCreate(BaseModel):
    """
    Schema for creating question template
    Time Complexity: O(1)
    Space Complexity: O(1)
    """
    question_text: str
    question_type: str
    role: Optional[str] = None
    experience_level: Optional[str] = None
    category: Optional[str] = None


class QuestionTemplateUpdate(BaseModel):
    """
    Schema for updating question template
    Time Complexity: O(1)
    Space Complexity: O(1)
    """
    question_text: Optional[str] = None
    question_type: Optional[str] = None
    role: Optional[str] = None
    experience_level: Optional[str] = None
    category: Optional[str] = None


class AnalyticsData(BaseModel):
    """
    Schema for analytics data
    Time Complexity: O(1)
    Space Complexity: O(n) where n = number of weaknesses/roles
    """
    total_students: int
    total_interviews: int
    average_score: float
    completion_rate: float
    most_common_weaknesses: List[Dict[str, Any]]  # [{"weakness": "Technical", "count": 10}]
    score_distribution: Dict[str, int]  # {"0-50": 5, "50-70": 10, "70-90": 15, "90-100": 3}
    role_statistics: List[Dict[str, Any]]  # [{"role": "Python Developer", "count": 5, "avg_score": 75}]

