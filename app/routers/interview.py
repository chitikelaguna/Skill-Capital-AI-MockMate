"""
Interview routes
"""

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form, Request, Body, Query
from fastapi.responses import StreamingResponse
from supabase import Client
from app.db.client import get_supabase_client
from app.schemas.interview import (
    InterviewSetupRequest, 
    InterviewSetupResponse,
    InterviewGenerateRequest,
    InterviewGenerateResponse,
    InterviewQuestion,
    StartInterviewRequest,
    StartInterviewResponse,
    SubmitAnswerRequest,
    SubmitAnswerResponse,
    InterviewEvaluationRequest,
    InterviewEvaluationResponse,
    TechnicalInterviewStartRequest,
    TechnicalInterviewStartResponse
)
from app.services.topic_generator import topic_generator
from app.services.question_generator import question_generator
from app.services.answer_evaluator import answer_evaluator
from app.services.interview_evaluator import interview_evaluator
from app.services.resume_parser import resume_parser
from app.services.technical_interview_engine import technical_interview_engine
from app.services.coding_interview_engine import coding_interview_engine
from app.utils.database import (
    get_user_profile,
    get_interview_session,
    get_question_by_number,
    get_all_answers_for_session,
    batch_insert_questions
)
from app.utils.datetime_utils import parse_datetime, get_current_timestamp
from app.utils.exceptions import NotFoundError, ValidationError, DatabaseError
from app.routers.interview_utils import (
    HR_WARMUP_QUESTIONS,
    HR_WARMUP_COUNT,
    test_supabase_connection,
    log_interview_transcript,
    build_resume_context_from_profile,
    build_context_from_cache,
    merge_resume_context
)
from typing import Optional, Dict, Any, List
from datetime import datetime
import uuid
import tempfile
import os
import json
import io
import base64
import urllib.parse
import logging
import traceback

logger = logging.getLogger(__name__)

# Coding endpoints moved to app.routers.coding_interview

# Import common interview router

from app.routers.hr_interview import router as hr_router
# Import STAR interview router
from app.routers.star_interview import router as star_router

router = APIRouter(prefix="/api/interview", tags=["interview"])

# Include common endpoints

# Include HR interview endpoints
router.include_router(hr_router)
# Include STAR interview endpoints
router.include_router(star_router)
# Include Technical interview endpoints
from app.routers.technical_interview import router as technical_router
router.include_router(technical_router)

# Technical endpoints moved to app.routers.technical_interview

# Coding endpoints moved to app.routers.coding_interview

# Include Coding interview endpoints
from app.routers.coding_interview import router as coding_router
router.include_router(coding_router)
