"""
Interview Evaluation Service using OpenAI
Analyzes all answers and generates comprehensive feedback report
"""

from typing import List, Dict, Optional
from app.schemas.interview import CategoryScore, InterviewEvaluationResponse
from app.config.settings import settings
import json
from datetime import datetime

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

class InterviewEvaluator:
    """Evaluate complete interview session and generate feedback"""
    
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
            self.feedback_prompt_template = ChatPromptTemplate.from_messages([
            ("system", """You are an expert interview coach and career advisor. Your task is to analyze a complete interview session and provide comprehensive feedback.

Based on the interview performance data provided, generate:
1. A personalized feedback summary (2-3 paragraphs) highlighting overall performance
2. List of strengths (3-5 items)
3. List of areas for improvement (3-5 items)
4. Specific learning recommendations (3-5 actionable items)

Be constructive, encouraging, and specific. Focus on actionable advice that will help the candidate improve.

Return your analysis as a JSON object with this structure:
{{
    "feedback_summary": "<2-3 paragraph summary>",
    "strengths": ["strength1", "strength2", ...],
    "areas_for_improvement": ["area1", "area2", ...],
    "recommendations": ["recommendation1", "recommendation2", ...]
}}"""),
            ("human", """Analyze this interview performance:

**Role:** {role}
**Experience Level:** {experience_level}
**Total Questions:** {total_questions}
**Answered Questions:** {answered_questions}

**Category Scores:**
- Clarity: {clarity_score}/100
- Accuracy: {accuracy_score}/100
- Confidence: {confidence_score}/100
- Communication: {communication_score}/100
- Overall Score: {overall_score}/100

**Question-by-Question Performance:**
{question_details}

Provide comprehensive feedback and recommendations as specified.""")
            ])
        else:
            self.feedback_prompt_template = None
    
    def calculate_category_scores(self, answers: List[Dict]) -> CategoryScore:
        """Calculate weighted average scores for each category"""
        if not answers:
            return CategoryScore(
                clarity=0,
                accuracy=0,
                confidence=0,
                communication=0
            )
        
        total_relevance = 0
        total_technical_accuracy = 0
        total_confidence = 0
        total_communication = 0
        total_weight = 0
        
        for answer in answers:
            # Use overall_score as weight (answers with higher scores are more reliable)
            weight = answer.get("overall_score", 50) / 100.0
            
            total_relevance += answer.get("relevance_score", 0) * weight
            total_technical_accuracy += answer.get("technical_accuracy_score", 0) * weight
            total_confidence += answer.get("confidence_score", 0) * weight
            total_communication += answer.get("communication_score", 0) * weight
            total_weight += weight
        
        if total_weight == 0:
            total_weight = len(answers)
        
        # Calculate weighted averages
        # Clarity: How well the answer addressed the question (relevance)
        # Accuracy: Technical correctness
        # Confidence: How confident the answer was
        # Communication: How well the answer was communicated
        clarity = total_relevance / total_weight if total_weight > 0 else 0
        accuracy = total_technical_accuracy / total_weight if total_weight > 0 else 0
        confidence = total_confidence / total_weight if total_weight > 0 else 0
        communication = total_communication / total_weight if total_weight > 0 else 0
        
        return CategoryScore(
            clarity=round(clarity, 2),
            accuracy=round(accuracy, 2),
            confidence=round(confidence, 2),
            communication=round(communication, 2)
        )
    
    def calculate_overall_score(self, category_scores: CategoryScore) -> float:
        """Calculate overall score from category scores"""
        overall = (
            category_scores.clarity +
            category_scores.accuracy +
            category_scores.confidence +
            category_scores.communication
        ) / 4.0
        return round(overall, 2)
    
    def generate_feedback(
        self,
        role: str,
        experience_level: str,
        total_questions: int,
        answered_questions: int,
        category_scores: CategoryScore,
        overall_score: float,
        question_details: List[Dict]
    ) -> Dict:
        """Generate comprehensive feedback using AI"""
        
        if not self.openai_available:
            return self._get_default_feedback(category_scores, overall_score)
        
        try:
            # Format question details
            details_text = ""
            for idx, detail in enumerate(question_details, 1):
                details_text += f"\nQuestion {idx} ({detail.get('type', 'Unknown')}):\n"
                details_text += f"  Score: {detail.get('overall_score', 0)}/100\n"
                details_text += f"  Feedback: {detail.get('feedback', 'No feedback')}\n"
            
            # Create prompt
            prompt = self.feedback_prompt_template.format_messages(
                role=role,
                experience_level=experience_level,
                total_questions=total_questions,
                answered_questions=answered_questions,
                clarity_score=category_scores.clarity,
                accuracy_score=category_scores.accuracy,
                confidence_score=category_scores.confidence,
                communication_score=category_scores.communication,
                overall_score=overall_score,
                question_details=details_text
            )
            
            # Get feedback from OpenAI
            response = self.llm.invoke(prompt)
            content = response.content.strip()
            
            # Try to extract JSON from response
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            # Parse JSON
            try:
                feedback_data = json.loads(content)
            except json.JSONDecodeError:
                # Try to extract JSON object
                import re
                json_match = re.search(r'\{.*\}', content, re.DOTALL)
                if json_match:
                    feedback_data = json.loads(json_match.group())
                else:
                    raise ValueError("Could not parse JSON from feedback response")
            
            return {
                "feedback_summary": feedback_data.get("feedback_summary", "No feedback available."),
                "strengths": feedback_data.get("strengths", []),
                "areas_for_improvement": feedback_data.get("areas_for_improvement", []),
                "recommendations": feedback_data.get("recommendations", [])
            }
            
        except Exception as e:
            print(f"Error generating feedback with AI: {str(e)}")
            return self._get_default_feedback(category_scores, overall_score)
    
    def _get_default_feedback(
        self,
        category_scores: CategoryScore,
        overall_score: float
    ) -> Dict:
        """Get default feedback when AI is not available"""
        
        strengths = []
        improvements = []
        recommendations = []
        
        # Analyze scores to generate basic feedback
        if category_scores.accuracy >= 70:
            strengths.append("Strong technical accuracy in your answers")
        else:
            improvements.append("Technical accuracy needs improvement")
            recommendations.append("Review core technical concepts for your role")
        
        if category_scores.communication >= 70:
            strengths.append("Clear and effective communication")
        else:
            improvements.append("Communication clarity can be enhanced")
            recommendations.append("Practice explaining technical concepts clearly")
        
        if category_scores.confidence >= 70:
            strengths.append("Confident responses")
        else:
            improvements.append("Build more confidence in responses")
            recommendations.append("Practice mock interviews to build confidence")
        
        if category_scores.clarity >= 70:
            strengths.append("Clear and structured answers")
        else:
            improvements.append("Answer structure and clarity")
            recommendations.append("Practice organizing thoughts before answering")
        
        if not strengths:
            strengths.append("Good effort in completing the interview")
        
        if not improvements:
            improvements.append("Continue practicing to maintain performance")
        
        if not recommendations:
            recommendations.append("Continue regular interview practice")
        
        feedback_summary = f"""Based on your interview performance, you achieved an overall score of {overall_score}/100. 
        Your performance shows {'strong' if overall_score >= 70 else 'room for improvement' if overall_score >= 50 else 'significant areas'} in various aspects.
        {'AI evaluation is not available. Please ensure OpenAI API key is configured for detailed feedback.' if not self.openai_available else ''}"""
        
        return {
            "feedback_summary": feedback_summary,
            "strengths": strengths,
            "areas_for_improvement": improvements,
            "recommendations": recommendations
        }
    
    def evaluate_interview(
        self,
        role: str,
        experience_level: str,
        answers: List[Dict],
        total_questions: int
    ) -> Dict:
        """Evaluate complete interview session"""
        
        # Calculate category scores
        category_scores = self.calculate_category_scores(answers)
        
        # Calculate overall score
        overall_score = self.calculate_overall_score(category_scores)
        
        # Prepare question details for feedback
        question_details = []
        for answer in answers:
            question_details.append({
                "type": answer.get("question_type", "Unknown"),
                "overall_score": answer.get("overall_score", 0),
                "feedback": answer.get("ai_feedback", "")
            })
        
        # Generate AI feedback
        feedback_data = self.generate_feedback(
            role=role,
            experience_level=experience_level,
            total_questions=total_questions,
            answered_questions=len(answers),
            category_scores=category_scores,
            overall_score=overall_score,
            question_details=question_details
        )
        
        return {
            "overall_score": overall_score,
            "category_scores": category_scores,
            "feedback_summary": feedback_data["feedback_summary"],
            "strengths": feedback_data["strengths"],
            "areas_for_improvement": feedback_data["areas_for_improvement"],
            "recommendations": feedback_data["recommendations"]
        }

# Create global instance
interview_evaluator = InterviewEvaluator()

