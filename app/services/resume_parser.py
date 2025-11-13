"""
Resume parsing service using LangChain and PyMuPDF
Extracts skills and experience level from resume files
"""

import os
import tempfile
from typing import Dict, List, Optional, Any
from pathlib import Path
import re

# Try to import PyMuPDF, handle import errors and DLL errors gracefully
PYMUPDF_AVAILABLE = False
fitz = None
try:
    import fitz  # PyMuPDF
    # Test if it actually works (not just imported) - DLL might fail at runtime
    try:
        # Quick test: try to create an empty document
        test_doc = fitz.open()
        test_doc.close()
        PYMUPDF_AVAILABLE = True
    except Exception:
        # DLL error or other runtime error
        PYMUPDF_AVAILABLE = False
        fitz = None
except Exception as e:
    # Catch all exceptions including ImportError and DLL load errors on Windows
    PYMUPDF_AVAILABLE = False
    fitz = None

# Try to import python-docx, handle import errors gracefully
try:
    from docx import Document
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False
    Document = None

# Note: LangChain components are not currently used in this parser
# They are kept for potential future use

class ResumeParser:
    """Parse resume files and extract skills and experience"""
    
    def __init__(self):
        self.skill_keywords = [
            # Programming Languages
            'python', 'java', 'javascript', 'typescript', 'c++', 'c#', 'go', 'rust', 'php', 'ruby',
            'swift', 'kotlin', 'scala', 'r', 'matlab', 'sql', 'html', 'css', 'sass', 'less',
            # Frameworks & Libraries
            'react', 'angular', 'vue', 'node.js', 'express', 'django', 'flask', 'fastapi',
            'spring', 'laravel', 'rails', 'asp.net', '.net', 'next.js', 'nuxt.js',
            # Databases
            'postgresql', 'mysql', 'mongodb', 'redis', 'elasticsearch', 'cassandra',
            'oracle', 'sqlite', 'dynamodb', 'firebase', 'supabase',
            
            # Cloud & DevOps
            'aws', 'azure', 'gcp', 'docker', 'kubernetes', 'jenkins', 'git', 'ci/cd',
            'terraform', 'ansible', 'linux', 'bash', 'shell scripting',
            # Tools & Others
            'git', 'github', 'gitlab', 'jira', 'agile', 'scrum', 'rest api', 'graphql',
            'microservices', 'machine learning', 'ai', 'data science', 'nlp', 'computer vision'
        ]
    
    def extract_text_from_pdf(self, file_path: str) -> str:
        """Extract text from PDF file using PyMuPDF with fallback"""
        if not os.path.exists(file_path):
            raise Exception(f"PDF file not found at path: {file_path}")
        
        # Check file size
        file_size = os.path.getsize(file_path)
        if file_size == 0:
            raise Exception("PDF file is empty (0 bytes)")
        
        print(f"[DEBUG] Attempting to parse PDF: {file_path} (size: {file_size} bytes)")
        
        # Try PyMuPDF first if available
        if PYMUPDF_AVAILABLE:
            try:
                # Open PDF in binary mode
                doc = fitz.open(file_path)
                print(f"[DEBUG] PDF opened successfully with PyMuPDF, pages: {len(doc)}")
                
                text = ""
                for page_num, page in enumerate(doc):
                    try:
                        page_text = page.get_text()
                        if page_text:
                            text += page_text + "\n"
                            print(f"[DEBUG] Extracted {len(page_text)} chars from page {page_num + 1}")
                    except Exception as page_error:
                        print(f"[WARNING] Error extracting text from page {page_num + 1}: {str(page_error)}")
                        continue
                
                doc.close()
                print(f"[DEBUG] Total text extracted: {len(text)} characters")
                
                if not text or len(text.strip()) < 10:
                    raise Exception("PDF file appears to be empty or contains no extractable text. The file might be image-based or corrupted.")
                
                return text
            except Exception as e:
                error_msg = str(e)
                print(f"[WARNING] PyMuPDF parsing failed: {error_msg}")
                print(f"[DEBUG] Falling back to PyPDF2...")
                # Continue to fallback below
        
        # Fallback: Try using PyPDF2 or pdfplumber if available
        try:
            import PyPDF2
            print("[DEBUG] Using PyPDF2 for PDF parsing")
            with open(file_path, 'rb') as pdf_file:
                pdf_reader = PyPDF2.PdfReader(pdf_file)
                print(f"[DEBUG] PDF opened with PyPDF2, pages: {len(pdf_reader.pages)}")
                text = ""
                for page_num, page in enumerate(pdf_reader.pages):
                    try:
                        page_text = page.extract_text() or ""
                        if page_text:
                            text += page_text + "\n"
                            print(f"[DEBUG] Extracted {len(page_text)} chars from page {page_num + 1} using PyPDF2")
                    except Exception as page_error:
                        print(f"[WARNING] Error extracting text from page {page_num + 1}: {str(page_error)}")
                        continue
                
                if not text or len(text.strip()) < 10:
                    raise Exception("PDF file appears to be empty or contains no extractable text.")
                
                print(f"[DEBUG] Total text extracted with PyPDF2: {len(text)} characters")
                return text
        except ImportError:
            print("[DEBUG] PyPDF2 not available, trying pdfplumber...")
            try:
                import pdfplumber
                print("[DEBUG] Using pdfplumber for PDF parsing")
                with pdfplumber.open(file_path) as pdf:
                    print(f"[DEBUG] PDF opened with pdfplumber, pages: {len(pdf.pages)}")
                    text = ""
                    for page_num, page in enumerate(pdf.pages):
                        try:
                            page_text = page.extract_text() or ""
                            if page_text:
                                text += page_text + "\n"
                                print(f"[DEBUG] Extracted {len(page_text)} chars from page {page_num + 1} using pdfplumber")
                        except Exception as page_error:
                            print(f"[WARNING] Error extracting text from page {page_num + 1}: {str(page_error)}")
                            continue
                    
                    if not text or len(text.strip()) < 10:
                        raise Exception("PDF file appears to be empty or contains no extractable text.")
                    
                    print(f"[DEBUG] Total text extracted with pdfplumber: {len(text)} characters")
                    return text
            except ImportError:
                raise Exception(
                    "PDF parsing libraries not available. Please install one of: "
                    "pip install pymupdf OR pip install PyPDF2 OR pip install pdfplumber"
                )
        except Exception as e:
            error_msg = str(e)
            print(f"[ERROR] Fallback PDF parsing error: {error_msg}")
            if "not a PDF" in error_msg.lower() or "invalid" in error_msg.lower() or "cannot read" in error_msg.lower():
                raise Exception("The file is not a valid PDF document. Please upload a valid PDF file.")
            raise Exception(f"Error extracting text from PDF: {str(e)}")
    
    def extract_text_from_docx(self, file_path: str) -> str:
        """Extract text from DOCX file"""
        if not os.path.exists(file_path):
            raise Exception(f"DOCX file not found at path: {file_path}")
        
        # Check file size
        file_size = os.path.getsize(file_path)
        if file_size == 0:
            raise Exception("DOCX file is empty (0 bytes)")
        
        print(f"[DEBUG] Attempting to parse DOCX: {file_path} (size: {file_size} bytes)")
        
        if not DOCX_AVAILABLE:
            raise Exception("python-docx is not available. Please install it with: pip install python-docx")
        
        try:
            doc = Document(file_path)
            print(f"[DEBUG] DOCX opened successfully")
            
            text_parts = []
            for paragraph in doc.paragraphs:
                if paragraph.text:
                    text_parts.append(paragraph.text)
            
            # Also extract text from tables
            for table in doc.tables:
                for row in table.rows:
                    for cell in row.cells:
                        if cell.text:
                            text_parts.append(cell.text)
            
            text = "\n".join(text_parts)
            print(f"[DEBUG] Total text extracted: {len(text)} characters")
            
            if not text or len(text.strip()) < 10:
                raise Exception("DOCX file appears to be empty or contains no extractable text.")
            
            return text
        except Exception as e:
            error_msg = str(e)
            print(f"[ERROR] DOCX parsing error: {error_msg}")
            if "not a docx" in error_msg.lower() or "invalid" in error_msg.lower() or "corrupt" in error_msg.lower() or "cannot open" in error_msg.lower():
                raise Exception("The file is not a valid DOCX document. Please upload a valid DOCX file.")
            raise Exception(f"Error extracting text from DOCX: {str(e)}")
    
    def extract_text(self, file_path: str, file_extension: str) -> str:
        """Extract text from resume file based on extension"""
        file_extension = file_extension.lower()
        
        if file_extension == '.pdf':
            return self.extract_text_from_pdf(file_path)
        elif file_extension in ['.docx', '.doc']:
            return self.extract_text_from_docx(file_path)
        else:
            raise ValueError(f"Unsupported file type: {file_extension}")
    
    def extract_skills(self, text: str) -> List[str]:
        """Extract skills from resume text"""
        text_lower = text.lower()
        found_skills = []
        
        for skill in self.skill_keywords:
            # Check for skill in various formats
            patterns = [
                rf'\b{re.escape(skill)}\b',
                rf'\b{re.escape(skill.replace(".", "\\."))}\b',
            ]
            
            for pattern in patterns:
                if re.search(pattern, text_lower, re.IGNORECASE):
                    # Capitalize properly
                    skill_formatted = skill.title() if '.' not in skill else skill.upper()
                    if skill_formatted not in found_skills:
                        found_skills.append(skill_formatted)
                    break
        
        return found_skills[:20]  # Limit to top 20 skills
    
    def extract_experience_level(self, text: str) -> Optional[str]:
        """Extract experience level from resume text"""
        text_lower = text.lower()
        
        # Patterns to match experience
        experience_patterns = [
            (r'\b(\d+)\s*(?:years?|yrs?|y\.?)\s*(?:of\s*)?experience', 'years'),
            (r'experience[:\s]+(\d+)\s*(?:years?|yrs?)', 'years'),
            (r'(\d+)\s*(?:years?|yrs?)\s*(?:in|of)', 'years'),
            (r'fresher|fresh\s*graduate|no\s*experience|entry\s*level', 'fresher'),
        ]
        
        # Check for fresher first
        for pattern, _ in experience_patterns:
            if pattern.startswith('fresher'):
                if re.search(pattern, text_lower, re.IGNORECASE):
                    return "Fresher"
        
        # Check for years of experience
        max_years = 0
        for pattern, _ in experience_patterns:
            if pattern.startswith('fresher'):
                continue
            matches = re.finditer(pattern, text_lower, re.IGNORECASE)
            for match in matches:
                try:
                    years = int(match.group(1))
                    max_years = max(max_years, years)
                except (IndexError, ValueError):
                    continue
        
        if max_years > 0:
            return f"{max_years}yrs"
        
        # Check for keywords that might indicate experience level
        if re.search(r'senior|lead|principal|architect', text_lower):
            return "5yrs+"
        elif re.search(r'mid|middle|intermediate', text_lower):
            return "2-4yrs"
        elif re.search(r'junior|entry|associate', text_lower):
            return "1yrs"
        
        return "Fresher"  # Default
    
    def extract_keywords(self, text: str) -> Dict[str, List[str]]:
        """Extract keywords including tools, technologies, and job titles"""
        text_lower = text.lower()
        keywords = {
            "tools": [],
            "technologies": [],
            "job_titles": [],
            "projects": []
        }
        
        # Extract tools and technologies (more comprehensive)
        tech_keywords = [
            # Frameworks
            'django', 'flask', 'fastapi', 'react', 'angular', 'vue', 'next.js', 'nuxt.js',
            'spring', 'express', 'laravel', 'rails', 'asp.net', '.net',
            # Tools
            'docker', 'kubernetes', 'jenkins', 'git', 'github', 'gitlab', 'jira', 'confluence',
            'terraform', 'ansible', 'puppet', 'chef', 'vagrant',
            # Databases
            'postgresql', 'mysql', 'mongodb', 'redis', 'elasticsearch', 'cassandra',
            'oracle', 'sqlite', 'dynamodb', 'firebase', 'supabase',
            # Cloud
            'aws', 'azure', 'gcp', 'heroku', 'vercel', 'netlify',
            # Other technologies
            'rest api', 'graphql', 'microservices', 'serverless', 'lambda',
            'machine learning', 'ai', 'data science', 'nlp', 'computer vision',
            'blockchain', 'web3', 'ethereum', 'solidity'
        ]
        
        for keyword in tech_keywords:
            pattern = rf'\b{re.escape(keyword.replace(".", "\\."))}\b'
            if re.search(pattern, text_lower, re.IGNORECASE):
                formatted = keyword.title() if '.' not in keyword else keyword
                if formatted not in keywords["technologies"]:
                    keywords["technologies"].append(formatted)
        
        # Extract job titles
        job_title_patterns = [
            r'(?:software|web|mobile|full.?stack|front.?end|back.?end|devops|data|ml|ai)\s+(?:engineer|developer|architect|specialist)',
            r'(?:senior|junior|lead|principal)\s+(?:software|web|mobile|full.?stack|front.?end|back.?end|devops|data|ml|ai)\s+(?:engineer|developer|architect)',
            r'(?:python|java|javascript|react|angular|vue|node)\s+(?:developer|engineer)',
            r'data\s+(?:scientist|engineer|analyst)',
            r'(?:machine\s+learning|ml|ai)\s+(?:engineer|scientist)',
            r'devops\s+(?:engineer|specialist)',
            r'system\s+(?:administrator|admin|architect)',
            r'qa\s+(?:engineer|tester|analyst)',
            r'product\s+(?:manager|owner)',
            r'technical\s+(?:lead|manager|architect)'
        ]
        
        for pattern in job_title_patterns:
            matches = re.finditer(pattern, text_lower, re.IGNORECASE)
            for match in matches:
                title = match.group(0).title()
                if title not in keywords["job_titles"]:
                    keywords["job_titles"].append(title)
        
        # Extract project mentions (simplified - looks for "project" followed by description)
        project_patterns = [
            r'project[:\s]+([A-Z][^.!?]{10,100})',
            r'built\s+([a-z\s]{10,80})\s+(?:using|with|in)',
            r'developed\s+([a-z\s]{10,80})\s+(?:using|with|in)',
            r'created\s+([a-z\s]{10,80})\s+(?:using|with|in)'
        ]
        
        for pattern in project_patterns:
            matches = re.finditer(pattern, text_lower, re.IGNORECASE)
            for match in matches:
                if len(match.groups()) > 0:
                    project = match.group(1).strip()[:80]
                    if project and project not in keywords["projects"]:
                        keywords["projects"].append(project)
        
        return keywords
    
    def extract_name(self, text: str) -> Optional[str]:
        """Extract name from resume text (usually at the beginning)"""
        lines = text.split('\n')[:10]  # Check first 10 lines
        for line in lines:
            line = line.strip()
            if len(line) > 3 and len(line) < 50:  # Reasonable name length
                # Check if it looks like a name (contains letters, may have spaces)
                if re.match(r'^[A-Za-z\s\.\-]+$', line) and not any(word.lower() in ['email', 'phone', 'address', 'resume', 'cv'] for word in line.split()):
                    # Check if it's not an email or phone
                    if '@' not in line and not re.match(r'^[\d\s\-\+\(\)]+$', line):
                        return line.title()
        return None
    
    def extract_email(self, text: str) -> Optional[str]:
        """Extract email address from resume text"""
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        matches = re.findall(email_pattern, text)
        if matches:
            return matches[0].lower()
        return None
    
    def parse_resume(self, file_path: str, file_extension: str) -> Dict[str, Any]:
        """Parse resume and extract all relevant information"""
        try:
            # Extract text
            text = self.extract_text(file_path, file_extension)
            
            if not text or len(text.strip()) < 50:
                raise ValueError("Resume file appears to be empty or invalid")
            
            # Extract personal information
            name = self.extract_name(text)
            email = self.extract_email(text)
            
            # Extract skills
            skills = self.extract_skills(text)
            
            # Extract experience level
            experience_level = self.extract_experience_level(text)
            
            # Extract additional keywords
            keywords = self.extract_keywords(text)
            
            return {
                "name": name,
                "email": email,
                "skills": skills,
                "experience_level": experience_level,
                "keywords": keywords,
                "text_length": len(text),
                "extracted_text_preview": text[:500]  # First 500 chars for debugging
            }
        except Exception as e:
            raise Exception(f"Error parsing resume: {str(e)}")

# Create global instance
resume_parser = ResumeParser()

