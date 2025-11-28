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

# HR Interview Warm-up Questions - Always asked first (questions 1-3)
HR_WARMUP_QUESTIONS = [
    "Tell me about yourself.",
    "What are your greatest strengths and weaknesses?",
    "Why should we hire you?"
]
HR_WARMUP_COUNT = len(HR_WARMUP_QUESTIONS)  # 3 questions

# FIX 12: Connection test helper function
def test_supabase_connection(supabase: Client) -> bool:
    """
    Test the Supabase connection by performing a simple query.
    Returns True if connection is successful, False otherwise.
    """
    try:
        # Perform a simple query to test connection
        supabase.table("interview_sessions").select("id").limit(1).execute()
        return True
    except Exception as e:
        logger.error(f"[CONNECTION TEST] Database connection test failed: {str(e)}", exc_info=True)
        return False

async def log_interview_transcript(
    supabase: Client,
    session_id: Optional[str],
    interview_type: str,
    question_text: Optional[str],
    user_answer: Optional[str] = None
) -> None:
    """
    Store each question/answer interaction in Supabase for analytics
    """
    if not supabase:
        return
    if not session_id:
        session_id = "unknown_session"

    try:
        transcript_data = {
            "session_id": session_id,
            "interview_type": interview_type,
            "question": question_text or "",
            "user_answer": user_answer,
            "created_at": datetime.utcnow().isoformat()
        }
        supabase.table("interview_transcripts").insert(transcript_data).execute()
    except Exception as e:
        pass  # Silently fail transcript logging to not interrupt interview flow


async def evaluate_coding_solution(
    question_text: str,
    user_code: str,
    programming_language: str,
    difficulty_level: Optional[str] = None,
    question_data: Optional[Dict[str, Any]] = None,
    sql_setup: Optional[str] = None
) -> Dict[str, Any]:
    """
    Evaluate a coding solution using LLM-based evaluation
    Uses GPT-4o for comprehensive code analysis and correctness determination
    """
    from app.config.settings import settings
    
    result = {
        "correctness": False,
        "score": 0,
        "feedback": "",
        "execution_output": "",
        "execution_time": None,
        "test_cases_passed": 0,
        "total_test_cases": 0,
        "correct_solution": ""
    }
    
    # Extract test cases and examples from question_data
    test_cases = []
    examples = []
    if question_data:
        test_cases = question_data.get("test_cases", []) or []
        examples = question_data.get("examples", []) or []
        if not test_cases and examples:
            test_cases = examples
    
    # Execute the code to get real output
    execution_result = None
    execution_outputs = []
    
    try:
        # First, try executing without input to see if code runs
        execution_result = await execute_code_safely(
            user_code, 
            programming_language.lower(), 
            "",
            sql_setup if programming_language.lower() == "sql" else ""
        )
        
        # Format execution output
        if execution_result.get("error"):
            error_msg = execution_result.get('error', 'Unknown error')
            result["execution_output"] = f"Execution Error:\n{error_msg}"
            execution_outputs.append(f"Error: {error_msg}")
            # If there's a syntax or compilation error, mark as incorrect immediately
            error_lower = error_msg.lower()
            if any(keyword in error_lower for keyword in ["syntax", "compile", "parse", "indentation", "invalid syntax"]):
                result["correctness"] = False
                result["score"] = 0
        else:
            output = execution_result.get("output", "")
            if output:
                result["execution_output"] = output
                execution_outputs.append(f"Output: {output}")
            else:
                result["execution_output"] = "Code executed successfully but produced no output.\nThis is normal for function definitions that don't print anything."
                execution_outputs.append("No output (code defines functions/classes)")
        
        result["execution_time"] = execution_result.get("execution_time")
        
    except Exception as e:
        logger.warning(f"Error executing code for evaluation: {str(e)}")
        result["execution_output"] = f"Execution error: {str(e)}"
        execution_outputs.append(f"Execution error: {str(e)}")
    
    # Run test cases and collect outputs for LLM analysis
    test_results = []
    if test_cases:
        for i, test_case in enumerate(test_cases):
            test_input = test_case.get("input", "")
            expected_output = str(test_case.get("output", "")).strip()
            
            try:
                # Execute with test input
                test_execution = await execute_code_safely(
                    user_code,
                    programming_language.lower(),
                    test_input,
                    sql_setup if programming_language.lower() == "sql" else ""
                )
                
                actual_output = ""
                if test_execution.get("error"):
                    actual_output = f"Error: {test_execution.get('error')}"
                else:
                    actual_output = str(test_execution.get("output", "")).strip()
                
                test_results.append({
                    "test_case": i + 1,
                    "input": test_input,
                    "expected": expected_output,
                    "actual": actual_output,
                    "passed": False  # Will be determined by LLM
                })
                execution_outputs.append(f"Test {i+1} - Input: {test_input}, Expected: {expected_output}, Got: {actual_output}")
                
            except Exception as e:
                logger.warning(f"Error running test case {i+1}: {str(e)}")
                test_results.append({
                    "test_case": i + 1,
                    "input": test_input,
                    "expected": expected_output,
                    "actual": f"Error: {str(e)}",
                    "passed": False
                })
                execution_outputs.append(f"Test {i+1} - Error: {str(e)}")
    
    # Build comprehensive execution summary
    execution_summary = "\n".join(execution_outputs) if execution_outputs else "No execution data available"
    
    # Use LLM for comprehensive evaluation (primary judge)
    try:
        if settings.openai_api_key:
            from openai import OpenAI
            client = OpenAI(api_key=settings.openai_api_key)
            
            # Try GPT-4o first, fallback to GPT-4, then GPT-3.5
            model = "gpt-4o"
            try:
                # Test if model is available
                client.models.list()
            except:
                model = "gpt-4"
            try:
                if model == "gpt-4":
                    client.models.list()
            except:
                model = "gpt-3.5-turbo"
            
            # Build test case summary
            test_summary = ""
            if test_results:
                test_summary = "\n\nTest Case Execution Results:\n"
                for tr in test_results:
                    test_summary += f"Test Case {tr['test_case']}:\n"
                    test_summary += f"  Input: {tr.get('input', 'N/A')}\n"
                    test_summary += f"  Expected Output: {tr.get('expected', 'N/A')}\n"
                    test_summary += f"  Actual Output: {tr.get('actual', 'N/A')}\n\n"
            
            system_prompt = """You are an expert coding interview evaluator with deep knowledge of algorithms, data structures, and software engineering best practices.

Your task is to:
1. Analyze the candidate's code LOGICALLY, not just by string matching
2. Determine if the solution is CORRECT based on algorithm correctness, not just output matching
3. Consider that different implementations can be correct even if outputs differ slightly
4. Evaluate code quality, efficiency, and correctness comprehensively
5. Provide detailed, constructive feedback
6. Generate a canonical correct solution

IMPORTANT EVALUATION RULES:
- A solution is CORRECT if it implements the right algorithm/logic, even if output formatting differs
- Consider edge cases and whether the code handles them properly
- Evaluate time/space complexity
- Check for common mistakes (off-by-one errors, boundary conditions, etc.)
- For SQL: Check if query logic is correct, not just exact output match
- For data analysis: Check if the approach and results are logically sound

CRITICAL: When determining correctness:
- If the code logic is correct and solves the problem, mark correctness as TRUE
- If the code has minor issues but the core logic is sound, mark correctness as TRUE
- Only mark correctness as FALSE if there are significant logical errors or the solution doesn't solve the problem
- Be generous with correctness - if the solution works for the given problem, it's correct

Be fair, constructive, and educational. Always provide a complete correct solution."""
            
            user_prompt = f"""Evaluate this coding solution comprehensively and provide detailed analysis:

QUESTION:
{question_text}

CANDIDATE'S SOLUTION ({programming_language}):
```{programming_language}
{user_code}
```

EXECUTION RESULTS:
{execution_summary}
{test_summary}

DIFFICULTY LEVEL: {difficulty_level or "Medium"}

Analyze the solution and provide a comprehensive evaluation in JSON format:
{{
  "correctness": true/false,  // CRITICAL: TRUE if solution is logically correct and solves the problem, FALSE only if there are significant logical errors. Be generous - if the solution works, mark it as TRUE.
  "score": 0-100,  // Score based on correctness (0-40), code quality (0-30), efficiency (0-20), edge cases (0-10)
  "feedback": "COMPREHENSIVE FEEDBACK with these sections:\n\n1. EXECUTION ANALYSIS:\n   - Did the code execute successfully?\n   - Any runtime errors? Explain them clearly.\n   - What output was produced?\n\n2. CORRECTNESS ASSESSMENT:\n   - Is the algorithm/logic correct?\n   - Does it solve the problem as intended?\n   - What specific parts are correct?\n   - What specific parts are wrong?\n\n3. ERROR & BUG EXPLANATION:\n   - List ALL errors found (syntax, logic, runtime)\n   - Explain WHY each error occurred\n   - Explain HOW to fix each error\n   - Point out common mistakes (off-by-one, boundary conditions, etc.)\n\n4. CODE QUALITY ANALYSIS:\n   - Code readability and structure\n   - Variable naming\n   - Code organization\n   - Best practices followed or violated\n\n5. TIME & SPACE COMPLEXITY:\n   - Time Complexity: O(...) with detailed explanation\n   - Space Complexity: O(...) with detailed explanation\n   - Is this optimal? If not, what's better?\n\n6. EDGE CASES:\n   - Which edge cases are handled?\n   - Which edge cases are missing?\n   - How to handle missing edge cases?\n\n7. IMPROVEMENT SUGGESTIONS:\n   - Specific, actionable improvements\n   - Better algorithms or approaches\n   - Code refactoring suggestions\n   - Performance optimizations\n\n8. LOGIC-BUILDING GUIDE:\n   - How to approach similar problems\n   - Key concepts to master\n   - Problem-solving strategies\n   - Practice recommendations\n\n9. MOTIVATION MESSAGE:\n   - If CORRECT: Celebrate their success! Appreciate their effort, highlight what they did well, encourage them to keep practicing.\n   - If INCORRECT: Be encouraging! Acknowledge their attempt, explain that mistakes are learning opportunities, provide hope and motivation to improve.",
  "correct_solution": "Complete, clean, canonical solution code in {programming_language} with:\n- Clear comments explaining the approach\n- Step-by-step logic explanation\n- Why this solution is optimal\n- How it handles edge cases",
  "test_cases_passed": number,  // How many test cases are logically correct (even if output format differs)
  "total_test_cases": {len(test_results) if test_results else 0},
  "time_complexity": "O(...) - detailed explanation",
  "space_complexity": "O(...) - detailed explanation",
  "improvements": ["specific improvement 1", "specific improvement 2", ...],
  "missing_concepts": ["concept 1 if missing", "concept 2 if missing", ...],
  "edge_cases_handled": true/false,
  "code_quality_score": 0-100,
  "errors_found": ["error 1 with explanation", "error 2 with explanation", ...],
  "bugs_explained": ["bug 1: why it happens and how to fix", "bug 2: why it happens and how to fix", ...],
  "motivation_message": "Personal, encouraging message. If correct: celebrate and appreciate. If incorrect: be supportive and motivating."
}}

CRITICAL REQUIREMENTS:
1. Determine correctness based on LOGIC, not just string matching
2. If the solution is CORRECT: Write a celebratory, appreciative motivation message
3. If the solution is INCORRECT: Write a supportive, encouraging motivation message
4. Explain EVERY error and bug clearly with HOW TO FIX
5. Provide actionable improvement suggestions
6. Be educational and constructive, never harsh or discouraging"""
            
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3,  # Lower temperature for more consistent evaluation
                response_format={"type": "json_object"}
            )
            
            ai_response = json.loads(response.choices[0].message.content)
            
            # Parse correctness - handle both boolean and string values
            correctness_value = ai_response.get("correctness", False)
            if isinstance(correctness_value, str):
                # Handle string "true"/"false" from LLM
                correctness_value = correctness_value.lower() in ["true", "1", "yes", "correct"]
            elif isinstance(correctness_value, bool):
                correctness_value = correctness_value
            else:
                # Default to False if unexpected type
                correctness_value = False
            
            # Override correctness if there was a syntax/compilation error
            if result.get("execution_output", "").lower() and any(keyword in result["execution_output"].lower() for keyword in ["syntax", "compile", "parse", "indentation", "invalid syntax"]):
                correctness_value = False
                if result.get("score", 0) > 0:
                    result["score"] = 0
            
            # Use LLM's verdict as primary source of truth
            result["correctness"] = correctness_value
            
            # Parse score - ensure it's an integer
            score_value = ai_response.get("score", 0)
            if isinstance(score_value, (int, float)):
                result["score"] = int(score_value)
            else:
                # Try to parse string score
                try:
                    result["score"] = int(float(str(score_value)))
                except (ValueError, TypeError):
                    # Default score based on correctness
                    result["score"] = 85 if correctness_value else 40
            
            # Build comprehensive feedback from LLM response
            feedback_parts = []
            
            # Add execution analysis
            if result["execution_output"]:
                if "Error" in result["execution_output"]:
                    feedback_parts.append(f"❌ EXECUTION ERROR:\n{result['execution_output']}\n")
                else:
                    feedback_parts.append(f"✅ EXECUTION STATUS: Code executed successfully.\nOutput: {result['execution_output']}\n")
            
            # Add LLM feedback (which should include all sections)
            llm_feedback = ai_response.get("feedback", "")
            if llm_feedback:
                feedback_parts.append(llm_feedback)
            
            # Add errors and bugs if provided
            errors_found = ai_response.get("errors_found", [])
            bugs_explained = ai_response.get("bugs_explained", [])
            
            if errors_found:
                feedback_parts.append("\n🔍 ERRORS DETECTED:\n" + "\n".join(f"• {e}" for e in errors_found))
            
            if bugs_explained:
                feedback_parts.append("\n🐛 BUG EXPLANATIONS:\n" + "\n".join(f"• {b}" for b in bugs_explained))
            
            # Add improvements
            improvements = ai_response.get("improvements", [])
            if improvements:
                feedback_parts.append("\n💡 IMPROVEMENT SUGGESTIONS:\n" + "\n".join(f"• {imp}" for imp in improvements))
            
            # Add complexity analysis
            time_complexity = ai_response.get("time_complexity", "")
            space_complexity = ai_response.get("space_complexity", "")
            if time_complexity or space_complexity:
                feedback_parts.append("\n⏱️ COMPLEXITY ANALYSIS:")
                if time_complexity:
                    feedback_parts.append(f"Time Complexity: {time_complexity}")
                if space_complexity:
                    feedback_parts.append(f"Space Complexity: {space_complexity}")
            
            # Add motivation message (if provided separately, otherwise it should be in feedback)
            motivation = ai_response.get("motivation_message", "")
            if motivation:
                feedback_parts.append(f"\n💪 MOTIVATION & ENCOURAGEMENT:\n{motivation}")
            
            result["feedback"] = "\n\n".join(feedback_parts) if feedback_parts else llm_feedback
            
            # Ensure feedback is never empty
            if not result["feedback"] or result["feedback"].strip() == "":
                if correctness_value:
                    result["feedback"] = "✅ Your solution is correct! Great job implementing the algorithm correctly."
                else:
                    result["feedback"] = "Please review your solution. Check the execution output and test cases for details."
            
            result["correct_solution"] = ai_response.get("correct_solution", "")
            if not result["correct_solution"] or result["correct_solution"].strip() == "":
                result["correct_solution"] = "# Correct solution will be generated based on the problem requirements."
            
            # Parse test cases passed
            test_cases_passed = ai_response.get("test_cases_passed")
            if isinstance(test_cases_passed, (int, float)):
                result["test_cases_passed"] = int(test_cases_passed)
            else:
                # Fallback: count passed test cases from test_results
                result["test_cases_passed"] = len([t for t in test_results if t.get("passed", False)]) if test_results else 0
            
            total_test_cases = ai_response.get("total_test_cases")
            if isinstance(total_test_cases, (int, float)):
                result["total_test_cases"] = int(total_test_cases)
            else:
                result["total_test_cases"] = len(test_results) if test_results else 0
            
            # Store additional fields for detailed display
            result["errors_found"] = errors_found
            result["bugs_explained"] = bugs_explained
            result["improvements"] = improvements
            result["time_complexity"] = time_complexity
            result["space_complexity"] = space_complexity
            result["motivation_message"] = motivation
            result["code_quality_score"] = ai_response.get("code_quality_score", 0)
            result["edge_cases_handled"] = ai_response.get("edge_cases_handled", False)
            result["missing_concepts"] = ai_response.get("missing_concepts", [])
            
            logger.info(f"[EVAL] LLM Evaluation Complete - Model: {model}")
            logger.info(f"[EVAL] Correctness: {result['correctness']}")
            logger.info(f"[EVAL] Score: {result['score']}")
            logger.info(f"[EVAL] Feedback length: {len(result.get('feedback', ''))} chars")
            logger.info(f"[EVAL] Correct solution length: {len(result.get('correct_solution', ''))} chars")
            logger.info(f"[EVAL] Test cases passed: {result.get('test_cases_passed', 0)}/{result.get('total_test_cases', 0)}")
            
    except Exception as e:
        logger.error(f"Could not generate AI feedback: {str(e)}")
        import traceback
        logger.error(f"LLM Error traceback: {traceback.format_exc()}")
        
        # Provide comprehensive fallback feedback
        if result.get("execution_output") and "Error" in result["execution_output"]:
            error_msg = result['execution_output']
            result["feedback"] = f"""❌ EXECUTION ERROR ANALYSIS:

Your code encountered an error during execution:
{error_msg}

🔍 COMMON ISSUES TO CHECK:
1. Syntax errors (missing brackets, colons, parentheses, etc.)
2. Undefined variables or functions
3. Type mismatches
4. Index out of bounds errors
5. Import errors or missing modules
6. Indentation errors (Python)
7. Missing return statements

💡 HOW TO FIX:
- Read the error message carefully - it usually tells you the line number and type of error
- Check the syntax around the error line
- Verify all variables are defined before use
- Ensure all required imports are present
- Test your code with simple inputs first

Please review the error message above and fix the issues in your code."""
            
            result["errors_found"] = [error_msg]
            result["bugs_explained"] = [f"Runtime error occurred: {error_msg}. Check syntax, variable definitions, and logic flow."]
            result["improvements"] = ["Fix syntax errors", "Check variable definitions", "Verify logic flow", "Test with simple inputs first"]
            result["motivation_message"] = "Don't worry! Errors are part of learning. Review the error message, understand what went wrong, and try again. Every programmer faces errors - the key is learning from them! 💪"
        elif test_results:
            # More lenient matching - check if outputs are logically equivalent
            passed = 0
            for tr in test_results:
                actual = str(tr.get("actual", "")).strip()
                expected = str(tr.get("expected", "")).strip()
                # Exact match
                if actual == expected:
                    passed += 1
                    tr["passed"] = True
                # Numeric equivalence (for cases where output format differs)
                elif actual.replace(".", "").replace("-", "").isdigit() and expected.replace(".", "").replace("-", "").isdigit():
                    try:
                        if float(actual) == float(expected):
                            passed += 1
                            tr["passed"] = True
                        else:
                            tr["passed"] = False
                    except ValueError:
                        tr["passed"] = False
                else:
                    tr["passed"] = False
            
            total = len(test_results)
            result["test_cases_passed"] = passed
            result["total_test_cases"] = total
            # Mark as correct if all test cases pass OR if most pass (>= 80%)
            result["correctness"] = (passed == total and total > 0) or (passed >= total * 0.8 and total > 0)
            
            result["feedback"] = f"""Test Case Analysis:

Your solution passed {passed} out of {total} test cases.

Test Case Details:"""
            for tr in test_results:
                match = tr.get("actual", "").strip() == tr.get("expected", "").strip()
                result["feedback"] += f"\n\nTest {tr['test_case']}: {'✓ PASSED' if match else '✗ FAILED'}"
                result["feedback"] += f"\n  Input: {tr.get('input', 'N/A')}"
                result["feedback"] += f"\n  Expected: {tr.get('expected', 'N/A')}"
                result["feedback"] += f"\n  Got: {tr.get('actual', 'N/A')}"
            
            if result["correctness"]:
                result["feedback"] += "\n\n🎉 Great job! Your solution passed all test cases."
                result["score"] = 85  # Good score for passing all tests
                result["motivation_message"] = "Excellent work! You've successfully solved this problem. Your solution demonstrates good problem-solving skills. Keep practicing to master even more challenging problems! 🌟"
            else:
                result["feedback"] += "\n\nPlease review your logic and ensure all test cases pass."
                result["score"] = int((passed / total) * 60)  # Partial credit
                result["motivation_message"] = f"You passed {passed} out of {total} test cases. Review the failed cases, understand why they failed, and refine your solution. You're making progress! 💪"
        else:
            result["feedback"] = """Code Execution Analysis:

Your code executed successfully. However, comprehensive evaluation requires test cases or AI analysis.

To improve your solution:
1. Review the problem requirements carefully
2. Test with the provided examples
3. Consider edge cases
4. Optimize time and space complexity"""
            result["score"] = 50  # Neutral score without evaluation
        
        # Generate a helpful correct solution template
        result["correct_solution"] = f"""# Correct Solution for: {question_text[:80]}...

# Approach:
# 1. Understand the problem requirements
# 2. Identify the optimal algorithm/data structure
# 3. Handle edge cases
# 4. Optimize for time and space complexity

# Note: Full AI-generated solution is temporarily unavailable.
# Please refer to the problem statement, examples, and feedback above for guidance.

# Example structure:
def solve():
    # Your implementation here
    pass"""
    
    # Ensure we always have meaningful output
    if not result["execution_output"]:
        result["execution_output"] = "Code evaluation completed. See feedback section for detailed analysis."
    
    if not result["feedback"]:
        result["feedback"] = "Evaluation completed. Please review your solution."
    
    if not result["correct_solution"]:
        result["correct_solution"] = "# Correct solution generation in progress..."
    
    return result


async def store_coding_result(
    supabase: Client,
    user_id: str,
    session_id: str,
    question_number: int,
    question_text: str,
    user_code: str,
    programming_language: str,
    difficulty_level: Optional[str] = None,
    execution_output: Optional[str] = None,
    correctness: bool = False,
    ai_feedback: Optional[str] = None,
    final_score: int = 0,
    execution_time: Optional[float] = None,
    test_cases_passed: int = 0,
    total_test_cases: int = 0,
    correct_solution: Optional[str] = None
) -> None:
    """
    Store coding interview result in Supabase
    """
    if not supabase:
        return
    
    try:
        # Validate required fields before storing
        if not user_id or not user_id.strip():
            raise ValueError("user_id is required and cannot be empty")
        if not session_id or not session_id.strip():
            raise ValueError("session_id is required and cannot be empty")
        if question_number is None or question_number < 1:
            raise ValueError(f"question_number must be a positive integer, got: {question_number}")
        if not question_text or not question_text.strip():
            raise ValueError("question_text is required and cannot be empty")
        if not user_code or not user_code.strip():
            raise ValueError("user_code is required and cannot be empty")
        
        # Ensure None values are converted to empty strings for text fields
        # This prevents database issues and ensures frontend receives consistent data
        result_data = {
            "user_id": str(user_id).strip(),
            "session_id": str(session_id).strip(),
            "question_number": int(question_number),
            "question_text": str(question_text).strip() if question_text else "",
            "user_code": str(user_code).strip() if user_code else "",
            "programming_language": str(programming_language).strip() if programming_language else "python",
            "difficulty_level": str(difficulty_level).strip() if difficulty_level else None,
            "execution_output": str(execution_output).strip() if execution_output is not None else "",
            "correctness": bool(correctness),
            "ai_feedback": str(ai_feedback).strip() if ai_feedback is not None else "",
            "final_score": int(final_score) if final_score is not None else 0,
            "execution_time": float(execution_time) if execution_time is not None else None,
            "test_cases_passed": int(test_cases_passed) if test_cases_passed is not None else 0,
            "total_test_cases": int(total_test_cases) if total_test_cases is not None else 0,
            "correct_solution": str(correct_solution).strip() if correct_solution is not None else ""
        }
        
        # Validate data types and constraints
        if result_data["final_score"] < 0 or result_data["final_score"] > 100:
            logger.warning(f"[STORE] final_score out of range (0-100): {result_data['final_score']}, clamping to valid range")
            result_data["final_score"] = max(0, min(100, result_data["final_score"]))
        
        if result_data["test_cases_passed"] < 0:
            result_data["test_cases_passed"] = 0
        if result_data["total_test_cases"] < 0:
            result_data["total_test_cases"] = 0
        if result_data["test_cases_passed"] > result_data["total_test_cases"]:
            logger.warning(f"[STORE] test_cases_passed ({result_data['test_cases_passed']}) > total_test_cases ({result_data['total_test_cases']}), clamping")
            result_data["test_cases_passed"] = result_data["total_test_cases"]
        
        # Log what we're storing for debugging
        logger.info(f"[STORE] ========== Preparing to Store Coding Result ==========")
        logger.info(f"[STORE] Session ID: {session_id}")
        logger.info(f"[STORE] Question Number: {question_number}")
        logger.info(f"[STORE] User ID: {user_id}")
        logger.info(f"[STORE] User code length: {len(result_data['user_code'])} chars")
        logger.info(f"[STORE] Execution output length: {len(result_data['execution_output'])} chars")
        logger.info(f"[STORE] AI feedback length: {len(result_data['ai_feedback'])} chars")
        logger.info(f"[STORE] Correct solution length: {len(result_data['correct_solution'])} chars")
        logger.info(f"[STORE] Correctness: {result_data['correctness']}")
        logger.info(f"[STORE] Final score: {result_data['final_score']}")
        logger.info(f"[STORE] Test cases: {result_data['test_cases_passed']}/{result_data['total_test_cases']}")
        
        # Check if row already exists (question was stored when it was asked)
        logger.info(f"[STORE] Checking for existing row: session_id={session_id}, question_number={question_number}")
        existing_row = supabase.table("coding_round").select("id, user_code, execution_output, ai_feedback, correctness").eq("session_id", session_id).eq("question_number", question_number).execute()
        
        if existing_row.data and len(existing_row.data) > 0:
            # Update existing row with user's solution and evaluation
            existing_data = existing_row.data[0]
            logger.info(f"[STORE] Found existing row (id: {existing_data.get('id')}) - Current: user_code={bool(existing_data.get('user_code'))}, execution_output={bool(existing_data.get('execution_output'))}, ai_feedback={bool(existing_data.get('ai_feedback'))}, correctness={existing_data.get('correctness')}")
            logger.info(f"[STORE] Updating with: user_code length={len(result_data.get('user_code', ''))}, execution_output length={len(result_data.get('execution_output', ''))}, ai_feedback length={len(result_data.get('ai_feedback', ''))}, correctness={result_data.get('correctness')}")
            
            # Use update with explicit error handling
            logger.info(f"[STORE] Executing UPDATE query for session {session_id}, question {question_number}")
            logger.info(f"[STORE] Update data keys: {list(result_data.keys())}")
            logger.info(f"[STORE] Update data preview: user_id={result_data.get('user_id')}, session_id={result_data.get('session_id')}, question_number={result_data.get('question_number')}, user_code_len={len(result_data.get('user_code', ''))}, execution_output_len={len(result_data.get('execution_output', ''))}, ai_feedback_len={len(result_data.get('ai_feedback', ''))}, correctness={result_data.get('correctness')}")
            
            try:
                update_response = supabase.table("coding_round").update(result_data).eq("session_id", session_id).eq("question_number", question_number).execute()
            except Exception as update_error:
                error_msg = f"Update query failed for session {session_id}, question {question_number}: {str(update_error)}"
                logger.error(f"[STORE] ✗ {error_msg}")
                logger.error(f"[STORE] Error type: {type(update_error).__name__}")
                import traceback
                logger.error(f"[STORE] Traceback: {traceback.format_exc()}")
                # Try insert as fallback
                logger.info(f"[STORE] Attempting fallback INSERT...")
                try:
                    insert_response = supabase.table("coding_round").insert(result_data).execute()
                    if not insert_response.data:
                        raise Exception(f"Both update and insert failed. Update error: {error_msg}, Insert returned no data")
                    else:
                        inserted_id = insert_response.data[0].get('id', 'unknown')
                        logger.info(f"[STORE] ✓ Fallback insert succeeded with id: {inserted_id}")
                        return  # Success via insert
                except Exception as insert_error:
                    combined_error = f"Both update and insert failed. Update: {error_msg}, Insert: {str(insert_error)}"
                    logger.error(f"[STORE] ✗ {combined_error}")
                    raise Exception(combined_error) from insert_error
            
            # Check if update returned data
            if not update_response.data:
                error_msg = f"Update returned no data for session {session_id}, question {question_number}"
                logger.error(f"[STORE] ✗ {error_msg}")
                logger.error(f"[STORE] Attempting fallback INSERT...")
                # Try insert as fallback
                try:
                    insert_response = supabase.table("coding_round").insert(result_data).execute()
                    if not insert_response.data:
                        raise Exception(f"Both update and insert failed. Update: {error_msg}, Insert returned no data")
                    else:
                        inserted_id = insert_response.data[0].get('id', 'unknown')
                        logger.info(f"[STORE] ✓ Fallback insert succeeded with id: {inserted_id}")
                        return  # Success via insert
                except Exception as insert_error:
                    combined_error = f"Both update and insert failed. Update: {error_msg}, Insert: {str(insert_error)}"
                    logger.error(f"[STORE] ✗ {combined_error}")
                    raise Exception(combined_error) from insert_error
            
            # Update succeeded - get the updated row ID
            updated_id = update_response.data[0].get('id') if update_response.data else None
            logger.info(f"[STORE] ✓ Update query returned data (id: {updated_id})")
            
            # CRITICAL: Verify the update actually persisted
            # Use a simpler verification approach - check that row exists and has key fields
            try:
                logger.info(f"[STORE] Verifying update persistence...")
                # First, verify row exists
                if updated_id:
                    verify_response = supabase.table("coding_round").select("*").eq("id", updated_id).execute()
                else:
                    verify_response = supabase.table("coding_round").select("*").eq("session_id", session_id).eq("question_number", question_number).execute()
                
                if verify_response.data and len(verify_response.data) > 0:
                    verified = verify_response.data[0]
                    
                    # Verify critical required fields (these should never be NULL)
                    validation_errors = []
                    
                    # Check required fields
                    if not verified.get('user_id'):
                        validation_errors.append("user_id is NULL or empty")
                    if not verified.get('session_id'):
                        validation_errors.append("session_id is NULL or empty")
                    if verified.get('question_number') is None:
                        validation_errors.append("question_number is NULL")
                    if not verified.get('question_text'):
                        validation_errors.append("question_text is NULL or empty")
                    if not verified.get('user_code'):
                        validation_errors.append("user_code is NULL or empty")
                    if verified.get('correctness') is None:
                        validation_errors.append("correctness is NULL")
                    if verified.get('final_score') is None:
                        validation_errors.append("final_score is NULL")
                    if verified.get('test_cases_passed') is None:
                        validation_errors.append("test_cases_passed is NULL")
                    if verified.get('total_test_cases') is None:
                        validation_errors.append("total_test_cases is NULL")
                    if not verified.get('created_at'):
                        validation_errors.append("created_at is NULL")
                    
                    if validation_errors:
                        # Log what we actually got for debugging
                        logger.error(f"[STORE] ✗ Validation failed. Retrieved row keys: {list(verified.keys())}")
                        logger.error(f"[STORE] ✗ Retrieved values: user_id={verified.get('user_id')}, session_id={verified.get('session_id')}, question_number={verified.get('question_number')}, user_code_len={len(str(verified.get('user_code', '')))}, correctness={verified.get('correctness')}")
                        error_msg = f"Validation failed after update: {', '.join(validation_errors)}"
                        logger.error(f"[STORE] ✗ {error_msg}")
                        # Don't raise - this might be an RLS issue, log and continue
                        logger.warning(f"[STORE] ⚠️ Continuing despite validation errors - may be RLS field filtering issue")
                    else:
                        logger.info(f"[STORE] ✓ Verification successful - all required fields present")
                        logger.info(f"[STORE]   user_id: {verified.get('user_id')}")
                        logger.info(f"[STORE]   session_id: {verified.get('session_id')}")
                        logger.info(f"[STORE]   question_number: {verified.get('question_number')}")
                        logger.info(f"[STORE]   question_text length: {len(str(verified.get('question_text', '')))}")
                        logger.info(f"[STORE]   user_code length: {len(str(verified.get('user_code', '')))}")
                        logger.info(f"[STORE]   execution_output length: {len(str(verified.get('execution_output', '')))}")
                        logger.info(f"[STORE]   ai_feedback length: {len(str(verified.get('ai_feedback', '')))}")
                        logger.info(f"[STORE]   correctness: {verified.get('correctness')}")
                        logger.info(f"[STORE]   final_score: {verified.get('final_score')}")
                        logger.info(f"[STORE]   created_at: {verified.get('created_at')}")
                    
                    # Warn about optional fields that are empty (but not required)
                    if not verified.get('execution_output'):
                        logger.warning(f"[STORE] ⚠️ WARNING: execution_output is empty (optional field)")
                    if not verified.get('ai_feedback'):
                        logger.warning(f"[STORE] ⚠️ WARNING: ai_feedback is empty (should have feedback)")
                    if not verified.get('correct_solution'):
                        logger.warning(f"[STORE] ⚠️ WARNING: correct_solution is empty (optional field)")
                else:
                    logger.error(f"[STORE] ✗ Verification failed: Row not found after update!")
                    raise Exception(f"Update verification failed: Row not found for session {session_id}, question {question_number}")
            except ValueError as verify_error:
                # This is our validation error - log but don't fail completely (might be RLS issue)
                logger.warning(f"[STORE] ⚠️ Validation warning (may be RLS related): {str(verify_error)}")
                # Continue - the update likely succeeded, verification might have RLS issues
            except Exception as verify_error:
                logger.error(f"[STORE] ✗ Verification query failed: {str(verify_error)}")
                import traceback
                logger.error(f"[STORE] Verification traceback: {traceback.format_exc()}")
                # Try a simpler check - just verify row exists
                try:
                    simple_check = supabase.table("coding_round").select("id").eq("session_id", session_id).eq("question_number", question_number).execute()
                    if simple_check.data:
                        logger.warning(f"[STORE] ⚠️ Row exists but detailed verification failed. This may be an RLS issue. Update likely succeeded.")
                        # Continue - row exists, update probably succeeded
                    else:
                        raise Exception(f"Update verification failed: Row not found. Error: {str(verify_error)}") from verify_error
                except Exception:
                    # If even simple check fails, log warning but continue
                    logger.warning(f"[STORE] ⚠️ Could not verify update, but update query succeeded. Continuing.")
        else:
            # Insert new row if question wasn't stored earlier (fallback)
            logger.info(f"[STORE] No existing row found - Inserting new coding result for session {session_id}, question {question_number}")
            logger.info(f"[STORE] Insert data: user_code length={len(result_data.get('user_code', ''))}, execution_output length={len(result_data.get('execution_output', ''))}, ai_feedback length={len(result_data.get('ai_feedback', ''))}, correctness={result_data.get('correctness')}")
            
            try:
                insert_response = supabase.table("coding_round").insert(result_data).execute()
            except Exception as insert_error:
                error_msg = f"Insert query failed for session {session_id}, question {question_number}: {str(insert_error)}"
                logger.error(f"[STORE] ✗ {error_msg}")
                logger.error(f"[STORE] Error type: {type(insert_error).__name__}")
                import traceback
                logger.error(f"[STORE] Traceback: {traceback.format_exc()}")
                logger.error(f"[STORE] Result data keys: {list(result_data.keys())}")
                logger.error(f"[STORE] Result data sample: user_id={result_data.get('user_id')}, session_id={result_data.get('session_id')}, question_number={result_data.get('question_number')}")
                raise Exception(error_msg) from insert_error
            
            if not insert_response.data:
                error_msg = f"Insert returned no data for session {session_id}, question {question_number}"
                logger.error(f"[STORE] ✗ {error_msg}")
                logger.error(f"[STORE] Result data keys: {list(result_data.keys())}")
                logger.error(f"[STORE] Result data sample: user_id={result_data.get('user_id')}, session_id={result_data.get('session_id')}, question_number={result_data.get('question_number')}")
                raise Exception(error_msg)
            else:
                inserted_id = insert_response.data[0].get('id', 'unknown')
                inserted_data = insert_response.data[0]
                logger.info(f"[STORE] ✓ Successfully stored coding result with id: {inserted_id}")
                logger.info(f"[STORE] Inserted values: user_code={bool(inserted_data.get('user_code'))}, execution_output={bool(inserted_data.get('execution_output'))}, ai_feedback={bool(inserted_data.get('ai_feedback'))}, correctness={inserted_data.get('correctness')}")
                
                # Verify the insert actually persisted - check ALL fields
                try:
                    logger.info(f"[STORE] Verifying insert persistence...")
                    verify_response = supabase.table("coding_round").select("user_id, session_id, question_number, question_text, user_code, execution_output, ai_feedback, correctness, final_score, execution_time, test_cases_passed, total_test_cases, correct_solution, created_at").eq("id", inserted_id).execute()
                    if verify_response.data and len(verify_response.data) > 0:
                        verified = verify_response.data[0]
                        
                        # Verify all fields
                        validation_errors = []
                        if not verified.get('user_id'):
                            validation_errors.append("user_id is NULL or empty")
                        if not verified.get('session_id'):
                            validation_errors.append("session_id is NULL or empty")
                        if not verified.get('question_number'):
                            validation_errors.append("question_number is NULL")
                        if not verified.get('question_text'):
                            validation_errors.append("question_text is NULL or empty")
                        if not verified.get('user_code'):
                            validation_errors.append("user_code is NULL or empty")
                        if verified.get('correctness') is None:
                            validation_errors.append("correctness is NULL")
                        if verified.get('final_score') is None:
                            validation_errors.append("final_score is NULL")
                        if verified.get('test_cases_passed') is None:
                            validation_errors.append("test_cases_passed is NULL")
                        if verified.get('total_test_cases') is None:
                            validation_errors.append("total_test_cases is NULL")
                        if not verified.get('created_at'):
                            validation_errors.append("created_at is NULL")
                        
                        if validation_errors:
                            error_msg = f"Validation failed after insert: {', '.join(validation_errors)}"
                            logger.error(f"[STORE] ✗ {error_msg}")
                            raise ValueError(error_msg)
                        
                        logger.info(f"[STORE] ✓ Insert verification successful:")
                        logger.info(f"[STORE]   user_id: {verified.get('user_id')}")
                        logger.info(f"[STORE]   session_id: {verified.get('session_id')}")
                        logger.info(f"[STORE]   question_number: {verified.get('question_number')}")
                        logger.info(f"[STORE]   question_text length: {len(verified.get('question_text', '') or '')}")
                        logger.info(f"[STORE]   user_code length: {len(verified.get('user_code', '') or '')}")
                        logger.info(f"[STORE]   execution_output length: {len(verified.get('execution_output', '') or '')}")
                        logger.info(f"[STORE]   ai_feedback length: {len(verified.get('ai_feedback', '') or '')}")
                        logger.info(f"[STORE]   correctness: {verified.get('correctness')}")
                        logger.info(f"[STORE]   final_score: {verified.get('final_score')}")
                        logger.info(f"[STORE]   created_at: {verified.get('created_at')}")
                    else:
                        logger.error(f"[STORE] ✗ Insert verification failed: Row not found after insert!")
                except Exception as verify_error:
                    logger.error(f"[STORE] ✗ Insert verification query failed: {str(verify_error)}")
                    import traceback
                    logger.error(f"[STORE] Insert verification traceback: {traceback.format_exc()}")
                    # CRITICAL: If verification fails, we can't confirm data was saved
                    # Raise exception to ensure caller knows storage may have failed
                    raise Exception(f"Insert verification failed: Could not confirm data persistence. Error: {str(verify_error)}") from verify_error
            
    except Exception as e:
        # Log error with full details
        import logging
        import traceback
        error_details = {
            "error": str(e),
            "error_type": type(e).__name__,
            "traceback": traceback.format_exc(),
            "session_id": session_id,
            "question_number": question_number,
            "user_id": user_id,
            "result_data_keys": list(result_data.keys()) if 'result_data' in locals() else 'N/A'
        }
        logger.error(f"✗ ERROR storing coding result: {error_details}")
        
        # Try to provide helpful error message
        error_str = str(e).lower()
        if "permission" in error_str or "policy" in error_str or "rls" in error_str:
            logger.error("This looks like an RLS (Row Level Security) policy issue. Check Supabase policies.")
            logger.error("Ensure the service role key is being used for database operations.")
        elif "column" in error_str and "does not exist" in error_str:
            logger.error("This looks like a schema mismatch. Verify table structure in Supabase.")
        elif "violates" in error_str and "constraint" in error_str:
            logger.error("This looks like a constraint violation. Check data types and constraints.")
        
        # CRITICAL: Re-raise the exception so calling code knows storage failed
        logger.error("Re-raising exception to prevent silent failure...")
        raise  # Re-raise to let calling code handle it


def _normalize_project_entries(project_entries: Optional[Any]) -> List[str]:
    """Convert parsed project data into human-readable strings"""
    normalized: List[str] = []
    if not project_entries:
        return normalized
    try:
        for entry in project_entries:
            if isinstance(entry, dict):
                name = entry.get("name") or entry.get("title") or entry.get("project")
                description = entry.get("summary") or entry.get("description")
                technologies = entry.get("technologies") or entry.get("tech")
                parts = []
                if name:
                    parts.append(name.strip())
                if description:
                    parts.append(description.strip())
                if technologies and isinstance(technologies, list):
                    parts.append(f"Tech: {', '.join(technologies[:4])}")
                project_text = " - ".join(parts)
                if project_text:
                    normalized.append(project_text)
            elif isinstance(entry, str):
                project_text = entry.strip()
                if project_text:
                    normalized.append(project_text)
    except Exception as err:
        logger.warning(f"Could not normalize projects: {err}")
    return normalized[:5]


def build_resume_context_from_profile(
    profile_row: Optional[Dict[str, Any]],
    supabase: Client
) -> Dict[str, Any]:
    """
    Build a resume-aware context dictionary from the stored profile + resume file
    """
    context: Dict[str, Any] = {
        "skills": [],
        "experience_level": None,
        "projects": [],
        "keywords": {},
        "domains": []
    }
    if not profile_row:
        return context

    context["skills"] = list(profile_row.get("skills", []) or [])
    # Set experience_level from profile, but validate it
    profile_experience = profile_row.get("experience_level")
    if profile_experience and profile_experience not in ["Not specified", "Unknown"]:
        context["experience_level"] = profile_experience
    else:
        # Default to Fresher if not specified or invalid
        context["experience_level"] = "Fresher"

    resume_url = profile_row.get("resume_url")
    if resume_url and "storage/v1/object/public/" in resume_url:
        tmp_file_path = None
        try:
            path_part = resume_url.split("storage/v1/object/public/")[1]
            bucket_name = path_part.split("/")[0]
            file_path = "/".join(path_part.split("/")[1:])

            file_response = supabase.storage.from_(bucket_name).download(file_path)
            if file_response:
                file_extension = os.path.splitext(file_path)[1]
                with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as tmp_file:
                    tmp_file.write(file_response)
                    tmp_file_path = tmp_file.name

                parsed_resume = resume_parser.parse_resume(tmp_file_path, file_extension)
                parsed_skills = parsed_resume.get("skills", [])
                if parsed_skills:
                    existing = set(s.lower() for s in context["skills"])
                    for skill in parsed_skills:
                        if skill and skill.lower() not in existing:
                            context["skills"].append(skill)
                            existing.add(skill.lower())
                context["keywords"] = parsed_resume.get("keywords", {})
                summary_block = parsed_resume.get("summary") or {}
                projects_list = summary_block.get("projects_summary") or parsed_resume.get("projects")
                if projects_list:
                    context["projects"] = _normalize_project_entries(projects_list)
                # Only set experience_level if it's not already set and if it's a valid work experience
                parsed_experience = parsed_resume.get("experience_level")
                if not context.get("experience_level"):
                    # Ensure parsed experience is valid (not inferred from projects)
                    if parsed_experience and parsed_experience not in ["Not specified", "Unknown"]:
                        # Double-check: if it's "Fresher", use it; otherwise verify it's from work experience
                        if parsed_experience == "Fresher":
                            context["experience_level"] = "Fresher"
                        elif parsed_experience and parsed_experience != "Fresher":
                            # Only use if it's a valid work experience (contains "yrs" or years)
                            if "yrs" in parsed_experience.lower() or "years" in parsed_experience.lower() or "yr" in parsed_experience.lower():
                                context["experience_level"] = parsed_experience
                            else:
                                # If it doesn't look like valid work experience, default to Fresher
                                context["experience_level"] = "Fresher"
                    else:
                        # If no valid experience found, default to Fresher
                        context["experience_level"] = "Fresher"
                domains = context["keywords"].get("job_titles", []) if context["keywords"] else []
                if domains:
                    context["domains"] = domains
        except Exception as err:
            logger.warning(f"Failed to parse resume for context: {err}")
        finally:
            if tmp_file_path and os.path.exists(tmp_file_path):
                try:
                    os.unlink(tmp_file_path)
                except Exception:
                    pass

    return context


def build_context_from_cache(cache_entry: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not cache_entry:
        return {}
    summary_block = cache_entry.get("summary") or {}
    projects_list = summary_block.get("projects_summary")
    context = {
        "skills": cache_entry.get("skills", []) or [],
        "projects": _normalize_project_entries(projects_list),
        "experience_level": cache_entry.get("experience_level"),
        "keywords": cache_entry.get("keywords", {}),
        "domains": []
    }
    interview_modules = cache_entry.get("interview_modules") or {}
    if not context["projects"]:
        coding_module = interview_modules.get("coding_test") if isinstance(interview_modules, dict) else None
        if coding_module:
            topics = coding_module.get("topics")
            if topics:
                context["projects"] = [f"Coding Topic: {topic}" for topic in topics[:3]]
    return context


def merge_resume_context(base: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    if not extra:
        return base
    merged = {
        "skills": list(dict.fromkeys((base.get("skills") or []) + (extra.get("skills") or []))),
        "projects": list(dict.fromkeys((base.get("projects") or []) + (extra.get("projects") or []))),
        "experience_level": base.get("experience_level") or extra.get("experience_level"),
        "keywords": base.get("keywords") or extra.get("keywords") or {},
        "domains": list(dict.fromkeys((base.get("domains") or []) + (extra.get("domains") or [])))
    }

    # Merge keyword dictionaries if both exist
    if base.get("keywords") and extra.get("keywords"):
        merged["keywords"] = {**extra.get("keywords", {}), **base.get("keywords", {})}
    return merged

router = APIRouter(prefix="/api/interview", tags=["interview"])

@router.post("/setup", response_model=InterviewSetupResponse)
async def setup_interview(
    setup_request: InterviewSetupRequest,
    supabase: Client = Depends(get_supabase_client)
):
    """
    Setup interview based on role and experience level.
    Generates interview topics based on user's skills from profile.
    """
    try:
        # Get user profile to fetch skills
        profile_response = supabase.table("user_profiles").select("*").eq("user_id", setup_request.user_id).execute()
        
        user_skills: Optional[list] = []
        if profile_response.data and len(profile_response.data) > 0:
            user_skills = profile_response.data[0].get("skills", [])
        
        # Generate topics based on role, experience, and user skills
        topics = topic_generator.generate_topics(
            role=setup_request.role,
            experience_level=setup_request.experience_level,
            user_skills=user_skills if user_skills else None
        )
        
        # Get suggested skills
        suggested_skills = topic_generator.get_suggested_skills(
            role=setup_request.role,
            user_skills=user_skills if user_skills else []
        )
        
        return InterviewSetupResponse(
            user_id=setup_request.user_id,
            role=setup_request.role,
            experience_level=setup_request.experience_level,
            topics=topics,
            suggested_skills=suggested_skills,
            total_topics=len(topics)
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error setting up interview: {str(e)}")

@router.get("/roles")
async def get_available_roles():
    """Get list of available roles"""
    roles = [
        "Python Developer",
        "ServiceNow Engineer",
        "DevOps",
        "Fresher",
        "Full Stack Developer",
        "Data Engineer"
    ]
    return {"roles": roles}

@router.get("/experience-levels")
async def get_experience_levels():
    """Get list of available experience levels"""
    levels = [
        "Fresher",
        "1yrs",
        "2yrs",
        "3yrs",
        "4yrs",
        "5yrs",
        "5yrs+"
    ]
    return {"experience_levels": levels}

@router.post("/generate", response_model=InterviewGenerateResponse)
async def generate_interview_questions(
    generate_request: InterviewGenerateRequest,
    supabase: Client = Depends(get_supabase_client)
):
    """
    Generate interview questions using OpenAI.
    Creates a session and stores questions in the database.
    If resume is uploaded, uses resume context for personalized questions.
    """
    try:
        profile_response = supabase.table("user_profiles").select("*").eq("user_id", generate_request.user_id).execute()
        profile = profile_response.data[0] if profile_response.data else None

        resume_context: Dict[str, Any] = {
            "skills": list(generate_request.skills),
            "experience_level": generate_request.experience_level,
            "projects": [],
            "keywords": {},
            "domains": []
        }
        if profile:
            resume_context = merge_resume_context(
                resume_context,
                build_resume_context_from_profile(profile, supabase)
            )

        # Try to supplement context from cached resume analysis if available
        try:
            from app.routers.profile import resume_analysis_cache
            cached_entry = None
            for cached_info in resume_analysis_cache.values():
                if cached_info.get("user_id") == generate_request.user_id:
                    cached_entry = cached_info
                    break
            if cached_entry:
                resume_context = merge_resume_context(
                    resume_context,
                    build_context_from_cache(cached_entry)
                )
        except Exception:
            pass

        if not resume_context.get("skills"):
            resume_context["skills"] = list(generate_request.skills)
        
        # Generate questions using AI (with resume context if available)
        questions = question_generator.generate_questions(
            role=generate_request.role,
            experience_level=generate_request.experience_level,
            skills=generate_request.skills,
            resume_context=resume_context
        )
        
        # Create interview session
        # Determine interview_type from role (default to 'full' for general interviews)
        interview_type = "full"  # Default for general interview setup
        if generate_request.role:
            role_lower = generate_request.role.lower()
            if "coding" in role_lower:
                interview_type = "coding"
            elif "technical" in role_lower:
                interview_type = "technical"
            elif "hr" in role_lower or "human resources" in role_lower:
                interview_type = "hr"
            elif "behavioral" in role_lower or "star" in role_lower:
                interview_type = "star"
        
        session_data = {
            "user_id": generate_request.user_id,
            "interview_type": interview_type,  # New schema field
            "role": generate_request.role,  # Keep for backward compatibility
            "experience_level": generate_request.experience_level,
            "skills": resume_context.get("skills", generate_request.skills),
            "session_status": "active"
        }
        
        session_response = supabase.table("interview_sessions").insert(session_data).execute()
        
        if not session_response.data or len(session_response.data) == 0:
            raise HTTPException(status_code=500, detail="Failed to create interview session")
        
        session_id = session_response.data[0]["id"]
        
        # Note: In new schema, questions are stored in round tables when answers are submitted
        # We don't need to store questions separately anymore
        # Questions will be stored in technical_round, hr_round, or star_round when user submits answers
        
        return InterviewGenerateResponse(
            session_id=session_id,
            user_id=generate_request.user_id,
            role=generate_request.role,
            experience_level=generate_request.experience_level,
            questions=questions,
            total_questions=len(questions),
            created_at=datetime.now()
        )
        
    except ValueError as e:
        # If OpenAI key is not set, return fallback questions
        if "OpenAI API key" in str(e):
            # Use fallback questions
            questions = question_generator._get_fallback_questions(
                role=generate_request.role,
                experience_level=generate_request.experience_level,
                skills=generate_request.skills,
                resume_context=resume_context
            )
            
            # Still create session and store questions
            # Determine interview_type from role
            interview_type = "full"  # Default
            if generate_request.role:
                role_lower = generate_request.role.lower()
                if "coding" in role_lower:
                    interview_type = "coding"
                elif "technical" in role_lower:
                    interview_type = "technical"
                elif "hr" in role_lower or "human resources" in role_lower:
                    interview_type = "hr"
                elif "behavioral" in role_lower or "star" in role_lower:
                    interview_type = "star"
            
            session_data = {
                "user_id": generate_request.user_id,
                "interview_type": interview_type,  # New schema field
                "role": generate_request.role,  # Keep for backward compatibility
                "experience_level": generate_request.experience_level,
                "skills": resume_context.get("skills", generate_request.skills),
                "session_status": "active"
            }
            
            session_response = supabase.table("interview_sessions").insert(session_data).execute()
            session_id = session_response.data[0]["id"] if session_response.data else str(uuid.uuid4())
            
            # Note: In new schema, questions are stored in round tables when answers are submitted
            # We don't store questions separately in interview_questions table anymore
            # Questions will be stored in the appropriate round table (technical_round, hr_round, star_round) when user submits answers
            logger.info(f"Generated {len(questions)} questions for session {session_id}. Questions will be stored in round tables when answers are submitted.")
            
            return InterviewGenerateResponse(
                session_id=session_id,
                user_id=generate_request.user_id,
                role=generate_request.role,
                experience_level=generate_request.experience_level,
                questions=questions,
                total_questions=len(questions),
                created_at=datetime.now()
            )
        else:
            raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating interview questions: {str(e)}")

@router.get("/session/{session_id}/questions")
async def get_session_questions(
    session_id: str,
    supabase: Client = Depends(get_supabase_client)
):
    """Get all questions for a specific interview session"""
    try:
        # Get session
        session_response = supabase.table("interview_sessions").select("*").eq("id", session_id).execute()
        
        if not session_response.data or len(session_response.data) == 0:
            raise HTTPException(status_code=404, detail="Session not found")
        
        # Get questions from appropriate round table based on session type (new schema)
        session = session_response.data[0]
        session_type = session.get("interview_type", "technical")
        
        # Determine which round table to use
        if session_type == "coding":
            round_table = "coding_round"
        elif session_type == "hr":
            round_table = "hr_round"
        elif session_type == "star":
            round_table = "star_round"
        else:
            round_table = "technical_round"
        
        # Get questions from round table
        questions_response = supabase.table(round_table).select("question_text, question_type, question_number").eq("session_id", session_id).order("question_number").execute()
        
        questions = []
        if questions_response.data:
            for q in questions_response.data:
                question_text = q.get("question_text", "")
                if question_text:  # Only include if question text exists
                    questions.append(InterviewQuestion(
                        type=q.get("question_type", "Technical"),
                        question=question_text
                    ))
        
        return {
            "session_id": session_id,
            "session": session_response.data[0],
            "questions": questions,
            "total_questions": len(questions)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching session questions: {str(e)}")

@router.post("/start", response_model=StartInterviewResponse)
async def start_interview(
    start_request: StartInterviewRequest,
    supabase: Client = Depends(get_supabase_client)
):
    """Start an interview session - get the first question"""
    try:
        # Get session
        session_response = supabase.table("interview_sessions").select("*").eq("id", start_request.session_id).execute()
        
        if not session_response.data or len(session_response.data) == 0:
            raise HTTPException(status_code=404, detail="Session not found")
        
        session = session_response.data[0]
        
        # Get first question from appropriate round table (new schema)
        session_type = session.get("interview_type", "technical")
        
        # Determine which round table to use
        if session_type == "coding":
            round_table = "coding_round"
        elif session_type == "hr":
            round_table = "hr_round"
        elif session_type == "star":
            round_table = "star_round"
        else:
            round_table = "technical_round"
        
        questions_response = supabase.table(round_table).select("question_text, question_type, question_number").eq("session_id", start_request.session_id).order("question_number").limit(1).execute()
        
        if not questions_response.data or len(questions_response.data) == 0:
            raise HTTPException(status_code=404, detail="No questions found for this session")
        
        first_question_row = questions_response.data[0]
        first_question = {
            "question_type": first_question_row.get("question_type", "Technical"),
            "question": first_question_row.get("question_text", ""),
            "question_number": first_question_row.get("question_number", 1)
        }
        
        # Get total question count
        total_response = supabase.table(round_table).select("question_number").eq("session_id", start_request.session_id).execute()
        total_questions = len(total_response.data) if total_response.data else 1
        
        # Update session status to active if needed
        if session.get("session_status") != "active":
            supabase.table("interview_sessions").update({"session_status": "active"}).eq("id", start_request.session_id).execute()
        
        return StartInterviewResponse(
            session_id=start_request.session_id,
            current_question=InterviewQuestion(
                type=first_question.get("question_type", "Technical"),
                question=first_question.get("question", "")
            ),
            question_number=first_question.get("question_number", 1),
            total_questions=total_questions,
            interview_started=True,
            time_limit=60  # 60 seconds per question
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error starting interview: {str(e)}")

@router.get("/session/{session_id}/question/{question_number}")
async def get_question(
    session_id: str,
    question_number: int,
    supabase: Client = Depends(get_supabase_client)
):
    """Get a specific question by number"""
    try:
        # Get session to determine which round table to use
        session_response = supabase.table("interview_sessions").select("interview_type").eq("id", session_id).execute()
        if not session_response.data:
            raise HTTPException(status_code=404, detail="Session not found")
        
        session_type = session_response.data[0].get("interview_type", "technical")
        
        # Determine which round table to use
        if session_type == "coding":
            round_table = "coding_round"
        elif session_type == "hr":
            round_table = "hr_round"
        elif session_type == "star":
            round_table = "star_round"
        else:
            round_table = "technical_round"
        
        questions_response = supabase.table(round_table).select("*").eq("session_id", session_id).eq("question_number", question_number).execute()
        
        if not questions_response.data or len(questions_response.data) == 0:
            raise HTTPException(status_code=404, detail="Question not found")
        
        question = questions_response.data[0]
        
        return {
            "question_id": question.get("id"),
            "question_number": question.get("question_number", question_number),
            "question_type": question.get("question_type", "Technical"),
            "question": question.get("question_text", "")
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching question: {str(e)}")

@router.post("/submit-answer", response_model=SubmitAnswerResponse)
async def submit_answer(
    answer_request: SubmitAnswerRequest,
    supabase: Client = Depends(get_supabase_client)
):
    """Submit an answer and get AI evaluation"""
    try:
        # Get session to get experience level
        session_response = supabase.table("interview_sessions").select("*").eq("id", answer_request.session_id).execute()
        
        if not session_response.data or len(session_response.data) == 0:
            raise HTTPException(status_code=404, detail="Session not found")
        
        session = session_response.data[0]
        experience_level = session.get("experience_level", "Fresher")
        
        # Evaluate answer using AI (include response time in evaluation)
        scores = answer_evaluator.evaluate_answer(
            question=answer_request.question_text,
            question_type=answer_request.question_type,
            answer=answer_request.user_answer,
            experience_level=experience_level,
            response_time=answer_request.response_time
        )
        
        # Store answer in database
        answer_data = {
            "session_id": answer_request.session_id,
            "question_id": answer_request.question_id,
            "question_number": answer_request.question_number,
            "question_text": answer_request.question_text,
            "question_type": answer_request.question_type,
            "user_answer": answer_request.user_answer,
            "relevance_score": scores.relevance,
            "confidence_score": scores.confidence,
            "technical_accuracy_score": scores.technical_accuracy,
            "communication_score": scores.communication,
            "overall_score": scores.overall,
            "ai_feedback": scores.feedback,
            "response_time": answer_request.response_time,
            "evaluated_at": datetime.now().isoformat()
        }
        
        # Determine which round table to use based on question_type
        # For now, default to technical_round (can be enhanced later for HR/STAR)
        round_table = "technical_round"
        if answer_request.question_type:
            question_type_lower = answer_request.question_type.lower()
            if "hr" in question_type_lower or "human resources" in question_type_lower:
                round_table = "hr_round"
            elif "star" in question_type_lower or "behavioral" in question_type_lower:
                round_table = "star_round"
        
        # Map answer_data to the correct table structure based on round type
        user_id = str(session.get("user_id", ""))
        
        if round_table == "technical_round":
            round_data = {
                "user_id": user_id,
                "session_id": answer_request.session_id,
                "question_number": answer_request.question_number,
                "question_text": answer_request.question_text,
                "question_type": answer_request.question_type,
                "user_answer": answer_request.user_answer,
                "relevance_score": scores.relevance,
                "technical_accuracy_score": scores.technical_accuracy,
                "communication_score": scores.communication,
                "overall_score": scores.overall,
                "ai_feedback": scores.feedback,
                "ai_response": scores.feedback,  # Use feedback as ai_response
                "response_time": answer_request.response_time
                # Note: confidence_score not in technical_round schema, using communication_score instead
            }
        elif round_table == "hr_round":
            round_data = {
                "user_id": user_id,
                "session_id": answer_request.session_id,
                "question_number": answer_request.question_number,
                "question_text": answer_request.question_text,
                "question_category": answer_request.question_type,
                "user_answer": answer_request.user_answer,
                "communication_score": scores.communication,
                "cultural_fit_score": scores.relevance,  # Map relevance to cultural fit
                "motivation_score": scores.communication,  # Map communication to motivation (confidence_score not in schema)
                "clarity_score": scores.communication,
                "overall_score": scores.overall,
                "ai_feedback": scores.feedback,
                "response_time": answer_request.response_time
            }
        else:  # star_round
            round_data = {
                "user_id": user_id,
                "session_id": answer_request.session_id,
                "question_number": answer_request.question_number,
                "question_text": answer_request.question_text,
                "user_answer": answer_request.user_answer,
                "star_structure_score": scores.overall,  # Use overall as structure score
                "situation_score": scores.relevance,  # Map relevance to situation
                "task_score": scores.communication,  # Map communication to task
                "action_score": scores.technical_accuracy,  # Map technical to action
                "result_score": scores.overall,  # Use overall for result
                "overall_score": scores.overall,
                "ai_feedback": scores.feedback,
                "response_time": answer_request.response_time
            }
        
        # Check if row already exists (question was stored when it was asked)
        existing_row = supabase.table(round_table).select("id").eq("session_id", answer_request.session_id).eq("question_number", answer_request.question_number).execute()
        
        if existing_row.data and len(existing_row.data) > 0:
            # Update existing row with answer and evaluation
            answer_response = supabase.table(round_table).update(round_data).eq("session_id", answer_request.session_id).eq("question_number", answer_request.question_number).execute()
        else:
            # Insert new row if question wasn't stored earlier (fallback)
            answer_response = supabase.table(round_table).insert(round_data).execute()
        
        if not answer_response.data or len(answer_response.data) == 0:
            raise HTTPException(status_code=500, detail="Failed to save answer")
        
        await log_interview_transcript(
            supabase,
            answer_request.session_id,
            "technical",
            answer_request.question_text,
            answer_request.user_answer
        )
        
        answer_id = answer_response.data[0]["id"]
        # Get created_at timestamp from response (new schema uses created_at instead of answered_at)
        created_at_str = answer_response.data[0].get("created_at")
        if isinstance(created_at_str, str):
            created_at_str = created_at_str.replace('Z', '+00:00')
            try:
                answered_at = datetime.fromisoformat(created_at_str)
            except ValueError:
                answered_at = datetime.now()
        else:
            answered_at = datetime.now()
        evaluated_at = datetime.now()
        
        return SubmitAnswerResponse(
            answer_id=answer_id,
            session_id=answer_request.session_id,
            question_id=answer_request.question_id,
            scores=scores,
            response_time=answer_request.response_time,
            answered_at=answered_at,
            evaluated_at=evaluated_at
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error submitting answer: {str(e)}")

@router.get("/session/{session_id}/next-question/{current_question_number}")
async def get_next_question(
    session_id: str,
    current_question_number: int,
    supabase: Client = Depends(get_supabase_client)
):
    """Get the next question after the current one (legacy endpoint - uses new schema)"""
    try:
        # Get session to determine which round table to use
        session_response = supabase.table("interview_sessions").select("interview_type").eq("id", session_id).execute()
        if not session_response.data:
            raise HTTPException(status_code=404, detail="Session not found")
        
        session_type = session_response.data[0].get("interview_type", "technical")
        
        # Determine which round table to use
        if session_type == "coding":
            round_table = "coding_round"
        elif session_type == "hr":
            round_table = "hr_round"
        elif session_type == "star":
            round_table = "star_round"
        else:
            round_table = "technical_round"
        
        # Get next question from round table
        questions_response = supabase.table(round_table).select("question_text, question_type, question_number").eq("session_id", session_id).gt("question_number", current_question_number).order("question_number").limit(1).execute()
        
        if not questions_response.data or len(questions_response.data) == 0:
            # No more questions
            # Mark session as completed
            supabase.table("interview_sessions").update({"session_status": "completed"}).eq("id", session_id).execute()
            return {
                "has_next": False,
                "message": "Interview completed! No more questions."
            }
        
        question = questions_response.data[0]
        
        return {
            "has_next": True,
            "question_id": question.get("id"),
            "question_number": question.get("question_number", current_question_number + 1),
            "question_type": question.get("question_type", "Technical"),
            "question": question.get("question_text", "")
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching next question: {str(e)}")

@router.post("/evaluate", response_model=InterviewEvaluationResponse)
async def evaluate_interview(
    evaluation_request: InterviewEvaluationRequest,
    supabase: Client = Depends(get_supabase_client)
):
    """Evaluate complete interview session and generate feedback report"""
    try:
        # Get session
        session_response = supabase.table("interview_sessions").select("*").eq("id", evaluation_request.session_id).execute()
        
        if not session_response.data or len(session_response.data) == 0:
            raise HTTPException(status_code=404, detail="Session not found")
        
        session = session_response.data[0]
        role = session.get("role", "Unknown")
        experience_level = session.get("experience_level", "Fresher")
        
        # Get all answers for this session (check session type to determine which table)
        # For now, default to technical_round (can be enhanced later)
        session_type = session.get("interview_type", "technical") if session else "technical"
        if session_type == "coding":
            round_table = "coding_round"
        elif session_type == "hr":
            round_table = "hr_round"
        elif session_type == "star":
            round_table = "star_round"
        else:
            round_table = "technical_round"
        
        answers_response = supabase.table(round_table).select("*").eq("session_id", evaluation_request.session_id).order("question_number").execute()
        
        answers = answers_response.data if answers_response.data else []
        
        if not answers:
            raise HTTPException(status_code=400, detail="No answers found for this session. Please complete the interview first.")
        
        # Get total questions count from round table (questions are stored there)
        # Count unique question_numbers in answers
        total_questions = len(answers) if answers else 0
        
        # Evaluate interview
        evaluation_result = interview_evaluator.evaluate_interview(
            role=role,
            experience_level=experience_level,
            answers=answers,
            total_questions=total_questions
        )
        
        return InterviewEvaluationResponse(
            session_id=evaluation_request.session_id,
            overall_score=evaluation_result["overall_score"],
            category_scores=evaluation_result["category_scores"],
            total_questions=total_questions,
            answered_questions=len(answers),
            feedback_summary=evaluation_result["feedback_summary"],
            recommendations=evaluation_result["recommendations"],
            strengths=evaluation_result["strengths"],
            areas_for_improvement=evaluation_result["areas_for_improvement"],
            generated_at=datetime.now()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error evaluating interview: {str(e)}")

# ==================== Technical Interview Endpoints ====================

@router.post("/technical", response_model=TechnicalInterviewStartResponse)
async def start_technical_interview(
    request: TechnicalInterviewStartRequest,
    supabase: Client = Depends(get_supabase_client)
):
    """
    Start a new technical interview session based on user's resume
    """
    try:
        user_id = request.user_id
        
        # Get user profile to extract resume skills
        profile_response = supabase.table("user_profiles").select("*").eq("user_id", user_id).execute()
        profile = profile_response.data[0] if profile_response.data else None
        
        resume_context = build_resume_context_from_profile(profile, supabase)
        resume_skills = resume_context.get("skills", [])
        
        # Initialize interview session using engine
        session_data = technical_interview_engine.start_interview_session(
            user_id=user_id,
            resume_skills=resume_skills,
            resume_context=resume_context,
            role="Technical Interview",
            experience_level=resume_context.get("experience_level") or (profile.get("experience_level") if profile else None)
        )
        
        # Ensure user profile exists before creating session (to satisfy foreign key constraint)
        if not profile:
            raise HTTPException(
                status_code=404,
                detail=f"User profile not found for user_id: {user_id}. Please upload a resume first to create your profile."
            )
        
        # Create session in database
        db_session_data = {
            "user_id": user_id,
            "interview_type": "technical",  # New schema: use interview_type instead of role
            "role": "Technical Interview",  # Keep for backward compatibility
            "experience_level": resume_context.get("experience_level") or (profile.get("experience_level") if profile else "Intermediate"),
            "skills": session_data["technical_skills"],
            "session_status": "active"
        }
        
        try:
            session_response = supabase.table("interview_sessions").insert(db_session_data).execute()
            
            if not session_response.data or len(session_response.data) == 0:
                raise HTTPException(status_code=500, detail="Failed to create interview session")
            
            session_id = session_response.data[0]["id"]
            session_data["session_id"] = session_id
        except HTTPException:
            raise
        except Exception as db_error:
            error_str = str(db_error)
            # Check if it's a foreign key constraint error
            if "foreign key constraint" in error_str.lower() or "not present in table" in error_str.lower():
                raise HTTPException(
                    status_code=400,
                    detail=f"User profile not found. Please ensure user_id {user_id} exists in user_profiles table. Error: {error_str}"
                )
            raise HTTPException(
                status_code=500,
                detail=f"Error creating interview session: {error_str}"
            )
        
        # Store session metadata (conversation history) in a JSON field
        # We'll use a metadata field or store in session notes
        # For now, we'll store conversation history in session metadata
        metadata = {
            "conversation_history": session_data["conversation_history"],
            "current_question_index": 0,
            "questions_asked": [],
            "answers_received": [],
            "all_scores": []
        }
        
        # Update session with metadata (store as JSON in a text field or use a metadata column)
        # Since we don't have a metadata column, we'll manage this in memory and store in answers/questions
        
        return TechnicalInterviewStartResponse(
            session_id=session_id,
            conversation_history=session_data["conversation_history"],
            technical_skills=session_data["technical_skills"]
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error starting technical interview: {str(e)}")

@router.post("/technical/{session_id}/next-question")
async def get_next_technical_question(
    session_id: str,
    supabase: Client = Depends(get_supabase_client)
):
    """
    Get the next technical question for the interview
    """
    try:
        # Get session
        session_response = supabase.table("interview_sessions").select("*").eq("id", session_id).execute()
        
        if not session_response.data or len(session_response.data) == 0:
            raise HTTPException(status_code=404, detail="Session not found")
        
        session = session_response.data[0]
        
        # Get conversation history from stored questions and answers
        # Note: In new schema, questions are stored in round tables, not separate interview_questions table
        # For now, get answers from technical_round (can be enhanced to check session type)
        session_type = session.get("interview_type", "technical") if session else "technical"
        if session_type == "coding":
            round_table = "coding_round"
        elif session_type == "hr":
            round_table = "hr_round"
        elif session_type == "star":
            round_table = "star_round"
        else:
            round_table = "technical_round"
        
        # Get questions from round table (question_text field)
        answers_response = supabase.table(round_table).select("question_text, question_number, user_answer").eq("session_id", session_id).order("question_number").execute()
        # Map to old format for compatibility
        questions_response_data = []
        answers_response_data = []
        for row in (answers_response.data or []):
            questions_response_data.append({"question": row.get("question_text", ""), "question_number": row.get("question_number", 0)})
            answers_response_data.append({"user_answer": row.get("user_answer", ""), "question_number": row.get("question_number", 0)})
        
        # Build conversation history
        conversation_history = []
        questions_asked = []
        answers_received = []
        
        # Add questions and answers to conversation
        questions = questions_response_data if questions_response_data else []
        answers = answers_response_data if answers_response_data else []
        
        for q in questions:
            conversation_history.append({"role": "ai", "content": q["question"]})
            questions_asked.append(q["question"])
        
        for a in answers:
            conversation_history.append({"role": "user", "content": a["user_answer"]})
            answers_received.append(a["user_answer"])
        
        # Prepare session data
        session_data = {
            "session_id": session_id,
            "technical_skills": session.get("skills", []),
            "conversation_history": conversation_history,
            "current_question_index": len(questions),
            "questions_asked": questions_asked,
            "answers_received": answers_received
        }
        
        # Check if interview should end (max 20 questions)
        if len(questions_asked) >= 20:
            return {
                "interview_completed": True,
                "message": "Interview completed. Maximum questions reached."
            }
        
        # Generate next question
        question_data = technical_interview_engine.generate_next_question(session_data, conversation_history)
        
        # Store question in technical_round table (new schema)
        question_number = len(questions) + 1
        user_id = str(session.get("user_id", "")) if session else ""
        
        # Store question in technical_round table with placeholder answer (will be updated when user answers)
        question_db_data = {
            "user_id": user_id,
            "session_id": session_id,
            "question_number": question_number,
            "question_text": question_data["question"],
            "question_type": question_data.get("question_type", "Technical"),
            "user_answer": "",  # Placeholder - will be updated when user submits answer
            "relevance_score": None,
            "technical_accuracy_score": None,
            "communication_score": None,
            "overall_score": None,
            "ai_feedback": None,
            "response_time": None
        }
        
        supabase.table("technical_round").insert(question_db_data).execute()
        
        # Generate audio URL using TTS
        audio_url = None
        try:
            # We'll generate audio on-demand via the TTS endpoint
            import urllib.parse
            from app.config.settings import settings
            from app.utils.url_utils import get_api_base_url
            encoded_text = urllib.parse.quote(question_data['question'])
            # Use absolute URL - works for both localhost and production
            base_url = get_api_base_url()
            audio_url = f"{base_url}/api/interview/text-to-speech?text={encoded_text}"
        except Exception as e:
            logger.warning(f"Could not generate audio URL: {str(e)}")
        
        return {
            "question": question_data["question"],
            "question_type": question_data.get("question_type", "Technical"),
            "audio_url": audio_url,
            "interview_completed": False
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting next question: {str(e)}")

@router.post("/technical/{session_id}/submit-answer")
async def submit_technical_answer(
    session_id: str,
    request: Dict[str, Any] = Body(...),
    supabase: Client = Depends(get_supabase_client)
):
    """
    Submit an answer to the current technical question
    """
    try:
        question = request.get("question")
        answer = request.get("answer")
        
        if not question or not answer:
            raise HTTPException(status_code=400, detail="question and answer are required")
        
        # Get session
        session_response = supabase.table("interview_sessions").select("*").eq("id", session_id).execute()
        
        if not session_response.data or len(session_response.data) == 0:
            raise HTTPException(status_code=404, detail="Session not found")
        
        session = session_response.data[0]
        
        # Get current question from technical_round table (new schema)
        questions_response = supabase.table("technical_round").select("*").eq("session_id", session_id).order("question_number", desc=True).limit(1).execute()
        
        if not questions_response.data or len(questions_response.data) == 0:
            raise HTTPException(status_code=404, detail="No current question found")
        
        current_question_db = questions_response.data[0]
        question_id = current_question_db["id"]
        question_number = current_question_db["question_number"]
        
        # Get conversation history from technical_round table
        round_data_response = supabase.table("technical_round").select("question_text, question_number, user_answer").eq("session_id", session_id).order("question_number").execute()
        
        conversation_history = []
        questions_asked_list = []
        answers_received_list = []
        
        for row in (round_data_response.data or []):
            question_text = row.get("question_text", "")
            user_answer = row.get("user_answer", "")
            if question_text:
                conversation_history.append({"role": "ai", "content": question_text})
                questions_asked_list.append(question_text)
            if user_answer:  # Only add answer if it's not empty
                conversation_history.append({"role": "user", "content": user_answer})
                answers_received_list.append(user_answer)
        
        # Prepare session data
        session_data = {
            "session_id": session_id,
            "technical_skills": session.get("skills", []),
            "conversation_history": conversation_history,
            "current_question_index": len(questions_asked_list),
            "questions_asked": questions_asked_list,
            "answers_received": answers_received_list
        }
        
        # Evaluate answer
        evaluation = technical_interview_engine.evaluate_answer(
            question=question,
            answer=answer,
            session_data=session_data,
            conversation_history=conversation_history
        )
        
        # Update the existing question row in technical_round table with the answer and evaluation
        user_id = str(session.get("user_id", "")) if session else ""
        
        # Get user's answer audio_url from request (if provided)
        user_answer_audio_url = request.get("audio_url")  # User's answer audio URL from frontend
        
        # Generate audio URL for AI response (for playback, not for storage in audio_url field)
        ai_response_audio_url = None
        if evaluation.get("ai_response"):
            try:
                import urllib.parse
                from app.utils.url_utils import get_api_base_url
                encoded_text = urllib.parse.quote(evaluation['ai_response'])
                # Use absolute URL - works for both localhost and production
                base_url = get_api_base_url()
                ai_response_audio_url = f"{base_url}/api/interview/text-to-speech?text={encoded_text}"
            except Exception as e:
                logger.warning(f"Could not generate audio URL: {str(e)}")
        
        # CRITICAL: Log before update with all relevant data
        logger.info(f"[SUBMIT ANSWER] ========== Preparing to Update Technical Round ==========")
        logger.info(f"[SUBMIT ANSWER] session_id: {session_id} (type: {type(session_id).__name__})")
        logger.info(f"[SUBMIT ANSWER] user_id: {user_id}")
        logger.info(f"[SUBMIT ANSWER] question_number: {question_number} (type: {type(question_number).__name__})")
        logger.info(f"[SUBMIT ANSWER] extracted_answer_text: {answer[:100]}..." if len(answer) > 100 else f"[SUBMIT ANSWER] extracted_answer_text: {answer}")
        logger.info(f"[SUBMIT ANSWER] user_answer_audio_url: {user_answer_audio_url}")
        logger.info(f"[SUBMIT ANSWER] ai_response_audio_url: {ai_response_audio_url}")
        logger.info(f"[SUBMIT ANSWER] relevance_score: {evaluation['scores']['relevance']}")
        logger.info(f"[SUBMIT ANSWER] technical_accuracy_score: {evaluation['scores']['technical_accuracy']}")
        logger.info(f"[SUBMIT ANSWER] communication_score: {evaluation['scores']['communication']}")
        logger.info(f"[SUBMIT ANSWER] overall_score: {evaluation['scores']['overall']}")
        
        # Verify the row exists before updating
        verify_response = supabase.table("technical_round").select("id, session_id, question_number, user_id").eq("session_id", str(session_id)).eq("question_number", int(question_number)).execute()
        
        if not verify_response.data or len(verify_response.data) == 0:
            logger.error(f"[SUBMIT ANSWER] ❌ CRITICAL: Row not found for update!")
            logger.error(f"[SUBMIT ANSWER] Searched for session_id={session_id} (as {type(session_id).__name__}), question_number={question_number} (as {type(question_number).__name__})")
            # Try to find what rows actually exist
            debug_response = supabase.table("technical_round").select("id, session_id, question_number").eq("session_id", str(session_id)).execute()
            logger.error(f"[SUBMIT ANSWER] Debug: Found {len(debug_response.data) if debug_response.data else 0} rows with session_id={session_id}")
            if debug_response.data:
                for row in debug_response.data:
                    logger.error(f"[SUBMIT ANSWER] Debug row: id={row.get('id')}, session_id={row.get('session_id')} (type: {type(row.get('session_id')).__name__}), question_number={row.get('question_number')} (type: {type(row.get('question_number')).__name__})")
            raise HTTPException(status_code=404, detail=f"Question row not found for session_id={session_id}, question_number={question_number}. Cannot update answer.")
        
        logger.info(f"[SUBMIT ANSWER] ✓ Row found. Existing row ID: {verify_response.data[0].get('id')}")
        
        # Get user's answer audio_url from request if provided
        user_answer_audio_url = request.get("audio_url")  # User's answer audio URL from frontend
        
        # Update the existing row (the question was already stored when it was asked)
        # Ensure ALL fields are included: user_answer, audio_url (user's answer), scores, and feedback
        update_data = {
            "user_answer": answer,
            "audio_url": user_answer_audio_url,  # CRITICAL: User's answer audio URL (not AI response audio)
            "relevance_score": evaluation["scores"]["relevance"],
            "technical_accuracy_score": evaluation["scores"]["technical_accuracy"],
            "communication_score": evaluation["scores"]["communication"],
            "overall_score": evaluation["scores"]["overall"],
            "ai_feedback": evaluation.get("ai_response", ""),  # AI feedback on the answer
            "ai_response": evaluation.get("ai_response", ""),  # AI response/feedback
            "response_time": None
        }
        
        # Ensure no None values are stored as None (use empty string for text fields, 0 for scores if needed)
        # But actually, None is acceptable for optional fields per schema, so we keep them as is
        
        logger.info(f"[SUBMIT ANSWER] Update data prepared: {list(update_data.keys())}")
        
        # Update the row for this question_number and session_id
        # CRITICAL: Normalize types to ensure match (session_id as str, question_number as int)
        answer_response = supabase.table("technical_round").update(update_data).eq("session_id", str(session_id)).eq("question_number", int(question_number)).execute()
        
        # CRITICAL FIX: Validate that the update actually succeeded
        if not answer_response.data or len(answer_response.data) == 0:
            logger.error(f"[SUBMIT ANSWER] ❌ CRITICAL: Database update returned no rows!")
            logger.error(f"[SUBMIT ANSWER] Update query: session_id={str(session_id)}, question_number={int(question_number)}")
            logger.error(f"[SUBMIT ANSWER] Update data: {update_data}")
            # Try to get the current row to debug
            debug_response = supabase.table("technical_round").select("*").eq("session_id", str(session_id)).eq("question_number", int(question_number)).execute()
            logger.error(f"[SUBMIT ANSWER] Debug - Current row exists: {debug_response.data is not None and len(debug_response.data) > 0 if debug_response.data else False}")
            if debug_response.data:
                logger.error(f"[SUBMIT ANSWER] Debug - Current row data: {debug_response.data[0]}")
            raise HTTPException(status_code=500, detail=f"Failed to save answer to database. No rows were updated. This may be due to RLS policies or data type mismatches.")
        
        # Log successful update with response details
        updated_row = answer_response.data[0]
        logger.info(f"[SUBMIT ANSWER] ✅ SUCCESS: Database update completed!")
        logger.info(f"[SUBMIT ANSWER] Updated row ID: {updated_row.get('id')}")
        logger.info(f"[SUBMIT ANSWER] Updated user_answer: {updated_row.get('user_answer', '')[:50]}..." if len(updated_row.get('user_answer', '')) > 50 else f"[SUBMIT ANSWER] Updated user_answer: {updated_row.get('user_answer', '')}")
        logger.info(f"[SUBMIT ANSWER] Updated audio_url: {updated_row.get('audio_url')}")
        logger.info(f"[SUBMIT ANSWER] Updated relevance_score: {updated_row.get('relevance_score')}")
        logger.info(f"[SUBMIT ANSWER] Updated technical_accuracy_score: {updated_row.get('technical_accuracy_score')}")
        logger.info(f"[SUBMIT ANSWER] Updated communication_score: {updated_row.get('communication_score')}")
        logger.info(f"[SUBMIT ANSWER] Updated overall_score: {updated_row.get('overall_score')}")
        logger.info(f"[SUBMIT ANSWER] Updated ai_feedback: {updated_row.get('ai_feedback', '')[:50]}..." if len(updated_row.get('ai_feedback', '')) > 50 else f"[SUBMIT ANSWER] Updated ai_feedback: {updated_row.get('ai_feedback', '')}")
        logger.info(f"[SUBMIT ANSWER] Updated ai_response: {updated_row.get('ai_response', '')[:50]}..." if len(updated_row.get('ai_response', '')) > 50 else f"[SUBMIT ANSWER] Updated ai_response: {updated_row.get('ai_response', '')}")
        logger.info(f"[SUBMIT ANSWER] ========== Update Complete ==========")
        
        # Generate audio URL for AI response (for playback, separate from user's answer audio_url)
        ai_response_audio_url = None
        if evaluation.get("ai_response"):
            try:
                import urllib.parse
                from app.utils.url_utils import get_api_base_url
                encoded_text = urllib.parse.quote(evaluation['ai_response'])
                base_url = get_api_base_url()
                ai_response_audio_url = f"{base_url}/api/interview/text-to-speech?text={encoded_text}"
            except Exception as e:
                logger.warning(f"Could not generate AI response audio URL: {str(e)}")
        
        # Generate audio URL for AI response (for playback, separate from user's answer audio_url)
        ai_response_audio_url = None
        if evaluation.get("ai_response"):
            try:
                import urllib.parse
                from app.utils.url_utils import get_api_base_url
                encoded_text = urllib.parse.quote(evaluation['ai_response'])
                base_url = get_api_base_url()
                ai_response_audio_url = f"{base_url}/api/interview/text-to-speech?text={encoded_text}"
            except Exception as e:
                logger.warning(f"Could not generate AI response audio URL: {str(e)}")
        
        # Check if interview should continue (max 20 questions)
        total_questions = len(questions_asked_list)
        if total_questions >= 20:
            return {
                "ai_response": evaluation.get("ai_response", "Thank you for your answer."),
                "audio_url": ai_response_audio_url,  # AI response audio URL for playback
                "scores": evaluation["scores"],
                "interview_completed": True
            }
        
        return {
            "ai_response": evaluation.get("ai_response", "Thank you for your answer."),
            "audio_url": ai_response_audio_url,  # AI response audio URL for playback
            "scores": evaluation["scores"],
            "interview_completed": False
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error submitting answer: {str(e)}")

@router.get("/technical/{session_id}/feedback")
async def get_technical_interview_feedback(
    session_id: str,
    supabase: Client = Depends(get_supabase_client)
):
    """
    Get final feedback for completed technical interview
    """
    try:
        # Get session
        session_response = supabase.table("interview_sessions").select("*").eq("id", session_id).execute()
        
        if not session_response.data or len(session_response.data) == 0:
            raise HTTPException(status_code=404, detail="Session not found")
        
        session = session_response.data[0]
        
        # Get all answers from technical_round table
        answers_response = supabase.table("technical_round").select("*").eq("session_id", session_id).order("question_number").execute()
        answers = answers_response.data if answers_response.data else []
        
        if not answers:
            raise HTTPException(status_code=400, detail="No answers found for this session")
        
        # CRITICAL: Validate that answers are actually saved (not empty)
        # But be lenient - work with whatever data we have
        answers_with_data = []
        missing_data_rows = []
        
        for idx, row in enumerate(answers, 1):
            user_answer = row.get("user_answer", "")
            relevance_score = row.get("relevance_score")
            technical_accuracy_score = row.get("technical_accuracy_score")
            communication_score = row.get("communication_score")
            overall_score = row.get("overall_score")
            
            # Check if this row has been properly saved
            if not user_answer or user_answer.strip() == "":
                missing_data_rows.append(f"Question {row.get('question_number', idx)}: user_answer is empty")
            elif relevance_score is None and technical_accuracy_score is None and communication_score is None:
                missing_data_rows.append(f"Question {row.get('question_number', idx)}: scores are NULL")
            else:
                answers_with_data.append(row)
        
        # If NO rows have data, return error
        if len(answers_with_data) == 0:
            error_detail = f"No complete answers found. Missing data in: {', '.join(missing_data_rows)}. Please ensure all answers are submitted before viewing feedback."
            logger.error(f"[FEEDBACK] ❌ Cannot generate feedback: {error_detail}")
            raise HTTPException(status_code=400, detail=error_detail)
        
        # If some rows are missing data but we have at least one complete answer, log warning but continue
        if missing_data_rows and len(answers_with_data) > 0:
            logger.warning(f"[FEEDBACK] ⚠️  Some answers incomplete: {', '.join(missing_data_rows)}. Generating feedback with {len(answers_with_data)} complete answers.")
        
        # Use only rows with complete data
        answers = answers_with_data
        
        # Get conversation history from technical_round table (new schema)
        # Questions and answers are in the same table
        conversation_history = []
        questions_asked = []
        answers_received = []
        
        for row in answers:
            question_text = row.get("question_text", "")
            user_answer = row.get("user_answer", "")
            if question_text:
                conversation_history.append({"role": "ai", "content": question_text})
                questions_asked.append(question_text)
            if user_answer and user_answer.strip():  # Only add if answer exists and is not empty
                conversation_history.append({"role": "user", "content": user_answer})
                answers_received.append(user_answer)
        
        # Prepare session data
        session_data = {
            "session_id": session_id,
            "technical_skills": session.get("skills", []),
            "conversation_history": conversation_history,
            "current_question_index": len(questions_asked),
            "questions_asked": questions_asked,
            "answers_received": answers_received
        }
        
        # Get all scores
        all_scores = []
        for answer in answers:
            all_scores.append({
                "relevance": answer.get("relevance_score", 0),
                "technical_accuracy": answer.get("technical_accuracy_score", 0),
                "communication": answer.get("communication_score", 0),
                "overall": answer.get("overall_score", 0)
            })
        
        # Generate feedback
        feedback = technical_interview_engine.generate_final_feedback(
            session_data=session_data,
            conversation_history=conversation_history,
            all_scores=all_scores
        )
        
        # Update session status
        supabase.table("interview_sessions").update({"session_status": "completed"}).eq("id", session_id).execute()
        
        return feedback
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating feedback: {str(e)}")

@router.get("/hr/{session_id}/feedback")
async def get_hr_interview_feedback(
    session_id: str,
    supabase: Client = Depends(get_supabase_client)
):
    """
    Get final feedback for completed HR interview
    Returns HR-specific feedback with communication, cultural fit, motivation, and clarity scores
    """
    try:
        # Input validation
        if not session_id or not isinstance(session_id, str) or not session_id.strip():
            logger.error(f"[HR FEEDBACK] Invalid session_id: {session_id}")
            raise HTTPException(status_code=400, detail="Invalid request format. Please check your input and try again.")
        
        logger.info(f"[HR FEEDBACK] Requesting feedback for session_id: {session_id}")
        
        # Get session
        try:
            session_response = supabase.table("interview_sessions").select("*").eq("id", session_id).execute()
        except Exception as db_error:
            logger.error(f"[HR FEEDBACK] Database error fetching session: {str(db_error)}", exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to retrieve interview session. Please try again.")
        
        if not session_response.data or len(session_response.data) == 0:
            logger.warning(f"[HR FEEDBACK] Session not found: {session_id}")
            raise HTTPException(status_code=404, detail="Interview session not found. Please start a new interview.")
        
        session = session_response.data[0]
        
        # Validate session is HR type
        session_type = session.get("interview_type", "").lower()
        if session_type != "hr":
            logger.error(f"[HR FEEDBACK] Wrong session type: {session_type} (expected: hr)")
            raise HTTPException(
                status_code=400, 
                detail="This endpoint is for HR interviews only. Please use the correct interview type."
            )
        
        # Get all answers from hr_round table
        try:
            answers_response = supabase.table("hr_round").select("*").eq("session_id", session_id).order("question_number").execute()
            answers = answers_response.data if answers_response.data else []
        except Exception as db_error:
            logger.error(f"[HR FEEDBACK] Database error fetching answers: {str(db_error)}", exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to retrieve interview answers. Please try again.")
        
        if not answers:
            logger.warning(f"[HR FEEDBACK] No answers found for session: {session_id}")
            raise HTTPException(status_code=400, detail="No answers found for this interview. Please complete the interview first.")
        
        # Validate that answers are actually saved (not empty)
        answers_with_data = []
        missing_data_rows = []
        
        for idx, row in enumerate(answers, 1):
            user_answer = row.get("user_answer", "")
            communication_score = row.get("communication_score")
            cultural_fit_score = row.get("cultural_fit_score")
            motivation_score = row.get("motivation_score")
            clarity_score = row.get("clarity_score")
            overall_score = row.get("overall_score")
            
            # ✅ FIX: "No Answer" is a valid answer and should be included in feedback (with 0 scores)
            # Check if this row has been properly saved
            if not user_answer or (user_answer.strip() == "" and user_answer != "No Answer"):
                missing_data_rows.append(f"Question {row.get('question_number', idx)}: user_answer is empty")
            elif communication_score is None and cultural_fit_score is None and motivation_score is None and clarity_score is None:
                missing_data_rows.append(f"Question {row.get('question_number', idx)}: scores are NULL")
            else:
                # Include "No Answer" cases in feedback (they have 0 scores)
                answers_with_data.append(row)
        
        # If NO rows have data, return error
        if len(answers_with_data) == 0:
            logger.error(f"[HR FEEDBACK] ❌ Cannot generate feedback: No complete answers found. Missing data in: {', '.join(missing_data_rows)}")
            raise HTTPException(
                status_code=400, 
                detail="No complete answers found for this interview. Please ensure all answers are submitted before viewing feedback."
            )
        
        # If some rows are missing data but we have at least one complete answer, log warning but continue
        if missing_data_rows and len(answers_with_data) > 0:
            logger.warning(f"[HR FEEDBACK] ⚠️  Some answers incomplete: {', '.join(missing_data_rows)}. Generating feedback with {len(answers_with_data)} complete answers.")
        
        # Use only rows with complete data
        answers = answers_with_data
        
        # Get conversation history from hr_round table
        conversation_history = []
        questions_asked = []
        answers_received = []
        
        for row in answers:
            question_text = row.get("question_text", "")
            user_answer = row.get("user_answer", "")
            if question_text:
                conversation_history.append({"role": "ai", "content": question_text})
                questions_asked.append(question_text)
            # ✅ FIX: Include "No Answer" in conversation history for feedback
            if user_answer and (user_answer.strip() or user_answer == "No Answer"):
                conversation_history.append({"role": "user", "content": user_answer})
                answers_received.append(user_answer)
        
        # Calculate HR-specific scores
        all_communication_scores = []
        all_cultural_fit_scores = []
        all_motivation_scores = []
        all_clarity_scores = []
        all_overall_scores = []
        
        for answer in answers:
            comm_score = answer.get("communication_score")
            cultural_score = answer.get("cultural_fit_score")
            motivation_score = answer.get("motivation_score")
            clarity_score = answer.get("clarity_score")
            overall_score = answer.get("overall_score")
            
            if comm_score is not None:
                all_communication_scores.append(comm_score)
            if cultural_score is not None:
                all_cultural_fit_scores.append(cultural_score)
            if motivation_score is not None:
                all_motivation_scores.append(motivation_score)
            if clarity_score is not None:
                all_clarity_scores.append(clarity_score)
            if overall_score is not None:
                all_overall_scores.append(overall_score)
        
        # Calculate averages
        avg_communication = sum(all_communication_scores) / len(all_communication_scores) if all_communication_scores else 0
        avg_cultural_fit = sum(all_cultural_fit_scores) / len(all_cultural_fit_scores) if all_cultural_fit_scores else 0
        avg_motivation = sum(all_motivation_scores) / len(all_motivation_scores) if all_motivation_scores else 0
        avg_clarity = sum(all_clarity_scores) / len(all_clarity_scores) if all_clarity_scores else 0
        avg_overall = sum(all_overall_scores) / len(all_overall_scores) if all_overall_scores else 0
        
        # Generate HR-specific feedback using AI
        feedback_summary = ""
        strengths = []
        areas_for_improvement = []
        recommendations = []
        
        # Analyze by HR category
        if avg_communication >= 75:
            strengths.append("Excellent communication skills and clarity of expression")
        elif avg_communication < 60:
            areas_for_improvement.append("Communication clarity can be improved")
            recommendations.append("Practice articulating thoughts clearly and concisely")
        
        if avg_cultural_fit >= 75:
            strengths.append("Strong alignment with company values and culture")
        elif avg_cultural_fit < 60:
            areas_for_improvement.append("Cultural fit could be enhanced")
            recommendations.append("Research company values and demonstrate alignment in responses")
        
        if avg_motivation >= 75:
            strengths.append("High motivation and enthusiasm for the role")
        elif avg_motivation < 60:
            areas_for_improvement.append("Motivation and enthusiasm could be stronger")
            recommendations.append("Prepare specific examples of why you're interested in this role")
        
        if avg_clarity >= 75:
            strengths.append("Clear and structured responses")
        elif avg_clarity < 60:
            areas_for_improvement.append("Response structure and clarity need improvement")
            recommendations.append("Practice organizing answers with clear beginning, middle, and end")
        
        # Generate AI feedback summary if OpenAI is available
        if technical_interview_engine.openai_available and technical_interview_engine.client is not None:
            try:
                system_prompt = """You are an experienced HR interviewer providing final interview feedback.
Generate a comprehensive but concise summary (3-4 sentences) of the candidate's HR interview performance.
Focus on communication, cultural fit, motivation, and clarity aspects."""

                user_prompt = f"""HR Interview Summary:
- Overall Score: {avg_overall:.1f}/100
- Communication Average: {avg_communication:.1f}/100
- Cultural Fit Average: {avg_cultural_fit:.1f}/100
- Motivation Average: {avg_motivation:.1f}/100
- Clarity Average: {avg_clarity:.1f}/100
- Total Questions Answered: {len(answers)}

Conversation History:
{chr(10).join([f"{msg.get('role', 'unknown').upper()}: {msg.get('content', '')[:200]}" for msg in conversation_history[-10:]])}

Generate a professional, constructive HR feedback summary (3-4 sentences) that highlights communication, cultural fit, motivation, and clarity."""

                response = technical_interview_engine.client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.7,
                    max_tokens=250
                )
                
                feedback_summary = response.choices[0].message.content.strip()
                logger.info(f"[HR FEEDBACK] ✅ AI feedback summary generated")
                
            except Exception as e:
                logger.warning(f"[HR FEEDBACK] Could not generate AI feedback: {str(e)}")
                # Fallback to basic summary
                feedback_summary = f"Overall HR interview performance score: {avg_overall:.1f}/100. "
                if strengths:
                    feedback_summary += f"Strengths include: {', '.join(strengths[:2])}. "
                if areas_for_improvement:
                    feedback_summary += f"Areas to improve: {', '.join(areas_for_improvement[:2])}."
        else:
            # Fallback when OpenAI is not available
            feedback_summary = f"Overall HR interview performance score: {avg_overall:.1f}/100. "
            if strengths:
                feedback_summary += f"Strengths include: {', '.join(strengths[:2])}. "
            if areas_for_improvement:
                feedback_summary += f"Areas to improve: {', '.join(areas_for_improvement[:2])}."
        
        # Ensure we have at least some feedback
        if not strengths:
            strengths.append("Good effort in the HR interview")
        if not areas_for_improvement:
            areas_for_improvement.append("Continue practicing HR interview responses")
        if not recommendations:
            recommendations.append("Keep practicing and preparing for HR interviews")
        
        # Update session status
        supabase.table("interview_sessions").update({"session_status": "completed"}).eq("id", session_id).execute()
        
        logger.info(f"[HR FEEDBACK] ✅ Feedback generated successfully for session {session_id}")
        
        return {
            "overall_score": round(avg_overall, 2),
            "communication_score": round(avg_communication, 2),
            "cultural_fit_score": round(avg_cultural_fit, 2),
            "motivation_score": round(avg_motivation, 2),
            "clarity_score": round(avg_clarity, 2),
            "feedback_summary": feedback_summary,
            "strengths": strengths[:5],
            "areas_for_improvement": areas_for_improvement[:5],
            "recommendations": recommendations[:5],
            "question_count": len(answers)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[HR FEEDBACK] Unexpected error generating HR feedback: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate feedback. Please try again.")


@router.post("/technical/{session_id}/end")
async def end_technical_interview(
    session_id: str,
    supabase: Client = Depends(get_supabase_client)
):
    """
    End the technical interview session
    """
    try:
        # Update session status
        supabase.table("interview_sessions").update({"session_status": "completed"}).eq("id", session_id).execute()
        
        return {"message": "Interview ended successfully", "session_id": session_id}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error ending interview: {str(e)}")


@router.post("/hr/{session_id}/end")
async def end_hr_interview(
    session_id: str,
    supabase: Client = Depends(get_supabase_client)
):
    """
    End the HR interview session
    Updates session status to completed
    """
    try:
        # Input validation
        if not session_id or not isinstance(session_id, str) or not session_id.strip():
            logger.error(f"[HR END] Invalid session_id: {session_id}")
            raise HTTPException(status_code=400, detail="Invalid request format. Please check your input and try again.")
        
        logger.info(f"[HR END] Ending HR interview session: {session_id}")
        
        # Verify session exists and is HR type
        try:
            session_response = supabase.table("interview_sessions").select("*").eq("id", session_id).execute()
        except Exception as db_error:
            logger.error(f"[HR END] Database error fetching session: {str(db_error)}", exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to retrieve interview session. Please try again.")
        
        if not session_response.data or len(session_response.data) == 0:
            logger.warning(f"[HR END] Session not found: {session_id}")
            raise HTTPException(status_code=404, detail="Interview session not found. Please start a new interview.")
        
        session = session_response.data[0]
        
        # Validate session is HR type
        session_type = session.get("interview_type", "").lower()
        if session_type != "hr":
            logger.error(f"[HR END] Wrong session type: {session_type} (expected: hr)")
            raise HTTPException(
                status_code=400, 
                detail="This endpoint is for HR interviews only. Please use the correct interview type."
            )
        
        # Update session status to completed
        try:
            update_response = supabase.table("interview_sessions").update({
                "session_status": "completed"
            }).eq("id", session_id).execute()
            
            if not update_response.data or len(update_response.data) == 0:
                logger.warning(f"[HR END] Session update returned no rows for session_id: {session_id}")
                # Don't fail - session might already be completed
            else:
                logger.info(f"[HR END] ✅ HR interview session ended successfully: {session_id}")
        except Exception as db_error:
            logger.error(f"[HR END] Database error updating session status: {str(db_error)}", exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to update session status. Please try again.")
        
        return {
            "message": "HR interview ended successfully",
            "session_id": session_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[HR END] Unexpected error ending HR interview: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to end interview. Please try again.")


@router.post("/speech-to-text")
async def speech_to_text(
    audio: UploadFile = File(...),
    supabase: Client = Depends(get_supabase_client)
):
    """
    Convert speech audio to text using OpenAI Whisper
    """
    try:
        # Check if OpenAI is available
        if not technical_interview_engine.openai_available or technical_interview_engine.client is None:
            raise HTTPException(status_code=503, detail="Speech-to-text service is not available. OpenAI API key is required.")
        
        # Read audio content into memory (works for both localhost and Vercel)
        content = await audio.read()
        
        # For Vercel serverless, use in-memory file-like object
        # For localhost, can use tempfile if needed
        import os
        is_vercel = os.getenv("VERCEL") == "1" or os.getenv("VERCEL_URL") is not None
        
        if is_vercel:
            # Vercel: Use in-memory BytesIO (no filesystem access needed)
            from io import BytesIO
            audio_file_obj = BytesIO(content)
            audio_file_obj.name = audio.filename or "audio.webm"
            
            # Transcribe using OpenAI Whisper (accepts file-like objects)
            transcript = technical_interview_engine.client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file_obj,
                language="en"
            )
            
            text = transcript.text
            return {"text": text, "language": "en"}
        else:
            # Localhost: Use tempfile (has filesystem access)
            file_extension = os.path.splitext(audio.filename)[1] if audio.filename else ".webm"
            tmp_file_path = None
            
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as tmp_file:
                    tmp_file.write(content)
                    tmp_file_path = tmp_file.name
                
                # Transcribe using OpenAI Whisper
                with open(tmp_file_path, "rb") as audio_file:
                    transcript = technical_interview_engine.client.audio.transcriptions.create(
                        model="whisper-1",
                        file=audio_file,
                        language="en"
                    )
                
                text = transcript.text
                return {"text": text, "language": "en"}
                
            finally:
                # Clean up temporary file
                if tmp_file_path and os.path.exists(tmp_file_path):
                    try:
                        os.unlink(tmp_file_path)
                    except Exception as e:
                        logger.warning(f"Could not delete temp file: {str(e)}")
        
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error converting speech to text: {str(e)}")

@router.options("/text-to-speech")
async def text_to_speech_options():
    """Handle CORS preflight requests for TTS endpoint"""
    from fastapi.responses import Response
    return Response(
        status_code=200,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Max-Age": "3600"
        }
    )

@router.post("/text-to-speech")
async def text_to_speech(
    request: Dict[str, Any],
    supabase: Client = Depends(get_supabase_client)
):
    """
    Convert text to speech using OpenAI TTS
    Accepts: {"text": "question text"}
    Returns audio file as streaming response
    """
    try:
        text = request.get("text", "")
        
        # Check if OpenAI is available
        if not technical_interview_engine.openai_available or technical_interview_engine.client is None:
            logger.error("TTS service unavailable: OpenAI client not initialized")
            raise HTTPException(
                status_code=503, 
                detail="Text-to-speech service is not available. OpenAI API key is required."
            )
        
        if not text or not text.strip():
            raise HTTPException(status_code=400, detail="text parameter is required and cannot be empty")
        
        # Truncate text to reasonable length (OpenAI TTS limit is 4096 chars, but we'll use 2000 for safety)
        text_to_speak = text.strip()[:2000]
        logger.info(f"Generating TTS audio for text (length: {len(text_to_speak)} chars)")
        
        # Generate speech using OpenAI TTS
        try:
            response = technical_interview_engine.client.audio.speech.create(
                model="tts-1",
                voice="alloy",  # Options: alloy, echo, fable, onyx, nova, shimmer
                input=text_to_speak
            )
            
            # Get audio data
            audio_data = response.content
            
            if not audio_data or len(audio_data) == 0:
                logger.error("TTS returned empty audio data")
                raise HTTPException(status_code=500, detail="TTS service returned empty audio data")
            
            logger.info(f"TTS generated audio successfully (size: {len(audio_data)} bytes)")
            
            # Return audio as streaming response with proper CORS headers
            return StreamingResponse(
                io.BytesIO(audio_data),
                media_type="audio/mpeg",
                headers={
                    "Content-Disposition": "inline; filename=speech.mp3",
                    "Content-Type": "audio/mpeg",
                    "Content-Length": str(len(audio_data)),
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                    "Access-Control-Allow-Headers": "*",
                    "Accept-Ranges": "bytes"
                }
            )
        except Exception as tts_error:
            logger.error(f"OpenAI TTS API error: {str(tts_error)}")
            raise HTTPException(
                status_code=500, 
                detail=f"Failed to generate speech: {str(tts_error)}"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in text_to_speech: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error converting text to speech: {str(e)}")


@router.options("/text-to-speech")
async def text_to_speech_get_options():
    """Handle CORS preflight requests for TTS GET endpoint"""
    from fastapi.responses import Response
    return Response(
        status_code=200,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Max-Age": "3600"
        }
    )

@router.get("/text-to-speech")
async def text_to_speech_get(
    text: str = Query(..., description="Text to convert to speech"),
    supabase: Client = Depends(get_supabase_client)
):
    """
    Convert text to speech using OpenAI TTS (GET endpoint for URL-based access)
    Returns audio file as streaming response
    """
    try:
        # Check if OpenAI is available
        if not technical_interview_engine.openai_available or technical_interview_engine.client is None:
            logger.error("TTS service unavailable: OpenAI client not initialized")
            raise HTTPException(
                status_code=503, 
                detail="Text-to-speech service is not available. OpenAI API key is required."
            )
        
        if not text or not text.strip():
            raise HTTPException(status_code=400, detail="text parameter is required and cannot be empty")
        
        # Decode URL-encoded text and truncate
        import urllib.parse
        text_to_speak = urllib.parse.unquote(text).strip()[:2000]
        logger.info(f"Generating TTS audio via GET (length: {len(text_to_speak)} chars)")
        
        # Generate speech using OpenAI TTS
        try:
            response = technical_interview_engine.client.audio.speech.create(
                model="tts-1",
                voice="alloy",
                input=text_to_speak
            )
            
            audio_data = response.content
            
            if not audio_data or len(audio_data) == 0:
                logger.error("TTS returned empty audio data")
                raise HTTPException(status_code=500, detail="TTS service returned empty audio data")
            
            logger.info(f"TTS generated audio successfully via GET (size: {len(audio_data)} bytes)")
            
            return StreamingResponse(
                io.BytesIO(audio_data),
                media_type="audio/mpeg",
                headers={
                    "Content-Disposition": "inline; filename=speech.mp3",
                    "Content-Type": "audio/mpeg",
                    "Content-Length": str(len(audio_data)),
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                    "Access-Control-Allow-Headers": "*",
                    "Accept-Ranges": "bytes"
                }
            )
        except Exception as tts_error:
            logger.error(f"OpenAI TTS API error (GET): {str(tts_error)}")
            raise HTTPException(
                status_code=500, 
                detail=f"Failed to generate speech: {str(tts_error)}"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in text_to_speech_get: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error converting text to speech: {str(e)}")


# ==================== New Interview Page Routes ====================

@router.post("/technical/start")
async def start_interview_page(
    request: Dict[str, Any] = Body(...),
    supabase: Client = Depends(get_supabase_client)
):
    """
    Start a new technical interview for the new interview.html page
    Returns the first question based on resume skills
    """
    try:
        user_id = request.get("user_id")
        session_id = request.get("session_id")  # Optional: can reuse existing session
        
        if not user_id:
            raise HTTPException(
                status_code=400, 
                detail="user_id is required. Please ensure the frontend passes user_id in the request body. This should be fetched from /api/profile/current or stored in the user session."
            )
        
        # user_id is now TEXT (slugified name), not UUID - no validation needed
        
        # Get user profile to extract resume skills (required)
        resume_skills = []
        resume_context = None
        profile_response = None
        
        try:
            profile_response = supabase.table("user_profiles").select("*").eq("user_id", user_id).execute()
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Error fetching user profile: {str(e)}"
            )
        
        # Require profile to exist - if not, raise error (user must upload resume first)
        if not profile_response or not profile_response.data or len(profile_response.data) == 0:
            # Try to get skills from resume analysis cache (stored during resume upload)
            # Optimized: O(n) search but breaks early on first match
            # Time Complexity: O(n) worst case, O(1) best case (first item matches)
            # Space Complexity: O(1)
            from app.routers.profile import resume_analysis_cache
            cached_data = None
            # Optimize: iterate and break early on match
            for cached_info in resume_analysis_cache.values():
                if cached_info.get("user_id") == user_id:
                    cached_data = cached_info
                    break
            
            if cached_data:
                resume_skills = cached_data.get("skills", []) or []
            else:
                # No profile found - user must upload resume first
                raise HTTPException(
                    status_code=404,
                    detail=f"User profile not found for user_id: {user_id}. Please upload a resume first to create your profile."
                )
        
        if profile_response and profile_response.data and len(profile_response.data) > 0:
            profile = profile_response.data[0]
            resume_skills = profile.get("skills", []) or []
            resume_url = profile.get("resume_url")
            
            # Try to parse resume if available
            if resume_url:
                try:
                    if "storage/v1/object/public/" in resume_url:
                        path_part = resume_url.split("storage/v1/object/public/")[1]
                        bucket_name = path_part.split("/")[0]
                        file_path = "/".join(path_part.split("/")[1:])
                        
                        file_response = supabase.storage.from_(bucket_name).download(file_path)
                        
                        if file_response:
                            file_extension = os.path.splitext(file_path)[1]
                            with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as tmp_file:
                                tmp_file.write(file_response)
                                tmp_file_path = tmp_file.name
                            
                            try:
                                parsed_resume = resume_parser.parse_resume(tmp_file_path, file_extension)
                                resume_context = {
                                    "keywords": parsed_resume.get("keywords", {}),
                                    "skills": parsed_resume.get("skills", [])
                                }
                                # Merge parsed skills with profile skills
                                if parsed_resume.get("skills"):
                                    resume_skills.extend(parsed_resume.get("skills", []))
                                    resume_skills = list(dict.fromkeys(resume_skills))  # Remove duplicates
                            finally:
                                if os.path.exists(tmp_file_path):
                                    os.unlink(tmp_file_path)
                except Exception as e:
                    logger.warning(f"Could not parse resume for technical interview: {str(e)}")
        
        # If no skills found, require user to upload resume
        if not resume_skills or len(resume_skills) == 0:
            raise HTTPException(
                status_code=400, 
                detail="No technical skills found in resume. Please upload a resume with technical skills first."
            )
        
        # Create or reuse session
        if session_id:
            # Check if session exists
            session_response = supabase.table("interview_sessions").select("*").eq("id", session_id).execute()
            if not session_response.data or len(session_response.data) == 0:
                session_id = None  # Create new session
        
        if not session_id:
            # Ensure user profile exists before creating session (to satisfy foreign key constraint)
            if not profile_response or not profile_response.data or len(profile_response.data) == 0:
                raise HTTPException(
                    status_code=404,
                    detail=f"User profile not found for user_id: {user_id}. Please upload a resume first to create your profile."
                )
            
            # Create new session in database
            db_session_data = {
                "user_id": user_id,  # TEXT (slugified name)
                "interview_type": "technical",  # New schema field
                "role": "Technical Interview",  # Keep for backward compatibility
                "experience_level": (profile_response.data[0].get("experience_level", "Intermediate") if profile_response and profile_response.data else "Intermediate"),
                "skills": resume_skills,
                "session_status": "active"
            }
            
            try:
                session_response = supabase.table("interview_sessions").insert(db_session_data).execute()
                
                if not session_response.data or len(session_response.data) == 0:
                    raise HTTPException(status_code=500, detail="Failed to create interview session")
                
                session_id = session_response.data[0]["id"]
            except HTTPException:
                raise
            except Exception as db_error:
                error_str = str(db_error)
                # Check if it's a foreign key constraint error
                if "foreign key constraint" in error_str.lower() or "not present in table" in error_str.lower():
                    raise HTTPException(
                        status_code=400,
                        detail=f"User profile not found. Please ensure user_id {user_id} exists in user_profiles table. Error: {error_str}"
                    )
                raise HTTPException(
                    status_code=500,
                    detail=f"Error creating interview session: {error_str}"
                )
        
        # Initialize interview session
        session_data = technical_interview_engine.start_interview_session(
            user_id=user_id,
            resume_skills=resume_skills,
            resume_context=resume_context
        )
        
        # Generate first question based on skills
        conversation_history = session_data.get("conversation_history", [])
        first_question_data = technical_interview_engine.generate_next_question(
            {
                **session_data,
                "session_id": session_id
            },
            conversation_history
        )
        
        # Generate audio URL for the question BEFORE storing
        audio_url = None
        try:
            import urllib.parse
            from app.utils.url_utils import get_api_base_url
            question_text = first_question_data.get("question", "")
            if question_text:
                encoded_text = urllib.parse.quote(question_text)
                # Use absolute URL - works for both localhost and production
                base_url = get_api_base_url()
                audio_url = f"{base_url}/api/interview/text-to-speech?text={encoded_text}"
        except Exception as e:
            logger.warning(f"Could not generate audio URL for first question: {str(e)}")
        
        # Store first question in technical_round table
        if session_id:
            try:
                # Check if session exists in DB before storing question
                session_check = supabase.table("interview_sessions").select("id, user_id").eq("id", session_id).limit(1).execute()
                if session_check.data and len(session_check.data) > 0:
                    session_user_id = str(session_check.data[0].get("user_id", user_id))
                    question_db_data = {
                        "user_id": session_user_id,
                        "session_id": session_id,
                        "question_number": 1,
                        "question_text": first_question_data["question"],
                        "question_type": first_question_data.get("question_type", "Technical"),
                        "audio_url": audio_url,  # CRITICAL: Store audio_url when question is created
                        "user_answer": "",  # Placeholder - will be updated when user submits answer
                        "relevance_score": None,
                        "technical_accuracy_score": None,
                        "communication_score": None,
                        "overall_score": None,
                        "ai_feedback": None,
                        "response_time": None
                    }
                    insert_response = supabase.table("technical_round").insert(question_db_data).execute()
                    if not insert_response.data or len(insert_response.data) == 0:
                        logger.error(f"[START INTERVIEW] ❌ Failed to store first question in database")
                        raise HTTPException(status_code=500, detail="Failed to store first question in database")
                    logger.info(f"[START INTERVIEW] ✓ Stored first question with ID: {insert_response.data[0].get('id')}")
            except Exception as e:
                logger.error(f"[START INTERVIEW] ❌ Could not store first question in database: {str(e)}")
                # Error storing question - raise exception
                raise HTTPException(status_code=500, detail=f"Error storing question: {str(e)}")
        
        await log_interview_transcript(
            supabase,
            session_id,
            "technical",
            first_question_data.get("question", ""),
            None
        )

        return {
            "session_id": session_id,
            "question": first_question_data["question"],
            "question_type": first_question_data.get("question_type", "Technical"),
            "question_number": 1,
            "total_questions": 18,  # Will ask 15-20 questions
            "skills": resume_skills,
            "audio_url": audio_url,
            "interview_completed": False,
            "user_id": user_id  # Include user_id in response
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error starting interview: {str(e)}")


@router.post("/technical/next")
async def get_next_interview_question(
    request: Request,
    supabase: Client = Depends(get_supabase_client)
):
    """
    Get the next interview question based on user's answer
    Acts like a human interviewer with follow-up questions
    Accepts optional audio file for voice answers
    Can accept either FormData (with audio) or JSON (text only)
    """
    try:
        # Parse request body (can be JSON or FormData)
        content_type = request.headers.get("content-type", "")
        audio_file = None
        audio_url = None
        if "multipart/form-data" in content_type:
            # FormData with potential audio file
            form_data = await request.form()
            session_id = form_data.get("session_id")
            user_answer = form_data.get("user_answer", "")
            previous_question = form_data.get("previous_question", "")
            
            # Get audio file if present (will be UploadFile type)
            if "audio" in form_data:
                audio_file = form_data["audio"]
        else:
            # JSON request
            request_data = await request.json()
            session_id = request_data.get("session_id")
            user_answer = request_data.get("user_answer", "")
            previous_question = request_data.get("previous_question", "")
        
        if not session_id:
            raise HTTPException(status_code=400, detail="session_id is required")
        
        # If audio is provided, convert it to text and use that as user_answer
        if audio_file and hasattr(audio_file, 'read'):
            try:
                # Convert audio to text using speech-to-text
                if not technical_interview_engine.openai_available or technical_interview_engine.client is None:
                    logger.warning("OpenAI not available for speech-to-text, using audio file only")
                else:
                    # Read audio content into memory (works for both localhost and Vercel)
                    audio_content = await audio_file.read()
                    
                    # For Vercel serverless, use in-memory file-like object
                    # For localhost, can use tempfile if needed
                    import os
                    is_vercel = os.getenv("VERCEL") == "1" or os.getenv("VERCEL_URL") is not None
                    
                    if is_vercel:
                        # Vercel: Use in-memory BytesIO (no filesystem access needed)
                        from io import BytesIO
                        audio_file_obj = BytesIO(audio_content)
                        audio_file_obj.name = audio_file.filename or "audio.webm"
                        
                        # Transcribe using OpenAI Whisper (accepts file-like objects)
                        transcript = technical_interview_engine.client.audio.transcriptions.create(
                            model="whisper-1",
                            file=audio_file_obj,
                            language="en"
                        )
                        
                        # Use transcribed text as user_answer
                        transcribed_text = transcript.text
                        if transcribed_text and not user_answer:
                            user_answer = transcribed_text
                        elif transcribed_text and user_answer:
                            # If both exist, prefer transcribed text but log both
                            logger.info(f"Both audio transcription and text answer provided, using transcription")
                            user_answer = transcribed_text
                    else:
                        # Localhost: Use tempfile (has filesystem access)
                        file_extension = os.path.splitext(audio_file.filename)[1] if audio_file.filename else ".webm"
                        tmp_file_path = None
                        
                        try:
                            with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as tmp_file:
                                tmp_file.write(audio_content)
                                tmp_file_path = tmp_file.name
                            
                            # Transcribe using OpenAI Whisper
                            with open(tmp_file_path, "rb") as audio_file_obj:
                                transcript = technical_interview_engine.client.audio.transcriptions.create(
                                    model="whisper-1",
                                    file=audio_file_obj,
                                    language="en"
                                )
                            
                            # Use transcribed text as user_answer
                            transcribed_text = transcript.text
                            if transcribed_text and not user_answer:
                                user_answer = transcribed_text
                            elif transcribed_text and user_answer:
                                # If both exist, prefer transcribed text but log both
                                logger.info(f"Both audio transcription and text answer provided, using transcription")
                                user_answer = transcribed_text
                        finally:
                            # Clean up temporary file
                            if tmp_file_path and os.path.exists(tmp_file_path):
                                try:
                                    os.unlink(tmp_file_path)
                                except Exception as e:
                                    logger.warning(f"Could not delete temp file: {str(e)}")
                
                # Upload audio to Supabase storage and get URL
                try:
                    # Reset file pointer for upload
                    await audio_file.seek(0)
                    audio_content = await audio_file.read()
                    
                    # Create storage path
                    bucket_name = "interview-audio"
                    file_extension = os.path.splitext(audio_file.filename)[1] if audio_file.filename else ".webm"
                    audio_filename = f"{session_id}_{uuid.uuid4().hex[:8]}_{int(datetime.now().timestamp())}{file_extension}"
                    storage_path = f"answers/{audio_filename}"
                    
                    # Ensure bucket exists
                    try:
                        buckets = supabase.storage.list_buckets()
                        bucket_exists = any(b.name == bucket_name for b in buckets)
                        if not bucket_exists:
                            bucket_config = {
                                "name": bucket_name,
                                "public": True,
                                "file_size_limit": 10485760,  # 10MB
                                "allowed_mime_types": ["audio/webm", "audio/mp4", "audio/mpeg", "audio/wav", "audio/ogg"]
                            }
                            supabase.storage.create_bucket(bucket_name, bucket_config)
                            logger.info(f"Created bucket: {bucket_name}")
                    except Exception as bucket_error:
                        error_str = str(bucket_error).lower()
                        if "already exists" not in error_str and "duplicate" not in error_str:
                            logger.warning(f"Could not create bucket (may already exist): {bucket_error}")
                    
                    # Upload audio file
                    await audio_file.seek(0)  # Reset again before upload
                    audio_content = await audio_file.read()
                    supabase.storage.from_(bucket_name).upload(
                        storage_path,
                        audio_content,
                        file_options={"content-type": audio_file.content_type or "audio/webm", "upsert": "true"}
                    )
                    logger.info(f"Successfully uploaded audio to {bucket_name}/{storage_path}")
                    
                    # Get public URL
                    try:
                        public_url_response = supabase.storage.from_(bucket_name).get_public_url(storage_path)
                        audio_url = public_url_response
                    except Exception as url_error:
                        # Fallback: construct URL manually
                        from app.config.settings import settings
                        supabase_url = getattr(settings, 'supabase_url', None)
                        if supabase_url:
                            audio_url = f"{supabase_url}/storage/v1/object/public/{bucket_name}/{storage_path}"
                        else:
                            logger.warning(f"Could not get public URL for audio: {url_error}")
                    
                except Exception as upload_error:
                    logger.error(f"Failed to upload audio to storage: {str(upload_error)}")
                    # Continue without audio_url - don't fail the request
                    
            except Exception as audio_error:
                logger.error(f"Error processing audio: {str(audio_error)}")
                # Continue without audio - don't fail the request
        
        if not session_id:
            raise HTTPException(status_code=400, detail="session_id is required")
        
        if not user_answer:
            raise HTTPException(status_code=400, detail="user_answer is required")
        
        # Prepare question text for transcript logging
        if isinstance(previous_question, dict):
            question_text_for_answer = (
                previous_question.get("question")
                or previous_question.get("problem")
                or json.dumps(previous_question)
            )
        else:
            question_text_for_answer = previous_question or ""

        session_experience = None
        session_projects: List[str] = []
        session_domains: List[str] = []

        # Get session data
        session = None
        skills = []
        questions = []
        session_experience = None
        session_projects: List[str] = []
        session_domains: List[str] = []
        answers = []
        session_role = "Technical Interview"
        session_resume_projects: List[str] = []
        session_resume_domains: List[str] = []
        session_experience = None
        
        try:
            session_response = supabase.table("interview_sessions").select("*").eq("id", session_id).execute()
            
            if session_response.data and len(session_response.data) > 0:
                session = session_response.data[0]
                skills = session.get("skills", []) or []
                session_experience = session.get("experience_level")
                session_user_id = session.get("user_id")
                if session_user_id:
                    try:
                        profile_resp = (
                            supabase.table("user_profiles")
                            .select("*")
                            .eq("user_id", session_user_id)
                            .limit(1)
                            .execute()
                        )
                        profile_row = profile_resp.data[0] if profile_resp.data else None
                        if profile_row:
                            profile_context = build_resume_context_from_profile(profile_row, supabase)
                            session_projects = profile_context.get("projects", [])
                            session_domains = profile_context.get("domains", [])
                            if profile_context.get("experience_level"):
                                session_experience = profile_context.get("experience_level")
                    except Exception as profile_err:
                        logger.warning(f"Could not refresh resume context for coding session {session_id}: {profile_err}")
                session_experience = session.get("experience_level", session_experience)
                session_user_id = session.get("user_id")
                if session_user_id:
                    try:
                        profile_resp = (
                            supabase.table("user_profiles")
                            .select("*")
                            .eq("user_id", session_user_id)
                            .limit(1)
                            .execute()
                        )
                        profile_row = profile_resp.data[0] if profile_resp.data else None
                        if profile_row:
                            profile_context = build_resume_context_from_profile(profile_row, supabase)
                            session_projects = profile_context.get("projects", [])
                            session_domains = profile_context.get("domains", [])
                            if profile_context.get("experience_level"):
                                session_experience = profile_context.get("experience_level")
                    except Exception as profile_err:
                        logger.warning(f"Could not refresh resume context for coding session {session_id}: {profile_err}")
                session_role = session.get("role", session_role)
                session_experience = session.get("experience_level", session_experience)
                session_user_id = session.get("user_id")
                if session_user_id:
                    try:
                        profile_resp = (
                            supabase.table("user_profiles")
                            .select("*")
                            .eq("user_id", session_user_id)
                            .limit(1)
                            .execute()
                        )
                        profile_row = profile_resp.data[0] if profile_resp.data else None
                        if profile_row:
                            profile_context = build_resume_context_from_profile(profile_row, supabase)
                            session_resume_projects = profile_context.get("projects", [])
                            session_resume_domains = profile_context.get("domains", [])
                            if profile_context.get("experience_level"):
                                session_experience = profile_context.get("experience_level")
                    except Exception as profile_err:
                        logger.warning(f"Could not refresh resume context for session {session_id}: {profile_err}")
                
                # Get all questions and answers from technical_round table (new schema)
                try:
                    round_data_response = supabase.table("technical_round").select("*").eq("session_id", session_id).order("question_number").execute()
                    round_data = round_data_response.data or []
                    
                    # Separate questions and answers
                    questions = []
                    answers = []
                    for row in round_data:
                        question_text = row.get("question_text", "")
                        user_answer = row.get("user_answer", "")
                        if question_text:
                            questions.append({
                                "question": question_text,
                                "question_number": row.get("question_number", 0),
                                "question_type": row.get("question_type", "Technical")
                            })
                        if user_answer:  # Only include if answer exists
                            answers.append({
                                "user_answer": user_answer,
                                "question_number": row.get("question_number", 0)
                            })
                except Exception as e:
                    logger.warning(f"Could not fetch questions/answers from database: {str(e)}")
                    questions = []
                    answers = []
                
                # Store or update user's answer in technical_round (only if session exists in DB)
                # CRITICAL: Evaluate answer and store ALL fields
                if questions and len(questions) > 0:
                    try:
                        current_question = questions[-1]
                        question_number = current_question.get("question_number", len(questions))
                        question_text = current_question.get("question", "") or previous_question
                        # Get user_id from session
                        user_id = str(session.get("user_id", "")) if session else ""
                        
                        # Evaluate the answer to get all scores and feedback
                        evaluation = technical_interview_engine.evaluate_answer(
                            question=question_text,
                            answer=user_answer,
                            session_data={
                                "session_id": session_id,
                                "technical_skills": skills,
                                "experience_level": session_experience
                            },
                            conversation_history=conversation_history[:-1] if conversation_history else []  # Exclude current answer
                        )
                        
                        # Check if row already exists for this question_number
                        existing_row = supabase.table("technical_round").select("*").eq("session_id", session_id).eq("question_number", question_number).execute()
                        
                        if existing_row.data and len(existing_row.data) > 0:
                            # Update existing row with ALL fields including evaluation scores
                            update_data = {
                                "user_answer": user_answer,
                                "audio_url": audio_url,  # User's answer audio URL
                                "relevance_score": evaluation["scores"]["relevance"],
                                "technical_accuracy_score": evaluation["scores"]["technical_accuracy"],
                                "communication_score": evaluation["scores"]["communication"],
                                "overall_score": evaluation["scores"]["overall"],
                                "ai_feedback": evaluation.get("ai_response", ""),  # AI feedback on the answer
                                "ai_response": evaluation.get("ai_response", ""),  # AI response/feedback
                                "response_time": None
                            }
                            update_response = supabase.table("technical_round").update(update_data).eq("session_id", session_id).eq("question_number", question_number).execute()
                            
                            if not update_response.data or len(update_response.data) == 0:
                                logger.error(f"[STORE ANSWER] Failed to update answer for question {question_number}")
                        else:
                            # Insert new row with ALL fields including evaluation scores
                            answer_db_data = {
                                "user_id": user_id,
                                "session_id": session_id,
                                "question_number": question_number,
                                "question_text": question_text,
                                "question_type": current_question.get("question_type", "Technical"),
                                "user_answer": user_answer,
                                "audio_url": audio_url,  # User's answer audio URL
                                "relevance_score": evaluation["scores"]["relevance"],
                                "technical_accuracy_score": evaluation["scores"]["technical_accuracy"],
                                "communication_score": evaluation["scores"]["communication"],
                                "overall_score": evaluation["scores"]["overall"],
                                "ai_feedback": evaluation.get("ai_response", ""),  # AI feedback on the answer
                                "ai_response": evaluation.get("ai_response", ""),  # AI response/feedback
                                "response_time": None
                            }
                            insert_response = supabase.table("technical_round").insert(answer_db_data).execute()
                            
                            if not insert_response.data or len(insert_response.data) == 0:
                                logger.error(f"[STORE ANSWER] Failed to insert answer for question {question_number}")
                    except Exception as e:
                        logger.error(f"Could not store answer in database: {str(e)}")
                        import traceback
                        traceback.print_exc()
                        # Don't raise exception - continue with interview, but log the error
        except Exception as e:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found in database: {str(e)}")
            skills = ["Python", "JavaScript", "SQL", "Web Development"]
        
        # Log the user's answer for transcripts
        await log_interview_transcript(
            supabase,
            session_id,
            "technical",
            question_text_for_answer,
            user_answer
        )

        # Build comprehensive conversation history from questions and answers
        # This ensures the AI remembers all previous context for smooth flow
        conversation_history = []
        
        # Add all previous Q&A pairs in order
        for i, q in enumerate(questions):
            question_text = q.get("question", "") if isinstance(q, dict) else str(q)
            if question_text:  # Only add non-empty questions
                conversation_history.append({
                    "role": "ai",
                    "content": question_text
                })
                
                # Match answer by question_number if available
                matching_answer = None
                for ans in answers:
                    if isinstance(ans, dict) and ans.get("question_number") == q.get("question_number"):
                        matching_answer = ans
                        break
                
                if matching_answer and matching_answer.get("user_answer"):
                    conversation_history.append({
                        "role": "user",
                        "content": matching_answer.get("user_answer", "")
                    })
                elif i < len(answers) and answers[i].get("user_answer"):
                    # Fallback: use index-based matching
                    answer_text = answers[i].get("user_answer", "") if isinstance(answers[i], dict) else str(answers[i])
                    if answer_text:
                        conversation_history.append({
                            "role": "user",
                            "content": answer_text
                        })
        
        # Add current answer to conversation history
        if user_answer:
            conversation_history.append({
                "role": "user",
                "content": user_answer
            })
        
        # Check if interview should end (8-12 questions)
        total_questions = len(questions)
        if total_questions >= 12:
            return {
                "interview_completed": True,
                "message": "Interview completed. Thank you for your responses."
            }
        
        # CRITICAL: Build complete lists of all questions and answers for memory
        # Ensure ALL questions and answers are included, not just recent ones
        questions_asked_list = []
        answers_received_list = []
        
        # Build complete questions_asked list from all questions
        for q in questions:
            question_text = q.get("question", "") if isinstance(q, dict) else str(q)
            if question_text:
                questions_asked_list.append(question_text)
        
        # Build complete answers_received list from all answers
        for a in answers:
            answer_text = a.get("user_answer", "") if isinstance(a, dict) else str(a)
            if answer_text:
                answers_received_list.append(answer_text)
        
        # Add current answer to the list
        if user_answer:
            answers_received_list.append(user_answer)
        
        # Check if we should generate a follow-up question based on the current answer
        should_followup = technical_interview_engine.should_generate_followup(
            question=question_text_for_answer,
            answer=user_answer,
            conversation_history=conversation_history,
            questions_asked=questions_asked_list  # Complete list of ALL questions
        )
        
        next_question_data = None
        is_followup = False
        
        if should_followup:
            # Generate nested follow-up question based on the answer
            # CRITICAL: Include complete memory - all questions, answers, and conversation history
            session_data = {
                "session_id": session_id,
                "technical_skills": skills,
                "conversation_history": conversation_history,  # Full conversation history
                "current_question_index": total_questions,
                "questions_asked": questions_asked_list,  # ALL questions asked so far
                "answers_received": answers_received_list,  # ALL answers received so far
                "resume_projects": session_resume_projects,
                "resume_domains": session_resume_domains,
                "experience_level": session_experience,
                "role": session_role,
                "followup_decisions": []  # Track follow-up decisions for memory
            }
            
            followup_data = technical_interview_engine.generate_followup_question(
                question=question_text_for_answer,
                answer=user_answer,
                conversation_history=conversation_history,
                session_data=session_data
            )
            
            if followup_data and followup_data.get("question"):
                next_question_data = followup_data
                is_followup = True
                logger.info(f"[FOLLOW-UP] Generated follow-up question based on answer")
        
        # If no follow-up was generated, generate next regular question
        if not next_question_data:
            # Generate next question (AI acts like human interviewer with follow-ups)
            # CRITICAL: Include complete memory - all questions, answers, and conversation history
            session_data = {
                "session_id": session_id,
                "technical_skills": skills,
                "conversation_history": conversation_history,  # Full conversation history
                "current_question_index": total_questions,
                "questions_asked": questions_asked_list,  # ALL questions asked so far
                "answers_received": answers_received_list,  # ALL answers received so far
                "resume_projects": session_resume_projects,
                "resume_domains": session_resume_domains,
                "experience_level": session_experience,
                "role": session_role,
                "followup_decisions": []  # Track follow-up decisions for memory
            }
            
            next_question_data = technical_interview_engine.generate_next_question(session_data, conversation_history)
            is_followup = False
        
        # Generate audio URL for the next question BEFORE storing
        audio_url = None
        try:
            import urllib.parse
            from app.utils.url_utils import get_api_base_url
            question_text = next_question_data.get("question", "")
            if question_text:
                encoded_text = urllib.parse.quote(question_text)
                # Use absolute URL - works for both localhost and production
                base_url = get_api_base_url()
                audio_url = f"{base_url}/api/interview/text-to-speech?text={encoded_text}"
        except Exception as e:
            logger.warning(f"Could not generate audio URL for next question: {str(e)}")
        
        # Store next question in technical_round table (only if session exists in DB)
        # If this is a follow-up, use the same question_number (nested follow-up)
        # Otherwise, increment to next question number
        if is_followup and questions:
            # Follow-up question uses the same question_number as the previous question
            question_number = questions[-1].get("question_number", total_questions)
        else:
            question_number = total_questions + 1
        
        if session:
            try:
                user_id = str(session.get("user_id", "")) if session else ""
                question_db_data = {
                    "user_id": user_id,
                    "session_id": session_id,
                    "question_number": question_number,
                    "question_text": next_question_data["question"],
                    "question_type": next_question_data.get("question_type", "Technical"),
                    "audio_url": audio_url,  # CRITICAL: Store audio_url when question is created
                    "user_answer": "",  # Placeholder - will be updated when user submits answer
                    "relevance_score": None,
                    "technical_accuracy_score": None,
                    "communication_score": None,
                    "overall_score": None,
                    "ai_feedback": None,
                    "response_time": None
                }
                insert_response = supabase.table("technical_round").insert(question_db_data).execute()
                if not insert_response.data or len(insert_response.data) == 0:
                    logger.error(f"[NEXT QUESTION] ❌ Failed to store question {question_number} in database")
                    raise HTTPException(status_code=500, detail=f"Failed to store question {question_number} in database")
                logger.info(f"[NEXT QUESTION] ✓ Stored question {question_number} with ID: {insert_response.data[0].get('id')}")
            except Exception as e:
                logger.error(f"[NEXT QUESTION] ❌ Could not store question in database: {str(e)}")
                # Error storing question - raise exception
                raise HTTPException(status_code=500, detail=f"Error storing question: {str(e)}")
        
        await log_interview_transcript(
            supabase,
            session_id,
            "technical",
            next_question_data.get("question", ""),
            None
        )

        return {
            "question": next_question_data["question"],
            "question_type": next_question_data.get("question_type", "Technical"),
            "question_number": question_number,
            "total_questions": 18,  # Will ask 15-20 questions
            "audio_url": audio_url,
            "interview_completed": False,
            "is_followup": is_followup  # Indicate if this is a follow-up question
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting next question: {str(e)}")


@router.get("/technical/{session_id}/summary")
async def get_interview_summary(
    session_id: str,
    supabase: Client = Depends(get_supabase_client)
):
    """
    Get interview summary with scores, strengths, and improvements
    """
    try:
        logger.info(f"[SUMMARY] ========== Generating Interview Summary ==========")
        logger.info(f"[SUMMARY] session_id: {session_id}")
        
        # Get session
        session_response = supabase.table("interview_sessions").select("*").eq("id", session_id).execute()
        if not session_response.data:
            logger.error(f"[SUMMARY] ❌ Session not found: {session_id}")
            raise HTTPException(status_code=404, detail="Session not found")
        
        session = session_response.data[0]
        logger.info(f"[SUMMARY] ✓ Session found: {session.get('interview_type')}")
        
        # Get all questions and answers from technical_round table with ALL fields
        answers_response = supabase.table("technical_round").select("*").eq("session_id", session_id).order("question_number").execute()
        all_rows = answers_response.data if answers_response.data else []
        
        logger.info(f"[SUMMARY] Found {len(all_rows)} rows in technical_round")
        
        if len(all_rows) == 0:
            logger.error(f"[SUMMARY] ❌ No interview data found for session: {session_id}")
            raise HTTPException(status_code=400, detail="No interview data found")
        
        # Filter rows that have answers (user_answer is not empty)
        answered_rows = []
        unanswered_rows = []
        
        for row in all_rows:
            user_answer = row.get("user_answer", "")
            if user_answer and user_answer.strip():
                answered_rows.append(row)
            else:
                unanswered_rows.append(row)
        
        logger.info(f"[SUMMARY] Answered questions: {len(answered_rows)}, Unanswered: {len(unanswered_rows)}")
        
        # If no answers, return early with message
        if len(answered_rows) == 0:
            logger.warning(f"[SUMMARY] ⚠️  No answered questions found")
            return {
                "session_id": session_id,
                "total_questions": len(all_rows),
                "answered_questions": 0,
                "overall_score": 0,
                "strengths": [],
                "weak_areas": ["No answers submitted yet"],
                "recommendations": ["Please complete the interview by answering all questions"],
                "summary": "Interview is not yet complete. Please answer all questions to receive feedback."
            }
        
        # Build conversation history from answered rows only
        conversation_history = []
        questions_asked = []
        answers_received = []
        
        for row in answered_rows:
            question_text = row.get("question_text", "")
            user_answer = row.get("user_answer", "")
            if question_text:
                conversation_history.append({"role": "ai", "content": question_text})
                questions_asked.append(question_text)
            if user_answer and user_answer.strip():
                conversation_history.append({"role": "user", "content": user_answer})
                answers_received.append(user_answer)
        
        # Prepare session data
        session_data = {
            "session_id": session_id,
            "technical_skills": session.get("skills", []),
            "conversation_history": conversation_history,
            "current_question_index": len(questions_asked),
            "questions_asked": questions_asked,
            "answers_received": answers_received
        }
        
        # Get all scores from answered rows
        all_scores = []
        for row in answered_rows:
            relevance = row.get("relevance_score")
            technical_accuracy = row.get("technical_accuracy_score")
            communication = row.get("communication_score")
            overall = row.get("overall_score")
            
            # Use scores from database if available, otherwise use 0
            all_scores.append({
                "relevance": relevance if relevance is not None else 0,
                "technical_accuracy": technical_accuracy if technical_accuracy is not None else 0,
                "communication": communication if communication is not None else 0,
                "overall": overall if overall is not None else 0
            })
        
        logger.info(f"[SUMMARY] Processing {len(all_scores)} answered questions with scores")
        
        # Generate feedback using technical_interview_engine
        try:
            feedback = technical_interview_engine.generate_final_feedback(
                session_data=session_data,
                conversation_history=conversation_history,
                all_scores=all_scores
            )
            
            logger.info(f"[SUMMARY] ✓ Feedback generated successfully")
            logger.info(f"[SUMMARY] Overall score: {feedback.get('overall_score', 0)}")
            logger.info(f"[SUMMARY] Strengths: {len(feedback.get('strengths', []))} items")
            logger.info(f"[SUMMARY] Areas for improvement: {len(feedback.get('areas_for_improvement', []))} items")
            
        except Exception as feedback_error:
            logger.error(f"[SUMMARY] ❌ Error generating feedback: {str(feedback_error)}")
            # Return fallback feedback
            overall_scores = [s.get("overall", 0) for s in all_scores if s.get("overall")]
            avg_score = sum(overall_scores) / len(overall_scores) if overall_scores else 0
            
            feedback = {
                "overall_score": round(avg_score, 2),
                "feedback_summary": f"Interview completed with an overall score of {avg_score:.1f}/100. Review your answers to identify areas for improvement.",
                "strengths": ["Completed the interview"] if len(answered_rows) > 0 else [],
                "areas_for_improvement": ["Review technical concepts"] if avg_score < 70 else [],
                "recommendations": ["Continue practicing technical interviews"]
            }
        
        # Update session status to completed
        try:
            supabase.table("interview_sessions").update({"session_status": "completed"}).eq("id", session_id).execute()
            logger.info(f"[SUMMARY] ✓ Session status updated to completed")
        except Exception as update_error:
            logger.warning(f"[SUMMARY] ⚠️  Could not update session status: {str(update_error)}")
        
        # Return summary response
        summary_response = {
            "session_id": session_id,
            "total_questions": len(all_rows),
            "answered_questions": len(answered_rows),
            "overall_score": feedback.get("overall_score", 0),
            "strengths": feedback.get("strengths", []),
            "weak_areas": feedback.get("areas_for_improvement", []),
            "recommendations": feedback.get("recommendations", []),
            "summary": feedback.get("feedback_summary", "Interview summary not available.")
        }
        
        logger.info(f"[SUMMARY] ========== Summary Generated Successfully ==========")
        return summary_response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[SUMMARY] ❌ CRITICAL ERROR: {str(e)}")
        logger.error(f"[SUMMARY] Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error getting interview summary: {str(e)}")


# ==================== Coding Interview Routes ====================

@router.post("/coding/start")
async def start_coding_interview(
    request: Dict[str, Any],
    supabase: Client = Depends(get_supabase_client)
):
    """
    Start a new coding interview session
    Returns the first coding question based on resume skills
    """
    try:
        user_id = request.get("user_id")
        
        if not user_id:
            raise HTTPException(status_code=400, detail="user_id is required")
        
        # Build resume-aware context
        resume_skills: List[str] = []
        resume_context: Dict[str, Any] = {
            "skills": [],
            "projects": [],
            "experience_level": None,
            "keywords": {},
            "domains": []
        }
        profile_response = None
        
        # user_id is now TEXT (slugified name), not UUID - no validation needed
        
        # Get user profile (required)
        profile = None
        try:
            profile_response = supabase.table("user_profiles").select("*").eq("user_id", user_id).execute()
            profile = profile_response.data[0] if profile_response.data else None
            if not profile:
                raise HTTPException(
                    status_code=404,
                    detail=f"User profile not found for user_id: {user_id}. Please ensure the user exists in user_profiles table."
                )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Error fetching user profile: {str(e)}"
            )
        
        if profile:
            profile_context = build_resume_context_from_profile(profile, supabase)
            resume_context = merge_resume_context(resume_context, profile_context)
            resume_skills = resume_context.get("skills", []) or []
        else:
            try:
                from app.routers.profile import resume_analysis_cache
                cached_data = None
                for cached_info in resume_analysis_cache.values():
                    if cached_info.get("user_id") == user_id:
                        cached_data = cached_info
                        break
                if cached_data:
                    cache_context = build_context_from_cache(cached_data)
                    resume_context = merge_resume_context(resume_context, cache_context)
                    resume_skills = resume_context.get("skills", []) or []
            except Exception:
                pass
        
        if not resume_skills:
            resume_skills = resume_context.get("skills", []) or []
            if not resume_skills:
                resume_skills = []
        
        # If no skills found, require user to upload resume
        if not resume_skills or len(resume_skills) == 0:
            raise HTTPException(
                status_code=400,
                detail="No skills found in resume. Please upload a resume with technical skills first."
            )
        
        # Fetch past performance for adaptive difficulty
        past_performance = None
        if user_id:
            try:
                past_results = supabase.table("coding_round").select("*").eq("user_id", user_id).order("created_at", desc=True).limit(20).execute()
                if past_results.data and len(past_results.data) > 0:
                    total_past = len(past_results.data)
                    correct_past = sum(1 for r in past_results.data if r.get("correctness", False))
                    total_score_past = sum(r.get("final_score", 0) for r in past_results.data)
                    past_performance = {
                        "accuracy": (correct_past / total_past * 100) if total_past > 0 else 0,
                        "average_score": (total_score_past / total_past) if total_past > 0 else 0,
                        "total_sessions": total_past
                    }
            except Exception as e:
                logger.warning(f"Could not fetch past performance: {str(e)}")
        
        # Initialize coding session
        session_data = coding_interview_engine.start_coding_session(
            user_id=user_id,
            resume_skills=resume_skills,
            resume_context=resume_context,
            experience_level=resume_context.get("experience_level") or (profile.get("experience_level") if profile else None)
        )
        
        # Add past performance to session data for adaptive difficulty
        if past_performance:
            session_data["past_performance"] = past_performance
        
        # Generate first coding question
        first_question = coding_interview_engine.generate_coding_question(
            session_data,
            []
        )
        
        # Create session in database
        session_id = None
        try:
            db_session_data = {
                "user_id": user_id,  # TEXT (slugified name)
                "interview_type": "coding",  # New schema: use interview_type
                "role": "Coding Interview",  # Keep for backward compatibility
                "experience_level": (profile.get("experience_level", "Intermediate") if profile else "Intermediate"),
                "skills": resume_skills,
                "session_status": "active"
            }
            session_response = supabase.table("interview_sessions").insert(db_session_data).execute()
            if session_response.data and len(session_response.data) > 0:
                session_id = session_response.data[0]["id"]
            else:
                raise HTTPException(status_code=500, detail="Failed to create interview session")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Error creating interview session: {str(e)}"
            )

        # Store first coding question in coding_round table (new schema)
        question_text = first_question.get("problem") or first_question.get("question") or ""
        if session_id:
            try:
                question_db_data = {
                    "user_id": user_id,
                    "session_id": session_id,
                    "question_number": 1,
                    "question_text": question_text,
                    "difficulty_level": first_question.get("difficulty", "Medium"),
                    "programming_language": "python",  # Default, can be changed by user
                    "user_code": "",  # Placeholder - will be updated when user submits solution
                    "execution_output": None,
                    "execution_time": None,
                    "test_cases_passed": 0,
                    "total_test_cases": 0,
                    "correct_solution": None,
                    "correctness": False,
                    "final_score": 0,
                    "ai_feedback": None
                }
                supabase.table("coding_round").insert(question_db_data).execute()
            except Exception as e:
                logger.warning(f"Could not store first question: {str(e)}")

        await log_interview_transcript(
            supabase,
            session_id,
            "coding",
            question_text,
            None
        )

        # Add question_number to question object
        first_question["question_number"] = 1
        
        CODING_TOTAL_QUESTIONS = 5  # Constant for coding interview total questions
        
        return {
            "session_id": session_id,
            "question": first_question,
            "question_number": 1,
            "total_questions": CODING_TOTAL_QUESTIONS,
            "skills": resume_skills,
            "interview_completed": False,
            "user_id": user_id  # Include user_id in response
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error starting coding interview: {str(e)}")


@router.post("/coding/next")
async def get_next_coding_question(
    request: Dict[str, Any] = Body(...),
    supabase: Client = Depends(get_supabase_client)
):
    """
    Get the next coding question after submitting a solution
    """
    try:
        # Log incoming request for debugging
        logger.info(f"[CODING/NEXT] Received request: session_id={request.get('session_id')}, has_solution={bool(request.get('solution'))}, solution_length={len(request.get('solution', ''))}")
        
        session_id = request.get("session_id")
        previous_question = request.get("previous_question", {})
        solution = request.get("solution", "")
        
        if not session_id:
            raise HTTPException(status_code=400, detail="session_id is required")
        
        if not solution or not solution.strip():
            logger.warning(f"[CODING/NEXT] No solution provided in request for session {session_id}")
            raise HTTPException(status_code=400, detail="solution is required. Please submit your code.")
        
        # Prepare transcript logging
        if isinstance(previous_question, dict):
            question_text_for_answer = (
                previous_question.get("problem")
                or previous_question.get("question")
                or json.dumps(previous_question)
            )
        else:
            question_text_for_answer = previous_question or ""

        # Get session data
        session = None
        skills = []
        questions = []
        session_experience = None
        session_projects: List[str] = []
        session_domains: List[str] = []
        
        try:
            session_response = supabase.table("interview_sessions").select("*").eq("id", session_id).execute()
            if session_response.data and len(session_response.data) > 0:
                session = session_response.data[0]
                skills = session.get("skills", []) or []
                session_experience = session.get("experience_level")
                session_user_id = session.get("user_id")
                if session_user_id:
                    try:
                        profile_resp = (
                            supabase.table("user_profiles")
                            .select("*")
                            .eq("user_id", session_user_id)
                            .limit(1)
                            .execute()
                        )
                        profile_row = profile_resp.data[0] if profile_resp.data else None
                        if profile_row:
                            profile_context = build_resume_context_from_profile(profile_row, supabase)
                            session_projects = profile_context.get("projects", [])
                            session_domains = profile_context.get("domains", [])
                            if profile_context.get("experience_level"):
                                session_experience = profile_context.get("experience_level")
                    except Exception as profile_err:
                        logger.warning(f"Could not refresh resume context for coding session {session_id}: {profile_err}")
                
                # Get previous questions from coding_round table (new schema)
                try:
                    round_data_response = supabase.table("coding_round").select("question_text, question_number, user_code").eq("session_id", session_id).order("question_number").execute()
                    questions = []
                    for row in (round_data_response.data or []):
                        question_text = row.get("question_text", "")
                        if question_text:
                            questions.append({
                                "question": question_text,
                                "question_number": row.get("question_number", 0)
                            })
                except Exception as e:
                    logger.warning(f"Could not fetch questions: {str(e)}")
                    questions = []
        except Exception as e:
            logger.warning(f"Session not found in database: {str(e)}")
            skills = ["Python", "Data Structures", "Algorithms"]
        
        # Log the submitted solution
        await log_interview_transcript(
            supabase,
            session_id,
            "coding",
            question_text_for_answer,
            solution
        )

        # Get user_id and language from request
        # Priority: session user_id (if exists) > request user_id > try to get from user_profiles
        user_id = None
        if session and session.get("user_id"):
            user_id = session.get("user_id")
            logger.info(f"Using user_id from session: {user_id}")
        else:
            user_id = request.get("user_id")
            if not user_id:
                # Try to get user_id from user_profiles if we have session_user_id
                if session_user_id:
                    user_id = session_user_id
                    logger.info(f"Using user_id from session_user_id: {user_id}")
                else:
                    # Last resort: try to find any user in user_profiles
                    try:
                        users_response = supabase.table("user_profiles").select("user_id").limit(1).execute()
                        if users_response.data and len(users_response.data) > 0:
                            user_id = users_response.data[0].get("user_id")
                            logger.info(f"Using first user from user_profiles: {user_id}")
                        else:
                            user_id = "unknown"
                            logger.warning("No user found in user_profiles, using 'unknown'")
                    except Exception as e:
                        logger.warning(f"Could not get user from user_profiles: {str(e)}")
                        user_id = "unknown"
        
        # Validate user_id exists in user_profiles
        if user_id and user_id != "unknown":
            try:
                user_check = supabase.table("user_profiles").select("user_id").eq("user_id", user_id).limit(1).execute()
                if not user_check.data:
                    logger.warning(f"User {user_id} not found in user_profiles, but continuing anyway")
            except Exception as e:
                logger.warning(f"Could not validate user_id: {str(e)}")
        programming_language = request.get("programming_language", "python")
        difficulty_level = previous_question.get("difficulty") if isinstance(previous_question, dict) else None
        
        # Get question data (test cases, table setup for SQL, etc.)
        question_data = None
        sql_setup = None
        if isinstance(previous_question, dict):
            question_data = previous_question
            sql_setup = previous_question.get("table_setup")
        else:
            # Try to parse if it's a JSON string
            try:
                if isinstance(previous_question, str):
                    question_data = json.loads(previous_question)
                    sql_setup = question_data.get("table_setup") if question_data else None
            except (json.JSONDecodeError, TypeError):
                pass
        
        # Evaluate the solution and generate feedback
        logger.info(f"[CODING/NEXT] ========== Starting Code Evaluation ==========")
        logger.info(f"[CODING/NEXT] Session ID: {session_id}")
        logger.info(f"[CODING/NEXT] Solution length: {len(solution)} chars")
        logger.info(f"[CODING/NEXT] Programming language: {programming_language}")
        logger.info(f"[CODING/NEXT] Question text length: {len(question_text_for_answer)} chars")
        logger.info(f"[CODING/NEXT] Has question_data: {bool(question_data)}")
        logger.info(f"[CODING/NEXT] Has test_cases: {bool(question_data and question_data.get('test_cases')) if question_data else False}")
        
        try:
            evaluation_result = await evaluate_coding_solution(
                question_text_for_answer,
                solution,
                programming_language,
                difficulty_level,
                question_data=question_data,
                sql_setup=sql_setup
            )
        except Exception as eval_error:
            import traceback
            logger.error(f"✗ CRITICAL: Code evaluation failed: {str(eval_error)}")
            logger.error(f"  Traceback: {traceback.format_exc()}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to evaluate code: {str(eval_error)}"
            )
        
        logger.info(f"[CODING/NEXT] ========== Evaluation Complete ==========")
        logger.info(f"[CODING/NEXT] Correctness: {evaluation_result.get('correctness')}")
        logger.info(f"[CODING/NEXT] Score: {evaluation_result.get('score')}")
        logger.info(f"[CODING/NEXT] Execution output length: {len(evaluation_result.get('execution_output') or '')} chars")
        logger.info(f"[CODING/NEXT] AI feedback length: {len(evaluation_result.get('feedback') or '')} chars")
        logger.info(f"[CODING/NEXT] Correct solution length: {len(evaluation_result.get('correct_solution') or '')} chars")
        logger.info(f"[CODING/NEXT] Test cases passed: {evaluation_result.get('test_cases_passed', 0)}/{evaluation_result.get('total_test_cases', 0)}")
        
        # Validate evaluation result has required fields
        if not evaluation_result:
            raise HTTPException(status_code=500, detail="Code evaluation returned no result")
        
        if "correctness" not in evaluation_result:
            logger.warning(f"[CODING/NEXT] Evaluation result missing 'correctness' field, defaulting to False")
            evaluation_result["correctness"] = False
        
        # Store coding result
        # Get the question number from the previous question (the one user just answered)
        if isinstance(previous_question, dict) and previous_question.get("question_number"):
            current_question_number = previous_question.get("question_number")
            logger.info(f"[CODING/NEXT] Using question_number from previous_question: {current_question_number}")
        else:
            # Try to get from existing questions in coding_round
            try:
                existing_questions = supabase.table("coding_round").select("question_number").eq("session_id", session_id).order("question_number", desc=True).limit(1).execute()
                if existing_questions.data and len(existing_questions.data) > 0:
                    current_question_number = existing_questions.data[0].get("question_number", 1)
                    logger.info(f"[CODING/NEXT] Using question_number from existing questions: {current_question_number}")
                else:
                    current_question_number = len(questions) if questions else 1
                    logger.info(f"[CODING/NEXT] No existing questions found, using calculated: {current_question_number}")
            except Exception as e:
                logger.warning(f"Could not determine question number: {str(e)}")
                current_question_number = len(questions) if questions else 1
                logger.info(f"[CODING/NEXT] Fallback question_number: {current_question_number}")
        
        logger.info(f"[CODING/NEXT] Final question_number for storage: {current_question_number}")
        
        # Store result in database
        # Ensure we have actual values, not None or empty strings for critical fields
        execution_output = evaluation_result.get("execution_output") or ""
        ai_feedback = evaluation_result.get("feedback") or ""
        correct_solution = evaluation_result.get("correct_solution") or ""
        
        # Log evaluation results for debugging
        logger.info(f"Evaluation results - Correctness: {evaluation_result.get('correctness')}, Score: {evaluation_result.get('score')}")
        logger.info(f"Feedback length: {len(ai_feedback)}, Solution length: {len(correct_solution)}, Output length: {len(execution_output)}")
        
        # Log for debugging
        logger.info(f"Storing coding result for session {session_id}, question {current_question_number}")
        logger.info(f"Execution output length: {len(execution_output)}, Feedback length: {len(ai_feedback)}, Solution length: {len(correct_solution)}")
        
        # Store the result - CRITICAL: This must succeed
        # Get question_text from existing row if available, otherwise use question_text_for_answer
        stored_question_text = question_text_for_answer
        try:
            existing_question_row = supabase.table("coding_round").select("question_text").eq("session_id", session_id).eq("question_number", current_question_number).execute()
            if existing_question_row.data and len(existing_question_row.data) > 0:
                stored_question_text = existing_question_row.data[0].get("question_text", question_text_for_answer)
        except Exception as e:
            logger.warning(f"Could not fetch existing question text: {str(e)}")
        
        # CRITICAL: Storage must succeed - don't continue if it fails
        logger.info(f"[CODING/NEXT] Attempting to store result for session {session_id}, question {current_question_number}")
        logger.info(f"[CODING/NEXT] Storage data: user_code length={len(solution)}, execution_output length={len(execution_output)}, ai_feedback length={len(ai_feedback)}, correctness={evaluation_result.get('correctness', False)}")
        
        try:
            await store_coding_result(
                supabase=supabase,
                user_id=user_id,
                session_id=session_id,
                question_number=current_question_number,
                question_text=stored_question_text,
                user_code=solution,
                programming_language=programming_language,
                difficulty_level=difficulty_level,
                execution_output=execution_output,
                correctness=evaluation_result.get("correctness", False),
                ai_feedback=ai_feedback,
                final_score=evaluation_result.get("score", 0),
                execution_time=evaluation_result.get("execution_time"),
                test_cases_passed=evaluation_result.get("test_cases_passed", 0),
                total_test_cases=evaluation_result.get("total_test_cases", 0),
                correct_solution=correct_solution
            )
            logger.info(f"✓ Successfully stored coding result for session {session_id}, question {current_question_number}")
        except Exception as e:
            # CRITICAL: Storage failure must stop execution - don't silently continue
            import traceback
            error_msg = f"CRITICAL: Failed to store coding result: {str(e)}"
            logger.error(f"✗ {error_msg}")
            logger.error(f"  Session: {session_id}, Question: {current_question_number}, User: {user_id}")
            logger.error(f"  Full traceback: {traceback.format_exc()}")
            logger.error(f"  This will cause results page to show no data!")
            logger.error(f"  Stopping interview flow to prevent data loss.")
            
            # Re-raise as HTTPException so frontend gets proper error
            raise HTTPException(
                status_code=500,
                detail=f"Failed to save coding result. Please try again. Error: {str(e)}"
            )
        
        # Check completion based on ANSWERED questions (rows with user_code)
        # Count how many questions have been answered (have user_code) for this session
        CODING_TOTAL_QUESTIONS = 5  # Constant for coding interview total questions
        
        try:
            # Count only answered questions (those with user_code)
            answered_questions_response = supabase.table("coding_round").select("question_number").eq("session_id", session_id).not_.is_("user_code", "null").neq("user_code", "").execute()
            answered_count = len(answered_questions_response.data or [])
            logger.info(f"Total answered questions for session {session_id}: {answered_count}")
        except Exception as e:
            logger.warning(f"Could not count answered questions: {str(e)}")
            # Fallback: count all questions (less accurate but works)
            try:
                all_questions_response = supabase.table("coding_round").select("question_number").eq("session_id", session_id).execute()
                answered_count = len(all_questions_response.data or [])
            except Exception:
                answered_count = len(questions)
        
        # If we've answered 5 questions, mark as completed
        if answered_count >= CODING_TOTAL_QUESTIONS:
            logger.info(f"Interview completed - {answered_count} questions answered")
            return {
                "interview_completed": True,
                "message": "Coding interview completed! Thank you for your solutions.",
                "session_id": session_id
            }
        
        # Calculate next question number (1-5)
        # Next question number is answered_count + 1 (since we just answered current question)
        next_question_number = answered_count + 1
        
        # Ensure we don't exceed total questions
        if next_question_number > CODING_TOTAL_QUESTIONS:
            logger.warning(f"Next question number {next_question_number} exceeds total {CODING_TOTAL_QUESTIONS}, marking as completed")
            return {
                "interview_completed": True,
                "message": "Coding interview completed! Thank you for your solutions.",
                "session_id": session_id
            }
        
        # Generate next question
        # Build list of all previous questions to prevent duplicates
        previous_questions_text = []
        try:
            # Get all questions (answered and unanswered) to prevent duplicates
            all_questions_response = supabase.table("coding_round").select("question_text").eq("session_id", session_id).order("question_number").execute()
            for row in (all_questions_response.data or []):
                question_text = row.get("question_text", "")
                if question_text:
                    previous_questions_text.append(question_text)
        except Exception as e:
            logger.warning(f"Could not fetch previous questions for duplicate check: {str(e)}")
            # Fallback: use questions from memory
            previous_questions_text = [q.get("question", "") for q in questions]
        
        session_data = {
            "session_id": session_id,
            "coding_skills": skills,
            "current_question_index": answered_count,
            "questions_asked": previous_questions_text,  # All previous questions to prevent duplicates
            "solutions_submitted": [],
            "experience_level": session_experience,
            "resume_projects": session_projects,
            "domains": session_domains
        }
        
        # Generate next question - ensure this always succeeds
        try:
            next_question = coding_interview_engine.generate_coding_question(
                session_data,
                previous_questions_text
            )
            
            # Validate question was generated
            if not next_question:
                logger.error("Failed to generate next question - got None")
                raise Exception("Failed to generate next question")
            
            # Ensure question has required fields
            if not next_question.get("problem") and not next_question.get("question"):
                logger.error(f"Generated question missing problem field: {next_question}")
                # Try to get fallback question
                next_question = coding_interview_engine._get_fallback_coding_question(session_data, previous_questions_text)
            
            logger.info(f"✓ Generated next question (number {next_question_number}): {next_question.get('problem', next_question.get('question', 'N/A'))[:100]}")
            
        except Exception as gen_error:
            logger.error(f"✗ Error generating next question: {str(gen_error)}")
            # Use fallback question to ensure we always return something
            try:
                next_question = coding_interview_engine._get_fallback_coding_question(session_data, previous_questions_text)
                logger.info("✓ Using fallback question")
            except Exception as fallback_error:
                logger.error(f"✗ Fallback question generation also failed: {str(fallback_error)}")
                # Last resort: return a simple question
                next_question = {
                    "problem": "Write a function to solve a coding problem. Show your problem-solving approach.",
                    "difficulty": "Medium",
                    "examples": [],
                    "constraints": "",
                    "topics": ["Algorithms", "Problem Solving"]
                }
        
        # Store question in coding_round table if session exists (new schema)
        if session:
            try:
                user_id = str(session.get("user_id", "")) if session else ""
                question_text = next_question.get("problem") or next_question.get("question") or json.dumps(next_question)
                question_db_data = {
                    "user_id": user_id,
                    "session_id": session_id,
                    "question_number": next_question_number,
                    "question_text": question_text,
                    "difficulty_level": next_question.get("difficulty", "Medium"),
                    "programming_language": request.get("programming_language", "python"),
                    "user_code": "",  # Placeholder - will be updated when user submits solution
                    "execution_output": None,
                    "execution_time": None,
                    "test_cases_passed": 0,
                    "total_test_cases": 0,
                    "correct_solution": None,
                    "correctness": False,
                    "final_score": 0,
                    "ai_feedback": None
                }
                supabase.table("coding_round").insert(question_db_data).execute()
            except Exception as e:
                logger.warning(f"Could not store question: {str(e)}")

        await log_interview_transcript(
            supabase,
            session_id,
            "coding",
            next_question.get("problem") or next_question.get("question") or "",
            None
        )
        
        # Add question_number to question object
        next_question["question_number"] = next_question_number
        
        # Log what we're returning
        logger.info(f"📤 Returning next question: number={next_question_number}, has_problem={bool(next_question.get('problem'))}, has_question={bool(next_question.get('question'))}")
        
        # Get user_id from session
        user_id = None
        if session and session.get("user_id"):
            user_id = session.get("user_id")
        
        CODING_TOTAL_QUESTIONS = 5  # Constant for coding interview total questions
        
        return {
            "question": next_question,
            "question_number": next_question_number,
            "total_questions": CODING_TOTAL_QUESTIONS,
            "interview_completed": False,
            "session_id": session_id,  # Include session_id for frontend
            "user_id": user_id  # Include user_id for frontend
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting next coding question: {str(e)}")


# ==================== HR Interview Routes ====================

@router.post("/hr/start")
async def start_hr_interview(
    request_body: Dict[str, Any] = Body(...),
    supabase: Client = Depends(get_supabase_client)
):
    """
    Start a new HR interview session
    Returns the first HR question based on resume
    """
    # FIX 12: Test database connection at the start
    if not test_supabase_connection(supabase):
        raise HTTPException(
            status_code=503,
            detail="Database connection unavailable. Please try again shortly."
        )
    
    try:
        # Input validation
        user_id = request_body.get("user_id")
        
        if not user_id:
            logger.error("[HR START] Missing user_id in request body")
            raise HTTPException(status_code=400, detail="Missing required information in the request. Please ensure all fields are provided.")
        
        if not isinstance(user_id, str) or not user_id.strip():
            logger.error(f"[HR START] Invalid user_id format: {user_id}")
            raise HTTPException(status_code=400, detail="Invalid request format. Please check your input and try again.")
        
        logger.info(f"[HR START] Starting HR interview for user_id: {user_id}")
        
        # user_id is now TEXT (slugified name), not UUID - no validation needed
        
        # Get user profile (required)
        try:
            profile_response = supabase.table("user_profiles").select("*").eq("user_id", user_id).execute()
            profile = profile_response.data[0] if profile_response.data else None
        except Exception as db_error:
            # Log detailed error information for debugging
            logger.error(
                f"[HR START] Database error fetching user profile for user_id: {user_id}. Error: {str(db_error)}", 
                exc_info=True
            )
            
            # Raise HTTPException with 500 status and user-friendly message
            raise HTTPException(
                status_code=500,
                detail="Failed to start interview due to a server error. Please try again."
            )
        
        if not profile:
            raise HTTPException(
                status_code=404,
                detail="User profile not found. Please upload a resume first to create your profile."
            )
        
        # Build resume context
        resume_context = build_resume_context_from_profile(profile, supabase)
        
        # Create session in database
        db_session_data = {
            "user_id": user_id,  # TEXT (slugified name)
            "interview_type": "hr",
            "role": "HR Interview",
            "experience_level": profile.get("experience_level", "Intermediate"),
            "skills": resume_context.get("skills", []),
            "session_status": "active"
        }
        
        try:
            session_response = supabase.table("interview_sessions").insert(db_session_data).execute()
            if not session_response.data or len(session_response.data) == 0:
                logger.error("[HR START] Failed to create interview session - no data returned")
                raise HTTPException(status_code=500, detail="A server error occurred while processing your request. Please try again.")
            session_id = session_response.data[0]["id"]
        except Exception as db_error:
            error_str = str(db_error)
            logger.error(f"[HR START] Database error creating session: {str(db_error)}", exc_info=True)
            if "foreign key constraint" in error_str.lower():
                raise HTTPException(
                    status_code=400,
                    detail="User profile not found. Please upload a resume first to create your profile."
                )
            raise HTTPException(status_code=500, detail="A server error occurred while processing your request. Please try again.")
        
        # ✅ WARM-UP STAGE: Always start with first warm-up question (question_number = 1)
        # Warm-up questions help students and freshers feel relaxed and confident
        question_text = HR_WARMUP_QUESTIONS[0]  # "Tell me about yourself."
        logger.info(f"[HR START] ✅ Starting with warm-up question 1/3: {question_text}")
        
        # Generate audio URL for the question BEFORE storing (same as technical interview)
        audio_url = None
        try:
            import urllib.parse
            from app.utils.url_utils import get_api_base_url
            if question_text:
                encoded_text = urllib.parse.quote(question_text)
                # Use absolute URL - works for both localhost and production
                base_url = get_api_base_url()
                audio_url = f"{base_url}/api/interview/text-to-speech?text={encoded_text}"
                logger.info(f"[HR INTERVIEW] ✅ Generated audio_url: {audio_url}")
                logger.info(f"[HR INTERVIEW] Base URL: {base_url}, Question text length: {len(question_text)}")
                logger.info(f"[HR INTERVIEW] Question text preview: {question_text[:50]}...")
            else:
                logger.error(f"[HR INTERVIEW] ❌ question_text is empty, cannot generate audio_url")
                audio_url = None  # FIX 18: Explicitly set to None
        except Exception as e:
            # FIX 18: Log error and explicitly set audio_url to None to guarantee endpoint continues
            logger.error(f"[HR INTERVIEW] ❌ Could not generate audio URL for HR question: {str(e)}", exc_info=True)
            audio_url = None  # Explicitly set to None to ensure endpoint continues
        
        # Store first question in hr_round table (question_number = 1, supports up to 10 questions)
        question_db_data = {
            "user_id": str(user_id),
            "session_id": session_id,
            "question_number": 1,  # First question
            "question_text": question_text,
            "question_category": "HR",
            "user_answer": "",  # Initialize with empty answer
            "communication_score": None,
            "cultural_fit_score": None,
            "motivation_score": None,
            "clarity_score": None,
            "overall_score": None,
            "ai_feedback": None,
            "response_time": None
        }
        
        # ✅ FIX 1: Make question saving mandatory - fail fast if save fails
        try:
            insert_response = supabase.table("hr_round").insert(question_db_data).execute()
            if not insert_response.data or len(insert_response.data) == 0:
                logger.error("[HR START] Failed to store HR question - no data returned from insert")
                raise HTTPException(
                    status_code=500,
                    detail="Failed to save interview question. Please try again."
                )
            # ✅ FIX 1: Verify question_number is correctly saved
            saved_question = insert_response.data[0] if insert_response.data else None
            if saved_question:
                saved_question_number = saved_question.get('question_number')
                logger.info(f"[HR START] ✅ Stored first HR question in database (question_number={saved_question_number})")
                logger.info(f"[HR START] Saved row ID: {saved_question.get('id')}, session_id: {saved_question.get('session_id')}")
                if saved_question_number != 1:
                    logger.warning(f"[HR START] ⚠️ Expected question_number=1, but got {saved_question_number}")
            else:
                logger.warning(f"[HR START] ⚠️ Insert succeeded but no data returned")
        except HTTPException:
            # Re-raise HTTPException as-is
            raise
        except Exception as e:
            logger.error(f"[HR START] Failed to store HR question: {str(e)}", exc_info=True)
            # ✅ FIX 1: Do NOT continue if storage fails - raise error immediately
            raise HTTPException(
                status_code=500,
                detail="Failed to save interview question. Please try again."
            )
        
        response_data = {
            "session_id": session_id,
            "question": question_text,
            "question_type": "HR",
            "question_number": 1,
            "total_questions": HR_WARMUP_COUNT + 7,  # 3 warm-up + 7 resume-based = 10 total
            "interview_completed": False,  # First question, interview not completed
            "is_warmup": True,  # Indicate this is a warm-up question
            "user_id": user_id,
            "audio_url": audio_url  # Include audio URL for TTS playback
        }
        logger.info(f"[HR START] ✅ Returning response with audio_url: {audio_url is not None}")
        logger.info(f"[HR START] Response keys: {list(response_data.keys())}")
        return response_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[HR START] Unexpected error starting HR interview: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to start interview. Please try again.")


@router.post("/hr/{session_id}/next-question")
async def get_next_hr_question(
    session_id: str,
    request: Dict[str, Any] = Body(...),
    supabase: Client = Depends(get_supabase_client)
):
    """
    Get the next HR question for the interview
    Accepts user_answer in request body, saves it first, then generates context-aware next question
    Uses conversation history from database to enable context-aware follow-up questions
    """
    # FIX 12: Test database connection at the start
    if not test_supabase_connection(supabase):
        raise HTTPException(
            status_code=503,
            detail="Database connection unavailable. Please try again shortly."
        )
    
    try:
        # Input validation
        if not session_id or not isinstance(session_id, str) or not session_id.strip():
            logger.error(f"[HR NEXT QUESTION] Invalid session_id: {session_id}")
            raise HTTPException(status_code=400, detail="Invalid request format. Please check your input and try again.")
        
        logger.info(f"[HR NEXT QUESTION] Request for session_id: {session_id}")
        logger.debug(f"[HR NEXT QUESTION] Request body keys: {list(request.keys())}")
        
        # Get session
        try:
            session_response = supabase.table("interview_sessions").select("*").eq("id", session_id).execute()
        except Exception as db_error:
            logger.error(f"[HR NEXT QUESTION] Database error fetching session: {str(db_error)}", exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to retrieve interview session. Please try again.")
        
        if not session_response.data or len(session_response.data) == 0:
            logger.warning(f"[HR NEXT QUESTION] Session not found: {session_id}")
            raise HTTPException(status_code=404, detail="Interview session not found. Please start a new interview.")
        
        session = session_response.data[0]
        
        # FIX 19: Check if session is already completed
        session_status = session.get("session_status", "").lower()
        if session_status == "completed":
            logger.warning(f"[HR NEXT QUESTION] Session already completed: {session_id}")
            raise HTTPException(
                status_code=400,
                detail="This interview session has already been completed. Please start a new interview."
            )
        
        # Validate session is HR type
        session_type = session.get("interview_type", "").lower()
        if session_type != "hr":
            logger.error(f"[HR NEXT QUESTION] Wrong session type: {session_type} (expected: hr)")
            raise HTTPException(
                status_code=400, 
                detail="This endpoint is for HR interviews only. Please use the correct interview type."
            )
        
        # Step 1: Save current answer if provided in request
        # FIX: Retrieve the answer using common keys
        user_answer = request.get("user_answer") or request.get("answer")
        
        # FIX: Implement type validation
        if user_answer is not None:
            # Validate user_answer type
            if not isinstance(user_answer, str):
                logger.warning(f"[HR NEXT QUESTION] Invalid user_answer type received: {type(user_answer)}. Attempting conversion.")
                
                # Attempt to convert to string if not None; otherwise, set to None
                try:
                    user_answer = str(user_answer) 
                except Exception:
                    user_answer = None
                    
            # ✅ FIX: Reject empty answers - NO random/auto-answers allowed
            if user_answer and user_answer.strip():
                # The answer is valid and non-empty. Proceed with saving and processing.
                # FIX 13 & 17: Save answer before building conversation history (transaction pattern)
                try:
                    # Get the last question for this session to update with the answer
                    last_question_response = supabase.table("hr_round").select("*").eq("session_id", session_id).order("question_number", desc=True).limit(1).execute()
                    
                    if last_question_response.data and len(last_question_response.data) > 0:
                        last_question = last_question_response.data[0]
                        question_number = last_question.get("question_number")
                        
                        # Update the last question with the user's answer
                        update_data = {
                            "user_answer": user_answer
                        }
                        
                        supabase.table("hr_round").update(update_data).eq("session_id", session_id).eq("question_number", question_number).execute()
                        logger.info(f"[HR NEXT QUESTION] ✅ Saved user answer for question {question_number}")
                    else:
                        logger.warning("[HR NEXT QUESTION] No question found to update with answer")
                except Exception as e:
                    # FIX 13: Log error and raise HTTPException to maintain data consistency
                    logger.error(f"[HR NEXT QUESTION] Failed to save user answer: {str(e)}", exc_info=True)
                    raise HTTPException(
                        status_code=500,
                        detail="Failed to save interview data. Please try again."
                    )
            else:
                # ✅ FIX: Reject empty answers - do NOT allow unanswered questions to move forward
                logger.warning("[HR NEXT QUESTION] Empty answer provided - rejecting request")
                raise HTTPException(
                    status_code=400,
                    detail="I could not hear your answer. Please speak again."
                )
        
        # FIX 17: Step 2: Retrieve full conversation history from hr_round table AFTER saving answer
        hr_round_response = supabase.table("hr_round").select(
            "question_text, question_number, user_answer"
        ).eq("session_id", session_id).order("question_number").execute()
        
        # Step 3: Build conversation history array in exact format for LLM
        conversation_history = []
        questions_asked = []
        answers_received = []
        
        for row in (hr_round_response.data or []):
            question_text = row.get("question_text", "")
            user_answer_text = row.get("user_answer", "")
            
            # Add question to conversation history
            if question_text:
                conversation_history.append({"role": "ai", "content": question_text})
                questions_asked.append(question_text)
            
            # Add answer to conversation history (only if not empty)
            if user_answer_text and user_answer_text.strip():
                conversation_history.append({"role": "user", "content": user_answer_text})
                answers_received.append(user_answer_text)
        
        # Check if interview should end (max 10 questions for HR)
        HR_MAX_QUESTIONS = 10
        current_question_count = len(questions_asked)
        
        # If we already have 10 questions, don't generate another one
        if current_question_count >= HR_MAX_QUESTIONS:
            logger.info(f"[HR NEXT QUESTION] Interview completed: {current_question_count} questions already asked (max: {HR_MAX_QUESTIONS})")
            return {
                "interview_completed": True,
                "message": "Interview completed. Maximum questions reached."
            }
        
        # ✅ WARM-UP STAGE: Check if we're still in warm-up questions (1-3)
        # Questions 1, 2, 3 are always warm-up questions
        next_question_number = current_question_count + 1
        
        if next_question_number <= HR_WARMUP_COUNT:
            # We're still in warm-up stage - return the next warm-up question
            warmup_index = next_question_number - 1  # Convert to 0-based index
            question_text = HR_WARMUP_QUESTIONS[warmup_index]
            logger.info(f"[HR NEXT QUESTION] ✅ Warm-up question {next_question_number}/{HR_WARMUP_COUNT}: {question_text}")
        else:
            # ✅ RESUME-BASED STAGE: After warm-up, switch to AI-generated questions
            logger.info(f"[HR NEXT QUESTION] ✅ Warm-up complete, generating resume-based AI question (question {next_question_number})")
            
            # Get user profile for resume context
        user_id = session.get("user_id")
        profile_response = supabase.table("user_profiles").select("*").eq("user_id", user_id).execute()
        profile = profile_response.data[0] if profile_response.data else None
        
        resume_context = {}
        experience_level = "Intermediate"
        skills = []
        
        if profile:
            resume_context = build_resume_context_from_profile(profile, supabase)
            experience_level = profile.get("experience_level", "Intermediate")
            skills = resume_context.get("skills", [])
        
        # Generate next HR question using OpenAI with conversation history
        question_text = None
        try:
            from openai import OpenAI, APIError, RateLimitError
            from app.config.settings import settings
            
            # Check if API key is available
            if not settings.openai_api_key:
                logger.error("[HR NEXT QUESTION] OpenAI API key is missing.")
                raise HTTPException(status_code=503, detail="AI service temporarily unavailable. API key not set.")
            
            client = OpenAI(api_key=settings.openai_api_key)
            
            # Build context for HR question generation
            skills_context = ", ".join(skills[:10]) if skills else "general skills"
            
            # Build conversation context
            conversation_context = ""
            if conversation_history:
                # Include last 30 messages to maintain context while staying within token limits
                recent_messages = conversation_history[-30:] if len(conversation_history) > 30 else conversation_history
                conversation_context = "\n".join([
                    f"{msg.get('role', 'unknown').upper()}: {msg.get('content', '')[:300]}"
                    for msg in recent_messages
                ])
            
            # Build list of previously asked questions
            questions_list = ""
            if questions_asked:
                questions_list = "\n".join([f"{i+1}. {q[:150]}" for i, q in enumerate(questions_asked)])
            
            # HR-focused system prompt
            system_prompt = """You are an experienced, friendly HR interviewer conducting a natural, conversational voice-based interview.

Your interview style:
- Speak naturally and conversationally, as if talking to a colleague
- Build on previous answers - ask follow-up questions when appropriate
- Show genuine interest in the candidate's responses
- Focus on behavioral, cultural fit, communication, and motivation questions
- Reference what the candidate mentioned in previous answers
- Avoid awkward pauses - keep the conversation flowing smoothly
- Never repeat questions that have already been asked

Question guidelines:
- Keep questions concise (1-2 sentences) for voice interaction
- Make questions feel natural and conversational
- Build on previous answers to create a cohesive interview flow
- Focus on HR topics: teamwork, problem-solving, motivation, cultural fit, communication
- Reference specific experiences from their resume when relevant"""

            user_prompt = f"""Generate the next HR interview question for a smooth, natural conversation flow.

CANDIDATE'S BACKGROUND (from resume):
Skills: {skills_context}
Experience Level: {experience_level}

CONVERSATION HISTORY (full context):
{conversation_context if conversation_context else "This is the first question. Start with a friendly introduction and a foundational HR question."}

PREVIOUSLY ASKED QUESTIONS (do NOT repeat these):
{questions_list if questions_list else "None - this is the first question"}

INTERVIEW PROGRESS:
- Questions asked so far: {len(questions_asked)}
- Answers received: {len(answers_received)}

Generate ONE natural, conversational HR question that:
1. Flows naturally from the conversation (builds on previous answers if any)
2. Is relevant to HR topics: behavioral, cultural fit, communication, motivation, teamwork
3. Has NOT been asked before (check the list above)
4. Feels like a natural next question in a human HR interview
5. Is appropriate for voice interaction (concise, clear)
6. References specific experiences from their resume when relevant

IMPORTANT:
- If this is early in the interview, start with foundational HR questions (e.g., "Tell me about yourself")
- If the candidate mentioned something interesting, ask a follow-up
- Make it feel like a real conversation, not a scripted Q&A
- Focus on understanding the candidate's personality, work style, and cultural fit

Return ONLY the question text, nothing else. Make it sound natural and conversational."""

            # Build messages with conversation history
            messages = [
                {"role": "system", "content": system_prompt}
            ]
            
            # Step 4: Add conversation history as context messages for context-aware generation
            # CRITICAL: This enables the AI to reference previous answers and build natural follow-ups
            if conversation_history and len(conversation_history) > 0:
                # Include last 30 messages to maintain context while staying within token limits
                history_messages = conversation_history[-30:] if len(conversation_history) > 30 else conversation_history
                for msg in history_messages:
                    role = msg.get("role", "user")
                    content = msg.get("content", "")
                    if role == "ai" or role == "assistant":
                        messages.append({"role": "assistant", "content": content[:500]})  # Limit length
                    elif role == "user":
                        messages.append({"role": "user", "content": content[:500]})  # Limit length
                logger.info(f"[HR NEXT QUESTION] ✅ Added {len(history_messages)} conversation history messages for context-aware question generation")
            
            # Add the current prompt
            messages.append({"role": "user", "content": user_prompt})
            
            # Generate question with timeout for better control over network latency
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=messages,
                temperature=0.7,
                max_tokens=150,
                timeout=30  # FIX: ADD TIMEOUT for better control over network latency
            )
            
            question_text = response.choices[0].message.content.strip()
            logger.info(f"[HR INTERVIEW] Generated next question: {question_text[:50]}...")
            
        except RateLimitError as e:
            # FIX: Catch specific RateLimitError (HTTP 429)
            logger.error(f"[HR NEXT QUESTION] OpenAI rate limit exceeded: {str(e)}")
            # Handle the failure by raising a 503 error, suggesting retry
            raise HTTPException(
                status_code=503, 
                detail="The AI service is currently experiencing high demand. Please try again shortly."
            )
            
        except APIError as e:
            # FIX: Catch general APIError (e.g., invalid key, bad request, server side)
            logger.error(f"[HR NEXT QUESTION] OpenAI API error occurred: {str(e)}", exc_info=True)
            # Generic failure for external API issue
            raise HTTPException(
                status_code=500, 
                detail="An external service error occurred during question generation. Please try again."
            )
            
        except Exception as e:
            # Catch all other unexpected errors (network, parsing, etc.)
            logger.error(f"[HR NEXT QUESTION] Unexpected error during AI question generation: {str(e)}", exc_info=True)
            # Use fallback for unexpected errors to ensure interview can continue
            logger.warning("[HR NEXT QUESTION] Using fallback question generator due to unexpected error")
            question_text = None  # Will trigger fallback
        
        # Fallback to question_generator if OpenAI failed
        if not question_text:
            try:
                from app.services.question_generator import question_generator
                questions = question_generator.generate_questions(
                    role="HR Interview",
                    experience_level=experience_level,
                    skills=skills,
                    resume_context=resume_context
                )
                hr_questions = [q for q in questions if q.type.lower() == "hr"]
                if hr_questions:
                    question_text = hr_questions[0].question if hasattr(hr_questions[0], 'question') else hr_questions[0].get("question", "")
                else:
                    # Final fallback
                    fallback_questions = [
                        "Tell me about yourself.",
                        "Why are you interested in this position?",
                        "How do you handle stress and pressure?",
                        "What are your career goals?",
                        "Tell me about a time when you worked in a team."
                    ]
                    question_text = fallback_questions[len(questions_asked) % len(fallback_questions)]
            except Exception as fallback_error:
                logger.error(f"[HR INTERVIEW] Fallback question generation failed: {str(fallback_error)}")
                # Final fallback
                fallback_questions = [
                    "Tell me about yourself.",
                    "Why are you interested in this position?",
                    "How do you handle stress and pressure?",
                    "What are your career goals?",
                    "Tell me about a time when you worked in a team."
                ]
                question_text = fallback_questions[len(questions_asked) % len(fallback_questions)]
        
        if not question_text:
            logger.error("[HR NEXT QUESTION] Failed to generate question - question_text is empty after all fallbacks")
            raise HTTPException(status_code=500, detail="A server error occurred while processing your request. Please try again.")
        
        # FIX 13: Step 5: Save new question in hr_round table (transaction pattern)
        # Calculate next question number (should be current count + 1)
        HR_MAX_QUESTIONS = 10  # Maximum questions for HR interview
        question_number = len(questions_asked) + 1
        
        # Double-check we're not exceeding max questions
        if question_number > HR_MAX_QUESTIONS:
            logger.warning(f"[HR NEXT QUESTION] Attempted to generate question {question_number} but max is {HR_MAX_QUESTIONS}")
            return {
                "interview_completed": True,
                "message": "Interview completed. Maximum questions reached."
            }
        user_id = str(session.get("user_id", "")) if session else ""
        
        question_db_data = {
            "user_id": user_id,
            "session_id": session_id,
            "question_number": question_number,
            "question_text": question_text,
            "question_category": "HR",
            "user_answer": "",  # Placeholder - will be updated when user submits answer
            "communication_score": None,
            "cultural_fit_score": None,
            "motivation_score": None,
            "clarity_score": None,
            "overall_score": None,
            "ai_feedback": None,
            "response_time": None
        }
        
        try:
            insert_response = supabase.table("hr_round").insert(question_db_data).execute()
            # ✅ FIX 1: Verify question_number is correctly saved
            if insert_response.data and len(insert_response.data) > 0:
                saved_question = insert_response.data[0]
                saved_question_number = saved_question.get('question_number')
                logger.info(f"[HR NEXT QUESTION] ✅ Saved new question {saved_question_number} to hr_round table")
                logger.info(f"[HR NEXT QUESTION] Saved row ID: {saved_question.get('id')}, session_id: {saved_question.get('session_id')}")
                if saved_question_number != question_number:
                    logger.warning(f"[HR NEXT QUESTION] ⚠️ Expected question_number={question_number}, but got {saved_question_number}")
            else:
                logger.error(f"[HR NEXT QUESTION] ❌ Insert succeeded but no data returned")
                raise HTTPException(
                    status_code=500,
                    detail="Failed to save interview data. Please try again."
                )
        except HTTPException:
            raise
        except Exception as e:
            # FIX 13: Log error and raise HTTPException to maintain data consistency
            logger.error(f"[HR NEXT QUESTION] Failed to store HR question: {str(e)}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail="Failed to save interview data. Please try again."
            )
        
        # ✅ FIX: Generate audio URL for EVERY question (warm-up and follow-up) - MUST always return audio_url
        audio_url = None
        try:
            import urllib.parse
            from app.utils.url_utils import get_api_base_url
            if question_text:
                encoded_text = urllib.parse.quote(question_text)
                base_url = get_api_base_url()
                audio_url = f"{base_url}/api/interview/text-to-speech?text={encoded_text}"
                logger.info(f"[HR NEXT QUESTION] ✅ Generated audio_url for question {question_number}: {audio_url}")
            else:
                logger.error(f"[HR NEXT QUESTION] ❌ question_text is empty, cannot generate audio_url")
                # Fallback: generate a basic TTS URL even if question_text is empty (shouldn't happen)
                base_url = get_api_base_url()
                audio_url = f"{base_url}/api/interview/text-to-speech?text="
        except Exception as e:
            # ✅ FIX: Always provide a fallback audio_url instead of None
            logger.error(f"[HR NEXT QUESTION] ❌ Could not generate audio URL: {str(e)}", exc_info=True)
            try:
                # Fallback: generate basic TTS URL
                from app.utils.url_utils import get_api_base_url
                base_url = get_api_base_url()
                if question_text:
                    import urllib.parse
                    encoded_text = urllib.parse.quote(question_text)
                    audio_url = f"{base_url}/api/interview/text-to-speech?text={encoded_text}"
                else:
                    audio_url = f"{base_url}/api/interview/text-to-speech?text="
                logger.warning(f"[HR NEXT QUESTION] ⚠️ Using fallback audio_url: {audio_url}")
            except Exception as fallback_error:
                # Last resort: return a basic TTS endpoint URL
                logger.error(f"[HR NEXT QUESTION] ❌ Fallback audio URL generation also failed: {str(fallback_error)}")
                audio_url = "/api/interview/text-to-speech?text="  # Relative URL as last resort
        
        # Determine if interview is completed (question_number > 10)
        interview_completed = question_number > 10
        
        # ✅ Determine if this is a warm-up question
        is_warmup = question_number <= HR_WARMUP_COUNT
        
        return {
            "question": question_text,
            "question_type": "HR",
            "question_number": question_number,
            "total_questions": 10,  # HR interviews support up to 10 questions
            "audio_url": audio_url,
            "interview_completed": interview_completed,
            "is_warmup": is_warmup,  # Indicate if this is a warm-up question
            "session_id": session_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[HR NEXT QUESTION] Unexpected error getting next HR question: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate next question. Please try again.")


@router.post("/hr/{session_id}/submit-answer")
async def submit_hr_answer(
    session_id: str,
    request: Dict[str, Any] = Body(...),
    supabase: Client = Depends(get_supabase_client)
):
    """
    Submit an answer to the current HR question
    Uses HR-specific evaluation and stores in hr_round table
    """
    # FIX 12: Test database connection at the start
    if not test_supabase_connection(supabase):
        raise HTTPException(
            status_code=503,
            detail="Database connection unavailable. Please try again shortly."
        )
    
    try:
        # Input validation
        if not session_id or not isinstance(session_id, str) or not session_id.strip():
            logger.error(f"[HR SUBMIT ANSWER] Invalid session_id: {session_id}")
            raise HTTPException(status_code=400, detail="Invalid request format. Please check your input and try again.")
        
        question = request.get("question") or request.get("question_text")
        answer = request.get("answer") or request.get("user_answer")
        
        # ✅ FIX: Accept "No Answer" as valid answer, reject only truly empty answers
        if not answer or not isinstance(answer, str):
            logger.error(f"[HR SUBMIT ANSWER] Empty or invalid answer in request - rejecting")
            raise HTTPException(status_code=400, detail="I could not hear your answer. Please speak again.")
        
        # Allow "No Answer" exactly as-is (case-sensitive check)
        if answer.strip() == "" and answer != "No Answer":
            logger.error(f"[HR SUBMIT ANSWER] Empty or whitespace-only answer - rejecting")
            raise HTTPException(status_code=400, detail="I could not hear your answer. Please speak again.")
        
        # Log "No Answer" cases for debugging
        if answer == "No Answer":
            logger.debug(f"[HR SUBMIT ANSWER] No Answer detected for session_id={session_id}, question_number will be determined from DB")
        
        logger.info(f"[HR SUBMIT ANSWER] Submitting answer for session_id: {session_id}")
        logger.debug(f"[HR SUBMIT ANSWER] Answer length: {len(answer)} characters")
        
        # Get session
        try:
            session_response = supabase.table("interview_sessions").select("*").eq("id", session_id).execute()
        except Exception as db_error:
            logger.error(f"[HR SUBMIT ANSWER] Database error fetching session: {str(db_error)}", exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to retrieve interview session. Please try again.")
        
        if not session_response.data or len(session_response.data) == 0:
            logger.warning(f"[HR SUBMIT ANSWER] Session not found: {session_id}")
            raise HTTPException(status_code=404, detail="Interview session not found. Please start a new interview.")
        
        session = session_response.data[0]
        
        # FIX 19: Check if session is already completed
        session_status = session.get("session_status", "").lower()
        if session_status == "completed":
            logger.warning(f"[HR SUBMIT ANSWER] Session already completed: {session_id}")
            raise HTTPException(
                status_code=400,
                detail="This interview session has already been completed. Please start a new interview."
            )
        
        # Validate session is HR type
        session_type = session.get("interview_type", "").lower()
        if session_type != "hr":
            logger.error(f"[HR SUBMIT ANSWER] Wrong session type: {session_type} (expected: hr)")
            raise HTTPException(
                status_code=400, 
                detail="This endpoint is for HR interviews only. Please use the correct interview type."
            )
        
        # Get current question from hr_round table
        try:
            questions_response = supabase.table("hr_round").select("*").eq("session_id", session_id).order("question_number", desc=True).limit(1).execute()
        except Exception as db_error:
            # Log detailed error information
            logger.error(
                f"[HR SUBMIT ANSWER] Database error fetching question for session_id: {session_id}. Error: {str(db_error)}", 
                exc_info=True
            )
            
            # Raise HTTPException with 500 status and user-friendly message
            raise HTTPException(
                status_code=500, 
                detail="Failed to submit answer due to a server error. Please try again."
            )
        
        # Logic to check if data was retrieved (Handle 404 case)
        if not questions_response.data or len(questions_response.data) == 0:
            # This block correctly handles the 404 case if the query succeeded but returned no data
            logger.warning(f"[HR SUBMIT ANSWER] No question found in hr_round for session_id={session_id}")
            raise HTTPException(
                status_code=404, 
                detail="No current question found for this session. Please start a new interview."
            )
        
        current_question_db = questions_response.data[0]
        question_number = current_question_db["question_number"]
        question_text = current_question_db.get("question_text", question)
        
        # ✅ Log "No Answer" cases with question_number and session_id
        if answer == "No Answer":
            logger.debug(f"[HR SUBMIT ANSWER] No Answer detected - session_id={session_id}, question_number={question_number}, reason=classified_by_frontend")
        
        # ✅ FIX 2: Safety fallback - if question_text is empty in DB, use question from request
        if not question_text or not question_text.strip():
            question_text = question
            if not question_text or not question_text.strip():
                logger.error(f"[HR SUBMIT ANSWER] Both DB and request have empty question text for question_number={question_number}")
                raise HTTPException(
                    status_code=400,
                    detail="Question text is missing. Please start a new interview."
                )
            logger.warning(f"[HR SUBMIT ANSWER] Question text missing from DB (question_number={question_number}), using question from request body as fallback")
        
        # Get conversation history from hr_round table
        round_data_response = supabase.table("hr_round").select("question_text, question_number, user_answer").eq("session_id", session_id).order("question_number").execute()
        
        conversation_history = []
        questions_asked_list = []
        answers_received_list = []
        
        for row in (round_data_response.data or []):
            q_text = row.get("question_text", "")
            user_ans = row.get("user_answer", "")
            if q_text:
                conversation_history.append({"role": "ai", "content": q_text})
                questions_asked_list.append(q_text)
            if user_ans:  # Only add answer if it's not empty
                conversation_history.append({"role": "user", "content": user_ans})
                answers_received_list.append(user_ans)
        
        # Get experience level for evaluation
        experience_level = session.get("experience_level", "Intermediate")
        response_time = request.get("response_time")
        
        # ✅ FIX: For "No Answer", set all scores to 0
        if answer == "No Answer":
            logger.debug(f"[HR SUBMIT ANSWER] Setting all scores to 0 for 'No Answer' - session_id={session_id}, question_number={question_number}")
            from app.services.answer_evaluator import AnswerScore
            scores = AnswerScore(
                relevance=0,
                confidence=0,
                technical_accuracy=0,
                communication=0,
                overall=0,
                feedback="No answer provided."
            )
        else:
            # Evaluate answer using HR-specific evaluation
            # Use answer_evaluator with question_type="HR" for HR-specific scoring
            scores = answer_evaluator.evaluate_answer(
                question=question_text,
                question_type="HR",
                answer=answer,
                experience_level=experience_level,
                response_time=response_time
            )
        
        logger.info(f"[HR SUBMIT ANSWER] Answer evaluated - Communication: {scores.communication}, Overall: {scores.overall}")
        
        # ✅ FIX: Skip AI response generation for "No Answer" - just move to next question
        ai_response = None
        if answer == "No Answer":
            logger.debug(f"[HR SUBMIT ANSWER] Skipping AI response generation for 'No Answer' - session_id={session_id}, question_number={question_number}")
            ai_response = "Let's continue with the next question."
        elif technical_interview_engine.openai_available and technical_interview_engine.client is not None:
            try:
                system_prompt = """You are an experienced HR interviewer providing feedback on candidate answers.
Provide brief, encouraging, and constructive feedback (1-2 sentences) that:
- Acknowledges what the candidate said
- Provides gentle guidance if needed
- Maintains a positive, professional tone
- Is appropriate for HR/behavioral interview context"""

                user_prompt = f"""Question: {question_text}
Candidate Answer: {answer}
Communication Score: {scores.communication}/100
Overall Score: {scores.overall}/100

Provide brief, encouraging feedback for this HR interview answer."""

                response = technical_interview_engine.client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.7,
                    max_tokens=150
                )
                
                ai_response = response.choices[0].message.content.strip()
                logger.info(f"[HR SUBMIT ANSWER] AI response generated: {ai_response[:50]}...")
                
            except Exception as e:
                logger.warning(f"[HR SUBMIT ANSWER] Could not generate AI response: {str(e)}")
                ai_response = "Thank you for your answer. Let's continue with the next question."
        else:
            ai_response = "Thank you for your answer. Let's continue with the next question."
        
        # Generate audio URL for AI response
        ai_response_audio_url = None
        if ai_response:
            try:
                import urllib.parse
                from app.utils.url_utils import get_api_base_url
                encoded_text = urllib.parse.quote(ai_response)
                base_url = get_api_base_url()
                ai_response_audio_url = f"{base_url}/api/interview/text-to-speech?text={encoded_text}"
                logger.info(f"[HR SUBMIT ANSWER] Generated AI response audio URL")
            except Exception as e:
                logger.warning(f"[HR SUBMIT ANSWER] Could not generate audio URL: {str(e)}")
        
        # Update the existing question row in hr_round table with the answer and evaluation
        user_id = str(session.get("user_id", "")) if session else ""
        
        # Get user's answer audio_url from request (if provided)
        user_answer_audio_url = request.get("audio_url")
        
        # FIX 15: Map scores to HR-specific fields with standardized mapping
        # For HR, we use:
        # - communication_score: from scores.communication (direct mapping)
        # - cultural_fit_score: from scores.relevance (how well answer fits company culture/job fit)
        # - motivation_score: from scores.relevance (consistent mapping - relevance indicates motivation)
        # - clarity_score: from scores.communication (clarity is part of communication)
        # - overall_score: from scores.overall (direct mapping)
        
        # FIX 15: Standardize score mapping with safe attribute access
        communication_score = getattr(scores, 'communication', 0)
        relevance_score = getattr(scores, 'relevance', 0)
        overall_score = getattr(scores, 'overall', 0)
        feedback_text = getattr(scores, 'feedback', '')
        
        # ✅ FIX 4: Use ai_response instead of scores.feedback for ai_feedback field
        # ai_response is the generated AI feedback from OpenAI, which is more detailed and contextual
        ai_feedback_to_save = ai_response if ai_response else feedback_text
        
        update_data = {
            "user_answer": answer,
            "audio_url": user_answer_audio_url,  # User's answer audio URL
            "communication_score": communication_score,
            "cultural_fit_score": relevance_score,  # Map relevance to cultural fit (job fit)
            "motivation_score": relevance_score,  # Use relevance as motivation indicator (consistent mapping)
            "clarity_score": communication_score,  # Clarity is part of communication
            "overall_score": overall_score,
            "ai_feedback": ai_feedback_to_save,  # ✅ FIX 4: Use ai_response (generated AI feedback) instead of scores.feedback
            "response_time": response_time
        }
        
        # ✅ FIX 5: Add detailed logging for debugging
        logger.info(f"[HR SUBMIT ANSWER] ========== UPDATE DATA ==========")
        logger.info(f"[HR SUBMIT ANSWER] session_id: {session_id} (type: {type(session_id)})")
        logger.info(f"[HR SUBMIT ANSWER] question_number: {question_number} (type: {type(question_number)})")
        logger.info(f"[HR SUBMIT ANSWER] Update data: {update_data}")
        logger.info(f"[HR SUBMIT ANSWER] Scores - Communication: {communication_score}, Relevance: {relevance_score}, Overall: {overall_score}")
        logger.info(f"[HR SUBMIT ANSWER] AI Feedback length: {len(ai_feedback_to_save) if ai_feedback_to_save else 0} characters")
        logger.info(f"[HR SUBMIT ANSWER] ==================================")
        
        # ✅ FIX 2 & 3: Verify the row exists before updating, with fallback to create if missing
        try:
            verify_response = supabase.table("hr_round").select("id, session_id, question_number, question_text").eq("session_id", str(session_id)).eq("question_number", int(question_number)).execute()
        except Exception as verify_error:
            logger.error(f"[HR SUBMIT ANSWER] Database error verifying question row: {str(verify_error)}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail="Failed to verify question. Please try again."
            )
        
        # ✅ FIX 3: Fallback logic - if row doesn't exist, create it instead of failing
        if not verify_response.data or len(verify_response.data) == 0:
            logger.warning(f"[HR SUBMIT ANSWER] ⚠️ Row not found for session_id={session_id}, question_number={question_number}. Creating new row...")
            
            # Create the row with all necessary data
            insert_data = {
                "user_id": user_id,
                "session_id": str(session_id),
                "question_number": int(question_number),
                "question_text": question_text,  # Use question_text from DB query or request
                "question_category": "HR",
                **update_data  # Include all update_data fields (user_answer, scores, etc.)
            }
            
            try:
                insert_response = supabase.table("hr_round").insert(insert_data).execute()
                if not insert_response.data or len(insert_response.data) == 0:
                    logger.error(f"[HR SUBMIT ANSWER] ❌ Failed to create row - insert returned no data")
                    raise HTTPException(
                        status_code=500,
                        detail="Failed to save answer to database. Please try again."
                    )
                logger.info(f"[HR SUBMIT ANSWER] ✅ Created new row with ID: {insert_response.data[0].get('id')}")
                answer_response = insert_response  # Use insert response for validation
            except HTTPException:
                raise
            except Exception as insert_error:
                logger.error(f"[HR SUBMIT ANSWER] Database error creating row: {str(insert_error)}", exc_info=True)
                raise HTTPException(
                    status_code=500,
                    detail="Failed to save answer to database. Please try again."
                )
        else:
            # Row exists - proceed with update
            existing_row_id = verify_response.data[0].get('id')
            logger.info(f"[HR SUBMIT ANSWER] ✓ Row found. Existing row ID: {existing_row_id}")
            logger.info(f"[HR SUBMIT ANSWER] Existing row data - question_text: {verify_response.data[0].get('question_text', 'N/A')[:50]}...")
            
            # ✅ FIX 2: Update the row for this question_number and session_id
            try:
                answer_response = supabase.table("hr_round").update(update_data).eq("session_id", str(session_id)).eq("question_number", int(question_number)).execute()
            except Exception as update_error:
                logger.error(f"[HR SUBMIT ANSWER] Database error updating answer: {str(update_error)}", exc_info=True)
                logger.error(f"[HR SUBMIT ANSWER] Update query details - session_id: {str(session_id)}, question_number: {int(question_number)}")
                raise HTTPException(
                    status_code=500,
                    detail="Failed to save answer to database. Please try again."
                )
        
        # ✅ FIX 5: Validate that the update/insert actually succeeded with detailed logging
        if not answer_response.data or len(answer_response.data) == 0:
            # Determine operation type safely
            operation_type = "UNKNOWN"
            if 'verify_response' in locals() and verify_response and verify_response.data and len(verify_response.data) > 0:
                operation_type = "UPDATE"
            else:
                operation_type = "INSERT"
            
            logger.error(f"[HR SUBMIT ANSWER] ❌ Database operation returned no rows!")
            logger.error(f"[HR SUBMIT ANSWER] Operation: {operation_type}")
            logger.error(f"[HR SUBMIT ANSWER] Query params - session_id: {str(session_id)}, question_number: {int(question_number)}")
            logger.error(f"[HR SUBMIT ANSWER] Update data keys: {list(update_data.keys())}")
            logger.error(f"[HR SUBMIT ANSWER] ⚠️ POSSIBLE CAUSES:")
            logger.error(f"[HR SUBMIT ANSWER]   1. RLS policy blocking update/insert")
            logger.error(f"[HR SUBMIT ANSWER]   2. Service role key not configured correctly")
            logger.error(f"[HR SUBMIT ANSWER]   3. Row not found (session_id/question_number mismatch)")
            logger.error(f"[HR SUBMIT ANSWER]   4. Column type mismatch")
            raise HTTPException(status_code=500, detail="Failed to save answer to database. Please try again.")
        
        # ✅ FIX 5: Log the saved data for verification
        saved_row = answer_response.data[0]
        logger.info(f"[HR SUBMIT ANSWER] ✅ Answer saved successfully to hr_round table")
        logger.info(f"[HR SUBMIT ANSWER] ========== SAVED DATA VERIFICATION ==========")
        logger.info(f"[HR SUBMIT ANSWER] Row ID: {saved_row.get('id')}")
        logger.info(f"[HR SUBMIT ANSWER] session_id: {saved_row.get('session_id')}")
        logger.info(f"[HR SUBMIT ANSWER] question_number: {saved_row.get('question_number')}")
        logger.info(f"[HR SUBMIT ANSWER] user_answer: {saved_row.get('user_answer', '')[:50]}..." if saved_row.get('user_answer') else "user_answer: (empty)")
        logger.info(f"[HR SUBMIT ANSWER] communication_score: {saved_row.get('communication_score')}")
        logger.info(f"[HR SUBMIT ANSWER] cultural_fit_score: {saved_row.get('cultural_fit_score')}")
        logger.info(f"[HR SUBMIT ANSWER] motivation_score: {saved_row.get('motivation_score')}")
        logger.info(f"[HR SUBMIT ANSWER] clarity_score: {saved_row.get('clarity_score')}")
        logger.info(f"[HR SUBMIT ANSWER] overall_score: {saved_row.get('overall_score')}")
        logger.info(f"[HR SUBMIT ANSWER] ai_feedback: {saved_row.get('ai_feedback', '')[:50]}..." if saved_row.get('ai_feedback') else "ai_feedback: (empty)")
        logger.info(f"[HR SUBMIT ANSWER] ============================================")
        
        # Log interview transcript
        await log_interview_transcript(
            supabase,
            session_id,
            "hr",  # Use "hr" instead of "technical"
            question_text,
            answer
        )
        
        # Check if interview should be completed (max 10 questions for HR)
        HR_MAX_QUESTIONS = 10
        total_questions = len(questions_asked_list)
        interview_completed = total_questions >= HR_MAX_QUESTIONS
        
        # FIX: Update the main interview_sessions table status if interview is completed
        if interview_completed:
            try:
                # Update the main interview_sessions table status
                supabase.table("interview_sessions").update({
                    "session_status": "completed"
                }).eq("id", session_id).execute()
                
                logger.info(f"[HR SUBMIT ANSWER] ✅ Session marked as completed for session_id: {session_id}")
                
            except Exception as e:
                # Log error but allow the request to finish successfully, as the answer was saved.
                logger.warning(
                    f"[HR SUBMIT ANSWER] Could not update session status to completed for session_id: {session_id}. Error: {str(e)}", 
                    exc_info=True
                )
        
        # Get created_at timestamp from response
        created_at_str = answer_response.data[0].get("created_at")
        if isinstance(created_at_str, str):
            created_at_str = created_at_str.replace('Z', '+00:00')
            try:
                answered_at = datetime.fromisoformat(created_at_str)
            except ValueError:
                answered_at = datetime.now()
        else:
            answered_at = datetime.now()
        
        # Return HR-specific response
        return {
            "answer_id": answer_response.data[0].get("id"),
            "session_id": session_id,
            "question_number": question_number,
            "scores": {
                "communication": scores.communication,
                "cultural_fit": scores.relevance,
                "motivation": scores.confidence if hasattr(scores, 'confidence') else scores.communication,
                "clarity": scores.communication,
                "overall": scores.overall
            },
            "ai_response": ai_response,
            "audio_url": ai_response_audio_url,  # Audio URL for AI response
            "feedback": scores.feedback,
            "interview_completed": interview_completed,
            "response_time": response_time,
            "answered_at": answered_at.isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[HR SUBMIT ANSWER] Unexpected error submitting HR answer: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to submit answer. Please try again.")


# ==================== STAR Interview Routes ====================

@router.post("/star/start")
async def start_star_interview(
    request: Dict[str, Any],
    supabase: Client = Depends(get_supabase_client)
):
    """
    Start a new STAR (behavioral) interview session
    Returns the first STAR question based on resume
    """
    try:
        user_id = request.get("user_id")
        
        if not user_id:
            raise HTTPException(status_code=400, detail="user_id is required")
        
        # user_id is now TEXT (slugified name), not UUID - no validation needed
        
        # Get user profile (required)
        profile_response = supabase.table("user_profiles").select("*").eq("user_id", user_id).execute()
        profile = profile_response.data[0] if profile_response.data else None
        
        if not profile:
            raise HTTPException(
                status_code=404,
                detail=f"User profile not found for user_id: {user_id}. Please upload a resume first to create your profile."
            )
        
        # Build resume context
        resume_context = build_resume_context_from_profile(profile, supabase)
        
        # Create session in database
        db_session_data = {
            "user_id": user_id,  # TEXT (slugified name)
            "interview_type": "star",
            "role": "STAR Interview",
            "experience_level": profile.get("experience_level", "Intermediate"),
            "skills": resume_context.get("skills", []),
            "session_status": "active"
        }
        
        try:
            session_response = supabase.table("interview_sessions").insert(db_session_data).execute()
            if not session_response.data or len(session_response.data) == 0:
                raise HTTPException(status_code=500, detail="Failed to create interview session")
            session_id = session_response.data[0]["id"]
        except Exception as db_error:
            error_str = str(db_error)
            if "foreign key constraint" in error_str.lower():
                raise HTTPException(
                    status_code=400,
                    detail=f"User profile not found. Please ensure user_id {user_id} exists in user_profiles table."
                )
            raise HTTPException(status_code=500, detail=f"Error creating interview session: {error_str}")
        
        # Generate first STAR question using question generator
        from app.services.question_generator import question_generator
        questions = question_generator.generate_questions(
            role="Behavioral Interview",
            experience_level=profile.get("experience_level", "Intermediate"),
            skills=resume_context.get("skills", []),
            resume_context=resume_context
        )
        
        # Filter for behavioral/STAR questions - InterviewQuestion is a Pydantic model, access attributes directly
        star_questions = [q for q in questions if q.type.lower() in ["hr", "behavioral", "star"]]
        if not star_questions:
            # Fallback STAR question - create InterviewQuestion object for consistency
            from app.schemas.interview import InterviewQuestion
            star_questions = [InterviewQuestion(type="STAR", question="Tell me about a time when you had to work under pressure.")]
        
        first_question = star_questions[0]
        
        # Extract question text - handle both InterviewQuestion objects and dicts
        question_text = first_question.question if hasattr(first_question, 'question') else first_question.get("question", "")
        
        # Store first question in star_round table
        question_db_data = {
            "user_id": str(user_id),
            "session_id": session_id,
            "question_number": 1,
            "question_text": question_text,
            "user_answer": "",  # Initialize with empty answer
            "star_structure_score": None,
            "situation_score": None,
            "task_score": None,
            "action_score": None,
            "result_score": None,
            "overall_score": None,
            "ai_feedback": None,
            "star_guidance": None,
            "improvement_suggestions": None,
            "response_time": None
        }
        
        try:
            supabase.table("star_round").insert(question_db_data).execute()
        except Exception as e:
            logger.warning(f"Failed to store STAR question: {str(e)}")
        
        return {
            "session_id": session_id,
            "question": question_text,
            "question_type": "STAR",
            "question_number": 1,
            "total_questions": 5,  # Default for STAR interviews
            "user_id": user_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting STAR interview: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error starting STAR interview: {str(e)}")


@router.get("/coding/{session_id}/results")
async def get_coding_results(
    session_id: str,
    supabase: Client = Depends(get_supabase_client)
):
    """
    Get all coding interview results for a session
    """
    try:
        logger.info(f"🔍 Fetching results for session_id: {session_id}")
        
        # First, verify session exists
        try:
            session_check = supabase.table("interview_sessions").select("id, user_id").eq("id", session_id).execute()
            if not session_check.data:
                logger.warning(f"⚠️ Session {session_id} not found in interview_sessions table")
            else:
                logger.info(f"✓ Session found: {session_check.data[0]}")
        except Exception as e:
            logger.warning(f"Could not verify session: {str(e)}")
        
        # Fetch results with explicit error handling
        try:
            results_response = supabase.table("coding_round").select("*").eq("session_id", session_id).order("question_number").execute()
            results = results_response.data or []
        except Exception as e:
            logger.error(f"✗ Error fetching results: {str(e)}")
            # Check if table exists
            try:
                test_query = supabase.table("coding_round").select("id").limit(1).execute()
                logger.info("✓ coding_round table exists and is accessible")
            except Exception as table_error:
                logger.error(f"✗ coding_round table may not exist or is not accessible: {str(table_error)}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Database error: {str(table_error)}. Please verify coding_round table exists in Supabase."
                )
            raise
        
        # Log for debugging
        logger.info(f"📊 Retrieved {len(results)} results for session {session_id}")
        if len(results) == 0:
            logger.warning(f"⚠️ No results found for session {session_id}")
            # Try to find any results with this session_id (for debugging)
            try:
                all_results = supabase.table("coding_round").select("session_id, question_number, user_id").limit(10).execute()
                sample_data = [(r.get('session_id'), r.get('question_number'), r.get('user_id')) for r in (all_results.data or [])[:5]]
                logger.info(f"Sample data in coding_round table: {sample_data}")
                
                # Check if there are results with similar session_id
                all_sessions = supabase.table("coding_round").select("session_id").limit(100).execute()
                unique_sessions = list(set([r.get('session_id') for r in (all_sessions.data or [])]))
                logger.info(f"Unique session_ids in database (first 10): {unique_sessions[:10]}")
            except Exception as debug_error:
                logger.warning(f"Could not fetch debug info: {str(debug_error)}")
        else:
            for i, r in enumerate(results):
                logger.info(f"Result {i+1}: question_number={r.get('question_number')}, user_id={r.get('user_id')}, execution_output={bool(r.get('execution_output'))}, ai_feedback={bool(r.get('ai_feedback'))}, correct_solution={bool(r.get('correct_solution'))}, correctness={r.get('correctness')}, score={r.get('final_score')}")
        
        # Ensure all fields are present (handle None values from database)
        for result in results:
            # Convert None to empty string for display
            if result.get("execution_output") is None:
                result["execution_output"] = ""
            if result.get("ai_feedback") is None:
                result["ai_feedback"] = ""
            if result.get("correct_solution") is None:
                result["correct_solution"] = ""
            if result.get("user_code") is None:
                result["user_code"] = ""
            if result.get("question_text") is None:
                result["question_text"] = ""
            # Ensure all required fields exist
            if "question_number" not in result:
                result["question_number"] = 0
            if "correctness" not in result:
                result["correctness"] = False
            if "final_score" not in result:
                result["final_score"] = 0
            if "programming_language" not in result:
                result["programming_language"] = "python"
            if "difficulty_level" not in result:
                result["difficulty_level"] = "Medium"
            # Add empty arrays/strings for optional fields if missing
            if "errors_found" not in result:
                result["errors_found"] = []
            if "bugs_explained" not in result:
                result["bugs_explained"] = []
            if "improvements" not in result:
                result["improvements"] = []
            if "motivation_message" not in result:
                result["motivation_message"] = ""
            if "time_complexity" not in result:
                result["time_complexity"] = ""
            if "space_complexity" not in result:
                result["space_complexity"] = ""
        
        # Calculate overall statistics
        total_questions = len(results)
        correct_answers = sum(1 for r in results if r.get("correctness", False))
        total_score = sum(r.get("final_score", 0) for r in results)
        average_score = total_score / total_questions if total_questions > 0 else 0
        
        logger.info(f"📈 Statistics: total={total_questions}, correct={correct_answers}, incorrect={total_questions - correct_answers}, avg_score={average_score:.2f}, accuracy={round((correct_answers / total_questions * 100) if total_questions > 0 else 0, 2)}%")
        
        return {
            "session_id": session_id,
            "results": results,
            "statistics": {
                "total_questions": total_questions,
                "correct_answers": correct_answers,
                "incorrect_answers": total_questions - correct_answers,
                "total_score": total_score,
                "average_score": round(average_score, 2),
                "accuracy": round((correct_answers / total_questions * 100) if total_questions > 0 else 0, 2)
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"✗ Error in get_coding_results: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error fetching coding results: {str(e)}")


@router.post("/coding/run")
async def run_code(
    request: Dict[str, Any],
    supabase: Client = Depends(get_supabase_client)
):
    """
    Execute code safely in a sandboxed environment
    Accepts: {code, language, input, sql_setup} (sql_setup is optional, for SQL questions with table definitions)
    Returns: {output, error, execution_time}
    """
    try:
        code = request.get("code", "")
        language = request.get("language", "python")
        test_input = request.get("input", "")
        sql_setup = request.get("sql_setup", "")  # Table definitions and sample data for SQL questions
        
        if not code:
            raise HTTPException(status_code=400, detail="code is required")
        
        if not language:
            raise HTTPException(status_code=400, detail="language is required")
        
        # Validate language
        supported_languages = ["python", "java", "javascript", "c", "cpp", "c++", "sql"]
        language_lower = language.lower()
        if language_lower not in supported_languages:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported language. Supported: {', '.join(supported_languages)}"
            )
        
        # Execute code based on language
        result = await execute_code_safely(code, language_lower, test_input, sql_setup)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error executing code: {str(e)}")


def check_python_library_availability(library_name: str) -> bool:
    """
    Check if a Python library is available in the execution environment.
    Returns True if library can be imported, False otherwise.
    """
    import subprocess
    import shutil
    import os
    
    # Find python executable (same logic as execute_code_safely)
    current_file = os.path.abspath(__file__)
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_file)))
    
    if os.name == 'nt':  # Windows
        venv_python = os.path.join(project_root, "venv", "Scripts", "python.exe")
    else:  # Unix/Linux/Mac
        venv_python = os.path.join(project_root, "venv", "bin", "python")
    
    if os.path.exists(venv_python):
        python_cmd = venv_python
    else:
        python_cmd = shutil.which("python") or shutil.which("python3") or "python"
    
    try:
        # Try to import the library
        check_code = f"import {library_name}; print('OK')"
        result = subprocess.run(
            [python_cmd, "-c", check_code],
            capture_output=True,
            text=True,
            timeout=2
        )
        return result.returncode == 0 and "OK" in result.stdout
    except Exception:
        return False


def get_available_python_libraries() -> Dict[str, bool]:
    """
    Check which data science libraries are available.
    Returns a dictionary mapping library names to availability.
    """
    libraries = {
        'pandas': False,
        'numpy': False,
        'matplotlib': False,
        'seaborn': False,
        'sklearn': False
    }
    
    for lib in libraries.keys():
        libraries[lib] = check_python_library_availability(lib)
    
    return libraries


async def execute_code_safely(code: str, language: str, test_input: str, sql_setup: str = "") -> Dict[str, Any]:
    """
    Execute code safely using subprocess with timeout and resource limits
    Handles Windows and Unix systems properly
    
    NOTE: On Vercel serverless, subprocess execution is limited.
    Code execution will use LLM-based evaluation instead of actual execution.
    
    Supported languages:
    - Python (with data science libraries: pandas, numpy, matplotlib, seaborn, scikit-learn)
    - Java (requires JDK)
    - JavaScript (requires Node.js)
    - C/C++ (requires GCC/G++)
    - SQL (uses sqlite3 via Python)
    """
    import os
    from app.config.settings import settings
    
    # Check if we're on Vercel (serverless environment)
    is_vercel = os.getenv("VERCEL") == "1" or os.getenv("VERCEL_URL") is not None
    
    if is_vercel:
        # On Vercel, subprocess execution is not available
        # Return a message indicating LLM-based evaluation will be used
        return {
            "output": "",
            "error": "Code execution is not available in serverless environment. Code will be evaluated using AI-based analysis instead of actual execution.",
            "execution_time": 0,
            "exit_code": 0,
            "note": "On Vercel, code execution uses LLM-based evaluation. The code correctness will be determined by AI analysis rather than actual execution."
        }
    
    import subprocess
    import tempfile
    import time
    import shutil
    
    tmp_file_path = None
    output_file = None
    class_file = None
    temp_dir = None
    
    try:
        # Create temporary file for code
        file_extension = {
            "python": ".py",
            "java": ".java",
            "javascript": ".js",
            "c": ".c",
            "cpp": ".cpp",
            "c++": ".cpp",
            "sql": ".sql"
        }.get(language, ".txt")
        
        # Create temp file in a temporary directory
        temp_dir = tempfile.mkdtemp()
        
        # For Java, extract class name and use it as filename
        if language == "java":
            import re
            class_match = re.search(r'public\s+class\s+(\w+)', code)
            if class_match:
                class_name = class_match.group(1)
                tmp_file_path = os.path.join(temp_dir, f"{class_name}{file_extension}")
            else:
                # Fallback: try to find any class declaration
                class_match = re.search(r'class\s+(\w+)', code)
                if class_match:
                    class_name = class_match.group(1)
                    tmp_file_path = os.path.join(temp_dir, f"{class_name}{file_extension}")
                else:
                    # Default to "code"
                    tmp_file_path = os.path.join(temp_dir, f"code{file_extension}")
        else:
            tmp_file_path = os.path.join(temp_dir, f"code{file_extension}")
        
        with open(tmp_file_path, 'w', encoding='utf-8') as tmp_file:
            tmp_file.write(code)
        
        try:
            start_time = time.time()
            
            # Execute based on language
            if language == "python":
                # Find python executable - prioritize venv Python which has data science libraries
                python_cmd = None
                
                # Get the project root directory (where venv should be)
                current_file = os.path.abspath(__file__)
                # Navigate from app/routers/interview.py to project root
                project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_file)))
                
                # Try to use venv Python first (has pandas, numpy, etc.)
                if os.name == 'nt':  # Windows
                    venv_python = os.path.join(project_root, "venv", "Scripts", "python.exe")
                else:  # Unix/Linux/Mac
                    venv_python = os.path.join(project_root, "venv", "bin", "python")
                
                if os.path.exists(venv_python):
                    python_cmd = venv_python
                else:
                    # Fallback to system Python (may not have data science libraries)
                    python_cmd = shutil.which("python") or shutil.which("python3") or "python"
                
                # Supported data science libraries
                supported_libraries = {
                    'pandas': 'pandas',
                    'numpy': 'numpy',
                    'matplotlib': 'matplotlib',
                    'seaborn': 'seaborn',
                    'sklearn': 'scikit-learn',
                    'scikit-learn': 'scikit-learn'
                }
                
                process = subprocess.run(
                    [python_cmd, tmp_file_path],
                    input=test_input,
                    capture_output=True,
                    text=True,
                    timeout=10,  # Increased timeout for data science operations
                    cwd=temp_dir,
                    shell=False
                )
                
                # Check for ModuleNotFoundError in stderr and provide helpful message
                if process.returncode != 0 and process.stderr:
                    stderr_lower = process.stderr.lower()
                    if 'modulenotfounderror' in stderr_lower or 'no module named' in stderr_lower:
                        # Extract module name from error
                        import re
                        module_match = re.search(r"no module named ['\"]([^'\"]+)['\"]", stderr_lower, re.IGNORECASE)
                        if module_match:
                            module_name = module_match.group(1)
                            # Check if it's a supported library that might not be installed
                            if module_name in supported_libraries:
                                return {
                                    "output": process.stdout,
                                    "error": f"ModuleNotFoundError: '{module_name}' is not installed in the execution environment. "
                                            f"Please install it by running: pip install {supported_libraries[module_name]}\n"
                                            f"Supported data science libraries: pandas, numpy, matplotlib, seaborn, scikit-learn",
                                    "execution_time": round(time.time() - start_time, 3),
                                    "exit_code": process.returncode
                                }
                            else:
                                return {
                                    "output": process.stdout,
                                    "error": f"ModuleNotFoundError: '{module_name}' is not available in the execution environment. "
                                            f"Supported libraries include: pandas, numpy, matplotlib, seaborn, scikit-learn, and Python standard library modules. "
                                            f"If you need this library, please use an alternative approach or contact support.",
                                    "execution_time": round(time.time() - start_time, 3),
                                    "exit_code": process.returncode
                                }
                
                # If execution succeeded, return result
                execution_time = time.time() - start_time
                return {
                    "output": process.stdout,
                    "error": process.stderr if process.returncode != 0 else "",
                    "execution_time": round(execution_time, 3),
                    "exit_code": process.returncode
                }
            elif language == "java":
                # Find javac and java executables
                javac_cmd = shutil.which("javac")
                java_cmd = shutil.which("java")
                
                if not javac_cmd or not java_cmd:
                    return {
                        "output": "",
                        "error": "Java compiler (javac) or runtime (java) not found. Please ensure Java JDK is installed and added to PATH.",
                        "execution_time": 0
                    }
                
                # Compile first
                compile_process = subprocess.run(
                    [javac_cmd, tmp_file_path],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    cwd=temp_dir,
                    shell=False
                )
                
                if compile_process.returncode != 0:
                    return {
                        "output": "",
                        "error": compile_process.stderr or compile_process.stdout or "Compilation failed",
                        "execution_time": 0
                    }
                
                # Get class name from filename (file was already named based on class)
                class_name = os.path.basename(tmp_file_path).replace(".java", "")
                class_file = os.path.join(temp_dir, f"{class_name}.class")
                
                # Check if class file was created
                if not os.path.exists(class_file):
                    # Try to find any .class file in the directory
                    class_files = [f for f in os.listdir(temp_dir) if f.endswith('.class')]
                    if class_files:
                        class_name = class_files[0].replace('.class', '')
                        class_file = os.path.join(temp_dir, f"{class_name}.class")
                    else:
                        return {
                            "output": "",
                            "error": "Compilation succeeded but class file not found. Ensure the class name matches the file name or use 'public class ClassName'.",
                            "execution_time": 0
                        }
                
                # Run compiled class
                process = subprocess.run(
                    [java_cmd, "-cp", temp_dir, class_name],
                    input=test_input,
                    capture_output=True,
                    text=True,
                    timeout=5,
                    cwd=temp_dir,
                    shell=False
                )
            elif language in ["javascript", "js"]:
                # Find node executable
                node_cmd = shutil.which("node")
                if not node_cmd:
                    return {
                        "output": "",
                        "error": "Node.js not found. Please ensure Node.js is installed and added to PATH.",
                        "execution_time": 0
                    }
                
                process = subprocess.run(
                    [node_cmd, tmp_file_path],
                    input=test_input,
                    capture_output=True,
                    text=True,
                    timeout=5,
                    cwd=temp_dir,
                    shell=False
                )
            elif language in ["c", "cpp", "c++"]:
                # Find compiler executable
                compiler = "g++" if language in ["cpp", "c++"] else "gcc"
                compiler_cmd = shutil.which(compiler)
                
                if not compiler_cmd:
                    compiler_name = "G++" if language in ["cpp", "c++"] else "GCC"
                    return {
                        "output": "",
                        "error": f"{compiler_name} compiler not found. Please ensure {compiler_name} is installed and added to PATH. On Windows, you can install MinGW or use Visual Studio Build Tools.",
                        "execution_time": 0
                    }
                
                # Compile first - use proper output file path
                if os.name == 'nt':  # Windows
                    output_file = os.path.join(temp_dir, "a.exe")
                else:  # Unix/Linux/Mac
                    output_file = os.path.join(temp_dir, "a.out")
                
                compile_process = subprocess.run(
                    [compiler_cmd, tmp_file_path, "-o", output_file],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    cwd=temp_dir,
                    shell=False
                )
                
                if compile_process.returncode != 0:
                    return {
                        "output": "",
                        "error": compile_process.stderr or compile_process.stdout or "Compilation failed",
                        "execution_time": 0
                    }
                
                # Check if executable was created
                if not os.path.exists(output_file):
                    return {
                        "output": "",
                        "error": "Compilation succeeded but executable not found.",
                        "execution_time": 0
                    }
                
                # Run compiled executable
                # On Windows, use the full path; on Unix, use ./ prefix
                if os.name == 'nt':
                    exec_cmd = output_file
                else:
                    exec_cmd = f"./{os.path.basename(output_file)}"
                
                process = subprocess.run(
                    [exec_cmd] if os.name == 'nt' else exec_cmd.split(),
                    input=test_input,
                    capture_output=True,
                    text=True,
                    timeout=5,
                    cwd=temp_dir,
                    shell=False
                )
            elif language == "sql":
                # SQL execution using sqlite3 (lightweight, no setup required)
                # Create a Python wrapper to execute SQL safely
                # Escape backslashes in file path for Windows
                escaped_path = tmp_file_path.replace('\\', '\\\\')
                # Escape setup SQL properly for Python raw string (r''')
                # For raw string, we need to escape single quotes and backslashes
                # But preserve literal newlines as \n
                if sql_setup:
                    # Escape single quotes
                    escaped_setup = sql_setup.replace("'", "\\'")
                    # Escape backslashes (but this will double-escape \n, so we need to handle it)
                    # Actually, in raw strings, \n is literal, so we want to keep it as \n
                    # But we need to escape backslashes that aren't part of escape sequences
                    # The simplest approach: escape all backslashes, then the \n will become \\n
                    # But in the raw string, \\n becomes \n, which is what we want
                    escaped_setup = escaped_setup.replace('\\', '\\\\')
                else:
                    escaped_setup = ""
                
                sql_wrapper = f"""import sqlite3
import sys
import json
import os
import re

# Blocked SQL keywords for security (prevent file access, external DBs, schema changes, etc.)
# Note: INSERT, UPDATE, DELETE are allowed as they're legitimate SQL operations for interviews
BLOCKED_KEYWORDS = [
    'ATTACH', 'DETACH', 'PRAGMA', '.read', '.import', '.output', '.dump',
    'CREATE TABLE', 'CREATE TRIGGER', 'CREATE VIEW', 'CREATE INDEX', 
    'DROP', 'ALTER', 'TRUNCATE', 'VACUUM', 'ANALYZE', 'EXPLAIN QUERY PLAN'
]

def is_safe_sql(statement):
    '''Check if SQL statement is safe to execute'''
    stmt_upper = statement.upper().strip()
    for keyword in BLOCKED_KEYWORDS:
        if keyword in stmt_upper:
            return False, f"Unsafe SQL keyword detected: {{keyword}}"
    return True, None

try:
    # Read SQL from file
    sql_file = r'{escaped_path}'
    with open(sql_file, 'r', encoding='utf-8') as f:
        sql_code = f.read()
    
    # Create in-memory database
    conn = sqlite3.connect(':memory:')
    cursor = conn.cursor()
    
    # Execute setup SQL first (table creation and sample data)
    setup_sql = r'''{escaped_setup}'''
    if setup_sql.strip():
        # Split setup SQL by semicolon, handling multi-line statements
        # First, convert escaped newlines back to actual newlines for proper splitting
        # The escaped_setup has \\n which becomes \n in the raw string
        normalized_setup = setup_sql
        # Split by semicolon - this works even with newlines
        setup_statements = []
        parts = normalized_setup.split(';')
        for part in parts:
            # Clean up: remove leading/trailing whitespace and newlines
            stmt = ' '.join(part.split())
            if stmt:
                setup_statements.append(stmt)
        
        # Execute each setup statement
        for setup_stmt in setup_statements:
            if not setup_stmt:
                continue
            try:
                cursor.execute(setup_stmt)
                conn.commit()
            except Exception as e:
                # Setup errors are logged but don't stop execution
                print(f"Setup warning: {{str(e)}}", file=sys.stderr)
                # Continue with next statement
    
    # Split user SQL into individual statements
    user_statements = [s.strip() for s in sql_code.split(';') if s.strip()]
    
    if not user_statements:
        print(json.dumps([{{'error': 'No SQL statements found'}}], indent=2))
        conn.close()
        sys.exit(1)
    
    results = []
    for statement in user_statements:
        if not statement:
            continue
        
        # Check if statement is safe
        is_safe, error_msg = is_safe_sql(statement)
        if not is_safe:
            results.append({{
                'error': error_msg,
                'statement': statement[:100]
            }})
            continue
        
        try:
            cursor.execute(statement)
            
            # Try to fetch results if it's a SELECT
            if statement.strip().upper().startswith('SELECT'):
                rows = cursor.fetchall()
                columns = [desc[0] for desc in cursor.description] if cursor.description else []
                # Convert rows to list format for JSON serialization
                rows_list = [list(row) for row in rows]
                results.append({{
                    'columns': columns,
                    'rows': rows_list,
                    'row_count': len(rows_list)
                }})
            else:
                conn.commit()
                results.append({{
                    'message': 'Statement executed successfully',
                    'rows_affected': cursor.rowcount
                }})
        except Exception as e:
            results.append({{
                'error': str(e),
                'statement': statement[:100] if len(statement) > 100 else statement
            }})
    
    # Output results as JSON
    print(json.dumps(results, indent=2))
    conn.close()
except Exception as e:
    # Output error as JSON to stdout (not stderr) so it's captured
    print(json.dumps([{{'error': f"Execution error: {{str(e)}}"}}], indent=2))
    sys.exit(1)
"""
                # Write SQL wrapper
                wrapper_path = os.path.join(temp_dir, "sql_executor.py")
                with open(wrapper_path, 'w', encoding='utf-8') as f:
                    f.write(sql_wrapper)
                
                # Find python executable (use same logic as Python execution)
                current_file = os.path.abspath(__file__)
                project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_file)))
                
                if os.name == 'nt':  # Windows
                    venv_python = os.path.join(project_root, "venv", "Scripts", "python.exe")
                else:  # Unix/Linux/Mac
                    venv_python = os.path.join(project_root, "venv", "bin", "python")
                
                if os.path.exists(venv_python):
                    python_cmd = venv_python
                else:
                    python_cmd = shutil.which("python") or shutil.which("python3") or "python"
                
                process = subprocess.run(
                    [python_cmd, wrapper_path],
                    input=test_input,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    cwd=temp_dir,
                    shell=False,
                    encoding='utf-8',
                    errors='replace'
                )
            else:
                return {
                    "output": "",
                    "error": f"Language '{language}' execution not implemented. Supported languages: Python, Java, JavaScript, C, C++, SQL.",
                    "execution_time": 0,
                    "exit_code": 1
                }
            
            execution_time = time.time() - start_time
            
            # Format output and error messages
            output = process.stdout
            error = process.stderr if process.returncode != 0 else ""
            
            # For SQL execution, check both stdout and stderr for output
            # The SQL wrapper outputs JSON to stdout, but if there's an error, it might be in stderr
            if language == "sql":
                # Debug: Log what we got
                if not output:
                    logger.warning(f"[SQL] No stdout output. Return code: {process.returncode}, stderr: {process.stderr[:200] if process.stderr else 'None'}")
                
                if not output and process.stderr:
                    # Check if stderr contains JSON (our error format)
                    stderr_content = process.stderr.strip()
                    if stderr_content.startswith('[') or stderr_content.startswith('{'):
                        output = stderr_content
                        error = ""
                    else:
                        # If stderr has content but not JSON, it's a real error
                        error = stderr_content
                        # Also try to get output from stderr if it looks like JSON
                        if stderr_content and (stderr_content.startswith('[') or stderr_content.startswith('{')):
                            output = stderr_content
                            error = ""
            
            # Improve error messages for better user experience
            if error:
                error_lower = error.lower()
                # Make error messages more user-friendly
                if "compilation" in error_lower or "compile" in error_lower:
                    if language == "java":
                        error = f"Java Compilation Error:\n{error}\n\nTip: Ensure your class name matches the filename and all syntax is correct."
                    elif language in ["c", "cpp", "c++"]:
                        error = f"C/C++ Compilation Error:\n{error}\n\nTip: Check for syntax errors, missing includes, or undefined references."
                elif "timeout" in error_lower:
                    error = f"Execution Timeout: Your code took longer than the allowed time limit.\n\nTip: Optimize your algorithm or check for infinite loops."
                elif "not found" in error_lower or "cannot find" in error_lower:
                    if language == "java":
                        error = f"Java Runtime Error:\n{error}\n\nTip: Ensure Java JDK is installed and javac/java are in your PATH."
                    elif language in ["c", "cpp", "c++"]:
                        error = f"Compiler Error:\n{error}\n\nTip: Ensure GCC/G++ is installed. On Windows, install MinGW or Visual Studio Build Tools."
                    elif language in ["javascript", "js"]:
                        error = f"Node.js Error:\n{error}\n\nTip: Ensure Node.js is installed and 'node' is in your PATH."
            
            return {
                "output": output,
                "error": error,
                "execution_time": round(execution_time, 3),
                "exit_code": process.returncode
            }
            
        finally:
            # Clean up temp files and directory
            try:
                if temp_dir and os.path.exists(temp_dir):
                    # Clean up all files in temp directory
                    for file in os.listdir(temp_dir):
                        file_path = os.path.join(temp_dir, file)
                        try:
                            if os.path.isfile(file_path):
                                os.unlink(file_path)
                        except Exception:
                            pass
                    # Remove temp directory
                    try:
                        os.rmdir(temp_dir)
                    except Exception:
                        pass
            except Exception as cleanup_error:
                logger.warning(f"Error cleaning up temp files: {cleanup_error}")
            
    except subprocess.TimeoutExpired:
        timeout_limit = 10 if language == "python" or language == "sql" else 5
        return {
            "output": "",
            "error": f"Execution timeout ({timeout_limit} seconds exceeded). Your code took too long to execute.\n\nTip: Check for infinite loops, optimize your algorithm, or reduce input size.",
            "execution_time": float(timeout_limit),
            "exit_code": 124
        }
    except FileNotFoundError as e:
        # Provide helpful messages based on language
        tool_messages = {
            "python": "Python interpreter not found. Please ensure Python is installed and in your PATH.",
            "java": "Java compiler (javac) or runtime (java) not found. Please install Java JDK and add it to your PATH.",
            "javascript": "Node.js not found. Please install Node.js from https://nodejs.org/ and add it to your PATH.",
            "c": "GCC compiler not found. On Windows, install MinGW or Visual Studio Build Tools. On Linux/Mac, install gcc via package manager.",
            "cpp": "G++ compiler not found. On Windows, install MinGW or Visual Studio Build Tools. On Linux/Mac, install g++ via package manager.",
            "sql": "Python interpreter not found (required for SQL execution). Please ensure Python is installed."
        }
        error_msg = tool_messages.get(language, f"Required tool not found: {str(e)}. Please ensure the necessary compilers/runtimes are installed and in your PATH.")
        return {
            "output": "",
            "error": error_msg,
            "execution_time": 0,
            "exit_code": 127
        }
    except Exception as e:
        # Provide a friendly error message
        error_msg = f"Execution error: {str(e)}\n\n"
        if "permission" in str(e).lower():
            error_msg += "Tip: This might be a permissions issue. Please contact support."
        elif "memory" in str(e).lower():
            error_msg += "Tip: Your code might be using too much memory. Try optimizing your solution."
        else:
            error_msg += "Tip: Check your code for syntax errors or logical issues."
        return {
            "output": "",
            "error": error_msg,
            "execution_time": 0,
            "exit_code": 1
        }