# 🎯 Skill Capital AI MockMate

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-green.svg)](https://fastapi.tiangolo.com/)
[![Supabase](https://img.shields.io/badge/Supabase-PostgreSQL-orange.svg)](https://supabase.com/)
[![OpenAI](https://img.shields.io/badge/OpenAI-GPT--3.5--turbo-purple.svg)](https://openai.com/)
[![Vercel](https://img.shields.io/badge/Vercel-Serverless-black.svg)](https://vercel.com/)

> **An AI-Powered Interview Preparation Platform** - Practice mock interviews with personalized questions, get real-time AI feedback, and track your performance over time. Supports Technical, Coding, HR, and STAR behavioral interviews with voice interaction and comprehensive analytics.

---

## 📋 Table of Contents

- [Overview](#overview)
- [Features](#features)
- [System Architecture](#system-architecture)
- [Technology Stack](#technology-stack)
- [Installation](#installation)
- [Configuration](#configuration)
- [API Documentation](#api-documentation)
- [Database Schema](#database-schema)
- [Project Structure](#project-structure)
- [Development Guide](#development-guide)
- [Deployment](#deployment)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [License](#license)

---

## 🎯 Overview

**Skill Capital AI MockMate** is a full-stack interview preparation platform that uses AI to provide personalized mock interviews. The system analyzes user resumes, generates context-aware interview questions, and provides detailed feedback on answers.

### Key Capabilities

- 📄 **Resume Analysis** - Automatic skill extraction, experience level detection, and keyword extraction
- 🤖 **AI Question Generation** - Context-aware questions based on resume and role using OpenAI GPT models
- 💬 **Real-time Evaluation** - Multi-dimensional scoring with detailed feedback
- 📊 **Performance Analytics** - Track progress with comprehensive dashboards
- 🎤 **Voice Interaction** - Speech-to-text and text-to-speech for technical interviews
- 💻 **Coding Challenges** - Execute and evaluate code submissions with test cases

---

## ✨ Features

### Core Features

- ✅ **FastAPI Backend** - RESTful API with automatic OpenAPI documentation (Swagger/ReDoc)
- ✅ **Unified Frontend/Backend** - FastAPI serves both API and static frontend files
- ✅ **Supabase Integration** - PostgreSQL database with Row Level Security (RLS) and storage
- ✅ **Resume Upload & Parsing** - Support for PDF and DOCX files with text extraction
- ✅ **AI-Powered Question Generation** - Context-aware questions using OpenAI GPT models via LangChain
- ✅ **Multiple Interview Modes** - Technical, Coding, HR, and STAR (behavioral) interviews
- ✅ **Real-time Answer Evaluation** - AI-powered scoring with detailed feedback after each answer
- ✅ **Performance Dashboard** - Track progress with charts, analytics, and skill analysis
- ✅ **Voice Interaction** - Speech-to-text (Whisper) and text-to-speech for interviews
- ✅ **Code Execution** - Secure code execution with Piston API fallback for multiple languages
- ✅ **Rate Limiting** - In-memory rate limiting to prevent abuse
- ✅ **Request Validation** - Input validation and request size limits

### Resume Analysis

- ✅ **Automatic Skill Extraction** - Extracts technologies, tools, and skills from resumes
- ✅ **Experience Level Detection** - Identifies experience level from resume content
- ✅ **Resume Keyword Extraction** - Extracts technologies, job titles, and projects
- ✅ **Text Extraction** - Automatic text extraction from PDF and DOCX files

### Interview Features

- ✅ **Dynamic Topic Generation** - Rule-based topic generation based on role and experience
- ✅ **Context-Aware Questions** - Questions reference specific resume content
- ✅ **Multiple Question Types** - HR, Technical, Problem-solving, and Coding questions
- ✅ **Timed Interview Mode** - 60 seconds per question with automatic timeout
- ✅ **Response Time Tracking** - Included in AI evaluation
- ✅ **Question-by-Question Scoring** - Immediate feedback after each answer
- ✅ **Comprehensive Evaluation** - Post-interview analysis with recommendations

### Technical Interview

- ✅ **Conversational AI Interview** - Dynamic follow-up questions based on answers
- ✅ **Speech-to-Text** - Voice input using OpenAI Whisper API
- ✅ **Text-to-Speech** - Audio output for questions and feedback
- ✅ **Real-time Evaluation** - AI evaluates answers and provides immediate feedback
- ✅ **Session Management** - Track conversation history and scores
- ✅ **Audio Queue Management** - Prevents audio overlap, sequential playback
- ✅ **No Answer Detection** - Handles empty recordings gracefully

### Coding Interview

- ✅ **Multi-Language Support** - Python, Java, C, C++ code execution
- ✅ **Code Execution** - Secure execution with Piston API fallback
- ✅ **Test Case Validation** - Automatic test case checking with output normalization
- ✅ **SQL Support** - SQL coding questions with table setup
- ✅ **Difficulty Adaptation** - Adjusts difficulty based on performance
- ✅ **Performance Metrics** - Execution time, test case results, and correctness scoring
- ✅ **Smart Scoring** - LLM-based evaluation with test case override logic

### HR Interview

- ✅ **Behavioral Questions** - HR-focused interview questions
- ✅ **Voice Interaction** - Speech-to-text and text-to-speech support
- ✅ **Real-time Feedback** - Immediate AI feedback after each answer
- ✅ **No Answer Detection** - Handles empty recordings gracefully
- ✅ **Session Tracking** - Complete interview history and evaluation

### STAR Interview

- ✅ **STAR Method** - Situation, Task, Action, Result structured interviews
- ✅ **Performance Breakdown** - Detailed scoring across STAR components
- ✅ **Personalized Feedback** - Candidate-focused results dashboard
- ✅ **Participation Metrics** - Track engagement and completion rates
- ✅ **Visual Analytics** - Progress bars and score visualization

### Dashboard & Analytics

- ✅ **Performance Metrics** - Total interviews, average score, completion rate
- ✅ **Score Trend Charts** - Visualize performance over time
- ✅ **Skills Analysis** - Identify top 3 strong skills and weak areas
- ✅ **Resume Summary** - Quick view of profile and skills
- ✅ **Interview History** - View all past interviews with scores

---

## 🏗️ System Architecture

### High-Level Architecture

The system follows a clean architecture with clear separation of concerns:
```
┌─────────────────────────────────────────────────────────────┐
│                    Frontend Client (Browser)                 │
│              HTML/CSS/JavaScript + Chart.js                 │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        │ HTTP/REST API
                        │
┌────────────────────────▼─────────────────────────────────────┐
│                    FastAPI Backend                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │ Profile Router│  │Interview Router│ │Dashboard Router│   │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │Technical Router│ │Coding Router │  │HR/STAR Routers│    │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
└────────────────────────┬─────────────────────────────────────┘
                        │
        ┌───────────────┼───────────────┐
        │               │               │
┌────────▼────┐  ┌───────▼──────┐  ┌─────▼──────┐
│   Services   │  │   Services   │  │  Services  │
│ Resume Parser│  │  Question    │  │  Answer   │
│              │  │  Generator    │  │ Evaluator  │
└────────┬─────┘  └───────┬──────┘  └─────┬──────┘
        │                │               │
        └───────────────┬────────────────┘
                        │
        ┌───────────────┼───────────────┐
        │               │               │
┌────────▼────┐  ┌───────▼──────┐  ┌─────▼──────┐
│   OpenAI    │  │   LangChain   │  │  Supabase  │
│GPT-3.5/4 API│  │   Framework   │  │ PostgreSQL │
│Whisper+TTS  │  │               │  │  + Storage │
└─────────────┘  └───────────────┘  └────────────┘
```

### Complete User Workflow

#### 1️⃣ Resume Upload & Analysis Flow

```
User Dashboard → Click "Upload Resume"
                ↓
         Upload PDF/DOCX
                ↓
Backend Processing (5-10 min on Render free tier):
├─> Extract text with PyMuPDF/pdfplumber
├─> Parse resume data (name, email, skills, experience)
├─> Extract projects and keywords (regex-based)
├─> Generate enhanced summary (CPU-intensive, NO OpenAI)
├─> Upload to Supabase storage
└─> Store profile in user_profiles table
                ↓
Display Results:
├─> Personal information
├─> Extracted skills (tags)
├─> Enhanced summary
├─> Projects summary
└─> Interview module cards (4 types)
```

#### 2️⃣ Technical Interview Flow

```
Start Technical Interview
        ↓
POST /api/interview/technical/start
├─> Create session in technical_round table
└─> Generate first question (OpenAI GPT-3.5/4)
        ↓
Play Question Audio (auto-play)
        ↓
User Records Answer (Web Speech API)
        ↓
POST /api/interview/technical/{session_id}/submit-answer
├─> Convert speech to text (OpenAI Whisper)
├─> Evaluate answer with AI (OpenAI GPT)
│   └─> Returns: score (0-100), feedback, next question
├─> Store in database
└─> Convert feedback to speech (TTS)
        ↓
Display Immediate Feedback:
├─> Score badge (color-coded)
├─> Play feedback audio
└─> Show next question
        ↓
Repeat 3-4 until 5-10 questions answered
        ↓
End Interview → Generate Summary → Display Results
```

#### 3️⃣ HR Interview Flow

```
Same as Technical Interview:
- Pre-generated HR-focused questions
- Voice interaction (speech-to-text + TTS)
- Real-time AI evaluation after each answer
- Stored in hr_round table
- Immediate feedback display
```

#### 4️⃣ Coding Interview Flow

```
Start Coding Interview
        ↓
POST /api/interview/coding/start
├─> Create session in coding_round table
└─> Generate coding question (difficulty-based)
        ↓
User Writes Code in Browser Editor
├─> Syntax highlighting
├─> Language selection (Python/Java/C/C++)
└─> Can run code to test (Piston API)
        ↓
Submit Code
POST /api/interview/coding/{session_id}/next
├─> Execute code with ALL test cases (Piston API)
├─> Compare output with expected (normalized)
├─> Calculate score: passed_tests / total_tests * 100
├─> AI evaluation (if partial pass):
│   └─> OpenAI evaluates code quality + logic
└─> Store code, test results, score
        ↓
Display Results:
├─> Test case pass/fail breakdown
├─> Execution time
├─> Code quality feedback
└─> Next question or completion
        ↓
Repeat for 3-5 questions
        ↓
End Interview → Calculate Average → Show Final Results
```

#### 5️⃣ STAR Behavioral Interview Flow

```
Start STAR Interview
        ↓
POST /api/interview/star/start
└─> Generate behavioral questions (STAR method focus)
        ↓
User Provides Structured Answer:
├─> Situation (what was the context?)
├─> Task (what needed to be done?)
├─> Action (what did you do?)
└─> Result (what was the outcome?)
        ↓
POST /api/interview/star/{session_id}/submit-answer
├─> AI evaluates each STAR component separately:
│   ├─> Situation clarity score (0-100)
│   ├─> Task definition score (0-100)
│   ├─> Action detail score (0-100)
│   └─> Result impact score (0-100)
├─> Overall score = average of 4 components
└─> Store in star_round table
        ↓
Display Component Scores + Feedback
        ↓
Repeat for 5-7 questions
        ↓
End Interview → Generate STAR Breakdown → Show Radar Chart
```

#### 6️⃣ Dashboard & Analytics

```
GET /api/dashboard/performance/{user_id}
↓
Aggregate data from all interview tables:
├─> technical_round
├─> coding_round
├─> hr_round
└─> star_round
↓
Calculate Metrics:
├─> Total interviews completed
├─> Average score across all types
├─> Completion rate
├─> Top 3 strong skills
├─> Top 3 weak areas
└─> Recent interview history
↓
Display Dashboard (Chart.js):
├─> Score trend line chart
├─> Skills radar chart
├─> Interview type breakdown (pie chart)
└─> Recent interviews table
```

### Data Flow

1. **Resume Upload**: User uploads resume → Backend parses → Skills extracted → Stored in database
2. **Interview Setup**: User selects role/type → Topics generated → Questions generated (AI) → Session created
3. **Answer Submission**: User submits answer → Evaluated by AI → Scores calculated → Stored in database
4. **Interview Completion**: All answers aggregated → Final evaluation generated → Dashboard updated

### Voice Interaction Flow

```
Question Text (Database)
        ↓
GET /api/interview/text-to-speech?text=...
        ↓
OpenAI TTS API → Audio URL
        ↓
Frontend plays audio (HTML5 Audio API)
        ↓
User speaks → Record audio blob
        ↓
POST /api/interview/speech-to-text + audio file
        ↓
OpenAI Whisper API → Text transcription
        ↓
Process as normal text answer
```

### Code Execution Flow

```
User Code (Python/Java/C/C++)
        ↓
POST /api/interview/coding/run
        ↓
Piston API (https://emkc.org/api/v2/piston)
├─> Remote code execution sandbox
├─> Run with test cases
└─> Returns: output, execution time, errors
        ↓
Compare output with expected
        ↓
Pass/Fail decision + Score calculation
```

For detailed workflow diagrams, see [`project-workflow-documentation.md`](project-workflow-documentation.md).

---

## 🛠️ Technology Stack

### Backend

- **Python 3.11+** - Core programming language
- **FastAPI** - Modern async web framework
- **Uvicorn** - ASGI server
- **Pydantic** - Data validation and settings
- **LangChain** - LLM orchestration framework
- **OpenAI API** - GPT models for question generation and evaluation

### Database & Storage

- **Supabase (PostgreSQL)** - Primary database
- **Row Level Security (RLS)** - Data access control
- **Supabase Storage** - File storage for resumes

### Frontend

- **HTML5/CSS3** - Structure and styling
- **Vanilla JavaScript (ES6+)** - Application logic
- **Chart.js** - Performance visualization
- **Web Speech API** - Voice interaction

### PDF Processing

- **PyMuPDF (fitz)** - Primary PDF text extraction
- **pdfplumber** - Advanced PDF parsing
- **python-docx** - DOCX parsing
- **Text Extraction** - PDF and DOCX text extraction libraries

---

## 📦 Installation

### Prerequisites

- **Python 3.8+** (Python 3.11 recommended)
- **pip** (Python package manager)
- **Supabase Account** - For database and storage
- **OpenAI API Key** - For AI features (question generation, evaluation)

### Backend Setup

1. **Clone the repository**:
```bash
git clone <repository-url>
cd Skill-Capital-AI-MockMate
```

2. **Create a virtual environment**:
```bash
python -m venv venv
```

3. **Activate the virtual environment**:
   - **Windows (PowerShell)**:
   ```bash
   venv\Scripts\activate
   ```
   - **Windows (CMD)**:
   ```bash
   venv\Scripts\activate.bat
   ```
   - **macOS/Linux**:
   ```bash
   source venv/bin/activate
   ```

4. **Install dependencies**:
```bash
pip install -r requirements.txt
```

   **Note**: The `requirements.txt` file is in the project root, not in the `app/` directory.

5. **Set up Supabase Database**:
   - Create a new Supabase project at https://supabase.com
   - Go to SQL Editor and run the SQL from `app/database/schema.sql`
   - Create a storage bucket named `resume-uploads` (public access)

6. **Create `.env` file** in the project root:
```bash
# OpenAI Configuration
OPENAI_API_KEY=your_openai_api_key_here

# Supabase Configuration
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_supabase_anon_key
SUPABASE_SERVICE_KEY=your_supabase_service_role_key

# Backend Configuration
BACKEND_PORT=8000
ENVIRONMENT=development

# CORS Origins (comma-separated, optional)
CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:8000
```

7. **Run the application**:

   **Option 1: Using Python directly (recommended for development)**:
   ```bash
   python app/main.py
   ```

   **Option 2: Using uvicorn directly**:
   ```bash
   uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
   ```

   The application will:
   - Start the FastAPI server at `http://127.0.0.1:8000`
   - Serve the frontend at `http://127.0.0.1:8000/`
   - Auto-open your browser (development mode only)
   - API documentation available at `http://127.0.0.1:8000/docs`

### Frontend Setup

The frontend is automatically served by FastAPI. No separate setup is required!

- **Main Dashboard**: `http://127.0.0.1:8000/` or `http://127.0.0.1:8000/index.html`
- **Resume Analysis**: `http://127.0.0.1:8000/resume-analysis.html`
- **Technical Interview**: `http://127.0.0.1:8000/interview.html` or `http://127.0.0.1:8000/technical-interview.html`
- **Coding Interview**: `http://127.0.0.1:8000/coding-interview.html`
- **Coding Results**: `http://127.0.0.1:8000/coding-result.html`
- **HR Interview**: `http://127.0.0.1:8000/hr-interview.html`
- **STAR Interview**: `http://127.0.0.1:8000/star-interview.html`

---

## ⚙️ Configuration

### Environment Variables

All configuration is done through environment variables in the `.env` file:

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `OPENAI_API_KEY` | OpenAI API key for AI features | Yes | - |
| `SUPABASE_URL` | Supabase project URL | Yes | - |
| `SUPABASE_KEY` | Supabase anon/public key | Yes | - |
| `SUPABASE_SERVICE_KEY` | Supabase service role key | Yes | - |
| `BACKEND_PORT` | Backend server port | No | 8000 |
| `ENVIRONMENT` | Environment (development/production) | No | development |
| `CORS_ORIGINS` | Comma-separated CORS origins | No | Auto-detected |
| `VERCEL_URL` | Vercel deployment URL (auto-set by Vercel) | No | - |
| `FRONTEND_URL` | Frontend URL (for CORS) | No | - |
| `LANGCHAIN_TRACING_V2` | Enable LangChain tracing | No | false |
| `LANGCHAIN_PROJECT` | LangChain project name | No | - |

### Supabase Setup

1. **Create a Supabase Project**:
   - Go to https://supabase.com
   - Create a new project (choose a region close to your users)
   - Wait for project initialization (takes 1-2 minutes)
   - Note your project URL and API keys

2. **Run Database Schema**:
   - Go to SQL Editor in Supabase Dashboard
   - Click "New Query"
   - Copy and paste the **entire content** of `app/database/schema.sql`
   - Click "Run" to execute the SQL script
   - Verify tables are created:
     - `user_profiles`
     - `interview_sessions`
     - `technical_round`
     - `coding_round`
     - `hr_round`
     - `star_round`
     - `question_templates`
     - `interview_transcripts`
   - Check that RLS policies are enabled (should see 8+ policies)

3. **Create Storage Bucket**:
   - Go to Storage in Supabase Dashboard
   - Click "New bucket"
   - Name: `resume-uploads`
   - Set to **Public bucket** (or configure RLS policies for authenticated access)
   - Click "Create bucket"
   - Verify bucket is created and accessible

4. **Get API Keys**:
   - Go to Settings → API
   - Copy `Project URL` → Use as `SUPABASE_URL` in `.env`
   - Copy `anon public` key → Use as `SUPABASE_KEY` in `.env`
   - Copy `service_role` key → Use as `SUPABASE_SERVICE_KEY` in `.env`
   - **Important**: Keep `service_role` key secret - it bypasses RLS policies

5. **Verify Setup**:
   - Test database connection: `GET /api/health/database`
   - Should return `{"status": "connected"}`

### LangChain + OpenAI Setup

1. **Get OpenAI API Key**:
   - Go to https://platform.openai.com/api-keys
   - Create a new API key
   - Add it to `.env` as `OPENAI_API_KEY`

2. **LangChain Configuration** (Optional):
   - Set `LANGCHAIN_TRACING_V2=true` for tracing (optional)
   - Set `LANGCHAIN_PROJECT` for project name (optional)

---

## 📡 API Documentation

### Health & Configuration

- `GET /api/health` - Health check endpoint
- `GET /api/health/database` - Database connection health check
- `GET /api/config` - Get frontend configuration (Supabase credentials)

### Profile Management

- `GET /api/profile/current` - Get current user profile
- `GET /api/profile/{user_id}` - Get user profile by ID
- `POST /api/profile/` - Create user profile
- `PUT /api/profile/{user_id}` - Update user profile
- `POST /api/profile/upload-resume` - Upload and parse resume (authenticated users)
- `POST /api/profile/{user_id}/upload-resume` - Upload and parse resume (admin/manual upload)
- `GET /api/profile/resume-analysis/{session_id}` - Get resume analysis data
- `PUT /api/profile/resume-analysis/{session_id}/experience` - Update experience level

### Interview Management

- `GET /api/interview/roles` - Get available roles
- `GET /api/interview/experience-levels` - Get experience levels
- `POST /api/interview/setup` - Setup interview and generate topics
- `POST /api/interview/generate` - Generate interview questions using AI
- `POST /api/interview/start` - Start mock interview session
- `GET /api/interview/session/{session_id}/questions` - Get all questions for a session
- `GET /api/interview/session/{session_id}/question/{question_number}` - Get specific question
- `GET /api/interview/session/{session_id}/next-question/{current_question_number}` - Get next question
- `POST /api/interview/submit-answer` - Submit answer and get AI evaluation
- `POST /api/interview/evaluate` - Generate comprehensive evaluation report

### Technical Interview

- `POST /api/interview/technical/start` - Start technical interview session
- `POST /api/interview/technical/{session_id}/next-question` - Get next technical question
- `POST /api/interview/technical/{session_id}/submit-answer` - Submit technical answer with immediate feedback
- `GET /api/interview/technical/{session_id}/feedback` - Get final feedback summary
- `GET /api/interview/technical/{session_id}/summary` - Get interview summary
- `PUT /api/interview/technical/{session_id}/end` - End technical interview

### HR Interview

- `POST /api/interview/hr/start` - Start HR interview session
- `POST /api/interview/hr/{session_id}/next-question` - Get next HR question
- `POST /api/interview/hr/{session_id}/submit-answer` - Submit HR answer with immediate feedback
- `GET /api/interview/hr/{session_id}/feedback` - Get final feedback summary
- `PUT /api/interview/hr/{session_id}/end` - End HR interview

### STAR Interview

- `POST /api/interview/star/start` - Start STAR interview session
- `POST /api/interview/star/{session_id}/next-question` - Get next STAR question
- `POST /api/interview/star/{session_id}/submit-answer` - Submit STAR answer
- `GET /api/interview/star/{session_id}/feedback` - Get final feedback with STAR breakdown
- `PUT /api/interview/star/{session_id}/end` - End STAR interview

### Coding Interview

- `POST /api/interview/coding/start` - Start coding interview session
- `POST /api/interview/coding/{session_id}/next` - Get next coding question
- `POST /api/interview/coding/run` - Execute code (Python, Java, C, C++)
- `GET /api/interview/coding/{session_id}/results` - Get coding results and scores

### Speech Services

- `POST /api/interview/speech-to-text` - Convert speech audio to text (Whisper)
- `POST /api/interview/text-to-speech` - Convert text to speech (TTS) - POST with body
- `GET /api/interview/text-to-speech?text=...` - Convert text to speech (TTS) - GET with query

### Dashboard

- `GET /api/dashboard/performance/{user_id}` - Get performance dashboard data
- `GET /api/dashboard/trends/{user_id}` - Get trends and score progression data

### API Documentation

- `GET /docs` - Interactive Swagger UI documentation
- `GET /redoc` - ReDoc documentation

---

## 🗄️ Database Schema

The application uses Supabase (PostgreSQL) with the following main tables:

### Core Tables

- **user_profiles** - User profile information, skills, resume data, experience level
- **interview_sessions** - Interview session metadata, status, scores, timestamps
- **technical_round** - Technical interview questions, answers, scores, feedback
- **coding_round** - Coding interview questions, code solutions, test results, scores
- **hr_round** - HR interview questions, answers, scores, feedback
- **star_round** - STAR method behavioral interview data with component scores
- **question_templates** - Admin-managed question templates (optional)
- **interview_transcripts** - Interview transcripts for analytics (optional)

### Database Features

- **Row Level Security (RLS)**: All tables have RLS enabled
  - Users can only access their own data
  - Service role can access all data (for backend operations)
- **Automatic Timestamps**: `created_at` and `updated_at` managed by triggers
- **Foreign Keys**: Proper relationships between tables
- **Indexes**: Optimized for common queries (user_id, session_id)
- **Data Types**: 
  - `user_id`: TEXT (alphanumeric, hyphen, underscore)
  - `session_id`: UUID
  - `scores`: INTEGER (0-100)
  - `skills`: TEXT[] (array of strings)

### Schema Details

See `app/database/schema.sql` for the complete schema with:
- Table definitions with all columns and constraints
- Row Level Security (RLS) policies for data access control
- Indexes for performance optimization
- Foreign key constraints for data integrity
- Triggers for automatic timestamp updates
- Migration scripts for existing databases

### Database Integration

The application uses:
- **Supabase Python Client**: For database operations
- **Singleton Pattern**: Single Supabase client instance
- **Connection Pooling**: Handled by Supabase client
- **Error Handling**: Custom exceptions for database errors
- **Transaction Support**: Atomic updates for session status changes

---

## 📁 Project Structure

```
Skill-Capital-AI-MockMate/
├── api/                          # Vercel serverless entry point
│   └── index.py                  # Vercel handler for FastAPI app
├── app/                          # Backend application
│   ├── __init__.py
│   ├── main.py                   # FastAPI application entry point
│   ├── config/                   # Configuration
│   │   ├── __init__.py
│   │   └── settings.py           # Environment settings and CORS config
│   ├── database/                 # Database schema
│   │   ├── __init__.py
│   │   └── schema.sql            # Supabase database schema (complete)
│   ├── db/                       # Database client
│   │   ├── __init__.py
│   │   └── client.py             # Supabase client singleton
│   ├── routers/                  # API route handlers
│   │   ├── __init__.py
│   │   ├── profile.py            # User profile and resume upload
│   │   ├── interview.py          # General interview endpoints
│   │   ├── interview_common.py  # Common interview utilities
│   │   ├── interview_utils.py    # Interview helper functions
│   │   ├── technical_interview.py # Technical interview routes
│   │   ├── coding_interview.py   # Coding interview routes
│   │   ├── hr_interview.py       # HR interview routes
│   │   ├── star_interview.py     # STAR interview routes
│   │   ├── speech.py             # Speech-to-text and TTS routes
│   │   └── dashboard.py          # Performance dashboard
│   ├── schemas/                  # Pydantic models
│   │   ├── __init__.py
│   │   ├── user.py               # User profile schemas
│   │   ├── interview.py          # Interview schemas
│   │   └── dashboard.py          # Dashboard schemas
│   ├── services/                 # Business logic
│   │   ├── __init__.py
│   │   ├── resume_parser.py       # Resume parsing service
│   │   ├── question_generator.py  # AI question generation
│   │   ├── answer_evaluator.py    # Answer evaluation
│   │   ├── interview_evaluator.py # Interview evaluation
│   │   ├── topic_generator.py     # Topic generation
│   │   ├── coding_interview_engine.py # Coding interview engine
│   │   └── technical_interview_engine.py # Technical interview engine
│   └── utils/                    # Utility functions
│       ├── __init__.py
│       ├── database.py           # Database utilities
│       ├── datetime_utils.py     # Date/time helpers
│       ├── exceptions.py         # Custom exceptions
│       ├── file_utils.py         # File handling
│       ├── resume_parser_util.py # Resume parser utilities
│       ├── rate_limiter.py       # Rate limiting utilities
│       ├── request_validator.py   # Request validation
│       └── url_utils.py          # URL utilities
├── frontend/                     # Frontend files (served by FastAPI)
│   ├── index.html                # Main dashboard page
│   ├── resume-analysis.html      # Resume analysis page
│   ├── interview.html            # Technical interview page
│   ├── coding-interview.html     # Coding interview page
│   ├── coding-result.html         # Coding results page
│   ├── hr-interview.html         # HR interview page
│   ├── star-interview.html       # STAR interview page
│   ├── styles.css                # CSS styles
│   ├── app.js                    # Main JavaScript
│   ├── hr-interview.js           # HR interview JavaScript
│   ├── star-interview.js         # STAR interview JavaScript
│   ├── api-config.js             # API configuration
│   └── logo.png                  # Logo image
├── venv/                         # Python virtual environment (gitignored)
├── .env                          # Environment variables (create this, gitignored)
├── requirements.txt             # Python dependencies (root level)
├── vercel.json                   # Vercel deployment config
└── README.md                     # This file
```

---

## 🚀 Development Guide

### Project Architecture

- **Clean Architecture** - Separation of concerns with routers, services, and utils
- **Dependency Injection** - FastAPI's dependency system for database clients
- **Singleton Pattern** - Database client reuse
- **Error Handling** - Custom exceptions with proper HTTP status codes
- **Type Safety** - Pydantic models for request/response validation

### Adding New Features

1. **New API Endpoint**:
   - Add route handler in `app/routers/`
   - Create Pydantic schemas in `app/schemas/`
   - Implement business logic in `app/services/`
   - Register router in `app/main.py`

2. **New Service**:
   - Create service class in `app/services/`
   - Use dependency injection for database clients
   - Add error handling and logging

3. **Database Changes**:
   - Update `app/database/schema.sql`
   - Run SQL in Supabase SQL Editor
   - Update Pydantic models if needed

### Code Style

- Follow PEP 8 Python style guide
- Use type hints for all functions
- Add docstrings for all classes and functions
- Use Pydantic models for data validation

---

## 🚢 Deployment

### Railway

1. Connect your GitHub repository to Railway
2. Railway will auto-detect the `railway.json` configuration
3. Set environment variables in Railway dashboard
4. Deploy!

### Render

1. Create a new Web Service on Render
2. Connect your repository
3. Render will use `render.yaml` for configuration
4. Set environment variables in Render dashboard
5. Deploy!

### Vercel (Recommended for Serverless)

1. **Connect Repository**:
   - Go to [Vercel Dashboard](https://vercel.com)
   - Click "New Project"
   - Import your GitHub repository

2. **Configure Project**:
   - Vercel will auto-detect `vercel.json` configuration
   - Framework Preset: Other
   - Root Directory: `.` (project root)
   - Build Command: (leave empty - no build needed)
   - Output Directory: (leave empty)

3. **Set Environment Variables**:
   - Go to Project Settings → Environment Variables
   - Add all required variables:
     - `OPENAI_API_KEY`
     - `SUPABASE_URL`
     - `SUPABASE_KEY`
     - `SUPABASE_SERVICE_KEY`
     - `ENVIRONMENT=production` (optional)
   - **Note**: `VERCEL_URL` is automatically set by Vercel

4. **Deploy**:
   - Click "Deploy"
   - Wait for deployment to complete
   - Your app will be available at `https://your-project.vercel.app`

5. **Post-Deployment**:
   - Ensure Supabase database schema is set up
   - Create `resume-uploads` storage bucket in Supabase
   - Test the application at your Vercel URL

**Important Notes for Vercel**:
- Code execution uses Piston API fallback (no local compilers)
- All API routes are serverless functions
- Frontend is served through FastAPI static file serving

### Manual Deployment

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export OPENAI_API_KEY=your_key
export SUPABASE_URL=your_url
export SUPABASE_KEY=your_anon_key
export SUPABASE_SERVICE_KEY=your_service_key
export ENVIRONMENT=production

# Run with uvicorn (production)
uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 4
```

---

## 📖 Usage Guide

### Getting Started

1. **Upload Your Resume**:
   - Navigate to Resume Analysis page
   - Upload PDF or DOCX resume
   - Wait for analysis to complete
   - Review extracted skills and experience level

2. **Start an Interview**:
   - Choose interview type: Technical, Coding, HR, or STAR
   - Select your role and experience level
   - Begin answering questions

3. **During Interview**:
   - **Technical/HR**: Use voice recording or type answers
   - **Coding**: Write code in the editor, test with sample inputs
   - **STAR**: Structure answers using Situation, Task, Action, Result format
   - Receive immediate feedback after each answer

4. **View Results**:
   - Check performance dashboard for analytics
   - Review detailed feedback and recommendations
   - Track progress over time

### Interview Types

- **Technical Interview**: Conversational AI interview with voice support
- **Coding Interview**: Solve coding problems in Python, Java, C, or C++
- **HR Interview**: Behavioral questions with voice interaction
- **STAR Interview**: Structured behavioral interviews using STAR method

### Best Practices

- Upload an updated resume for better question personalization
- Speak clearly when using voice recording
- Review feedback after each answer to improve
- Practice regularly to track improvement over time

---

## 🐛 Troubleshooting

### Common Issues

1. **"Supabase configuration missing"**
   - Ensure `.env` file exists in project root
   - Check that `SUPABASE_URL` and `SUPABASE_KEY` are set correctly
   - Verify credentials in Supabase Dashboard → Settings → API

2. **"OpenAI API key not found"**
   - Set `OPENAI_API_KEY` in `.env` file
   - Restart the server after adding the key
   - Verify key is active at https://platform.openai.com/api-keys

3. **Resume parsing fails for LaTeX PDFs**
   - LaTeX-generated PDFs may not have extractable text
   - Export LaTeX PDFs as PDF/A from Overleaf for better compatibility
   - Ensure PDF has selectable text (not just vector graphics)

4. **CORS errors**
   - Check `CORS_ORIGINS` in `.env`
   - In development, the app allows all origins by default
   - On Vercel, CORS is handled automatically

5. **Database connection errors**
   - Verify Supabase credentials
   - Check that database schema is set up correctly (`app/database/schema.sql`)
   - Ensure RLS policies allow service role access
   - Test connection at `/api/health/database`

6. **Code execution fails (Coding Interview)**
   - System automatically uses Piston API fallback if local compilers not found
   - Check internet connection for Piston API access
   - Verify code syntax before submission

7. **Audio overlap in interviews**
   - System automatically queues audio playback
   - Wait for current audio to finish before starting new recording
   - Refresh page if audio issues persist

8. **Rate limiting errors (429)**
   - System limits: 30 requests/min per user, 60 requests/min per session
   - Wait a moment before retrying
   - Reduce request frequency if needed

---

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

### Contribution Guidelines

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## 📄 License

This project is for educational purposes.

---

## 📧 Support

For issues and questions, please open an issue on the repository.

---

**Built with ❤️ using FastAPI, OpenAI, LangChain, and Supabase**

---

## 📚 Additional Resources

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Supabase Documentation](https://supabase.com/docs)
- [OpenAI API Documentation](https://platform.openai.com/docs)
- [LangChain Documentation](https://python.langchain.com/)
- [Architecture Document](architecture.tex) - Complete LaTeX architecture document with diagrams

---

---

## 🔒 Security Features

- **Input Validation**: All user inputs are validated (user_id format, request size limits)
- **Rate Limiting**: In-memory rate limiting to prevent abuse
- **Row Level Security**: Supabase RLS policies for data access control
- **Error Handling**: Standardized error responses, no sensitive data leakage
- **Request Size Limits**: 2MB limit on request bodies (except file uploads)
- **Session Validation**: All interview endpoints validate session existence

---

## 🎯 Project Status

**Current Version**: 1.0.0  
**Completion**: ~95%  
**Status**: Production-ready for deployment

### Completed Features ✅
- All interview types (Technical, Coding, HR, STAR)
- Resume parsing and analysis
- Voice interaction (STT/TTS)
- Code execution with multi-language support
- Performance dashboard and analytics
- Rate limiting and request validation
- Comprehensive API documentation

### Known Limitations ⚠️
- Local code execution requires system compilers (Piston API fallback available)
- In-memory rate limiting (resets on server restart)

---

*Last Updated: December 2025*
