"""
User profile routes
Handles profile CRUD operations and resume upload
"""

import os
import uuid
import logging
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Query
from fastapi.responses import JSONResponse
from supabase import Client
from app.db.client import get_supabase_client
from app.schemas.user import UserProfileCreate, UserProfileUpdate, UserProfileResponse
from app.utils.resume_parser_util import parse_pdf, parse_docx
from app.config.settings import settings
from app.utils.database import get_user_profile
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
    if session_id not in resume_analysis_cache:
        raise HTTPException(status_code=404, detail="Resume analysis session not found")
    
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


@router.get("/{user_id}", response_model=UserProfileResponse)
async def get_profile(
    user_id: str, 
    supabase: Client = Depends(get_supabase_client)
):
    """
    Get user profile by user_id
    Time Complexity: O(1) - Single indexed query
    Space Complexity: O(1) - Returns single record
    Optimization: Uses utility function with optimized query
    """
    try:
        profile = await get_user_profile(supabase, user_id)
        if not profile:
            raise HTTPException(status_code=404, detail=f"User profile not found for user_id: {user_id}")
        
        # Ensure access_role is set (default to "Student" if not present)
        if 'access_role' not in profile or not profile.get('access_role'):
            profile['access_role'] = 'Student'
        
        return UserProfileResponse(**profile)
    except HTTPException:
        # Re-raise HTTP exceptions (like 404)
        raise
    except (NotFoundError, DatabaseError) as e:
        # Convert custom exceptions to HTTPException
        status_code = e.status_code if hasattr(e, 'status_code') else 500
        raise HTTPException(status_code=status_code, detail=str(e))
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"[ERROR] Profile fetch error: {str(e)}")
        print(f"[ERROR] Traceback: {error_details}")
        raise HTTPException(status_code=500, detail=f"Error fetching profile: {str(e)}")


@router.post("/", response_model=UserProfileResponse)
async def create_profile(
    profile: UserProfileCreate, 
    supabase: Client = Depends(get_supabase_client)
):
    """
    Create user profile
    Time Complexity: O(1) - Single insert operation
    Space Complexity: O(1) - Returns created record
    """
    try:
        response = supabase.table("user_profiles").insert(profile.model_dump()).execute()
        
        if not response.data or len(response.data) == 0:
            raise ValidationError("Failed to create profile")
        
        return UserProfileResponse(**response.data[0])
    except ValidationError:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error creating profile: {str(e)}")


@router.put("/{user_id}", response_model=UserProfileResponse)
async def update_profile(
    user_id: str, 
    profile_update: UserProfileUpdate, 
    supabase: Client = Depends(get_supabase_client)
):
    """
    Update user profile
    Time Complexity: O(1) - Single update operation
    Space Complexity: O(1) - Returns updated record
    Optimization: Filters None values before update
    """
    try:
        # Remove None values to avoid unnecessary updates
        update_data = {
            k: v for k, v in profile_update.model_dump().items() 
            if v is not None
        }
        
        if not update_data:
            raise ValidationError("No fields to update")
        
        response = (
            supabase.table("user_profiles")
            .update(update_data)
            .eq("user_id", user_id)
            .execute()
        )
        
        if not response.data or len(response.data) == 0:
            raise NotFoundError("User profile", user_id)
        
        return UserProfileResponse(**response.data[0])
    except (NotFoundError, ValidationError):
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating profile: {str(e)}")


@router.post("/{user_id}/upload-resume")
async def upload_resume(
    user_id: str,
    file: UploadFile = File(...),
    ocr: bool = Query(False, description="Enable OCR mode for LaTeX/scanned PDFs"),
    supabase: Client = Depends(get_supabase_client)
):
    """
    Upload resume and extract skills/experience
    Time Complexity: O(n) where n = file size (read/write operations)
    Space Complexity: O(n) - File content in memory + temp file
    Optimization: 
    - Uses utility functions for file operations
    - Validates file type early
    - Cleans up temp files in finally block
    - Supports files up to 2MB
    """
    temp_file_path: Optional[str] = None
    
    try:
        # Log incoming request
        logger.info(f"[UPLOAD] Received upload request for user: {user_id}")
        logger.info(f"[UPLOAD] Filename: {file.filename}")
        logger.info(f"[UPLOAD] Content type: {file.content_type}")
        
        # Validate file type by extension
        file_extension = extract_file_extension(file.filename or "")
        logger.info(f"[UPLOAD] Extracted extension: {file_extension}")
        
        if not file_extension:
            logger.error(f"[UPLOAD] No file extension found in filename: {file.filename}")
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "error": "Invalid file type. Only PDF and DOCX files are supported.",
                    "session_id": str(uuid.uuid4())
                }
            )
        
        if not validate_file_type(file_extension):
            logger.error(f"[UPLOAD] Invalid file extension: {file_extension}")
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "error": f"Invalid file type: {file_extension}. Only PDF and DOCX files are supported.",
                    "session_id": str(uuid.uuid4())
                }
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
                return JSONResponse(
                    status_code=400,
                    content={
                        "success": False,
                        "error": "Invalid file type. Only PDF and DOCX files are supported."
                    }
                )
        
        # Read file content (up to 2GB)
        # FastAPI UploadFile.read() automatically reads from the beginning
        # No need for seek(0) - it can cause issues with UploadFile objects
        logger.info(f"[UPLOAD] Reading file content...")
        file_content = await file.read()
        logger.info(f"[UPLOAD] File read successfully: {file.filename}, size: {len(file_content)} bytes")
        
        # Verify file is actually a PDF or DOCX by checking magic bytes
        if file_extension == '.pdf':
            if not file_content.startswith(b'%PDF'):
                logger.error(f"[UPLOAD] File does not have PDF magic bytes. First 20 bytes: {file_content[:20]}")
                session_id = str(uuid.uuid4())
                resume_analysis_cache[session_id] = {
                    "success": False,
                    "error": "The file is not a valid PDF. Please upload a valid PDF file.",
                    "name": None,
                    "email": None,
                    "skills": [],
                    "experience_level": "Not specified"
                }
                return JSONResponse(
                    status_code=400,
                    content={
                        "success": False,
                        "error": "The file is not a valid PDF. Please upload a valid PDF file.",
                        "session_id": session_id
                    }
                )
        elif file_extension in ['.docx', '.doc']:
            # DOCX files start with PK (ZIP format)
            if not (file_content.startswith(b'PK') or file_content.startswith(b'\xd0\xcf\x11\xe0')):
                logger.error(f"[UPLOAD] File does not have DOCX magic bytes. First 20 bytes: {file_content[:20]}")
                session_id = str(uuid.uuid4())
                resume_analysis_cache[session_id] = {
                    "success": False,
                    "error": "The file is not a valid DOCX document. Please upload a valid DOCX file.",
                    "name": None,
                    "email": None,
                    "skills": [],
                    "experience_level": "Not specified"
                }
                return JSONResponse(
                    status_code=400,
                    content={
                        "success": False,
                        "error": "The file is not a valid DOCX document. Please upload a valid DOCX file.",
                        "session_id": session_id
                    }
                )
        
        # Validate file size (max 2GB)
        max_size = 2 * 1024 * 1024 * 1024  # 2GB in bytes
        if len(file_content) > max_size:
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "error": "File size exceeds 2GB limit. Please upload a smaller file.",
                    "session_id": str(uuid.uuid4())  # Generate session_id even on error for redirect
                }
            )
        
        # Validate file is not empty
        if len(file_content) == 0:
            session_id = str(uuid.uuid4())
            # Store error in cache for frontend to display
            resume_analysis_cache[session_id] = {
                "success": False,
                "error": "The uploaded file is empty. Please upload a valid resume file.",
                "name": None,
                "email": None,
                "skills": [],
                "experience_level": "Not specified"
            }
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "error": "The uploaded file is empty. Please upload a valid resume file.",
                    "session_id": session_id
                }
            )
        
        # Save to temporary file for parsing
        logger.info(f"[UPLOAD] Saving file: {file.filename}, extension: {file_extension}, size: {len(file_content)} bytes")
        temp_file_path = await save_temp_file(file_content, file_extension)
        logger.info(f"[UPLOAD] Temp file saved to: {temp_file_path}")
        
        # Validate temp file was created and has content
        if not temp_file_path or not os.path.exists(temp_file_path):
            print(f"[ERROR] Temp file not created or doesn't exist: {temp_file_path}")
            session_id = str(uuid.uuid4())
            resume_analysis_cache[session_id] = {
                "success": False,
                "error": "Failed to save file for processing. Please try again.",
                "name": None,
                "email": None,
                "skills": [],
                "experience_level": "Not specified"
            }
            return JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "error": "Failed to save file for processing. Please try again.",
                    "session_id": session_id
                }
            )
        
        # Verify file size matches
        temp_file_size = os.path.getsize(temp_file_path)
        print(f"[DEBUG] Temp file size: {temp_file_size} bytes (original: {len(file_content)} bytes)")
        if temp_file_size != len(file_content):
            print(f"[ERROR] File size mismatch! Temp: {temp_file_size}, Original: {len(file_content)}")
            session_id = str(uuid.uuid4())
            resume_analysis_cache[session_id] = {
                "success": False,
                "error": "File was not saved correctly. Please try again.",
                "name": None,
                "email": None,
                "skills": [],
                "experience_level": "Not specified"
            }
            return JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "error": "File was not saved correctly. Please try again.",
                    "session_id": session_id
                }
            )
        
        # Parse resume using robust parser utility
        parsed_data = None
        
        try:
            logger.info(f"[UPLOAD] Starting parsing with extension: {file_extension}")
            # Use new robust parser utility
            if file_extension == '.pdf':
                logger.info(f"[UPLOAD] Parsing PDF with OCR fallback enabled")
                # Pass OCR mode flag (defaults to True for automatic fallback)
                parsed_data = parse_pdf(temp_file_path, use_ocr_fallback=True)
                logger.info(f"[UPLOAD] PDF parsing completed successfully")
            elif file_extension in ['.docx', '.doc']:
                logger.info(f"[UPLOAD] Parsing DOCX")
                parsed_data = parse_docx(temp_file_path)
                logger.info(f"[UPLOAD] DOCX parsing completed successfully")
            else:
                raise ValueError(f"Unsupported file extension: {file_extension}")
            
            # Map to expected format
            mapped_data = {
                "name": parsed_data.get("name"),
                "email": parsed_data.get("email"),
                "skills": parsed_data.get("skills", []),
                "experience_level": parsed_data.get("experience", "Not specified"),
                "keywords": {},
                "text_length": parsed_data.get("text_length", 0)
            }
            
            parsed_data = mapped_data
            
        except ImportError as import_error:
            # Missing parsing library
            error_msg = str(import_error)
            print(f"[ERROR] Missing parsing library: {import_error}")
            user_error = f"Resume parsing library not installed. {str(import_error)}"
            session_id = str(uuid.uuid4())
            resume_analysis_cache[session_id] = {
                "success": False,
                "error": user_error,
                "name": None,
                "email": None,
                "skills": [],
                "experience_level": "Not specified"
            }
            return JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "error": user_error,
                    "session_id": session_id
                }
            )
        except ValueError as value_error:
            # File format or content issues
            error_msg = str(value_error)
            error_msg_lower = error_msg.lower()
            print(f"[ERROR] Parsing failed (ValueError): {value_error}")
            
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
            
            session_id = str(uuid.uuid4())
            resume_analysis_cache[session_id] = {
                "success": False,
                "error": user_error,
                "name": None,
                "email": None,
                "skills": [],
                "experience_level": "Not specified"
            }
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "error": user_error,
                    "session_id": session_id
                }
            )
        except Exception as parse_error:
            # Other unexpected errors
            error_msg = str(parse_error).lower()
            print(f"[ERROR] Unexpected parsing error: {parse_error}")
            if "not installed" in error_msg or "import" in error_msg:
                user_error = "Resume parsing library not installed. Please install: pip install pdfminer.six pdfplumber python-docx PyMuPDF"
            else:
                user_error = f"Failed to parse resume: {str(parse_error)}"
            
            session_id = str(uuid.uuid4())
            resume_analysis_cache[session_id] = {
                "success": False,
                "error": user_error,
                "name": None,
                "email": None,
                "skills": [],
                "experience_level": "Not specified"
            }
            return JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "error": user_error,
                    "session_id": session_id
                }
            )
        
        # Upload to Supabase Storage
        storage_path = f"resumes/{user_id}/{file.filename}"
        resume_url = None
        try:
            supabase.storage.from_("resumes").upload(
                storage_path,
                file_content,
                file_options={"content-type": file.content_type or "application/pdf"}
            )
            # Get public URL if upload succeeded
            try:
                public_url_response = supabase.storage.from_("resumes").get_public_url(storage_path)
                resume_url = (
                    public_url_response 
                    if isinstance(public_url_response, str) 
                    else str(public_url_response)
                )
            except Exception:
                # Fallback: construct URL manually
                try:
                    resume_url = f"{settings.supabase_url}/storage/v1/object/public/resumes/{storage_path}"
                except Exception:
                    resume_url = None
        except Exception as storage_error:
            # If storage upload fails, still return parsed data
            logger.warning(f"[UPLOAD] Storage upload failed for user {user_id}: {storage_error}")
            resume_url = None
        
        # Update or create user profile with extracted data
        profile_data = {
            "user_id": user_id,
            "resume_url": resume_url,
            "skills": parsed_data.get("skills", []),
            "experience_level": parsed_data.get("experience_level", "Not specified")
        }
        
        # Add name and email if available
        if parsed_data.get("name"):
            profile_data["name"] = parsed_data["name"]
        if parsed_data.get("email"):
            profile_data["email"] = parsed_data["email"]
        
        # Check if profile exists (optimized: single query)
        # Don't fail if user profile lookup fails - we can still process the resume
        existing_profile = None
        try:
            existing_profile = await get_user_profile(supabase, user_id)
        except Exception as profile_lookup_error:
            logger.warning(f"[UPLOAD] Could not fetch existing profile for user {user_id}: {profile_lookup_error}. Will create new profile.")
            existing_profile = None
        
        try:
            if existing_profile:
                # Update existing profile
                response = (
                    supabase.table("user_profiles")
                    .update(profile_data)
                    .eq("user_id", user_id)
                    .execute()
                )
            else:
                # Create new profile
                response = (
                    supabase.table("user_profiles")
                    .insert(profile_data)
                    .execute()
                )
            
            # Generate a session ID for the analysis
            analysis_session_id = str(uuid.uuid4())
            
            # Store parsed data in cache (include user_id for later updates)
            resume_analysis_cache[analysis_session_id] = {
                "user_id": user_id,  # Store user_id for profile updates
                "name": parsed_data.get("name"),
                "email": parsed_data.get("email"),
                "skills": parsed_data.get("skills", []),
                "experience_level": parsed_data.get("experience_level", "Not specified"),
                "keywords": parsed_data.get("keywords", {}),
                "text_length": parsed_data.get("text_length", 0),
                "created_at": datetime.now().isoformat()
            }
            
            return JSONResponse(
                status_code=200,
                content={
                    "success": True,
                    "message": "Resume parsed successfully.",
                    "session_id": analysis_session_id,
                    "name": parsed_data.get("name"),
                    "email": parsed_data.get("email"),
                    "skills": parsed_data.get("skills", []),
                    "experience_level": parsed_data.get("experience_level", "Unknown"),
                    "keywords": parsed_data.get("keywords", {}),
                    "text_length": parsed_data.get("text_length", 0),
                    "resume_url": resume_url
                }
            )
        except Exception as db_error:
            # Database error - still return extracted data with session
            analysis_session_id = str(uuid.uuid4())
            
            resume_analysis_cache[analysis_session_id] = {
                "user_id": user_id,  # Store user_id for profile updates
                "name": parsed_data.get("name"),
                "email": parsed_data.get("email"),
                "skills": parsed_data.get("skills", []),
                "experience_level": parsed_data.get("experience_level", "Unknown"),
                "keywords": parsed_data.get("keywords", {}),
                "text_length": parsed_data.get("text_length", 0),
                "created_at": datetime.now().isoformat()
            }
            
            return JSONResponse(
                status_code=200,
                content={
                    "success": True,
                    "message": "Resume processed successfully (profile update failed)",
                    "session_id": analysis_session_id,
                    "name": parsed_data.get("name"),
                    "email": parsed_data.get("email"),
                    "skills": parsed_data["skills"],
                    "experience_level": parsed_data["experience_level"],
                    "keywords": parsed_data.get("keywords", {}),
                    "text_length": parsed_data.get("text_length", 0),
                    "resume_url": resume_url,
                    "warning": f"Profile update failed: {str(db_error)}"
                }
            )
    except Exception as e:
        import traceback
        error_message = str(e)
        error_traceback = traceback.format_exc()
        
        # Log the full error for debugging
        logger.error(f"[UPLOAD] Unexpected error in upload_resume: {error_message}")
        logger.error(f"[UPLOAD] Traceback: {error_traceback}")
        
        # Provide user-friendly error messages
        session_id = str(uuid.uuid4())
        
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
        
        # Store error in cache for frontend
        resume_analysis_cache[session_id] = {
            "success": False,
            "error": error_message,
            "name": None,
            "email": None,
            "skills": [],
            "experience_level": "Not specified"
        }
        
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": error_message,
                "session_id": session_id
            }
        )
    finally:
        # Clean up temporary file
        if temp_file_path:
            cleanup_temp_file(temp_file_path)
