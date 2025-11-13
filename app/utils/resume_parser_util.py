"""
Robust Resume Parser Utility
Handles PDF and DOCX parsing with multiple fallback libraries
"""

import os
import re
import logging
import platform
from typing import Dict, List, Optional, Any
from pathlib import Path

# Setup logger
logger = logging.getLogger(__name__)

# PDF Parsing Libraries
PYMUPDF_AVAILABLE = False
PYPDF2_AVAILABLE = False
PDFPLUMBER_AVAILABLE = False
PDFMINER_AVAILABLE = False

try:
    import fitz  # PyMuPDF
    try:
        test_doc = fitz.open()
        test_doc.close()
        PYMUPDF_AVAILABLE = True
    except Exception:
        PYMUPDF_AVAILABLE = False
except (ImportError, Exception):
    # Catch all exceptions including DLL load errors on Windows
    PYMUPDF_AVAILABLE = False
    pass

try:
    import PyPDF2
    PYPDF2_AVAILABLE = True
except ImportError:
    pass

try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    pass

try:
    from pdfminer.high_level import extract_text as pdfminer_extract
    PDFMINER_AVAILABLE = True
except ImportError:
    pass

# DOCX Parsing
DOCX_AVAILABLE = False
try:
    from docx import Document
    DOCX_AVAILABLE = True
except ImportError:
    pass

# OCR Libraries
OCR_AVAILABLE = False
TESSERACT_PATH = None

def configure_tesseract():
    """
    Automatically detect and configure Tesseract OCR path based on the operating system.
    Supports Windows, Linux, and macOS.
    
    Returns:
        bool: True if Tesseract is configured and available, False otherwise
    """
    global OCR_AVAILABLE, TESSERACT_PATH
    
    try:
        import pytesseract
    except ImportError:
        logger.warning("[RESUME_PARSER] pytesseract not installed. OCR fallback will not be available.")
        logger.warning("[RESUME_PARSER] Install with: pip install pytesseract")
        OCR_AVAILABLE = False
        return False
    
    system = platform.system()
    paths = {
        "Windows": [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            os.path.expanduser(r"~\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"),
        ],
        "Linux": [
            "/usr/bin/tesseract",
            "/usr/local/bin/tesseract",
        ],
        "Darwin": [  # macOS
            "/opt/homebrew/bin/tesseract",
            "/usr/local/bin/tesseract",
            "/opt/local/bin/tesseract",  # MacPorts
        ]
    }
    
    possible_paths = paths.get(system, [])
    
    # Try to find Tesseract in common paths
    tesseract_path = None
    for path in possible_paths:
        if os.path.exists(path):
            tesseract_path = path
            pytesseract.pytesseract.tesseract_cmd = path
            TESSERACT_PATH = path
            logger.info(f"[TESSERACT] Configured path: {path}")
            break
    
    # If not found in common paths, try to use system PATH
    if not tesseract_path:
        try:
            # This will raise an exception if Tesseract is not in PATH
            pytesseract.get_tesseract_version()
            # If we get here, Tesseract is in PATH
            logger.info("[TESSERACT] Found Tesseract in system PATH")
            OCR_AVAILABLE = True
            return True
        except Exception:
            # Tesseract not found in PATH either
            pass
    
    # Test if Tesseract is available at configured path
    if tesseract_path:
        try:
            pytesseract.get_tesseract_version()
            OCR_AVAILABLE = True
            logger.info("[RESUME_PARSER] OCR enabled and ready.")
            return True
        except Exception as e:
            logger.error(f"[TESSERACT] Tesseract found at {tesseract_path} but failed to initialize: {str(e)}")
            OCR_AVAILABLE = False
            return False
    else:
        # Tesseract not found
        install_url = "https://github.com/UB-Mannheim/tesseract/wiki"
        if system == "Windows":
            logger.warning(f"[TESSERACT] OCR engine not found for {system}. Please install it from: {install_url}")
        elif system == "Linux":
            logger.warning(f"[TESSERACT] OCR engine not found for {system}. Install with: sudo apt-get install tesseract-ocr")
        elif system == "Darwin":
            logger.warning(f"[TESSERACT] OCR engine not found for {system}. Install with: brew install tesseract")
        else:
            logger.warning(f"[TESSERACT] OCR engine not found for {system}. Please install Tesseract OCR manually.")
        OCR_AVAILABLE = False
        return False

# Initialize OCR libraries
try:
    import pytesseract
    from pdf2image import convert_from_path
    from PIL import Image
    
    # Configure Tesseract automatically
    configure_tesseract()
except ImportError:
    OCR_AVAILABLE = False
    logger.warning("[RESUME_PARSER] OCR libraries not installed. OCR fallback will not be available.")
    logger.warning("[RESUME_PARSER] Install with: pip install pytesseract pdf2image pillow")


def is_text_meaningful(text: str, min_length: int = 50) -> bool:
    """
    Check if extracted text is meaningful (not just metadata/page numbers).
    LaTeX PDFs often extract only page numbers or metadata, which we want to treat as 'no text'.
    
    Returns True if text appears to be meaningful resume content, False otherwise.
    """
    if not text or len(text.strip()) < min_length:
        return False
    
    # Check if text contains mostly numbers, whitespace, or special characters (likely metadata)
    text_stripped = text.strip()
    
    # Count alphanumeric characters (letters and numbers)
    alphanumeric_count = sum(1 for c in text_stripped if c.isalnum())
    total_chars = len(text_stripped)
    
    if total_chars == 0:
        return False
    
    # If less than 30% of text is alphanumeric, it's probably not meaningful
    alphanumeric_ratio = alphanumeric_count / total_chars
    if alphanumeric_ratio < 0.3:
        return False
    
    # Check for common resume keywords (if present, text is likely meaningful)
    resume_keywords = [
        'experience', 'education', 'skills', 'project', 'work', 'job',
        'university', 'college', 'degree', 'email', 'phone', 'address',
        'python', 'java', 'javascript', 'react', 'developer', 'engineer',
        'software', 'programming', 'technology', 'certification', 'achievement'
    ]
    text_lower = text.lower()
    keyword_count = sum(1 for keyword in resume_keywords if keyword in text_lower)
    
    # If we have at least 2 resume keywords, text is likely meaningful
    if keyword_count >= 2:
        return True
    
    # If text is long enough and has reasonable alphanumeric ratio, consider it meaningful
    if len(text_stripped) >= min_length and alphanumeric_ratio >= 0.5:
        return True
    
    return False


def extract_text_with_ocr(pdf_path: str) -> Optional[str]:
    """
    Extract text using OCR for PDFs without selectable text layer.
    Useful for LaTeX-generated PDFs, scanned documents, or image-based PDFs.
    """
    if not OCR_AVAILABLE:
        logger.warning("[OCR Parser] OCR not available - skipping OCR extraction")
        return None
    
    try:
        logger.info("[OCR Parser] Starting OCR extraction...")
        
        # Check if poppler is available (required for pdf2image)
        try:
            # Convert PDF pages to images
            images = convert_from_path(pdf_path, dpi=300)  # Higher DPI for better accuracy
            logger.info(f"[OCR Parser] Converted PDF to {len(images)} image(s)")
        except Exception as poppler_error:
            error_msg = str(poppler_error).lower()
            if "poppler" in error_msg or "pdftoppm" in error_msg:
                logger.error("[OCR Parser] Poppler not installed. On Windows, download from: https://github.com/oschwartz10612/poppler-windows/releases/")
                logger.error("[OCR Parser] On Linux: sudo apt-get install poppler-utils")
                logger.error("[OCR Parser] On macOS: brew install poppler")
            raise
        
        text_parts = []
        for page_num, page_image in enumerate(images):
            try:
                # Perform OCR on each page
                page_text = pytesseract.image_to_string(page_image, lang='eng')
                if page_text and page_text.strip():
                    text_parts.append(page_text.strip())
                    logger.info(f"[OCR Parser] Extracted {len(page_text)} chars from page {page_num + 1}")
            except Exception as page_error:
                logger.warning(f"[OCR Parser] Failed to OCR page {page_num + 1}: {str(page_error)}")
                continue
        
        if text_parts:
            full_text = "\n\n".join(text_parts)
            logger.info(f"[OCR Parser] OCR SUCCESS - Extracted {len(full_text)} characters total")
            return full_text
        else:
            logger.warning("[OCR Parser] OCR completed but no text was extracted")
            return None
            
    except Exception as e:
        logger.error(f"[OCR Parser] OCR extraction failed: {str(e)}")
        return None


def parse_pdf(file_path: str, use_ocr_fallback: bool = True) -> Dict[str, Any]:
    """
    Parse PDF file with multiple fallback libraries
    Returns structured data with name, email, skills, experience
    
    Improved to better handle LaTeX-generated PDFs by:
    1. Checking if extracted text is meaningful (not just metadata)
    2. Automatically trying OCR if text is not meaningful
    3. Better error messages for LaTeX PDFs
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"PDF file not found: {file_path}")
    
    file_size = os.path.getsize(file_path)
    logger.info(f"[RESUME_PARSER] Starting PDF parsing: {file_path} (size: {file_size} bytes)")
    
    # Check library availability
    available_parsers = []
    if PYMUPDF_AVAILABLE:
        available_parsers.append("PyMuPDF")
    if PDFPLUMBER_AVAILABLE:
        available_parsers.append("pdfplumber")
    if PDFMINER_AVAILABLE:
        available_parsers.append("pdfminer.six")
    if PYPDF2_AVAILABLE:
        available_parsers.append("PyPDF2")
    
    logger.info(f"[RESUME_PARSER] Available PDF parsers: {', '.join(available_parsers) if available_parsers else 'NONE'}")
    
    if not available_parsers:
        raise ImportError("No PDF parsing libraries are installed. Please install: pip install PyMuPDF pdfplumber pdfminer.six PyPDF2")
    
    text = None
    parser_used = None
    last_error = None
    text_is_meaningful = False
    
    # Try PyMuPDF first (most reliable)
    if PYMUPDF_AVAILABLE:
        try:
            logger.debug(f"[RESUME_PARSER] Attempting PyMuPDF parsing...")
            doc = fitz.open(file_path)
            text_parts = []
            for page_num, page in enumerate(doc):
                try:
                    page_text = page.get_text()
                    if page_text:
                        text_parts.append(page_text)
                        logger.debug(f"[RESUME_PARSER] PyMuPDF extracted {len(page_text)} chars from page {page_num + 1}")
                except Exception as page_error:
                    logger.warning(f"[RESUME_PARSER] PyMuPDF failed on page {page_num + 1}: {str(page_error)}")
            doc.close()
            text = "\n".join(text_parts)
            
            # Check if text is meaningful (not just metadata)
            if text:
                text_is_meaningful = is_text_meaningful(text, min_length=50)
                if text_is_meaningful:
                    parser_used = "PyMuPDF"
                    logger.info(f"[RESUME_PARSER] PyMuPDF SUCCESS - Extracted {len(text)} meaningful characters")
                else:
                    logger.warning(f"[RESUME_PARSER] PyMuPDF extracted {len(text)} chars but text appears to be metadata only (not meaningful)")
                    text = None  # Reset to trigger fallback
        except Exception as e:
            last_error = str(e)
            logger.error(f"[RESUME_PARSER] PyMuPDF failed: {str(e)}")
    
    # Fallback to pdfplumber
    if not text or not text_is_meaningful:
        if PDFPLUMBER_AVAILABLE:
            try:
                logger.debug(f"[RESUME_PARSER] Attempting pdfplumber parsing...")
                with pdfplumber.open(file_path) as pdf:
                    text_parts = []
                    for page_num, page in enumerate(pdf.pages):
                        try:
                            page_text = page.extract_text()
                            if page_text:
                                text_parts.append(page_text)
                                logger.debug(f"[RESUME_PARSER] pdfplumber extracted {len(page_text)} chars from page {page_num + 1}")
                        except Exception as page_error:
                            logger.warning(f"[RESUME_PARSER] pdfplumber failed on page {page_num + 1}: {str(page_error)}")
                    text = "\n".join(text_parts)
                
                if text:
                    text_is_meaningful = is_text_meaningful(text, min_length=50)
                    if text_is_meaningful:
                        parser_used = "pdfplumber"
                        logger.info(f"[RESUME_PARSER] pdfplumber SUCCESS - Extracted {len(text)} meaningful characters")
                    else:
                        logger.warning(f"[RESUME_PARSER] pdfplumber extracted {len(text)} chars but text appears to be metadata only")
                        text = None
            except Exception as e:
                last_error = str(e)
                logger.error(f"[RESUME_PARSER] pdfplumber failed: {str(e)}")
    
    # Fallback to pdfminer.six
    if not text or not text_is_meaningful:
        if PDFMINER_AVAILABLE:
            try:
                logger.debug(f"[RESUME_PARSER] Attempting pdfminer.six parsing...")
                text = pdfminer_extract(file_path)
                if text:
                    text_is_meaningful = is_text_meaningful(text, min_length=50)
                    if text_is_meaningful:
                        parser_used = "pdfminer.six"
                        logger.info(f"[RESUME_PARSER] pdfminer.six SUCCESS - Extracted {len(text)} meaningful characters")
                    else:
                        logger.warning(f"[RESUME_PARSER] pdfminer.six extracted {len(text)} chars but text appears to be metadata only")
                        text = None
            except Exception as e:
                last_error = str(e)
                logger.error(f"[RESUME_PARSER] pdfminer.six failed: {str(e)}")
    
    # Fallback to PyPDF2
    if not text or not text_is_meaningful:
        if PYPDF2_AVAILABLE:
            try:
                logger.debug(f"[RESUME_PARSER] Attempting PyPDF2 parsing...")
                with open(file_path, 'rb') as pdf_file:
                    pdf_reader = PyPDF2.PdfReader(pdf_file)
                    text_parts = []
                    for page_num, page in enumerate(pdf_reader.pages):
                        try:
                            page_text = page.extract_text()
                            if page_text:
                                text_parts.append(page_text)
                                logger.debug(f"[RESUME_PARSER] PyPDF2 extracted {len(page_text)} chars from page {page_num + 1}")
                        except Exception as page_error:
                            logger.warning(f"[RESUME_PARSER] PyPDF2 failed on page {page_num + 1}: {str(page_error)}")
                    text = "\n".join(text_parts)
                
                if text:
                    text_is_meaningful = is_text_meaningful(text, min_length=50)
                    if text_is_meaningful:
                        parser_used = "PyPDF2"
                        logger.info(f"[RESUME_PARSER] PyPDF2 SUCCESS - Extracted {len(text)} meaningful characters")
                    else:
                        logger.warning(f"[RESUME_PARSER] PyPDF2 extracted {len(text)} chars but text appears to be metadata only")
                        text = None
            except Exception as e:
                last_error = str(e)
                logger.error(f"[RESUME_PARSER] PyPDF2 failed: {str(e)}")
    
    # Final validation - try OCR if no meaningful text was extracted
    if not text or not text_is_meaningful:
        if use_ocr_fallback:
            if OCR_AVAILABLE:
                logger.info("[RESUME_PARSER] LaTeX-based PDF detected - running OCR to extract text...")
                logger.info("[RESUME_PARSER] No meaningful text extracted with standard parsers. Attempting OCR fallback...")
                ocr_text = extract_text_with_ocr(file_path)
                if ocr_text and is_text_meaningful(ocr_text, min_length=50):
                    text = ocr_text
                    parser_used = "OCR (Tesseract)"
                    text_is_meaningful = True
                    logger.info(f"[RESUME_PARSER] OCR fallback SUCCESS - Extracted {len(text)} meaningful characters")
                else:
                    logger.warning("[RESUME_PARSER] OCR fallback also failed to extract meaningful text")
            else:
                logger.warning("[RESUME_PARSER] LaTeX-based PDF detected but OCR fallback requested - Tesseract OCR is not installed. This PDF requires OCR.")
        
        # If still no meaningful text after OCR, raise error
        if not text or not text_is_meaningful:
            error_details = []
            if not available_parsers:
                error_details.append("No parsing libraries available")
            else:
                error_details.append(f"All parsers failed (tried: {', '.join(available_parsers)}")
                if use_ocr_fallback:
                    if OCR_AVAILABLE:
                        error_details.append("OCR fallback attempted")
                    else:
                        error_details.append("OCR fallback not available - Tesseract not installed")
                error_details.append(")")
            if last_error:
                error_details.append(f"Last error: {last_error}")
            
            logger.warning(f"[RESUME_PARSER] FAILED - No meaningful text found. {'. '.join(error_details)}")
            
            # Provide more specific error message for LaTeX/vector PDFs
            if use_ocr_fallback and not OCR_AVAILABLE:
                raise ValueError("LATEX_PDF_OCR_REQUIRED: LaTeX-based PDF detected - could not extract meaningful text from PDF. This appears to be a LaTeX-generated PDF (vector-based text) which requires OCR. Please install Tesseract OCR to enable LaTeX PDF support. See OCR_SETUP.md for installation instructions.")
            elif OCR_AVAILABLE and use_ocr_fallback:
                raise ValueError("LATEX_PDF_OCR_FAILED: LaTeX-based PDF detected - could not extract meaningful text from PDF. The file might be a LaTeX-generated PDF (vector-based), image-based (scanned), corrupted, or password-protected. OCR was attempted but failed. Please ensure your PDF contains readable text or try exporting as PDF/A from Overleaf.")
            else:
                raise ValueError("LATEX_PDF_NO_TEXT: LaTeX-based PDF detected - could not extract meaningful text from PDF. The file might be a LaTeX-generated PDF (vector-based), image-based (scanned), corrupted, or password-protected. For LaTeX-generated PDFs, OCR support is required. Please install Tesseract OCR or try exporting as PDF/A from Overleaf.")
    
    logger.info(f"[RESUME_PARSER] PDF parsing completed successfully using {parser_used}")
    return extract_resume_data(text)


def parse_docx(file_path: str) -> Dict[str, Any]:
    """
    Parse DOCX file
    Returns structured data with name, email, skills, experience
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"DOCX file not found: {file_path}")
    
    file_size = os.path.getsize(file_path)
    logger.info(f"[RESUME_PARSER] Starting DOCX parsing: {file_path} (size: {file_size} bytes)")
    
    if not DOCX_AVAILABLE:
        logger.error("[RESUME_PARSER] python-docx is not installed")
        raise ImportError("python-docx is not installed. Install with: pip install python-docx")
    
    try:
        logger.debug(f"[RESUME_PARSER] Attempting DOCX parsing with python-docx...")
        doc = Document(file_path)
        text_parts = []
        
        # Extract from paragraphs
        paragraph_count = 0
        for paragraph in doc.paragraphs:
            if paragraph.text:
                text_parts.append(paragraph.text)
                paragraph_count += 1
        logger.debug(f"[RESUME_PARSER] Extracted text from {paragraph_count} paragraphs")
        
        # Extract from tables
        table_count = 0
        for table in doc.tables:
            table_count += 1
            for row in table.rows:
                for cell in row.cells:
                    if cell.text:
                        text_parts.append(cell.text)
        logger.debug(f"[RESUME_PARSER] Extracted text from {table_count} tables")
        
        text = "\n".join(text_parts)
        logger.info(f"[RESUME_PARSER] DOCX parsing extracted {len(text)} characters")
        
        if not text or len(text.strip()) < 10:
            logger.warning(f"[RESUME_PARSER] DOCX file appears empty - only {len(text.strip())} characters extracted")
            raise ValueError("DOCX file appears to be empty or contains no extractable text. Please ensure your document contains text content.")
        
        logger.info(f"[RESUME_PARSER] DOCX parsing completed successfully")
        return extract_resume_data(text)
        
    except ImportError:
        raise  # Re-raise ImportError as-is
    except ValueError:
        raise  # Re-raise ValueError as-is
    except Exception as e:
        error_msg = str(e).lower()
        logger.error(f"[RESUME_PARSER] DOCX parsing failed: {str(e)}")
        if "not a docx" in error_msg or "invalid" in error_msg or "corrupt" in error_msg:
            raise ValueError("The file is not a valid DOCX document")
        raise Exception(f"Error parsing DOCX: {str(e)}")


def extract_resume_data(text: str) -> Dict[str, Any]:
    """
    Extract structured data from resume text
    Returns: {name, email, skills, experience}
    """
    text_lower = text.lower()
    
    # Extract name (usually in first few lines)
    name = extract_name(text)
    
    # Extract email
    email = extract_email(text)
    
    # Extract skills
    skills = extract_skills(text, text_lower)
    
    # Extract experience
    experience = extract_experience(text, text_lower)
    
    return {
        "name": name,
        "email": email,
        "skills": skills,
        "experience": experience,
        "text_length": len(text)
    }


def extract_name(text: str) -> Optional[str]:
    """Extract name from resume (usually at the top)"""
    lines = text.split('\n')[:15]  # Check first 15 lines
    for line in lines:
        line = line.strip()
        if 3 < len(line) < 50:  # Reasonable name length
            # Check if it looks like a name
            if re.match(r'^[A-Za-z\s\.\-]+$', line):
                # Exclude common non-name patterns
                excluded = ['email', 'phone', 'address', 'resume', 'cv', 'linkedin', 'github', 'objective', 'summary']
                if not any(word.lower() in excluded for word in line.split()):
                    if '@' not in line and not re.match(r'^[\d\s\-\+\(\)]+$', line):
                        return line.title()
    return None


def extract_email(text: str) -> Optional[str]:
    """Extract email address using regex"""
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    matches = re.findall(email_pattern, text)
    if matches:
        return matches[0].lower()
    return None


def extract_skills(text: str, text_lower: str) -> List[str]:
    """Extract skills from resume text"""
    skill_keywords = [
        # Programming Languages
        'python', 'java', 'javascript', 'typescript', 'c++', 'c#', 'go', 'rust', 'php', 'ruby',
        'swift', 'kotlin', 'scala', 'r', 'matlab', 'sql', 'html', 'css', 'sass', 'less',
        # Frameworks & Libraries
        'react', 'angular', 'vue', 'node.js', 'express', 'django', 'flask', 'fastapi',
        'spring', 'laravel', 'rails', 'tensorflow', 'pytorch', 'pandas', 'numpy',
        # Tools & Technologies
        'docker', 'kubernetes', 'aws', 'azure', 'gcp', 'git', 'jenkins', 'ci/cd',
        'mongodb', 'postgresql', 'mysql', 'redis', 'elasticsearch', 'kafka',
        # Other
        'agile', 'scrum', 'devops', 'microservices', 'rest api', 'graphql', 'supabase'
    ]
    
    found_skills = []
    for skill in skill_keywords:
        pattern = rf'\b{re.escape(skill)}\b'
        if re.search(pattern, text_lower, re.IGNORECASE):
            # Format skill name properly
            if '.' in skill:
                skill_formatted = skill.upper()
            elif skill == 'ci/cd':
                skill_formatted = 'CI/CD'
            else:
                skill_formatted = skill.title()
            
            if skill_formatted not in found_skills:
                found_skills.append(skill_formatted)
    
    return found_skills[:20]  # Limit to top 20


def extract_experience(text: str, text_lower: str) -> str:
    """Extract experience level or summary"""
    # Patterns for years of experience
    years_patterns = [
        r'\b(\d+)\s*(?:years?|yrs?|y\.?)\s*(?:of\s*)?experience',
        r'experience[:\s]+(\d+)\s*(?:years?|yrs?)',
        r'(\d+)\s*(?:years?|yrs?)\s*(?:in|of)',
    ]
    
    max_years = 0
    for pattern in years_patterns:
        matches = re.finditer(pattern, text_lower, re.IGNORECASE)
        for match in matches:
            try:
                years = int(match.group(1))
                max_years = max(max_years, years)
            except (IndexError, ValueError):
                continue
    
    if max_years > 0:
        return f"{max_years} years"
    
    # Check for keywords
    if re.search(r'fresher|fresh\s*graduate|no\s*experience|entry\s*level', text_lower):
        return "Fresher"
    elif re.search(r'senior|lead|principal|architect', text_lower):
        return "5+ years"
    elif re.search(r'mid|middle|intermediate', text_lower):
        return "2-4 years"
    elif re.search(r'junior|entry|associate', text_lower):
        return "1 year"
    
    return "Not specified"

