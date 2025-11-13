"""
Temporary test endpoint for resume parser verification
This will be removed after testing
"""

import os
import logging
from datetime import datetime
from fastapi import APIRouter, UploadFile, File
from fastapi.responses import JSONResponse
from app.utils.resume_parser_util import parse_pdf, parse_docx, OCR_AVAILABLE, PYMUPDF_AVAILABLE, PDFPLUMBER_AVAILABLE, PDFMINER_AVAILABLE, PYPDF2_AVAILABLE
from app.utils.file_utils import extract_file_extension, save_temp_file, cleanup_temp_file

router = APIRouter(prefix="/api", tags=["test"])

# Setup logger
logger = logging.getLogger(__name__)


@router.post("/test-resume-parse")
async def test_resume_parse(file: UploadFile = File(...)):
    """
    Test endpoint to verify resume parsing works correctly with full diagnostics.
    Returns which parser succeeded, text snippet, and structured fields.
    
    This endpoint will be removed after verification.
    """
    temp_file_path = None
    logs = []
    
    try:
        # Validate file type
        file_extension = extract_file_extension(file.filename or "")
        if file_extension not in ['.pdf', '.docx', '.doc']:
            return JSONResponse(
                status_code=400,
                content={
                    "status": "error",
                    "message": "Invalid file type. Only PDF and DOCX files are supported.",
                    "type": "InvalidFileType"
                }
            )
        
        # Read file content
        file_content = await file.read()
        file_size = len(file_content)
        logs.append(f"File uploaded: {file.filename}, size: {file_size} bytes")
        
        if file_size == 0:
            return JSONResponse(
                status_code=400,
                content={
                    "status": "error",
                    "message": "File is empty",
                    "type": "EmptyFile",
                    "logs": logs
                }
            )
        
        # Save to temporary file
        temp_file_path = await save_temp_file(file_content, file_extension)
        logs.append(f"Temp file saved: {temp_file_path}")
        
        # Track parser attempts
        parser_attempts = []
        parser_used = None
        raw_text = None
        
        # Parse based on file type
        if file_extension == '.pdf':
            # Check available parsers
            available_parsers = []
            if PYMUPDF_AVAILABLE:
                available_parsers.append("PyMuPDF")
            if PDFPLUMBER_AVAILABLE:
                available_parsers.append("pdfplumber")
            if PDFMINER_AVAILABLE:
                available_parsers.append("pdfminer.six")
            if PYPDF2_AVAILABLE:
                available_parsers.append("PyPDF2")
            
            logs.append(f"Available PDF parsers: {', '.join(available_parsers) if available_parsers else 'NONE'}")
            logs.append(f"OCR available: {OCR_AVAILABLE}")
            
            # Try parsing with OCR fallback enabled
            try:
                parsed_data = parse_pdf(temp_file_path, use_ocr_fallback=True)
                parser_used = "PDF parser (with OCR fallback if needed)"
                logs.append("PDF parsing succeeded")
            except Exception as parse_error:
                error_msg = str(parse_error)
                logs.append(f"PDF parsing failed: {error_msg}")
                
                # Try to determine which parser was attempted
                if "PyMuPDF" in error_msg or "fitz" in error_msg:
                    parser_attempts.append("PyMuPDF - failed")
                if "pdfplumber" in error_msg:
                    parser_attempts.append("pdfplumber - failed")
                if "pdfminer" in error_msg:
                    parser_attempts.append("pdfminer.six - failed")
                if "PyPDF2" in error_msg:
                    parser_attempts.append("PyPDF2 - failed")
                if "OCR" in error_msg or "Tesseract" in error_msg:
                    parser_attempts.append("OCR (Tesseract) - failed or not available")
                
                return JSONResponse(
                    status_code=400,
                    content={
                        "status": "error",
                        "message": f"No readable text — tried {', '.join(available_parsers)}. OCR: {'available' if OCR_AVAILABLE else 'not available'}. Error: {error_msg}",
                        "type": "NoText" if "LATEX_PDF" in error_msg or "no text" in error_msg.lower() else "ParseError",
                        "parser_attempts": parser_attempts,
                        "logs": logs
                    }
                )
        elif file_extension in ['.docx', '.doc']:
            try:
                parsed_data = parse_docx(temp_file_path)
                parser_used = "python-docx"
                logs.append("DOCX parsing succeeded")
            except Exception as parse_error:
                error_msg = str(parse_error)
                logs.append(f"DOCX parsing failed: {error_msg}")
                return JSONResponse(
                    status_code=400,
                    content={
                        "status": "error",
                        "message": f"DOCX parsing failed: {error_msg}",
                        "type": "ParseError",
                        "logs": logs
                    }
                )
        else:
            return JSONResponse(
                status_code=400,
                content={
                    "status": "error",
                    "message": f"Unsupported file extension: {file_extension}",
                    "type": "InvalidFileType",
                    "logs": logs
                }
            )
        
        # Extract parsed data
        name = parsed_data.get("name")
        email = parsed_data.get("email")
        skills = parsed_data.get("skills", [])
        experience = parsed_data.get("experience", "Not specified")
        text_length = parsed_data.get("text_length", 0)
        
        # Get text snippet (first 400 chars) - we need to extract raw text
        # Since parse_pdf/parse_docx don't return raw text, we'll note the length
        text_snippet = f"[Text length: {text_length} characters. Raw text not available in current implementation.]"
        
        logs.append(f"Parsed successfully - Name: {name}, Email: {email}, Skills: {len(skills)}, Experience: {experience}")
        
        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "parser_used": parser_used,
                "text_snippet": text_snippet,
                "text_length": text_length,
                "parsed": {
                    "name": name,
                    "email": email,
                    "skills": skills,
                    "experience": experience
                },
                "logs": logs
            }
        )
        
    except ImportError as e:
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"Missing parsing library: {str(e)}",
                "type": "MissingLibrary",
                "logs": logs
            }
        )
    except Exception as e:
        logger.exception("Unexpected error in test_resume_parse")
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"Unexpected error: {str(e)}",
                "type": "UnexpectedError",
                "logs": logs
            }
        )
    finally:
        # Cleanup temp file
        if temp_file_path:
            cleanup_temp_file(temp_file_path)
