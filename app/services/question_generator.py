"""
AI Question Generator Service using OpenAI and LangChain
Generates interview questions based on role, skills, and experience level
"""

from typing import List, Dict, Optional
from app.schemas.interview import InterviewQuestion
from app.config.settings import settings
import json

# Try to import OpenAI components, fallback if not available
# Using lazy imports to avoid dependency issues at module load time
OPENAI_AVAILABLE = False
ChatOpenAI = None
ChatPromptTemplate = None

def _try_import_langchain():
    """Lazy import of langchain components"""
    global OPENAI_AVAILABLE, ChatOpenAI, ChatPromptTemplate
    if OPENAI_AVAILABLE:
        return True
    
    try:
        from langchain_openai import ChatOpenAI
        from langchain.prompts import ChatPromptTemplate
        OPENAI_AVAILABLE = True
        return True
    except (ImportError, TypeError, AttributeError):
        try:
            # Fallback for older langchain versions
            from langchain.chat_models import ChatOpenAI
            from langchain.prompts import ChatPromptTemplate
            OPENAI_AVAILABLE = True
            return True
        except (ImportError, TypeError, AttributeError):
            OPENAI_AVAILABLE = False
            return False

class QuestionGenerator:
    """Generate interview questions using OpenAI"""
    
    def __init__(self):
        # Try to import langchain components
        _try_import_langchain()
        self.openai_available = OPENAI_AVAILABLE and bool(settings.openai_api_key)
        
        if self.openai_available and ChatOpenAI is not None:
            try:
                self.llm = ChatOpenAI(
                    model_name="gpt-3.5-turbo",
                    temperature=0.7,
                    openai_api_key=settings.openai_api_key
                )
            except Exception as e:
                print(f"Warning: Could not initialize OpenAI: {str(e)}")
                self.openai_available = False
                self.llm = None
        else:
            self.llm = None
        
        # Initialize prompt template only if ChatPromptTemplate is available
        if ChatPromptTemplate is not None:
            self.prompt_template = ChatPromptTemplate.from_messages([
            ("system", """You are an expert interview question generator for technical roles.
Your task is to generate comprehensive interview questions based on the role, experience level, skills, and resume context provided.

Generate questions in three categories:
1. HR Questions - Behavioral, cultural fit, communication skills
2. Technical Questions - Role-specific technical knowledge and skills
3. Problem-solving Questions - Scenarios, case studies, coding challenges

IMPORTANT: If resume context is provided (keywords, tools, technologies, job titles, projects), you MUST create personalized questions that reference specific items from the resume. For example:
- "You mentioned Django in your resume. Tell me about a project you built with it."
- "I see you have experience with AWS. Can you explain how you've used it in production?"
- "Your resume shows experience with microservices. Walk me through how you designed a microservices architecture."

For each question, provide:
- The question type (HR, Technical, or Problem-solving)
- A clear, professional question appropriate for the experience level
- If resume context is available, make questions personalized and specific to the candidate's background

Return the questions as a JSON array with this structure:
[
  {{"type": "HR", "question": "Tell me about yourself."}},
  {{"type": "Technical", "question": "You mentioned [technology] in your resume. Explain how you used it."}},
  {{"type": "Problem-solving", "question": "How would you approach [scenario]?"}}
]

Generate 10-15 questions total, distributed across all three categories.
For fresher roles, focus more on fundamentals and learning ability.
For experienced roles, include advanced concepts and system design.
When resume context is provided, prioritize personalized questions that reference the candidate's specific experience."""),
            ("human", """Generate interview questions for:
Role: {role}
Experience Level: {experience_level}
Skills: {skills}
{resume_context}

Please generate 10-15 questions covering HR, Technical, and Problem-solving categories.
Make questions appropriate for {experience_level} level and relevant to {role} role.
If specific skills are provided, include questions related to those skills.
{resume_instructions}

Return only valid JSON array, no additional text.""")
            ])
        else:
            self.prompt_template = None
    
    def generate_questions(
        self,
        role: str,
        experience_level: str,
        skills: List[str],
        resume_context: Optional[Dict[str, any]] = None
    ) -> List[InterviewQuestion]:
        """Generate interview questions using OpenAI with optional resume context"""
        
        if not self.openai_available:
            # Use fallback questions if OpenAI is not available
            return self._get_fallback_questions(role, experience_level, skills)
        
        try:
            # Format skills list
            skills_str = ", ".join(skills) if skills else "General skills for the role"
            
            # Format resume context if provided
            resume_context_str = ""
            resume_instructions = ""
            
            if resume_context:
                keywords = resume_context.get("keywords", {})
                technologies = keywords.get("technologies", [])
                tools = keywords.get("tools", [])
                job_titles = keywords.get("job_titles", [])
                projects = keywords.get("projects", [])
                
                context_parts = []
                if technologies:
                    context_parts.append(f"Technologies: {', '.join(technologies[:10])}")
                if tools:
                    context_parts.append(f"Tools: {', '.join(tools[:10])}")
                if job_titles:
                    context_parts.append(f"Previous Roles: {', '.join(job_titles[:5])}")
                if projects:
                    context_parts.append(f"Projects Mentioned: {', '.join(projects[:3])}")
                
                if context_parts:
                    resume_context_str = "\nResume Context:\n" + "\n".join(context_parts)
                    resume_instructions = "\nCRITICAL: Create personalized questions that reference specific technologies, tools, or experiences from the resume context above. For example, if Django is mentioned, ask about Django projects. If AWS is mentioned, ask about AWS experience. Make the questions feel tailored to this specific candidate's background."
            
            # Create prompt
            prompt = self.prompt_template.format_messages(
                role=role,
                experience_level=experience_level,
                skills=skills_str,
                resume_context=resume_context_str,
                resume_instructions=resume_instructions
            )
            
            # Generate response
            response = self.llm.invoke(prompt)
            
            # Parse response
            content = response.content.strip()
            
            # Try to extract JSON from response
            # Sometimes LLM wraps JSON in markdown code blocks
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            # Parse JSON
            try:
                questions_data = json.loads(content)
            except json.JSONDecodeError:
                # If direct parsing fails, try to extract JSON array
                import re
                json_match = re.search(r'\[.*\]', content, re.DOTALL)
                if json_match:
                    questions_data = json.loads(json_match.group())
                else:
                    raise ValueError("Could not parse JSON from LLM response")
            
            # Convert to InterviewQuestion objects
            questions = []
            for q in questions_data:
                if isinstance(q, dict) and "type" in q and "question" in q:
                    # Normalize question type
                    q_type = q["type"].strip()
                    if "HR" in q_type or "hr" in q_type.lower() or "behavioral" in q_type.lower():
                        q_type = "HR"
                    elif "technical" in q_type.lower() or "tech" in q_type.lower():
                        q_type = "Technical"
                    elif "problem" in q_type.lower() or "problem-solving" in q_type.lower():
                        q_type = "Problem-solving"
                    else:
                        q_type = "Technical"  # Default
                    
                    questions.append(InterviewQuestion(
                        type=q_type,
                        question=q["question"].strip()
                    ))
            
            # Ensure we have questions in all categories
            if len(questions) < 10:
                # Add fallback questions if not enough generated
                questions.extend(self._get_fallback_questions(role, experience_level, skills))
            
            # Limit to 15 questions max
            return questions[:15]
            
        except Exception as e:
            # Fallback to predefined questions if AI generation fails
            print(f"Error generating questions with AI: {str(e)}")
            return self._get_fallback_questions(role, experience_level, skills)
    
    def _get_fallback_questions(
        self,
        role: str,
        experience_level: str,
        skills: List[str]
    ) -> List[InterviewQuestion]:
        """Fallback questions if AI generation fails"""
        
        questions = []
        
        # HR Questions
        hr_questions = [
            "Tell me about yourself and your background.",
            "Why are you interested in this role?",
            "What are your strengths and weaknesses?",
            "Describe a challenging situation you faced and how you handled it.",
            "Where do you see yourself in 5 years?",
        ]
        
        # Technical Questions (role-specific)
        technical_questions = {
            "Python Developer": [
                "Explain the difference between list and tuple in Python.",
                "What are Python decorators and how do you use them?",
                "Explain the GIL (Global Interpreter Lock) in Python.",
                "How do you handle exceptions in Python?",
                "What is the difference between __str__ and __repr__?",
            ],
            "ServiceNow Engineer": [
                "Explain the ServiceNow data model and table structure.",
                "What is the difference between client scripts and business rules?",
                "How do you handle ServiceNow integrations?",
                "Explain the ServiceNow workflow engine.",
                "What are best practices for ServiceNow development?",
            ],
            "DevOps": [
                "Explain CI/CD pipeline and its benefits.",
                "What is containerization and how does Docker work?",
                "Explain Kubernetes architecture and components.",
                "How do you handle infrastructure as code?",
                "What monitoring tools have you used and why?",
            ],
            "Fresher": [
                "What programming languages are you familiar with?",
                "Explain basic data structures like arrays and linked lists.",
                "What is version control and how do you use Git?",
                "Describe the software development lifecycle.",
                "How do you approach learning new technologies?",
            ],
        }
        
        # Problem-solving Questions
        problem_questions = [
            "How would you debug a production issue that's affecting multiple users?",
            "Describe how you would design a scalable system for [specific use case].",
            "How would you optimize a slow-performing application?",
            "Explain your approach to code review and quality assurance.",
            "How do you prioritize tasks when working on multiple projects?",
        ]
        
        # Add HR questions
        for q in hr_questions[:3]:
            questions.append(InterviewQuestion(type="HR", question=q))
        
        # Add technical questions based on role
        role_tech = technical_questions.get(role, technical_questions["Fresher"])
        for q in role_tech[:5]:
            questions.append(InterviewQuestion(type="Technical", question=q))
        
        # Add problem-solving questions
        for q in problem_questions[:3]:
            questions.append(InterviewQuestion(type="Problem-solving", question=q))
        
        # Add skill-specific questions if skills provided
        if skills:
            for skill in skills[:3]:
                questions.append(InterviewQuestion(
                    type="Technical",
                    question=f"Tell me about your experience with {skill}."
                ))
        
        return questions[:15]

# Create global instance
question_generator = QuestionGenerator()

