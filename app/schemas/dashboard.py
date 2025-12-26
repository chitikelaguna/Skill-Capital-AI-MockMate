"""
Dashboard schemas
Pydantic models for dashboard responses
"""

from pydantic import BaseModel, ConfigDict
from typing import List, Optional, Dict
from datetime import datetime


class InterviewSummary(BaseModel):
    """
    Schema for interview session summary
    Time Complexity: O(1)
    Space Complexity: O(1)
    """
    model_config = ConfigDict()
    
    session_id: str
    role: str
    experience_level: str
    overall_score: float
    total_questions: int
    answered_questions: int
    completed_at: datetime
    session_status: str


class SkillAnalysis(BaseModel):
    """
    Schema for skill analysis
    Time Complexity: O(1)
    Space Complexity: O(1) - Fixed size (top 3)
    """
    strong_skills: List[str]  # Top 3 strong skills
    weak_areas: List[str]  # Top 3 weak areas


class TrendDataPoint(BaseModel):
    """
    Schema for trend data point
    Time Complexity: O(1)
    Space Complexity: O(1)
    """
    date: str  # Date in YYYY-MM-DD format
    score: float
    session_id: str


class PerformanceDashboardResponse(BaseModel):
    """
    Schema for performance dashboard response
    Time Complexity: O(1)
    Space Complexity: O(n) where n = number of recent interviews
    """
    user_id: str
    total_interviews: int
    average_score: float
    completion_rate: float = 0.0  # Percentage of questions answered
    recent_interviews: List[InterviewSummary]
    skill_analysis: SkillAnalysis
    resume_summary: Optional[Dict] = None


class TrendsDashboardResponse(BaseModel):
    """
    Schema for trends dashboard response
    Time Complexity: O(1)
    Space Complexity: O(n) where n = number of trend data points
    """
    user_id: str
    trend_data: List[TrendDataPoint]
    score_progression: Dict[str, float]  # Category scores over time

