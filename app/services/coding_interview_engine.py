"""
Coding Interview Engine
Generates coding questions based on resume skills and manages coding interview sessions
"""

from typing import List, Dict, Optional, Any
from app.config.settings import settings
import json
import re

# Try to import OpenAI
OPENAI_AVAILABLE = False
OpenAI = None

def _try_import_openai():
    """Lazy import of OpenAI"""
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

class CodingInterviewEngine:
    """Engine for managing coding interview sessions"""
    
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
    
    def start_coding_session(
        self,
        user_id: str,
        resume_skills: Optional[List[str]] = None,
        resume_context: Optional[Dict[str, Any]] = None,
        experience_level: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Start a new coding interview session
        Extracts coding-related skills from resume
        """
        # Extract coding-related skills
        coding_skills = []
        resume_projects: List[str] = []
        resume_domains: List[str] = []

        if resume_skills:
            # Filter for programming languages and DSA-related skills
            coding_keywords = ['python', 'java', 'javascript', 'c++', 'c', 'cpp', 'sql', 
                             'algorithm', 'data structure', 'dsa', 'leetcode', 'hackerrank',
                             'programming', 'coding', 'software development', 'web development']
            for skill in resume_skills:
                skill_lower = skill.lower()
                if any(keyword in skill_lower for keyword in coding_keywords):
                    coding_skills.append(skill)
        
        if resume_context:
            extra_skills = resume_context.get("skills", []) or []
            for skill in extra_skills:
                if skill and skill not in coding_skills:
                    coding_skills.append(skill)
            resume_projects = resume_context.get("projects", []) or []
            resume_domains = resume_context.get("domains", []) or []
            if not experience_level:
                experience_level = resume_context.get("experience_level")
            keywords = resume_context.get("keywords", {}) or {}
            if not resume_projects and keywords:
                resume_projects = keywords.get("projects", []) or []
        
        # If no coding skills found, use default
        if not coding_skills:
            coding_skills = ["Python", "Data Structures", "Algorithms"]
        
        # Remove duplicates and limit
        coding_skills = list(dict.fromkeys(coding_skills))[:15]
        
        return {
            "session_id": None,  # Will be set by the router
            "coding_skills": coding_skills,
            "current_question_index": 0,
            "questions_asked": [],
            "solutions_submitted": [],
            "experience_level": experience_level,
            "resume_projects": resume_projects,
            "domains": resume_domains
        }
    
    def generate_coding_question(
        self,
        session_data: Dict[str, Any],
        previous_questions: List[str]
    ) -> Dict[str, Any]:
        """
        Generate a coding question based on resume skills
        Returns question with test cases and expected output
        """
        coding_skills = session_data.get("coding_skills", [])
        experience_level = session_data.get("experience_level")
        resume_projects = session_data.get("resume_projects", [])
        resume_domains = session_data.get("domains", [])
        skills_context = ", ".join(coding_skills[:10]) if coding_skills else "general programming"
        
        # Fallback questions if OpenAI is not available
        if not self.openai_available or self.client is None:
            return self._get_fallback_coding_question(session_data, previous_questions)
        
        try:
            system_prompt = """You are a coding interview question generator. Generate coding problems suitable for online coding tests.
Each question should:
1. Be based on Data Structures and Algorithms (arrays, strings, linked lists, trees, graphs, dynamic programming, etc.)
2. Have clear problem statement
3. Include example input/output
4. Include test cases (at least 2-3)
5. Specify time and space complexity expectations
6. Be appropriate for the candidate's skill level

Return JSON with this structure:
{
  "problem": "Problem statement",
  "examples": [{"input": "...", "output": "...", "explanation": "..."}],
  "test_cases": [{"input": "...", "output": "..."}],
  "constraints": "...",
  "difficulty": "Easy/Medium/Hard",
  "topics": ["array", "string", etc.]
}"""

            # Get past performance for adaptive difficulty (passed from router)
            past_performance = session_data.get("past_performance")
            difficulty_label = self._determine_difficulty(experience_level, coding_skills, past_performance)
            project_context = ", ".join(resume_projects[:2]) if resume_projects else "recent real-world projects"
            domain_context = ", ".join(resume_domains[:2]) if resume_domains else "software engineering"

            user_prompt = f"""Generate a coding problem that mirrors the candidate's resume.

Key skills: {skills_context}
Notable experience level: {experience_level or 'Not specified'}
Projects/domains: {project_context} | {domain_context}

Previous questions asked: {len(previous_questions)}. Ensure the new problem is different from earlier ones.
Generate a {difficulty_label} level coding problem that references at least one of the skills or project contexts mentioned above."""

            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.7,
                response_format={"type": "json_object"}
            )
            
            content = response.choices[0].message.content
            question_data = json.loads(content)
            
            return {
                "problem": question_data.get("problem", ""),
                "examples": question_data.get("examples", []),
                "test_cases": question_data.get("test_cases", []),
                "constraints": question_data.get("constraints", ""),
                "difficulty": question_data.get("difficulty", "Medium"),
                "topics": question_data.get("topics", [])
            }
            
        except Exception as e:
            print(f"Error generating coding question: {str(e)}")
            return self._get_fallback_coding_question(session_data, previous_questions)
    
    def _determine_difficulty(
        self, 
        experience_level: Optional[str], 
        skills: List[str],
        past_performance: Optional[Dict[str, Any]] = None
    ) -> str:
        """Determine difficulty based on experience level and past performance:
        - Fresher (0 years) → Easy or Medium
        - 1-2 years → Medium
        - 3+ years → Hard
        
        Adaptive adjustment based on past performance:
        - If solved most questions correctly → increase difficulty
        - If struggled → decrease difficulty
        """
        import random
        
        # Base difficulty from experience
        base_difficulty = None
        years = self._parse_experience_years(experience_level)
        if years is not None:
            if years < 1:  # Fresher
                base_difficulty = random.choice(["Easy", "Medium"])
            elif years < 3:  # 1-2 years
                base_difficulty = "Medium"
            else:  # 3+ years
                base_difficulty = "Hard"
        else:
            # Fallback to skills-based difficulty if experience level not available
            if len(skills) >= 10:
                base_difficulty = "Hard"
            elif len(skills) >= 5:
                base_difficulty = "Medium"
            else:
                base_difficulty = "Easy"
        
        # Adaptive adjustment based on past performance
        if past_performance:
            accuracy = past_performance.get("accuracy", 0)
            average_score = past_performance.get("average_score", 0)
            
            # If user performed well (accuracy > 70% or average score > 70), increase difficulty
            if accuracy > 70 or average_score > 70:
                if base_difficulty == "Easy":
                    return "Medium"
                elif base_difficulty == "Medium":
                    return "Hard"
                # Already Hard, keep it
                return "Hard"
            # If user struggled (accuracy < 40% or average score < 40), decrease difficulty
            elif accuracy < 40 or average_score < 40:
                if base_difficulty == "Hard":
                    return "Medium"
                elif base_difficulty == "Medium":
                    return "Easy"
                # Already Easy, keep it
                return "Easy"
        
        return base_difficulty

    @staticmethod
    def _parse_experience_years(experience_level: Optional[str]) -> Optional[float]:
        if not experience_level:
            return None
        exp = experience_level.lower()
        if "fresher" in exp:
            return 0
        match = re.search(r'(\d+)\s*(?:\+|years|yrs|y)?', exp)
        if match:
            return float(match.group(1))
        range_match = re.search(r'(\d+)\s*-\s*(\d+)', exp)
        if range_match:
            return (float(range_match.group(1)) + float(range_match.group(2))) / 2
        return None
    
    def _get_fallback_coding_question(
        self,
        session_data: Dict[str, Any],
        previous_questions: List[str]
    ) -> Dict[str, Any]:
        """Fallback coding questions that remain resume-aware"""
        coding_skills = session_data.get("coding_skills", []) or []
        resume_projects = session_data.get("resume_projects", []) or []
        experience_level = session_data.get("experience_level")
        difficulty = self._determine_difficulty(experience_level, coding_skills)

        primary_skill = coding_skills[len(previous_questions) % len(coding_skills)] if coding_skills else "your preferred language"
        project_reference = resume_projects[len(previous_questions) % len(resume_projects)] if resume_projects else "a recent project"
        
        fallback_questions = [
            {
                "problem": "Given an array of integers, find the maximum sum of a contiguous subarray. Example: For array [-2, 1, -3, 4, -1, 2, 1, -5, 4], the maximum sum is 6 (subarray [4, -1, 2, 1]).",
                "examples": [
                    {
                        "input": "[-2, 1, -3, 4, -1, 2, 1, -5, 4]",
                        "output": "6",
                        "explanation": "The maximum sum subarray is [4, -1, 2, 1]"
                    }
                ],
                "test_cases": [
                    {"input": "[-2, 1, -3, 4, -1, 2, 1, -5, 4]", "output": "6"},
                    {"input": "[1, 2, 3, 4, 5]", "output": "15"},
                    {"input": "[-1, -2, -3]", "output": "-1"}
                ],
                "constraints": "1 <= array.length <= 10^5, -10^4 <= array[i] <= 10^4",
                "difficulty": "Medium",
                "topics": ["array", "dynamic programming"]
            },
            {
                "problem": "Given a string, find the length of the longest substring without repeating characters.\n\nExample: For 'abcabcbb', the answer is 3 (substring 'abc').",
                "examples": [
                    {
                        "input": "'abcabcbb'",
                        "output": "3",
                        "explanation": "The longest substring without repeating characters is 'abc'"
                    }
                ],
                "test_cases": [
                    {"input": "'abcabcbb'", "output": "3"},
                    {"input": "'bbbbb'", "output": "1"},
                    {"input": "'pwwkew'", "output": "3"}
                ],
                "constraints": "0 <= s.length <= 5 * 10^4",
                "difficulty": "Medium",
                "topics": ["string", "sliding window", "hash table"]
            },
            {
                "problem": "Given two sorted arrays, merge them into a single sorted array.\n\nExample: Merge [1, 3, 5] and [2, 4, 6] to get [1, 2, 3, 4, 5, 6].",
                "examples": [
                    {
                        "input": "[1, 3, 5] and [2, 4, 6]",
                        "output": "[1, 2, 3, 4, 5, 6]",
                        "explanation": "Merge the two sorted arrays maintaining sorted order"
                    }
                ],
                "test_cases": [
                    {"input": "[1, 3, 5], [2, 4, 6]", "output": "[1, 2, 3, 4, 5, 6]"},
                    {"input": "[1, 2, 3], [4, 5, 6]", "output": "[1, 2, 3, 4, 5, 6]"},
                    {"input": "[], [1, 2]", "output": "[1, 2]"}
                ],
                "constraints": "0 <= arr1.length, arr2.length <= 10^4",
                "difficulty": "Easy",
                "topics": ["array", "two pointers"]
            },
            {
                "problem": "Given a binary tree, find its maximum depth.\n\nThe maximum depth is the number of nodes along the longest path from the root node down to the farthest leaf node.",
                "examples": [
                    {
                        "input": "Tree: [3,9,20,null,null,15,7]",
                        "output": "3",
                        "explanation": "The tree has depth 3"
                    }
                ],
                "test_cases": [
                    {"input": "[3,9,20,null,null,15,7]", "output": "3"},
                    {"input": "[1,null,2]", "output": "2"}
                ],
                "constraints": "The number of nodes in the tree is in the range [0, 10^4]",
                "difficulty": "Easy",
                "topics": ["tree", "depth-first search", "breadth-first search"]
            },
            {
                "problem": "Given an array of integers, return indices of the two numbers such that they add up to a specific target.\n\nYou may assume that each input would have exactly one solution.",
                "examples": [
                    {
                        "input": "nums = [2, 7, 11, 15], target = 9",
                        "output": "[0, 1]",
                        "explanation": "nums[0] + nums[1] = 2 + 7 = 9"
                    }
                ],
                "test_cases": [
                    {"input": "[2, 7, 11, 15], 9", "output": "[0, 1]"},
                    {"input": "[3, 2, 4], 6", "output": "[1, 2]"},
                    {"input": "[3, 3], 6", "output": "[0, 1]"}
                ],
                "constraints": "2 <= nums.length <= 10^4, -10^9 <= nums[i] <= 10^9",
                "difficulty": "Easy",
                "topics": ["array", "hash table"]
            }
        ]
        
        # Select a question that hasn't been asked
        available = [q for q in fallback_questions if q["problem"] not in previous_questions]
        if not available:
            available = fallback_questions
        
        base_question = available[0]
        contextual_problem = f"While enhancing your '{project_reference}' work using {primary_skill}, you now need to solve the following challenge. {base_question['problem']}"
        return {
            "problem": contextual_problem,
            "examples": base_question.get("examples", []),
            "test_cases": base_question.get("test_cases", []),
            "constraints": base_question.get("constraints", ""),
            "difficulty": difficulty,
            "topics": base_question.get("topics", [])
        }

# Create global instance
coding_interview_engine = CodingInterviewEngine()

