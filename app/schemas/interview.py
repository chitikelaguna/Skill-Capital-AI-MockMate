"""
Interview-related schemas
Pydantic models for interview requests and responses
"""

from pydantic import BaseModel
from typing import List, Optional, Dict
from datetime import datetime


class InterviewSetupRequest(BaseModel):
    """
    Schema for interview setup request
    Time Complexity: O(1)
    Space Complexity: O(1)
    """
    user_id: str
    role: str
    experience_level: str


class InterviewTopic(BaseModel):
    """
    Schema for interview topic
    Time Complexity: O(1)
    Space Complexity: O(1)
    """
    topic: str
    description: str
    category: str  # e.g., "Technical", "Behavioral", "System Design"


class InterviewSetupResponse(BaseModel):
    """
    Schema for interview setup response
    Time Complexity: O(1)
    Space Complexity: O(n) where n = number of topics
    """
    user_id: str
    role: str
    experience_level: str
    topics: List[InterviewTopic]
    suggested_skills: List[str]
    total_topics: int


class InterviewQuestion(BaseModel):
    """
    Schema for interview question
    Time Complexity: O(1)
    Space Complexity: O(1)
    """
    type: str  # HR, Technical, Problem-solving
    question: str


class InterviewGenerateRequest(BaseModel):
    """
    Schema for interview question generation request
    Time Complexity: O(1)
    Space Complexity: O(n) where n = number of skills
    """
    user_id: str
    role: str
    experience_level: str
    skills: List[str]


class InterviewGenerateResponse(BaseModel):
    """
    Schema for interview question generation response
    Time Complexity: O(1)
    Space Complexity: O(n) where n = number of questions
    """
    session_id: str
    user_id: str
    role: str
    experience_level: str
    questions: List[InterviewQuestion]
    total_questions: int
    created_at: datetime


class AnswerScore(BaseModel):
    """
    Schema for answer scoring
    Time Complexity: O(1)
    Space Complexity: O(1)
    """
    relevance: int  # 0-100
    confidence: int  # 0-100
    technical_accuracy: int  # 0-100
    communication: int  # 0-100
    overall: int  # Average score
    feedback: str  # AI-generated feedback


class SubmitAnswerRequest(BaseModel):
    """
    Schema for submitting an answer
    Time Complexity: O(1)
    Space Complexity: O(1)
    """
    session_id: str
    question_id: str
    question_number: int
    question_text: str
    question_type: str
    user_answer: str
    response_time: Optional[int] = None  # Response time in seconds


class SubmitAnswerResponse(BaseModel):
    """
    Schema for answer submission response
    Time Complexity: O(1)
    Space Complexity: O(1)
    """
    answer_id: str
    session_id: str
    question_id: str
    scores: AnswerScore
    response_time: Optional[int] = None
    answered_at: datetime
    evaluated_at: datetime


class StartInterviewRequest(BaseModel):
    """
    Schema for starting an interview
    Time Complexity: O(1)
    Space Complexity: O(1)
    """
    session_id: str


class StartInterviewResponse(BaseModel):
    """
    Schema for starting interview response
    Time Complexity: O(1)
    Space Complexity: O(1)
    """
    session_id: str
    current_question: InterviewQuestion
    question_number: int
    total_questions: int
    interview_started: bool
    time_limit: int = 60  # Time limit per question in seconds


class CategoryScore(BaseModel):
    """
    Schema for category scores
    Time Complexity: O(1)
    Space Complexity: O(1)
    """
    clarity: float  # Weighted average
    accuracy: float  # Weighted average (technical_accuracy)
    confidence: float  # Weighted average
    communication: float  # Weighted average


class InterviewEvaluationRequest(BaseModel):
    """
    Schema for interview evaluation request
    Time Complexity: O(1)
    Space Complexity: O(1)
    """
    session_id: str


class InterviewEvaluationResponse(BaseModel):
    """
    Schema for interview evaluation response
    Time Complexity: O(1)
    Space Complexity: O(n) where n = number of recommendations/strengths
    """
    session_id: str
    overall_score: float
    category_scores: CategoryScore
    total_questions: int
    answered_questions: int
    feedback_summary: str
    recommendations: List[str]
    strengths: List[str]
    areas_for_improvement: List[str]
    generated_at: datetime


class TechnicalInterviewStartRequest(BaseModel):
    """
    Schema for starting a technical interview
    """
    user_id: str


class TechnicalInterviewStartResponse(BaseModel):
    """
    Schema for technical interview start response
    """
    session_id: str
    conversation_history: List[Dict[str, str]]
    technical_skills: List[str]
