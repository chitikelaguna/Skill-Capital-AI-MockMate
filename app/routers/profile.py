"""
User profile routes
Handles profile CRUD operations and resume upload
"""

import os
import uuid
import re
import json
import logging
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Query
from fastapi.responses import JSONResponse
from supabase import Client
from app.db.client import get_supabase_client
from app.schemas.user import UserProfileCreate, UserProfileUpdate, UserProfileResponse
from app.utils.resume_parser_util import parse_pdf, parse_docx
from app.services.resume_parser import resume_parser
from app.config.settings import settings
from app.utils.database import get_user_profile, get_authenticated_user
from app.utils.file_utils import validate_file_type, extract_file_extension, save_temp_file, cleanup_temp_file
from app.utils.exceptions import NotFoundError, ValidationError, DatabaseError
from typing import Optional
from datetime import datetime

# Setup logger
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/profile", tags=["profile"])

# In-memory storage for resume analysis (in production, use Redis or database)
resume_analysis_cache = {}

@router.get("/resume-analysis/{session_id}")
async def get_resume_analysis(
    session_id: str
):
    """Get resume analysis data by session ID"""
    # Check if this is an error session (starts with "error_")
    if session_id.startswith("error_"):
        logger.warning(f"Error session detected: {session_id}")
        # Return a proper error response instead of 404
        return JSONResponse(
            status_code=200,
            content={
                "success": False,
                "error": "Resume upload failed. Please try uploading again.",
                "session_id": session_id
            }
        )
    
    if session_id not in resume_analysis_cache:
        logger.warning(f"Session not found in cache: {session_id}")
        raise HTTPException(
            status_code=404, 
            detail=f"Resume analysis session not found. Session may have expired. Please upload your resume again."
        )
    
    return resume_analysis_cache[session_id]


@router.put("/resume-analysis/{session_id}/experience")
async def update_resume_experience(
    session_id: str,
    experience: str = Query(..., description="Experience level to update"),
    user_id: Optional[str] = Query(None, description="User ID (fallback if session not found)"),
    supabase: Client = Depends(get_supabase_client)
):
    """
    Update experience level for a resume analysis session
    Updates both the cache and the user profile in Supabase database
    If session not found, uses user_id to update profile directly
    """
    try:
        session_found = session_id in resume_analysis_cache
        cached_data = None
        resolved_user_id = None
        
        # Try to get user_id from cache first
        if session_found:
            cached_data = resume_analysis_cache[session_id]
            resolved_user_id = cached_data.get("user_id")
            logger.info(f"[EXPERIENCE_UPDATE] Session found in cache: {session_id}, user_id: {resolved_user_id}")
        else:
            logger.warning(f"[EXPERIENCE_UPDATE] Session not found in cache: {session_id}")
        
        # Fallback to user_id from query parameter if not in cache
        if not resolved_user_id and user_id:
            resolved_user_id = user_id
            logger.info(f"[EXPERIENCE_UPDATE] Using user_id from query parameter: {user_id}")
        
        # If we have user_id, update the profile directly (even if session not in cache)
        if resolved_user_id:
            # Update or create session in cache for future use
            if not session_found:
                logger.info(f"[EXPERIENCE_UPDATE] Recreating session in cache: {session_id}")
                resume_analysis_cache[session_id] = {
                    "user_id": resolved_user_id,
                    "experience_level": experience,
                    "created_at": datetime.now().isoformat()
                }
            else:
                # Update existing cache entry
                resume_analysis_cache[session_id]["experience_level"] = experience
            
            # Update user profile in Supabase database
            try:
                logger.info(f"[EXPERIENCE_UPDATE] Updating experience for user {resolved_user_id} to: {experience}")
                
                # Check if profile exists
                existing_profile = await get_user_profile(supabase, resolved_user_id)
                
                if existing_profile:
                    # Update existing profile
                    update_response = (
                        supabase.table("user_profiles")
                        .update({"experience_level": experience})
                        .eq("user_id", resolved_user_id)
                        .execute()
                    )
                    
                    if not update_response.data or len(update_response.data) == 0:
                        logger.warning(f"[EXPERIENCE_UPDATE] Profile update returned no data for user {resolved_user_id}")
                    else:
                        logger.info(f"[EXPERIENCE_UPDATE] Successfully updated profile for user {resolved_user_id}")
                else:
                    # Create new profile with experience
                    logger.info(f"[EXPERIENCE_UPDATE] Profile not found, creating new profile for user {resolved_user_id}")
                    create_response = (
                        supabase.table("user_profiles")
                        .insert({
                            "user_id": resolved_user_id,
                            "experience_level": experience
                        })
                        .execute()
                    )
                    
                    if not create_response.data or len(create_response.data) == 0:
                        logger.warning(f"[EXPERIENCE_UPDATE] Profile creation returned no data for user {resolved_user_id}")
                    else:
                        logger.info(f"[EXPERIENCE_UPDATE] Successfully created profile for user {resolved_user_id}")
            
            except Exception as db_error:
                # Log the error but don't fail the request - cache is already updated
                import traceback
                error_traceback = traceback.format_exc()
                logger.error(f"[EXPERIENCE_UPDATE] Failed to update Supabase profile for user {resolved_user_id}: {str(db_error)}")
                logger.error(f"[EXPERIENCE_UPDATE] Traceback: {error_traceback}")
                # Continue - cache update succeeded
        
        else:
            # No user_id available - just update cache if session exists
            if session_found:
                resume_analysis_cache[session_id]["experience_level"] = experience
                logger.warning(f"[EXPERIENCE_UPDATE] No user_id available, only updated cache for session: {session_id}")
            else:
                logger.error(f"[EXPERIENCE_UPDATE] Session not found and no user_id provided: {session_id}")
                raise HTTPException(
                    status_code=404, 
                    detail="Resume analysis session not found. Please provide user_id or upload resume again."
                )
        
        # Return success response
        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "success": True,
                "message": "Experience saved successfully",
                "experience_level": experience,
                "session_id": session_id
            }
        )
    
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_traceback = traceback.format_exc()
        logger.error(f"[EXPERIENCE_UPDATE] Unexpected error updating experience: {str(e)}")
        logger.error(f"[EXPERIENCE_UPDATE] Traceback: {error_traceback}")
        raise HTTPException(status_code=500, detail=f"Error updating experience: {str(e)}")


@router.get("/current", response_model=UserProfileResponse)
async def get_current_user(
    user_id: Optional[str] = Query(None, description="Optional user_id to fetch specific user profile"),
    supabase: Client = Depends(get_supabase_client)
):
    """
    Get current authenticated user from user_profiles table
    If user_id is provided, fetches that specific user profile
    Otherwise, returns the first user in user_profiles (for development/testing)
    Time Complexity: O(1) - Single query
    Space Complexity: O(1) - Returns single record
    """
    try:
        # If user_id is provided, fetch that specific user
        if user_id:
            user = await get_authenticated_user(supabase, user_id=user_id)
        else:
            # Otherwise, get first user (for development/testing)
            user = await get_authenticated_user(supabase)
        
        if not user:
            raise HTTPException(status_code=404, detail="No user found in user_profiles table. Please create a user profile first.")
        
        # User profile is already sanitized by get_authenticated_user
        # No need to manually set access_role as it's handled in sanitize_user_profile
        
        return UserProfileResponse(**user)
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"Error getting current user: {error_details}")
        raise HTTPException(status_code=500, detail=f"Error getting current user: {str(e)}")


@router.get("/{user_id}", response_model=UserProfileResponse)
async def get_user_profile_by_id(
    user_id: str,
    supabase: Client = Depends(get_supabase_client)
):
    """
    Get user profile by user_id
    Time Complexity: O(1) - Single indexed query
    Space Complexity: O(1) - Returns single record
    """
    try:
        logger.info(f"[PROFILE] Fetching profile for user_id: {user_id}")
        profile = await get_user_profile(supabase, user_id)
        if not profile:
            logger.warning(f"[PROFILE] Profile not found for user_id: {user_id}")
            raise HTTPException(
                status_code=404, 
                detail=f"User profile with user_id '{user_id}' not found. Please upload a resume to create your profile."
            )
        
        logger.info(f"[PROFILE] Profile found for user_id: {user_id}, name: {profile.get('name')}, email: {profile.get('email')}")
        
        # Ensure required fields are present for Pydantic validation
        if 'id' not in profile:
            logger.warning(f"[PROFILE] Profile missing 'id' field, using user_id as fallback")
            profile['id'] = profile.get('user_id', user_id)
        if 'created_at' not in profile:
            profile['created_at'] = None
        if 'updated_at' not in profile:
            profile['updated_at'] = None
        
        return UserProfileResponse(**profile)
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"[PROFILE] Error getting user profile by id: {error_details}")
        raise HTTPException(status_code=500, detail=f"Error getting user profile: {str(e)}")


@router.post("/upload-resume")
async def upload_resume(
    file: UploadFile = File(...),
    ocr: bool = Query(False, description="Enable OCR mode for LaTeX/scanned PDFs"),
    supabase: Client = Depends(get_supabase_client)
):
    """
    Upload resume and extract skills/experience
    Generates stable user_id from extracted name (slugified)
    Time Complexity: O(n) where n = file size (read/write operations)
    Space Complexity: O(n) - File content in memory + temp file
    Optimization: 
    - Uses utility functions for file operations
    - Validates file type early
    - Cleans up temp files in finally block
    - Supports files up to 2GB
    """
    temp_file_path: Optional[str] = None
    # Initialize session_id container at the very start to ensure it's always available
    # This must be initialized before any code that might raise exceptions
    # Use a list container to avoid closure scoping issues with nested functions
    # DO NOT create a local session_id variable - always use _session_id_container[0] directly
    _session_id_container: list = [f"session_{uuid.uuid4().hex}"]
    stable_user_id: Optional[str] = None
    interview_session_id: Optional[str] = None

    def build_error_response(
        message: str,
        *,
        status_code: int = 400,
        user_id: Optional[str] = None,
        session_override: Optional[str] = None
    ) -> JSONResponse:
        """
        Create a consistent error response with a cached payload so the frontend
        can always render a structured error object.
        This function does NOT use closure variables - only uses session_override parameter.
        """
        # Use session_override if provided, otherwise generate a new error session ID
        # Do NOT reference session_id from closure to avoid UnboundLocalError
        if session_override:
            resolved_session_id = session_override
        else:
            resolved_session_id = f"error_{uuid.uuid4().hex}"
        resume_analysis_cache[resolved_session_id] = {
            "success": False,
            "error": message,
            "name": None,
            "email": None,
            "skills": [],
            "experience_level": "Not specified",
            "user_id": user_id,
        }
        return JSONResponse(
            status_code=status_code,
            content={
                "success": False,
                "error": message,
                "session_id": resolved_session_id,
                "user_id": user_id,
            },
        )
    
    try:
        # Log incoming request
        logger.info(f"[UPLOAD] ========== START UPLOAD REQUEST ==========")
        logger.info(f"[UPLOAD] Received upload request")
        logger.info(f"[UPLOAD] Filename: {file.filename}")
        logger.info(f"[UPLOAD] Content type: {file.content_type}")
        logger.info(f"[UPLOAD] Route: POST /api/profile/upload-resume")
        
        # Validate file type by extension
        file_extension = extract_file_extension(file.filename or "")
        logger.info(f"[UPLOAD] Extracted extension: {file_extension}")
        
        if not file.filename:
            logger.error(f"[UPLOAD] No filename provided in upload")
            return build_error_response(
                "No file was uploaded. Please select a file and try again.",
                status_code=400,
                session_override=_session_id_container[0],
            )
        
        if not file_extension:
            logger.error(f"[UPLOAD] No file extension found in filename: {file.filename}")
            return build_error_response(
                "Invalid file type. Only PDF and DOCX files are supported.",
                status_code=400,
                session_override=_session_id_container[0],
            )
        
        if not validate_file_type(file_extension):
            logger.error(f"[UPLOAD] Invalid file extension: {file_extension}")
            return build_error_response(
                f"Invalid file type: {file_extension}. Only PDF and DOCX files are supported.",
                status_code=400,
                session_override=_session_id_container[0],
            )
        
        # Validate MIME type
        allowed_mime_types = {
            'application/pdf',
            'application/msword',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        }
        
        if file.content_type and file.content_type not in allowed_mime_types:
            # Check if extension matches even if MIME type is wrong (some browsers send wrong MIME)
            if file_extension not in ['.pdf', '.docx', '.doc']:
                return build_error_response(
                    "Invalid file type. Only PDF and DOCX files are supported.",
                    status_code=400,
                    session_override=_session_id_container[0],
                )
        
        # Read file content (up to 2GB)
        # FastAPI UploadFile.read() automatically reads from the beginning
        # No need for seek(0) - it can cause issues with UploadFile objects
        logger.info(f"[UPLOAD] Reading file content...")
        try:
            file_content = await file.read()
            logger.info(f"[UPLOAD] File read successfully: {file.filename}, size: {len(file_content)} bytes")
        except Exception as read_error:
            logger.error(f"[UPLOAD] Failed to read file content: {str(read_error)}")
            return build_error_response(
                f"Failed to read file: {str(read_error)}. Please try uploading again.",
                status_code=400,
                session_override=_session_id_container[0],
            )
        
        # Verify file is actually a PDF or DOCX by checking magic bytes
        logger.info(f"[UPLOAD] Validating file magic bytes for extension: {file_extension}")
        if file_extension == '.pdf':
            # Check for PDF magic bytes (some PDFs may have whitespace before %PDF)
            file_start = file_content[:10].strip()
            if not file_content.startswith(b'%PDF') and not file_start.startswith(b'%PDF'):
                logger.error(f"[UPLOAD] File does not have PDF magic bytes. First 20 bytes: {file_content[:20]}")
                logger.error(f"[UPLOAD] File size: {len(file_content)} bytes")
                return build_error_response(
                    "The file is not a valid PDF. Please upload a valid PDF file.",
                    status_code=400,
                    session_override=_session_id_container[0],
                )
            logger.info(f"[UPLOAD] PDF magic bytes validated successfully")
        elif file_extension in ['.docx', '.doc']:
            # DOCX files start with PK (ZIP format)
            if not (file_content.startswith(b'PK') or file_content.startswith(b'\xd0\xcf\x11\xe0')):
                logger.error(f"[UPLOAD] File does not have DOCX magic bytes. First 20 bytes: {file_content[:20]}")
                return build_error_response(
                    "The file is not a valid DOCX document. Please upload a valid DOCX file.",
                    status_code=400,
                    session_override=_session_id_container[0],
                )
        
        # Validate file size (max 2GB)
        max_size = 2 * 1024 * 1024 * 1024  # 2GB in bytes
        if len(file_content) > max_size:
            return build_error_response(
                "File size exceeds 2GB limit. Please upload a smaller file.",
                status_code=400,
                session_override=_session_id_container[0],
            )
        
        # Validate file is not empty
        if len(file_content) == 0:
            return build_error_response(
                "The uploaded file is empty. Please upload a valid resume file.",
                status_code=400,
                session_override=_session_id_container[0],
            )
        
        # Save to temporary file for parsing
        logger.info(f"[UPLOAD] Saving file: {file.filename}, extension: {file_extension}, size: {len(file_content)} bytes")
        temp_file_path = await save_temp_file(file_content, file_extension)
        logger.info(f"[UPLOAD] Temp file saved to: {temp_file_path}")
        
        # Validate temp file was created and has content
        if not temp_file_path or not os.path.exists(temp_file_path):
            logger.error(f"Temp file not created or doesn't exist: {temp_file_path}")
            return build_error_response(
                "Failed to save file for processing. Please try again.",
                status_code=500,
                session_override=_session_id_container[0],
            )
        
        # Verify file size matches
        temp_file_size = os.path.getsize(temp_file_path)
        if temp_file_size != len(file_content):
            logger.error(f"File size mismatch! Temp: {temp_file_size}, Original: {len(file_content)}")
            return build_error_response(
                "File was not saved correctly. Please try again.",
                status_code=500,
                session_override=_session_id_container[0],
            )
        
        # Parse resume using robust parser utility
        parsed_data = None
        
        try:
            logger.info(f"[UPLOAD] Starting parsing with extension: {file_extension}")
            logger.info(f"[UPLOAD] Temp file path: {temp_file_path}")
            logger.info(f"[UPLOAD] Temp file exists: {os.path.exists(temp_file_path) if temp_file_path else False}")
            
            # Use new robust parser utility
            if file_extension == '.pdf':
                logger.info(f"[UPLOAD] Parsing PDF with OCR fallback enabled")
                # Pass OCR mode flag (defaults to True for automatic fallback)
                parsed_data = parse_pdf(temp_file_path, use_ocr_fallback=True)
                logger.info(f"[UPLOAD] PDF parsing completed successfully")
                logger.info(f"[UPLOAD] Parsed data keys: {list(parsed_data.keys()) if parsed_data else 'None'}")
            elif file_extension in ['.docx', '.doc']:
                logger.info(f"[UPLOAD] Parsing DOCX")
                parsed_data = parse_docx(temp_file_path)
                logger.info(f"[UPLOAD] DOCX parsing completed successfully")
                logger.info(f"[UPLOAD] Parsed data keys: {list(parsed_data.keys()) if parsed_data else 'None'}")
            else:
                raise ValueError(f"Unsupported file extension: {file_extension}")
            
            # Log extracted data for debugging
            if parsed_data:
                logger.info(f"[UPLOAD] Extracted name: {parsed_data.get('name')}")
                logger.info(f"[UPLOAD] Extracted email: {parsed_data.get('email')}")
                logger.info(f"[UPLOAD] Extracted skills: {parsed_data.get('skills', [])}")
                logger.info(f"[UPLOAD] Extracted experience: {parsed_data.get('experience')}")
                logger.info(f"[UPLOAD] Text length: {parsed_data.get('text_length', 0)}")
            else:
                logger.error(f"[UPLOAD] parsed_data is None after parsing!")
            
            # Map to expected format
            mapped_data = {
                "name": parsed_data.get("name") if parsed_data else None,
                "email": parsed_data.get("email") if parsed_data else None,
                "skills": parsed_data.get("skills", []) if parsed_data else [],
                "experience_level": parsed_data.get("experience", "Not specified") if parsed_data else "Not specified",
                "keywords": {},
                "text_length": parsed_data.get("text_length", 0) if parsed_data else 0
            }
            
            logger.info(f"[UPLOAD] Mapped data - Name: {mapped_data.get('name')}, Email: {mapped_data.get('email')}, Skills count: {len(mapped_data.get('skills', []))}")
            
            # Generate stable user_id from name (slugify)
            # Capture module-level 're' in closure to avoid free variable error
            regex_module = re  # Capture module-level re for nested function
            def slugify_name(name: str) -> str:
                """Convert name to stable user_id slug"""
                if not name:
                    return "user-" + str(uuid.uuid4())[:8]
                # Convert to lowercase, replace spaces with hyphens, remove special chars
                slug = name.lower().strip()
                slug = regex_module.sub(r'[^\w\s-]', '', slug)  # Remove special chars
                slug = regex_module.sub(r'[-\s]+', '-', slug)  # Replace spaces/multiple hyphens with single hyphen
                slug = slug.strip('-')  # Remove leading/trailing hyphens
                if not slug:
                    return "user-" + str(uuid.uuid4())[:8]
                return slug
            
            # Generate stable user_id from extracted name
            extracted_name = mapped_data.get("name") or ""
            stable_user_id = slugify_name(extracted_name)
            logger.info(f"[UPLOAD] Generated stable user_id from name '{extracted_name}': {stable_user_id}")
            
            # Extract text for enhanced summary generation
            try:
                logger.info(f"[UPLOAD] Extracting full text for summary generation...")
                text = resume_parser.extract_text(temp_file_path, file_extension)
                logger.info(f"[UPLOAD] Extracted {len(text)} characters for summary")
                
                # Generate enhanced summary using resume_parser
                enhanced_summary = resume_parser.generate_enhanced_summary(mapped_data, text)
                mapped_data["summary"] = enhanced_summary
                logger.info(f"[UPLOAD] Generated enhanced summary")
                
                # Also extract keywords for better summary
                mapped_data["keywords"] = resume_parser.extract_keywords(text)
                logger.info(f"[UPLOAD] Extracted keywords")
                
                # Generate interview modules
                try:
                    interview_modules = resume_parser.generate_interview_modules(mapped_data, text)
                    mapped_data["interview_modules"] = interview_modules
                    logger.info(f"[UPLOAD] Generated interview modules")
                except Exception as modules_error:
                    logger.warning(f"[UPLOAD] Failed to generate interview modules: {str(modules_error)}")
                    mapped_data["interview_modules"] = None
            except Exception as summary_error:
                logger.warning(f"[UPLOAD] Failed to generate enhanced summary: {str(summary_error)}")
                logger.warning(f"[UPLOAD] Summary error details: {type(summary_error).__name__}: {summary_error}")
                import traceback
                logger.warning(f"[UPLOAD] Summary error traceback: {traceback.format_exc()}")
                mapped_data["summary"] = None
                mapped_data["interview_modules"] = None
            
            parsed_data = mapped_data
            
        except ImportError as import_error:
            # Missing parsing library
            error_msg = str(import_error)
            logger.error(f"Missing parsing library: {import_error}")
            user_error = f"Resume parsing library not installed. {str(import_error)}"
            return build_error_response(user_error, status_code=500, session_override=_session_id_container[0])
        except ValueError as value_error:
            # File format or content issues
            error_msg = str(value_error)
            error_msg_lower = error_msg.lower()
            logger.error(f"Parsing failed (ValueError): {value_error}")
            
            # Check for specific LaTeX PDF error codes first
            if "LATEX_PDF_OCR_REQUIRED" in error_msg:
                user_error = "This appears to be a LaTeX-generated PDF (from Overleaf). OCR is required but Tesseract is not installed. Please install Tesseract OCR to enable LaTeX PDF support. See OCR_SETUP.md for installation instructions."
            elif "LATEX_PDF_OCR_FAILED" in error_msg:
                user_error = "This appears to be a LaTeX-generated PDF. OCR was attempted but failed. Please try: 1) Exporting as PDF/A from Overleaf, 2) Ensuring the PDF contains readable text, or 3) Installing/updating Tesseract OCR."
            elif "LATEX_PDF_NO_TEXT" in error_msg:
                user_error = "Could not extract text from this PDF. It may be a LaTeX-generated PDF (vector-based), scanned image, or corrupted file. For LaTeX PDFs, please install Tesseract OCR or export as PDF/A from Overleaf."
            elif "latex" in error_msg_lower or "vector-based" in error_msg_lower:
                user_error = "This appears to be a LaTeX-generated PDF (vector-based text). OCR support may be required. Please install Tesseract OCR or try exporting your resume as PDF/A from Overleaf."
            elif "not a valid" in error_msg_lower or ("invalid" in error_msg_lower and "corrupt" not in error_msg_lower):
                user_error = "The file is not a valid PDF or DOCX document. Please upload a valid resume file."
            elif "corrupt" in error_msg_lower:
                user_error = "The file appears to be corrupted. Please try uploading a different file or re-exporting your resume."
            elif "could not extract" in error_msg_lower or "no extractable text" in error_msg_lower or "image-based" in error_msg_lower:
                user_error = "The resume contains no readable text. It might be a scanned/image-based PDF, LaTeX-generated PDF, corrupted, or password-protected. For LaTeX PDFs, please install Tesseract OCR or export as PDF/A from Overleaf."
            elif "empty" in error_msg_lower and "invalid" not in error_msg_lower:
                user_error = "The uploaded file appears to be empty or contains no extractable text. If this is a LaTeX PDF, please install Tesseract OCR."
            else:
                user_error = f"Resume parsing failed: {str(value_error)}"
            
            return build_error_response(user_error, status_code=400, session_override=_session_id_container[0])
        except Exception as parse_error:
            # Other unexpected errors
            error_msg = str(parse_error).lower()
            logger.error(f"Unexpected parsing error: {parse_error}")
            if "not installed" in error_msg or "import" in error_msg:
                user_error = "Resume parsing library not installed. Please install: pip install pdfplumber python-docx PyMuPDF"
            else:
                user_error = f"Failed to parse resume: {str(parse_error)}"
            
            return build_error_response(user_error, status_code=500, session_override=_session_id_container[0])
        
        # Upload to Supabase Storage (use stable_user_id)
        storage_path = f"{stable_user_id}/{file.filename}"
        resume_url = None
        bucket_name = "resume-uploads"
        try:
            # Try to create bucket if it doesn't exist
            try:
                # Check if bucket exists first
                try:
                    buckets = supabase.storage.list_buckets()
                    bucket_exists = any(b.name == bucket_name for b in buckets)
                    if not bucket_exists:
                        # Create bucket with proper configuration
                        bucket_config = {
                            "name": bucket_name,
                            "public": True,
                            "file_size_limit": 2147483648,  # 2GB
                            "allowed_mime_types": ["application/pdf", "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"]
                        }
                        supabase.storage.create_bucket(bucket_name, bucket_config)
                        logger.info(f"[UPLOAD] Created bucket: {bucket_name}")
                    else:
                        logger.info(f"[UPLOAD] Bucket {bucket_name} already exists")
                except Exception as list_error:
                    # If list_buckets fails, try to create anyway
                    logger.warning(f"[UPLOAD] Could not list buckets, attempting to create: {list_error}")
                    try:
                        bucket_config = {
                            "name": bucket_name,
                            "public": True,
                            "file_size_limit": 2147483648,  # 2GB
                            "allowed_mime_types": ["application/pdf", "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"]
                        }
                        supabase.storage.create_bucket(bucket_name, bucket_config)
                        logger.info(f"[UPLOAD] Created bucket: {bucket_name}")
                    except Exception as create_error:
                        error_str = str(create_error).lower()
                        # Bucket might already exist, which is fine
                        if "already exists" not in error_str and "duplicate" not in error_str:
                            logger.warning(f"[UPLOAD] Could not create bucket (may already exist): {create_error}")
            except Exception as bucket_error:
                error_str = str(bucket_error).lower()
                # Bucket might already exist, which is fine
                if "already exists" not in error_str and "duplicate" not in error_str and "bucket" not in error_str:
                    logger.warning(f"[UPLOAD] Could not create bucket (may already exist): {bucket_error}")
            
            # Upload file to resume-uploads bucket
            supabase.storage.from_(bucket_name).upload(
                storage_path,
                file_content,
                file_options={"content-type": file.content_type or "application/pdf", "upsert": "true"}
            )
            logger.info(f"[UPLOAD] Successfully uploaded to {bucket_name}/{storage_path}")
            
            # Get public URL if upload succeeded
            try:
                public_url_response = supabase.storage.from_(bucket_name).get_public_url(storage_path)
                resume_url = (
                    public_url_response 
                    if isinstance(public_url_response, str) 
                    else str(public_url_response)
                )
            except Exception:
                # Fallback: construct URL manually
                try:
                    resume_url = f"{settings.supabase_url}/storage/v1/object/public/{bucket_name}/{storage_path}"
                except Exception:
                    resume_url = None
        except Exception as storage_error:
            # If storage upload fails, still return parsed data
            logger.warning(f"[UPLOAD] Storage upload failed for user {stable_user_id}: {storage_error}")
            resume_url = None
        
        # Update or create user profile with extracted data
        # Get full resume text if available (for storing in resume_text field)
        resume_text_full = ""
        try:
            # Try to get full text from resume parser
            if temp_file_path:
                resume_text_full = resume_parser.extract_text(temp_file_path, file_extension)
                # Limit to first 10000 chars to avoid database issues
                if len(resume_text_full) > 10000:
                    resume_text_full = resume_text_full[:10000] + "... (truncated)"
        except Exception as text_extract_error:
            logger.warning(f"[UPLOAD] Could not extract full resume text: {text_extract_error}")
            resume_text_full = parsed_data.get("extracted_text_preview", "") or ""
        
        # Ensure email is provided (required field)
        email = mapped_data.get("email") or f"{stable_user_id}@example.com"
        
        profile_data = {
            "user_id": stable_user_id,  # Use stable user_id from name
            "email": email,  # Required field
            "resume_url": resume_url,
            "skills": mapped_data.get("skills", []),
            "experience_level": mapped_data.get("experience_level", "Not specified"),
            "resume_text": resume_text_full  # Store full resume text
        }
        
        # Add name if available
        if mapped_data.get("name"):
            profile_data["name"] = mapped_data["name"]
        
        # Extract and store projects, education, work_experience, certifications from summary
        summary = mapped_data.get("summary", {})
        if summary:
            # Store projects as JSONB
            projects_summary = summary.get("projects_summary", [])
            if projects_summary:
                # Note: 'json' is already imported at the top of the file
                profile_data["projects"] = json.dumps(projects_summary)
            
            # Extract years of experience
            experience_level = mapped_data.get("experience_level", "Fresher")
            years_of_experience = 0
            if experience_level and experience_level != "Fresher":
                # Try to extract number from experience_level (e.g., "2yrs" -> 2)
                # Note: 're' is already imported at the top of the file, no need to import again
                years_match = re.search(r'(\d+)', str(experience_level))
                if years_match:
                    years_of_experience = int(years_match.group(1))
            profile_data["years_of_experience"] = years_of_experience
            
            # Note: Education, work_experience, and certifications can be added later
            # when resume parser is enhanced to extract these fields
            # For now, set them as empty arrays
            # Note: 'json' is already imported at the top of the file
            profile_data["education"] = json.dumps([])
            profile_data["work_experience"] = json.dumps([])
            profile_data["certifications"] = json.dumps([])
        else:
            # Set defaults if no summary
            # Note: 'json' is already imported at the top of the file
            profile_data["projects"] = json.dumps([])
            profile_data["education"] = json.dumps([])
            profile_data["work_experience"] = json.dumps([])
            profile_data["certifications"] = json.dumps([])
            profile_data["years_of_experience"] = 0
        
        # Check if profile exists (optimized: single query) - use stable_user_id
        # Don't fail if user profile lookup fails - we can still process the resume
        existing_profile = None
        try:
            existing_profile = await get_user_profile(supabase, stable_user_id)
        except Exception as profile_lookup_error:
            logger.warning(f"[UPLOAD] Could not fetch existing profile for user {stable_user_id}: {profile_lookup_error}. Will create new profile.")
            existing_profile = None
        
        try:
            if existing_profile:
                # Update existing profile (same user_id, different resume)
                response = (
                    supabase.table("user_profiles")
                    .update(profile_data)
                    .eq("user_id", stable_user_id)
                    .execute()
                )
                # CRITICAL: Validate that update actually succeeded
                if not response.data or len(response.data) == 0:
                    logger.error(f"[UPLOAD] ❌ CRITICAL: Profile update returned no data for user_id: {stable_user_id}")
                    logger.error(f"[UPLOAD] Profile data: {profile_data}")
                    raise Exception(f"Failed to update profile in database. Update returned no rows. This may be due to RLS policies or validation errors.")
                logger.info(f"[UPLOAD] ✓ Updated existing profile for user_id: {stable_user_id}")
            else:
                # Create new profile
                response = (
                    supabase.table("user_profiles")
                    .insert(profile_data)
                    .execute()
                )
                # CRITICAL: Validate that insert actually succeeded
                if not response.data or len(response.data) == 0:
                    logger.error(f"[UPLOAD] ❌ CRITICAL: Profile insert returned no data for user_id: {stable_user_id}")
                    logger.error(f"[UPLOAD] Profile data: {profile_data}")
                    raise Exception(f"Failed to create profile in database. Insert returned no rows. This may be due to RLS policies, validation errors, or duplicate user_id.")
                logger.info(f"[UPLOAD] ✓ Created new profile for user_id: {stable_user_id}, id: {response.data[0].get('id')}")
            
            # CRITICAL: Verify profile was actually created/updated by querying it back
            try:
                verified_profile = await get_user_profile(supabase, stable_user_id)
                if not verified_profile:
                    logger.error(f"[UPLOAD] ❌ CRITICAL: Profile verification failed - profile not found after insert/update for user_id: {stable_user_id}")
                    raise Exception(f"Profile was not found in database after insert/update. This indicates a database issue.")
                logger.info(f"[UPLOAD] ✓ Profile verified in database for user_id: {stable_user_id}")
            except Exception as verify_error:
                logger.error(f"[UPLOAD] ❌ Profile verification error: {verify_error}")
                raise Exception(f"Failed to verify profile in database: {str(verify_error)}")
            
            # Auto-create interview session for this user
            interview_session_id = None
            try:
                # Check if active session exists for this user
                existing_sessions = supabase.table("interview_sessions").select("id").eq("user_id", stable_user_id).eq("session_status", "active").limit(1).execute()
                if existing_sessions.data and len(existing_sessions.data) > 0:
                    interview_session_id = existing_sessions.data[0]["id"]
                    logger.info(f"[UPLOAD] Reusing existing session: {interview_session_id}")
                else:
                    # Create new interview session
                    session_data = {
                        "user_id": stable_user_id,
                        "interview_type": "full",  # Default to full interview
                        "session_status": "active",
                        "experience_level": mapped_data.get("experience_level", "Intermediate"),
                        "skills": mapped_data.get("skills", [])
                    }
                    session_response = supabase.table("interview_sessions").insert(session_data).execute()
                    if session_response.data and len(session_response.data) > 0:
                        interview_session_id = session_response.data[0]["id"]
                        logger.info(f"[UPLOAD] Created new interview session: {interview_session_id}")
            except Exception as session_error:
                logger.warning(f"[UPLOAD] Could not create interview session: {session_error}")
                # Continue without session - user can start interview manually
            
            # Store parsed data in cache (include stable_user_id for later updates)
            # Use container to access session_id to avoid any scoping issues
            current_session_id = _session_id_container[0]
            resume_analysis_cache[current_session_id] = {
                "user_id": stable_user_id,  # Store stable user_id for profile updates
                "name": mapped_data.get("name"),
                "email": mapped_data.get("email"),
                "skills": mapped_data.get("skills", []),
                "experience_level": mapped_data.get("experience_level", "Not specified"),
                "keywords": mapped_data.get("keywords", {}),
                "text_length": mapped_data.get("text_length", 0),
                "summary": mapped_data.get("summary"),
                "interview_modules": mapped_data.get("interview_modules"),
                "created_at": datetime.now().isoformat()
            }
            
            return JSONResponse(
                status_code=200,
                content={
                    "success": True,
                    "message": "Resume parsed successfully.",
                    "session_id": current_session_id,
                    "interview_session_id": interview_session_id,  # Include interview session ID
                    "user_id": stable_user_id,  # Include stable user_id in response
                    "name": mapped_data.get("name"),
                    "email": mapped_data.get("email"),
                    "skills": mapped_data.get("skills", []),
                    "experience_level": mapped_data.get("experience_level", "Unknown"),
                    "keywords": mapped_data.get("keywords", {}),
                    "text_length": mapped_data.get("text_length", 0),
                    "summary": mapped_data.get("summary"),
                    "interview_modules": mapped_data.get("interview_modules"),
                    "resume_url": resume_url
                }
            )
        except Exception as db_error:
            # Database error - profile creation/update failed
            # Log the error with full details
            import traceback
            error_traceback = traceback.format_exc()
            logger.error(f"[UPLOAD] ❌ Database error creating/updating profile: {str(db_error)}")
            logger.error(f"[UPLOAD] Error traceback: {error_traceback}")
            
            # Use container to access session_id to avoid any scoping issues
            current_session_id = _session_id_container[0]
            
            # Store extracted data in cache even if DB save failed (user can still view analysis)
            resume_analysis_cache[current_session_id] = {
                "user_id": stable_user_id,  # Store stable user_id for profile updates
                "name": mapped_data.get("name"),
                "email": mapped_data.get("email"),
                "skills": mapped_data.get("skills", []),
                "experience_level": mapped_data.get("experience_level", "Unknown"),
                "keywords": mapped_data.get("keywords", {}),
                "text_length": mapped_data.get("text_length", 0),
                "summary": mapped_data.get("summary"),
                "interview_modules": mapped_data.get("interview_modules"),
                "created_at": datetime.now().isoformat()
            }
            
            # Return error response - profile creation failed
            # This is critical - we must return an error so frontend knows profile wasn't created
            return build_error_response(
                f"Resume parsed successfully, but failed to save profile to database: {str(db_error)}. Please try again or contact support.",
                status_code=500,
                user_id=stable_user_id,
                session_override=current_session_id
            )
    except Exception as e:
        import traceback
        error_message = str(e)
        error_traceback = traceback.format_exc()
        
        # Log the full error for debugging
        logger.error(f"[UPLOAD] Unexpected error in upload_resume: {error_message}")
        logger.error(f"[UPLOAD] Traceback: {error_traceback}")
        
        # Safely get session_id from container to avoid closure scoping issues
        # Using container pattern ensures we can always access the session_id value
        current_session_id = _session_id_container[0] if _session_id_container else f"error_{uuid.uuid4().hex}"
        
        # Provide user-friendly error messages
        if "Invalid file type" in error_message or "Unsupported file type" in error_message:
            error_message = "Invalid file type. Only PDF and DOCX files are supported."
        elif "LATEX_PDF_OCR_REQUIRED" in error_message:
            error_message = "This appears to be a LaTeX-generated PDF. OCR is required but Tesseract is not installed. Please install Tesseract OCR (see OCR_SETUP.md) or export as PDF/A from Overleaf."
        elif "LATEX_PDF_OCR_FAILED" in error_message or "LATEX_PDF_NO_TEXT" in error_message:
            error_message = "This appears to be a LaTeX-generated PDF. OCR was attempted but failed. Please install/update Tesseract OCR or export as PDF/A from Overleaf."
        elif "latex" in error_message.lower() or "vector-based" in error_message.lower():
            error_message = "This appears to be a LaTeX-generated PDF. OCR support may be required. Please install Tesseract OCR or export as PDF/A from Overleaf."
        elif "empty" in error_message.lower() and "invalid" not in error_message.lower():
            error_message = "The uploaded file appears to be empty or contains no extractable text. If this is a LaTeX PDF, please install Tesseract OCR."
        elif "uuid" in error_message.lower() or "user profile" in error_message.lower() or "22P02" in error_message:
            # Database/user ID error - don't mask as file format error
            error_message = f"Invalid user ID format. Please use a valid UUID format for user_id."
        elif "not a valid" in error_message.lower() and ("pdf" in error_message.lower() or "docx" in error_message.lower() or "document" in error_message.lower()):
            # Only treat as file format error if it's actually about the file
            error_message = f"The file format is invalid: {error_message}. Please upload a valid PDF or DOCX file."
        elif "size" in error_message.lower() or "2MB" in error_message.upper() or "2GB" in error_message.upper():
            error_message = "File size exceeds 2MB limit. Please upload a smaller file."
        else:
            # For debugging, include more details in development
            if "development" in str(settings.environment).lower():
                error_message = f"Failed to parse the uploaded resume: {error_message}. Please ensure the file is a valid PDF or DOCX document."
            else:
                error_message = "Failed to parse the uploaded resume. Please ensure the file is a valid PDF or DOCX document."
        
        return build_error_response(
            error_message,
            status_code=500,
            user_id=stable_user_id if stable_user_id else None,
            session_override=current_session_id,
        )
    finally:
        # Clean up temporary file
        if temp_file_path:
            cleanup_temp_file(temp_file_path)


# Route with user_id in path (for backward compatibility - user_id is ignored, generated from resume)
# This route must come AFTER /upload-resume to avoid route conflicts
@router.post("/{user_id}/upload-resume")
async def upload_resume_with_user_id(
    user_id: str,  # Ignored - backend generates user_id from resume name
    file: UploadFile = File(...),
    ocr: bool = Query(False, description="Enable OCR mode for LaTeX/scanned PDFs"),
    supabase: Client = Depends(get_supabase_client)
):
    """
    Upload resume with user_id in path (backward compatibility)
    Note: user_id parameter is ignored - backend generates stable user_id from resume name
    This route handles old frontend code that includes user_id in the URL path
    """
    logger.info(f"[UPLOAD] Received upload request with user_id in path: {user_id} (will be ignored, generating from resume)")
    # Delegate to main upload function (user_id is ignored)
    return await upload_resume(file=file, ocr=ocr, supabase=supabase)
