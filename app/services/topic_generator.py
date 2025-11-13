"""
Topic generator service for interview preparation
Generates interview topics based on role, experience level, and user skills
"""

from typing import List, Dict, Optional
from app.schemas.interview import InterviewTopic

class TopicGenerator:
    """Generate interview topics based on role and skills"""
    
    def __init__(self):
        # Role-based topic mappings
        self.role_topics: Dict[str, Dict[str, List[Dict[str, str]]]] = {
            "Python Developer": {
                "Technical": [
                    {"topic": "Python Fundamentals", "description": "Core Python concepts, data structures, and syntax"},
                    {"topic": "Object-Oriented Programming", "description": "Classes, inheritance, polymorphism, encapsulation"},
                    {"topic": "Python Libraries", "description": "NumPy, Pandas, Matplotlib, Requests, etc."},
                    {"topic": "Web Frameworks", "description": "Django, Flask, FastAPI - routing, ORM, middleware"},
                    {"topic": "Database Integration", "description": "SQLAlchemy, database queries, migrations"},
                    {"topic": "Testing", "description": "Unit testing, pytest, mocking, test coverage"},
                    {"topic": "Async Programming", "description": "asyncio, async/await, concurrent programming"},
                    {"topic": "API Development", "description": "REST APIs, GraphQL, API design principles"},
                ],
                "System Design": [
                    {"topic": "System Architecture", "description": "Designing scalable Python applications"},
                    {"topic": "Caching Strategies", "description": "Redis, Memcached, caching patterns"},
                    {"topic": "Message Queues", "description": "Celery, RabbitMQ, task queues"},
                ],
                "Behavioral": [
                    {"topic": "Problem Solving", "description": "Approach to solving complex problems"},
                    {"topic": "Code Review", "description": "Best practices, code quality"},
                ]
            },
            "ServiceNow Engineer": {
                "Technical": [
                    {"topic": "ServiceNow Platform", "description": "Platform architecture, tables, and data model"},
                    {"topic": "Scripting", "description": "Client scripts, server scripts, business rules"},
                    {"topic": "Service Catalog", "description": "Catalog items, workflows, request management"},
                    {"topic": "ITSM Processes", "description": "Incident, Problem, Change Management"},
                    {"topic": "Service Portal", "description": "Widget development, UI customization"},
                    {"topic": "Integration", "description": "REST APIs, SOAP, MID Server, web services"},
                    {"topic": "Workflow & Flow Designer", "description": "Workflow automation, flow designer"},
                    {"topic": "Reporting & Analytics", "description": "Reports, dashboards, performance analytics"},
                ],
                "System Design": [
                    {"topic": "ServiceNow Architecture", "description": "Instance design, data separation"},
                    {"topic": "Custom Application Development", "description": "Scoped apps, application development"},
                ],
                "Behavioral": [
                    {"topic": "ITIL Knowledge", "description": "ITIL processes and best practices"},
                    {"topic": "Stakeholder Management", "description": "Working with business users"},
                ]
            },
            "DevOps": {
                "Technical": [
                    {"topic": "CI/CD Pipelines", "description": "Jenkins, GitLab CI, GitHub Actions, pipeline design"},
                    {"topic": "Containerization", "description": "Docker, container orchestration, best practices"},
                    {"topic": "Kubernetes", "description": "K8s architecture, pods, services, deployments"},
                    {"topic": "Cloud Platforms", "description": "AWS, Azure, GCP - services and architecture"},
                    {"topic": "Infrastructure as Code", "description": "Terraform, CloudFormation, Ansible"},
                    {"topic": "Monitoring & Logging", "description": "Prometheus, Grafana, ELK stack, monitoring tools"},
                    {"topic": "Linux/Unix", "description": "Shell scripting, system administration"},
                    {"topic": "Networking", "description": "Load balancers, DNS, networking concepts"},
                ],
                "System Design": [
                    {"topic": "Scalable Infrastructure", "description": "Designing high-availability systems"},
                    {"topic": "Disaster Recovery", "description": "Backup strategies, failover mechanisms"},
                ],
                "Behavioral": [
                    {"topic": "Incident Management", "description": "Handling production incidents"},
                    {"topic": "Automation Mindset", "description": "Identifying automation opportunities"},
                ]
            },
            "Fresher": {
                "Technical": [
                    {"topic": "Programming Fundamentals", "description": "Basic programming concepts and logic"},
                    {"topic": "Data Structures & Algorithms", "description": "Arrays, linked lists, trees, sorting algorithms"},
                    {"topic": "Database Basics", "description": "SQL queries, normalization, basic database concepts"},
                    {"topic": "Version Control", "description": "Git basics, branching, merging"},
                    {"topic": "Software Development Lifecycle", "description": "SDLC phases, methodologies"},
                ],
                "System Design": [
                    {"topic": "Basic System Design", "description": "Understanding system components and interactions"},
                ],
                "Behavioral": [
                    {"topic": "Communication Skills", "description": "Expressing ideas clearly and effectively"},
                    {"topic": "Learning Attitude", "description": "Willingness to learn and adapt"},
                    {"topic": "Team Collaboration", "description": "Working in teams, collaboration skills"},
                ]
            },
            "Full Stack Developer": {
                "Technical": [
                    {"topic": "Frontend Technologies", "description": "React, Vue, Angular, HTML/CSS/JavaScript"},
                    {"topic": "Backend Development", "description": "Server-side programming, APIs, databases"},
                    {"topic": "Database Design", "description": "SQL, NoSQL, database optimization"},
                    {"topic": "API Design", "description": "REST, GraphQL, API best practices"},
                    {"topic": "Authentication & Authorization", "description": "JWT, OAuth, security best practices"},
                    {"topic": "Testing", "description": "Unit, integration, and E2E testing"},
                ],
                "System Design": [
                    {"topic": "Full Stack Architecture", "description": "Designing end-to-end applications"},
                    {"topic": "Performance Optimization", "description": "Frontend and backend optimization"},
                ],
                "Behavioral": [
                    {"topic": "Project Management", "description": "Managing full-stack projects"},
                ]
            },
            "Data Engineer": {
                "Technical": [
                    {"topic": "Data Pipelines", "description": "ETL/ELT processes, data transformation"},
                    {"topic": "Big Data Technologies", "description": "Hadoop, Spark, Kafka, data processing"},
                    {"topic": "Data Warehousing", "description": "Data warehouse design, dimensional modeling"},
                    {"topic": "SQL & NoSQL", "description": "Database design, query optimization"},
                    {"topic": "Cloud Data Services", "description": "AWS Redshift, Snowflake, BigQuery"},
                ],
                "System Design": [
                    {"topic": "Data Architecture", "description": "Designing scalable data systems"},
                ],
                "Behavioral": [
                    {"topic": "Data Quality", "description": "Ensuring data accuracy and reliability"},
                ]
            }
        }
        
        # Experience level adjustments
        self.experience_adjustments = {
            "Fresher": {
                "focus": "Fundamentals",
                "complexity": "Basic to Intermediate"
            },
            "1yrs": {
                "focus": "Practical Application",
                "complexity": "Intermediate"
            },
            "2yrs": {
                "focus": "Advanced Concepts",
                "complexity": "Intermediate to Advanced"
            },
            "3yrs": {
                "focus": "System Design",
                "complexity": "Advanced"
            },
            "4yrs": {
                "focus": "Architecture & Leadership",
                "complexity": "Advanced"
            },
            "5yrs": {
                "focus": "Senior Level",
                "complexity": "Advanced to Expert"
            },
            "5yrs+": {
                "focus": "Expert Level",
                "complexity": "Expert"
            }
        }
    
    def generate_topics(
        self, 
        role: str, 
        experience_level: str, 
        user_skills: Optional[List[str]] = None
    ) -> List[InterviewTopic]:
        """Generate interview topics based on role, experience, and user skills"""
        
        # Get base topics for the role
        role_data = self.role_topics.get(role, self.role_topics.get("Fresher", {}))
        
        topics: List[InterviewTopic] = []
        
        # Add topics from each category
        for category, topic_list in role_data.items():
            for topic_data in topic_list:
                # Adjust description based on experience level
                description = topic_data["description"]
                if experience_level in self.experience_adjustments:
                    adj = self.experience_adjustments[experience_level]
                    description += f" ({adj['complexity']} level)"
                
                topics.append(InterviewTopic(
                    topic=topic_data["topic"],
                    description=description,
                    category=category
                ))
        
        # If user has specific skills, prioritize or add related topics
        if user_skills:
            # Add skill-specific topics
            skill_topics = self._get_skill_specific_topics(user_skills, role)
            topics.extend(skill_topics)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_topics = []
        for topic in topics:
            key = (topic.topic, topic.category)
            if key not in seen:
                seen.add(key)
                unique_topics.append(topic)
        
        return unique_topics
    
    def _get_skill_specific_topics(self, skills: List[str], role: str) -> List[InterviewTopic]:
        """Generate additional topics based on user's specific skills"""
        skill_topics = []
        skills_lower = [s.lower() for s in skills]
        
        # Skill to topic mappings
        skill_topic_map = {
            "react": InterviewTopic(
                topic="React Advanced Concepts",
                description="Hooks, Context API, performance optimization, state management",
                category="Technical"
            ),
            "python": InterviewTopic(
                topic="Python Advanced Features",
                description="Decorators, generators, metaclasses, Python internals",
                category="Technical"
            ),
            "aws": InterviewTopic(
                topic="AWS Services Deep Dive",
                description="EC2, S3, Lambda, CloudFormation, architecture patterns",
                category="Technical"
            ),
            "docker": InterviewTopic(
                topic="Containerization Best Practices",
                description="Docker optimization, multi-stage builds, security",
                category="Technical"
            ),
            "kubernetes": InterviewTopic(
                topic="Kubernetes Advanced",
                description="K8s networking, storage, security, operators",
                category="Technical"
            ),
            "servicenow": InterviewTopic(
                topic="ServiceNow Advanced Development",
                description="Advanced scripting, custom applications, integrations",
                category="Technical"
            ),
        }
        
        for skill in skills_lower:
            for skill_key, topic in skill_topic_map.items():
                if skill_key in skill:
                    skill_topics.append(topic)
                    break
        
        return skill_topics
    
    def get_suggested_skills(self, role: str, user_skills: List[str]) -> List[str]:
        """Get suggested skills based on role"""
        role_skill_map = {
            "Python Developer": ["Python", "Django", "Flask", "FastAPI", "SQL", "Git", "Docker"],
            "ServiceNow Engineer": ["ServiceNow", "JavaScript", "ITIL", "REST API", "SQL"],
            "DevOps": ["Docker", "Kubernetes", "AWS", "Jenkins", "Terraform", "Linux", "Git"],
            "Fresher": ["Programming", "Data Structures", "Algorithms", "SQL", "Git"],
            "Full Stack Developer": ["JavaScript", "React", "Node.js", "SQL", "Git", "REST API"],
            "Data Engineer": ["Python", "SQL", "Spark", "Hadoop", "Kafka", "AWS"]
        }
        
        suggested = role_skill_map.get(role, [])
        # Filter out skills user already has
        user_skills_lower = [s.lower() for s in user_skills]
        return [s for s in suggested if s.lower() not in user_skills_lower]

# Create global instance
topic_generator = TopicGenerator()

