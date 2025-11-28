"""
Answer Evaluation Service using OpenAI
Evaluates user answers with scoring on multiple dimensions
"""

from typing import Dict, Optional
from app.schemas.interview import AnswerScore
from app.config.settings import settings
import json

# Try to import OpenAI components - lazy import to avoid dependency issues
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
            from langchain.chat_models import ChatOpenAI
            from langchain.prompts import ChatPromptTemplate
            OPENAI_AVAILABLE = True
            return True
        except (ImportError, TypeError, AttributeError):
            OPENAI_AVAILABLE = False
            return False

class AnswerEvaluator:
    """Evaluate interview answers using OpenAI"""
    
    def __init__(self):
        # Try to import langchain components
        _try_import_langchain()
        self.openai_available = OPENAI_AVAILABLE and bool(settings.openai_api_key)
        
        if self.openai_available and ChatOpenAI is not None:
            try:
                self.llm = ChatOpenAI(
                    model_name="gpt-3.5-turbo",
                    temperature=0.3,  # Lower temperature for more consistent scoring
                    openai_api_key=settings.openai_api_key
                )
            except Exception as e:
                pass  # OpenAI not available, will use fallback
                self.openai_available = False
                self.llm = None
        else:
            self.llm = None
        
        # Initialize prompt template only if ChatPromptTemplate is available
        if ChatPromptTemplate is not None:
            self.prompt_template = ChatPromptTemplate.from_messages([
            ("system", """You are an expert interview evaluator. Your task is to evaluate interview answers and provide scores on four dimensions:

1. **Relevance** (0-100): How well does the answer address the question? Does it stay on topic?
2. **Confidence** (0-100): How confident and clear is the answer? Does the candidate seem sure of their response?
3. **Technical Accuracy** (0-100): How technically correct is the answer? Are the facts and concepts accurate?
4. **Communication** (0-100): How well is the answer communicated? Is it clear, structured, and easy to understand?

For each dimension, provide a score from 0-100.
Calculate the overall score as the average of all four scores.

Also provide constructive feedback (2-3 sentences) that highlights strengths and areas for improvement.

When evaluating, consider the response time. Answers given too quickly may lack depth, while answers that take too long may indicate uncertainty. However, prioritize answer quality over speed.

Return your evaluation as a JSON object with this exact structure:
{{
    "relevance": <score 0-100>,
    "confidence": <score 0-100>,
    "technical_accuracy": <score 0-100>,
    "communication": <score 0-100>,
    "overall": <average score 0-100>,
    "feedback": "<feedback text>"
}}

Be fair but thorough in your evaluation. Consider the experience level when scoring."""),
            ("human", """Evaluate this interview answer:

**Question Type:** {question_type}
**Question:** {question}
**User's Answer:** {answer}
**Experience Level:** {experience_level}
**Response Time:** {response_time} seconds

Provide scores and feedback as specified. Note the response time in your feedback if relevant.""")
            ])
        else:
            self.prompt_template = None
    
    def evaluate_answer(
        self,
        question: str,
        question_type: str,
        answer: str,
        experience_level: str,
        response_time: Optional[int] = None
    ) -> AnswerScore:
        """Evaluate an answer and return scores"""
        
        # ✅ FIX: Return 0 scores for "No Answer"
        if answer == "No Answer":
            return AnswerScore(
                relevance=0,
                confidence=0,
                technical_accuracy=0,
                communication=0,
                overall=0,
                feedback="No answer provided."
            )
        
        if not self.openai_available:
            # Return default scores if OpenAI is not available
            return self._get_default_scores(answer)
        
        try:
            # Format response time
            response_time_str = f"{response_time} seconds" if response_time is not None else "Not provided"
            
            # Create prompt
            prompt = self.prompt_template.format_messages(
                question_type=question_type,
                question=question,
                answer=answer,
                experience_level=experience_level,
                response_time=response_time_str
            )
            
            # Get evaluation from OpenAI
            response = self.llm.invoke(prompt)
            content = response.content.strip()
            
            # Try to extract JSON from response
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            # Parse JSON
            try:
                evaluation_data = json.loads(content)
            except json.JSONDecodeError:
                # Try to extract JSON object
                import re
                json_match = re.search(r'\{.*\}', content, re.DOTALL)
                if json_match:
                    evaluation_data = json.loads(json_match.group())
                else:
                    raise ValueError("Could not parse JSON from evaluation response")
            
            # Extract scores
            relevance = int(evaluation_data.get("relevance", 50))
            confidence = int(evaluation_data.get("confidence", 50))
            technical_accuracy = int(evaluation_data.get("technical_accuracy", 50))
            communication = int(evaluation_data.get("communication", 50))
            feedback = evaluation_data.get("feedback", "No feedback provided.")
            
            # Calculate overall score
            overall = int((relevance + confidence + technical_accuracy + communication) / 4)
            
            # Ensure scores are in valid range
            relevance = max(0, min(100, relevance))
            confidence = max(0, min(100, confidence))
            technical_accuracy = max(0, min(100, technical_accuracy))
            communication = max(0, min(100, communication))
            overall = max(0, min(100, overall))
            
            return AnswerScore(
                relevance=relevance,
                confidence=confidence,
                technical_accuracy=technical_accuracy,
                communication=communication,
                overall=overall,
                feedback=feedback
            )
            
        except Exception as e:
            # Return default scores on error
            return self._get_default_scores(answer)
    
    def _get_default_scores(self, answer: str) -> AnswerScore:
        """Get default scores when AI evaluation is not available"""
        # Simple heuristic-based scoring
        answer_length = len(answer.split())
        
        # Base scores
        relevance = 60
        confidence = 60
        technical_accuracy = 60
        communication = 60
        
        # Adjust based on answer length
        if answer_length < 10:
            communication = 40
            confidence = 40
        elif answer_length > 100:
            communication = 70
            confidence = 70
        
        overall = int((relevance + confidence + technical_accuracy + communication) / 4)
        
        feedback = "AI evaluation is not available. Please ensure OpenAI API key is configured for detailed feedback."
        
        return AnswerScore(
            relevance=relevance,
            confidence=confidence,
            technical_accuracy=technical_accuracy,
            communication=communication,
            overall=overall,
            feedback=feedback
        )

# Create global instance
answer_evaluator = AnswerEvaluator()

