"""
Technical Interview Engine
Handles AI-powered technical interview sessions with voice interaction
"""

from typing import List, Dict, Optional, Any
from app.config.settings import settings
from app.services.resume_parser import resume_parser
from app.services.question_generator import question_generator
from app.services.answer_evaluator import answer_evaluator
import json
import os

# Try to import OpenAI components
OPENAI_AVAILABLE = False
OpenAI = None

def _try_import_openai():
    """Lazy import of OpenAI components"""
    global OPENAI_AVAILABLE, OpenAI
    if OPENAI_AVAILABLE:
        return True
    
    try:
        from openai import OpenAI
        OPENAI_AVAILABLE = True
        return True
    except ImportError:
        OPENAI_AVAILABLE = False
        return False

class TechnicalInterviewEngine:
    """Engine for managing technical interview sessions with voice interaction"""
    
    def __init__(self):
        _try_import_openai()
        self.openai_available = OPENAI_AVAILABLE and bool(settings.openai_api_key)
        
        if self.openai_available and OpenAI is not None:
            try:
                self.client = OpenAI(api_key=settings.openai_api_key)
            except Exception as e:
                print(f"Warning: Could not initialize OpenAI client: {str(e)}")
                self.openai_available = False
                self.client = None
        else:
            self.client = None
    
    def start_interview_session(
        self,
        user_id: str,
        resume_skills: Optional[List[str]] = None,
        resume_context: Optional[Dict[str, Any]] = None,
        role: Optional[str] = None,
        experience_level: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Start a new technical interview session enriched with resume-specific details
        """
        technical_skills = resume_skills or []
        resume_projects: List[str] = []
        resume_domains: List[str] = []
        
        if resume_context:
            keywords = resume_context.get("keywords", {}) or {}
            technologies = keywords.get("technologies", [])
            tools = keywords.get("tools", [])
            additional_skills = resume_context.get("skills", []) or []
            
            for skill in technologies + tools + additional_skills:
                if skill and skill not in technical_skills:
                    technical_skills.append(skill)
            
            resume_projects = resume_context.get("projects", []) or keywords.get("projects", []) or []
            resume_domains = resume_context.get("domains", []) or keywords.get("job_titles", []) or []
            experience_level = experience_level or resume_context.get("experience_level")
        
        technical_skills = list(dict.fromkeys(technical_skills))[:20]
        
        conversation_history = [{
            "role": "ai",
            "content": "Welcome to your technical interview! I'll tailor each question to the skills and projects you highlighted in your resume."
        }]
        
        return {
            "session_id": None,  # Will be set by the router
            "technical_skills": technical_skills,
            "conversation_history": conversation_history,
            "current_question_index": 0,
            "questions_asked": [],
            "answers_received": [],
            "resume_projects": resume_projects,
            "resume_domains": resume_domains,
            "role": role or "Technical Interview",
            "experience_level": experience_level
        }
    
    def generate_next_question(
        self,
        session_data: Dict[str, Any],
        conversation_history: List[Dict[str, str]]
    ) -> Dict[str, Any]:
        """
        Generate the next technical question based on conversation history and resume skills
        """
        technical_skills = session_data.get("technical_skills", [])
        questions_asked = session_data.get("questions_asked", [])
        answers_received = session_data.get("answers_received", [])
        
        if not self.openai_available or self.client is None:
            # Fallback to predefined questions
            return self._get_fallback_question(session_data, questions_asked)
        
        try:
            # Build context for question generation
            skills_context = ", ".join(technical_skills[:10]) if technical_skills else "general technical skills"
            
            # Build conversation context
            conversation_context = ""
            if conversation_history:
                recent_messages = conversation_history[-6:]  # Last 6 messages
                conversation_context = "\n".join([
                    f"{msg.get('role', 'unknown')}: {msg.get('content', '')[:200]}"
                    for msg in recent_messages
                ])
            
            # Generate question using OpenAI
            system_prompt = """You are a technical interviewer conducting a voice-based technical interview.
Your role is to ask relevant technical questions based on the candidate's resume skills and previous answers.
Questions should be:
1. Technical and domain-specific
2. Based on the skills mentioned in the resume
3. Progressive (start with basics, move to advanced)
4. Conversational and natural for voice interaction
5. One question at a time

Keep questions concise (1-2 sentences) suitable for voice interaction.
Do not repeat questions that have already been asked."""

            user_prompt = f"""Generate the next technical interview question.

Candidate's Technical Skills: {skills_context}

Previous Questions Asked: {len(questions_asked)} questions
Previous Answers: {len(answers_received)} answers

Recent Conversation:
{conversation_context if conversation_context else "This is the first question."}

Generate ONE technical question that:
- Is relevant to the candidate's skills: {skills_context}
- Hasn't been asked before
- Is appropriate for a voice interview
- Tests technical knowledge and problem-solving

Return ONLY the question text, nothing else."""

            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.7,
                max_tokens=150
            )
            
            question = response.choices[0].message.content.strip()
            
            # Remove quotes if present
            if question.startswith('"') and question.endswith('"'):
                question = question[1:-1]
            
            return {
                "question": question,
                "question_type": "Technical",
                "audio_url": None  # Will be generated by TTS endpoint
            }
            
        except Exception as e:
            print(f"Error generating question with AI: {str(e)}")
            return self._get_fallback_question(session_data, questions_asked)
    
    def evaluate_answer(
        self,
        question: str,
        answer: str,
        session_data: Dict[str, Any],
        conversation_history: List[Dict[str, str]]
    ) -> Dict[str, Any]:
        """
        Evaluate the candidate's answer and generate AI response
        """
        # Use existing answer evaluator
        scores = answer_evaluator.evaluate_answer(
            question=question,
            question_type="Technical",
            answer=answer,
            experience_level="Intermediate",  # Default, can be improved
            response_time=None
        )
        
        # Generate AI response using OpenAI if available
        ai_response = None
        if self.openai_available and self.client is not None:
            try:
                system_prompt = """You are a technical interviewer providing feedback during a voice interview.
After the candidate answers, provide:
1. Brief acknowledgment (1 sentence)
2. Follow-up question or move to next topic (1 sentence)

Keep responses natural and conversational for voice interaction.
Be encouraging but professional."""

                user_prompt = f"""Candidate's Answer: {answer}

Question: {question}

Evaluation Scores:
- Relevance: {scores.relevance}/100
- Technical Accuracy: {scores.technical_accuracy}/100
- Communication: {scores.communication}/100

Provide a brief, natural response (2-3 sentences max) that:
1. Acknowledges their answer
2. Provides brief feedback if needed
3. Either asks a follow-up or indicates moving to the next question

Keep it conversational and suitable for voice interaction."""

                response = self.client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.7,
                    max_tokens=100
                )
                
                ai_response = response.choices[0].message.content.strip()
                
            except Exception as e:
                print(f"Error generating AI response: {str(e)}")
                ai_response = "Thank you for your answer. Let's move to the next question."
        
        if not ai_response:
            ai_response = "Thank you for your answer. Let's move to the next question."
        
        return {
            "scores": {
                "relevance": scores.relevance,
                "technical_accuracy": scores.technical_accuracy,
                "communication": scores.communication,
                "overall": scores.overall
            },
            "ai_response": ai_response,
            "audio_url": None  # Will be generated by TTS endpoint
        }
    
    def generate_final_feedback(
        self,
        session_data: Dict[str, Any],
        conversation_history: List[Dict[str, str]],
        all_scores: List[Dict[str, int]]
    ) -> Dict[str, Any]:
        """
        Generate comprehensive interview feedback
        """
        if not all_scores:
            return {
                "overall_score": 0,
                "feedback_summary": "No answers provided.",
                "strengths": [],
                "areas_for_improvement": [],
                "recommendations": []
            }
        
        # Calculate overall score
        overall_scores = [s.get("overall", 0) for s in all_scores if s.get("overall")]
        avg_score = sum(overall_scores) / len(overall_scores) if overall_scores else 0
        
        # Analyze strengths and weaknesses
        strengths = []
        areas_for_improvement = []
        recommendations = []
        
        # Analyze by category
        relevance_scores = [s.get("relevance", 0) for s in all_scores]
        technical_scores = [s.get("technical_accuracy", 0) for s in all_scores]
        communication_scores = [s.get("communication", 0) for s in all_scores]
        
        avg_relevance = sum(relevance_scores) / len(relevance_scores) if relevance_scores else 0
        avg_technical = sum(technical_scores) / len(technical_scores) if technical_scores else 0
        avg_communication = sum(communication_scores) / len(communication_scores) if communication_scores else 0
        
        if avg_technical >= 75:
            strengths.append("Strong technical knowledge and accuracy")
        elif avg_technical < 60:
            areas_for_improvement.append("Technical accuracy needs improvement")
            recommendations.append("Review core technical concepts and practice explaining them clearly")
        
        if avg_communication >= 75:
            strengths.append("Clear and effective communication")
        elif avg_communication < 60:
            areas_for_improvement.append("Communication clarity can be improved")
            recommendations.append("Practice explaining technical concepts in simple terms")
        
        if avg_relevance >= 75:
            strengths.append("Answers are relevant and on-topic")
        elif avg_relevance < 60:
            areas_for_improvement.append("Work on staying focused and relevant in answers")
            recommendations.append("Practice structuring answers to directly address the question")
        
        # Generate summary using AI if available
        feedback_summary = f"Overall performance score: {avg_score:.1f}/100. "
        
        if self.openai_available and self.client is not None:
            try:
                system_prompt = """You are a technical interviewer providing final interview feedback.
Generate a comprehensive but concise summary (3-4 sentences) of the candidate's performance."""

                user_prompt = f"""Interview Summary:
- Overall Score: {avg_score:.1f}/100
- Technical Accuracy Average: {avg_technical:.1f}/100
- Communication Average: {avg_communication:.1f}/100
- Relevance Average: {avg_relevance:.1f}/100
- Total Questions: {len(all_scores)}

Generate a professional, constructive feedback summary (3-4 sentences)."""

                response = self.client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.7,
                    max_tokens=200
                )
                
                feedback_summary = response.choices[0].message.content.strip()
                
            except Exception as e:
                print(f"Error generating feedback summary: {str(e)}")
                feedback_summary = f"Overall performance score: {avg_score:.1f}/100. "
                if strengths:
                    feedback_summary += f"Strengths include: {', '.join(strengths[:2])}. "
                if areas_for_improvement:
                    feedback_summary += f"Areas to improve: {', '.join(areas_for_improvement[:2])}."
        
        # Ensure we have at least some feedback
        if not strengths:
            strengths.append("Good effort in the interview")
        if not areas_for_improvement:
            areas_for_improvement.append("Continue practicing technical interviews")
        if not recommendations:
            recommendations.append("Keep practicing and reviewing technical concepts")
        
        return {
            "overall_score": round(avg_score, 2),
            "feedback_summary": feedback_summary,
            "strengths": strengths[:5],
            "areas_for_improvement": areas_for_improvement[:5],
            "recommendations": recommendations[:5]
        }
    
    def _get_fallback_question(
        self,
        session_data: Dict[str, Any],
        questions_asked: List[str]
    ) -> Dict[str, Any]:
        """Fallback questions that still leverage resume-driven context"""
        technical_skills = session_data.get("technical_skills", []) or []
        resume_projects = session_data.get("resume_projects", []) or []
        resume_domains = session_data.get("resume_domains", []) or []
        experience_level = session_data.get("experience_level")

        skill = technical_skills[len(questions_asked) % len(technical_skills)] if technical_skills else "your core stack"
        project = resume_projects[len(questions_asked) % len(resume_projects)] if resume_projects else ""
        domain_label = resume_domains[0] if resume_domains else session_data.get("role") or "your recent role"

        project_reference = project or f"your recent {domain_label} project"

        templates = [
            f"In '{project_reference}', how did you architect critical components using {skill}? Walk me through the design decisions.",
            f"What trade-offs did you evaluate when scaling the {skill}-heavy modules in {project_reference}?",
            f"Describe how you would refactor a legacy feature from {project_reference} using {skill} to improve reliability.",
            f"Based on your experience with {skill}, how do you ensure observability and troubleshooting are baked into your solutions?",
            f"How would you mentor a junior engineer to ramp up on {skill} while contributing to {project_reference}?"
        ]

        if experience_level:
            templates.append(
                f"With {experience_level} under your belt, how do you decide when to introduce advanced {skill} patterns versus keeping implementations simple?"
            )

        question = templates[len(questions_asked) % len(templates)]

        return {
            "question": question,
            "question_type": "Technical",
            "audio_url": None
        }

# Create global instance
technical_interview_engine = TechnicalInterviewEngine()

