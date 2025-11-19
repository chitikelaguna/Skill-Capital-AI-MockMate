# Skill Capital AI MockMate

A comprehensive full-stack application for AI-powered interview preparation using FastAPI, HTML/CSS/JavaScript, Supabase, and OpenAI. Practice mock interviews with AI-generated questions, get real-time feedback, and track your performance over time.

## 🎯 Features

### Core Features
- ✅ **FastAPI Backend** - RESTful API with automatic OpenAPI documentation
- ✅ **Unified Frontend/Backend** - FastAPI serves both API and static frontend files
- ✅ **Supabase Integration** - PostgreSQL database with Row Level Security (RLS)
- ✅ **Resume Upload & Parsing** - Support for PDF and DOCX files with OCR fallback
- ✅ **AI-Powered Question Generation** - Context-aware questions using OpenAI GPT models
- ✅ **Multiple Interview Modes** - Text-based, Timed, and Technical interviews
- ✅ **Real-time Answer Evaluation** - AI-powered scoring with detailed feedback
- ✅ **Performance Dashboard** - Track progress with charts and analytics
- ✅ **Voice Support** - Speech-to-text and text-to-speech for technical interviews

### Resume Analysis
- ✅ **Automatic Skill Extraction** - Extracts technologies, tools, and skills from resumes
- ✅ **Experience Level Detection** - Identifies experience level from resume content
- ✅ **Resume Keyword Extraction** - Extracts technologies, job titles, and projects
- ✅ **Enhanced Summary Generation** - AI-generated resume summaries
- ✅ **Interview Module Suggestions** - Recommends interview topics based on resume
- ✅ **OCR Support** - Tesseract OCR for LaTeX-generated and scanned PDFs

### Interview Features
- ✅ **Dynamic Topic Generation** - Based on role, experience, and user skills
- ✅ **Context-Aware Questions** - Questions reference specific resume content
- ✅ **Multiple Question Types** - HR, Technical, and Problem-solving questions
- ✅ **Timed Interview Mode** - 60 seconds per question with automatic timeout
- ✅ **Response Time Tracking** - Included in AI evaluation
- ✅ **Question-by-Question Scoring** - Immediate feedback after each answer
- ✅ **Comprehensive Evaluation** - Post-interview analysis with recommendations

### Technical Interview
- ✅ **Conversational AI Interview** - Dynamic follow-up questions based on answers
- ✅ **Speech-to-Text** - Voice input using OpenAI Whisper API
- ✅ **Text-to-Speech** - Audio output for questions and feedback
- ✅ **Real-time Evaluation** - AI evaluates answers and provides feedback
- ✅ **Session Management** - Track conversation history and scores

### Dashboard & Analytics
- ✅ **Performance Metrics** - Total interviews, average score, completion rate
- ✅ **Score Trend Charts** - Visualize performance over time
- ✅ **Skills Analysis** - Identify top 3 strong skills and weak areas
- ✅ **Resume Summary** - Quick view of profile and skills
- ✅ **Interview History** - View all past interviews with scores

### Admin Features (Available but not active in main router)
- ✅ **Student Management** - View all students' interview results
- ✅ **Analytics Dashboard** - Score distribution, weaknesses, role statistics
- ✅ **Question Template Management** - Add, edit, and delete question templates

## 📁 Project Structure

```
Skill-Capital-AI-MockMate/
├── app/                          # Backend application
│   ├── __init__.py
│   ├── main.py                   # FastAPI application entry point
│   ├── requirements.txt          # Python dependencies
│   ├── config/                   # Configuration
│   │   ├── __init__.py
│   │   └── settings.py           # Environment settings and CORS config
│   ├── database/                 # Database schema
│   │   ├── __init__.py
│   │   └── schema.sql            # Supabase database schema
│   ├── db/                       # Database client
│   │   ├── __init__.py
│   │   └── client.py             # Supabase client singleton
│   ├── routers/                  # API route handlers
│   │   ├── __init__.py
│   │   ├── profile.py            # User profile and resume upload
│   │   ├── interview.py          # Interview endpoints
│   │   ├── dashboard.py          # Performance dashboard
│   │   ├── admin.py              # Admin panel (not active)
│   │   ├── auth.py               # Authentication (not active)
│   │   └── test_parser.py        # Resume parser testing
│   ├── schemas/                  # Pydantic models
│   │   ├── __init__.py
│   │   ├── user.py               # User profile schemas
│   │   ├── interview.py          # Interview schemas
│   │   ├── dashboard.py          # Dashboard schemas
│   │   └── admin.py              # Admin schemas
│   ├── services/                 # Business logic
│   │   ├── __init__.py
│   │   ├── resume_parser.py      # Resume parsing service
│   │   ├── question_generator.py # AI question generation
│   │   ├── answer_evaluator.py   # Answer evaluation
│   │   ├── interview_evaluator.py # Interview evaluation
│   │   ├── topic_generator.py    # Topic generation
│   │   └── technical_interview_engine.py # Technical interview engine
│   └── utils/                    # Utility functions
│       ├── __init__.py
│       ├── database.py           # Database utilities
│       ├── datetime_utils.py     # Date/time helpers
│       ├── exceptions.py         # Custom exceptions
│       ├── file_utils.py         # File handling
│       └── resume_parser_util.py # Resume parser utilities
├── frontend/                     # Frontend files (served by FastAPI)
│   ├── index.html                # Main application page
│   ├── resume-analysis.html      # Resume analysis page
│   ├── technical-interview.html  # Technical interview page
│   ├── styles.css                # CSS styles
│   ├── app.js                    # Main JavaScript
│   ├── technical-interview.js    # Technical interview JavaScript
│   └── logo.png                  # Logo image
├── .env                          # Environment variables (create this)
├── railway.json                  # Railway deployment config
├── render.yaml                   # Render deployment config
├── vercel.json                   # Vercel deployment config
└── README.md                     # This file
```

## 🚀 Setup Instructions

### Prerequisites

- **Python 3.8+** (Python 3.11 recommended)
- **pip** (Python package manager)
- **Supabase Account** - For database and storage
- **OpenAI API Key** - For AI features (question generation, evaluation)
- **Tesseract OCR** (Optional but recommended) - For LaTeX/scanned PDF parsing

### Backend Setup

1. **Clone the repository** (if not already done):
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
pip install -r app/requirements.txt
```

5. **Install Tesseract OCR** (Optional but recommended):

   **Windows:**
   - Download from: https://github.com/UB-Mannheim/tesseract/wiki
   - Install to default location: `C:\Program Files\Tesseract-OCR\`
   - The app will auto-detect it

   **Linux (Ubuntu/Debian):**
   ```bash
   sudo apt-get update
   sudo apt-get install tesseract-ocr
   ```

   **macOS:**
   ```bash
   brew install tesseract
   ```

   **Note:** Tesseract is required for parsing LaTeX-generated PDFs (like Overleaf) or scanned/image-based resumes.

6. **Set up Supabase Database**:
   - Create a new Supabase project at https://supabase.com
   - Go to SQL Editor and run the SQL from `app/database/schema.sql`
   - Create a storage bucket named `resumes` (public access)

7. **Create `.env` file** in the project root:
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

# Test User (for testing without authentication)
TEST_USER_ID=test_user_001

# CORS Origins (comma-separated, optional)
CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:8000
```

8. **Run the application**:
```bash
python app/main.py
```

The application will:
- Start the FastAPI server at `http://127.0.0.1:8000`
- Serve the frontend at `http://127.0.0.1:8000/`
- Auto-open your browser (if configured)
- API documentation available at `http://127.0.0.1:8000/docs`

### Frontend Setup

The frontend is automatically served by FastAPI. No separate setup is required!

- **Main Application**: `http://127.0.0.1:8000/`
- **Resume Analysis**: `http://127.0.0.1:8000/resume-analysis.html`
- **Technical Interview**: `http://127.0.0.1:8000/technical-interview.html`

## 📡 API Endpoints

### Health & Configuration
- `GET /api/health` - Health check endpoint
- `GET /api/config` - Get frontend configuration (Supabase credentials)

### Profile Management
- `GET /api/profile/{user_id}` - Get user profile
- `POST /api/profile/` - Create user profile
- `PUT /api/profile/{user_id}` - Update user profile
- `POST /api/profile/{user_id}/upload-resume` - Upload and parse resume
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
- `POST /api/interview/technical` - Start technical interview session
- `POST /api/interview/technical/{session_id}/next-question` - Get next technical question
- `POST /api/interview/technical/{session_id}/submit-answer` - Submit technical answer
- `GET /api/interview/technical/{session_id}/feedback` - Get final feedback
- `POST /api/interview/technical/{session_id}/end` - End technical interview
- `POST /api/interview/speech-to-text` - Convert speech audio to text (Whisper)
- `GET /api/interview/text-to-speech` - Convert text to speech (TTS)

### Dashboard
- `GET /api/dashboard/performance/{user_id}` - Get performance dashboard data
- `GET /api/dashboard/trends/{user_id}` - Get trends and score progression data

### Testing
- `POST /api/test-resume-parse` - Test resume parser (development only)

### API Documentation
- `GET /docs` - Interactive Swagger UI documentation
- `GET /redoc` - ReDoc documentation

## 🗄️ Database Schema

The application uses Supabase (PostgreSQL) with the following main tables:

- **user_profiles** - User profile information and skills
- **interview_sessions** - Interview session metadata
- **interview_questions** - Generated interview questions
- **interview_answers** - User answers with AI evaluation scores
- **question_templates** - Admin-managed question templates

See `app/database/schema.sql` for the complete schema with Row Level Security policies.

## 🔧 Configuration

### Environment Variables

All configuration is done through environment variables in the `.env` file:

| Variable | Description | Required |
|----------|-------------|----------|
| `OPENAI_API_KEY` | OpenAI API key for AI features | Yes |
| `SUPABASE_URL` | Supabase project URL | Yes |
| `SUPABASE_KEY` | Supabase anon/public key | Yes |
| `SUPABASE_SERVICE_KEY` | Supabase service role key | Yes |
| `BACKEND_PORT` | Backend server port | No (default: 8000) |
| `ENVIRONMENT` | Environment (development/production) | No (default: development) |
| `TEST_USER_ID` | Test user ID for development | No |
| `CORS_ORIGINS` | Comma-separated CORS origins | No |

### CORS Configuration

CORS is automatically configured based on the `ENVIRONMENT` variable:
- **Development**: Allows all origins (`*`)
- **Production**: Uses `CORS_ORIGINS` from environment or defaults

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

### Manual Deployment

```bash
# Install dependencies
pip install -r app/requirements.txt

# Set environment variables
export OPENAI_API_KEY=your_key
export SUPABASE_URL=your_url
# ... etc

# Run with uvicorn
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

## 🛠️ Technologies Used

### Backend
- **FastAPI** - Modern Python web framework
- **Uvicorn** - ASGI server
- **Pydantic** - Data validation and settings
- **Supabase** - Database and storage
- **OpenAI** - AI question generation and evaluation
- **LangChain** - AI orchestration framework

### Frontend
- **HTML5/CSS3** - Structure and styling
- **Vanilla JavaScript (ES6+)** - Application logic
- **Chart.js** - Performance charts and analytics

### Resume Parsing
- **PyMuPDF (fitz)** - PDF text extraction
- **python-docx** - DOCX parsing
- **pdfplumber** - Advanced PDF parsing
- **pdfminer.six** - PDF text extraction fallback
- **pytesseract** - OCR for scanned/LaTeX PDFs
- **Pillow** - Image processing for OCR

### Database
- **Supabase (PostgreSQL)** - Primary database
- **Row Level Security (RLS)** - Data access control

## 📝 Development

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

## 🐛 Troubleshooting

### Common Issues

1. **"Supabase configuration missing"**
   - Ensure `.env` file exists in project root
   - Check that `SUPABASE_URL` and `SUPABASE_KEY` are set correctly

2. **"OpenAI API key not found"**
   - Set `OPENAI_API_KEY` in `.env` file
   - Restart the server after adding the key

3. **Resume parsing fails for LaTeX PDFs**
   - Install Tesseract OCR (see setup instructions)
   - Ensure Tesseract is in system PATH

4. **CORS errors**
   - Check `CORS_ORIGINS` in `.env`
   - In development, the app allows all origins by default

5. **Database connection errors**
   - Verify Supabase credentials
   - Check that database schema is set up correctly
   - Ensure RLS policies allow service role access

## 📄 License

This project is for educational purposes.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📧 Support

For issues and questions, please open an issue on the repository.

---

**Built with ❤️ using FastAPI, OpenAI, and Supabase**
