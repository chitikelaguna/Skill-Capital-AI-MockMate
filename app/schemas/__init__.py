"""
Pydantic schemas for request/response validation
"""

from .user import (
    UserProfileCreate,
    UserProfileUpdate,
    UserProfileResponse,
    AuthRequest,
    AuthResponse
)

from .interview import (
    InterviewSetupRequest,
    InterviewSetupResponse,
    InterviewTopic,
    InterviewQuestion,
    InterviewGenerateRequest,
    InterviewGenerateResponse,
    AnswerScore,
    SubmitAnswerRequest,
    SubmitAnswerResponse,
    StartInterviewRequest,
    StartInterviewResponse,
    CategoryScore,
    InterviewEvaluationRequest,
    InterviewEvaluationResponse
)

from .admin import (
    StudentInterviewResult,
    QuestionTemplate,
    QuestionTemplateCreate,
    QuestionTemplateUpdate,
    AnalyticsData
)

from .dashboard import (
    InterviewSummary,
    SkillAnalysis,
    TrendDataPoint,
    PerformanceDashboardResponse,
    TrendsDashboardResponse
)

__all__ = [
    # User schemas
    "UserProfileCreate",
    "UserProfileUpdate",
    "UserProfileResponse",
    "AuthRequest",
    "AuthResponse",
    # Interview schemas
    "InterviewSetupRequest",
    "InterviewSetupResponse",
    "InterviewTopic",
    "InterviewQuestion",
    "InterviewGenerateRequest",
    "InterviewGenerateResponse",
    "AnswerScore",
    "SubmitAnswerRequest",
    "SubmitAnswerResponse",
    "StartInterviewRequest",
    "StartInterviewResponse",
    "CategoryScore",
    "InterviewEvaluationRequest",
    "InterviewEvaluationResponse",
    # Admin schemas
    "StudentInterviewResult",
    "QuestionTemplate",
    "QuestionTemplateCreate",
    "QuestionTemplateUpdate",
    "AnalyticsData",
    # Dashboard schemas
    "InterviewSummary",
    "SkillAnalysis",
    "TrendDataPoint",
    "PerformanceDashboardResponse",
    "TrendsDashboardResponse"
]

