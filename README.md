# Skill Capital AI MockMate

A full-stack application for AI-powered interview preparation using FastAPI, HTML/CSS/JavaScript, Supabase, and LangChain with OpenAI.

## Project Structure

```
AI_Interview_Prep/
├── backend/
│   ├── main.py              # FastAPI application entry point
│   ├── config.py            # Environment variable configuration
│   ├── requirements.txt     # Python dependencies
│   └── .env.example         # Example environment variables file
├── frontend/
│   ├── index.html           # Main HTML file
│   ├── styles.css           # CSS styles
│   └── app.js               # JavaScript application logic
└── README.md                # This file
```

## Features

- ✅ FastAPI backend with REST API endpoints
- ✅ HTML/CSS/JavaScript frontend
- ✅ **Supabase Authentication** (Signup/Login)
- ✅ **User Profile Management** with database storage
- ✅ **Resume Upload** to Supabase Storage (PDF/DOCX)
- ✅ **Automatic Skill Extraction** from resumes using PyMuPDF/python-docx
- ✅ **Experience Level Detection** from resume text
- ✅ **Interview Setup** with role and experience level selection
- ✅ **Dynamic Topic Generation** based on role, experience, and user skills
- ✅ **AI Question Generation** using OpenAI and LangChain (10-15 questions)
- ✅ **Question Storage** in database with session management
- ✅ **Text-Based Mock Interview** with chat interface
- ✅ **Real-time Answer Evaluation** using OpenAI (4 scoring dimensions)
- ✅ **Question-by-Question Scoring** displayed after each answer
- ✅ **Timed Interview Mode** with countdown timer (60 seconds per question)
- ✅ **Automatic Timeout Handling** - moves to next question when time expires
- ✅ **Response Time Tracking** - stored and included in AI evaluation
- ✅ **AI Evaluation & Feedback Engine** - comprehensive post-interview analysis
- ✅ **Weighted Category Scoring** - Clarity, Accuracy, Confidence, Communication
- ✅ **Personalized Recommendations** - AI-generated learning suggestions
- ✅ **Performance Dashboard** - track interview history and progress
- ✅ **Score Trend Charts** - visualize performance over time using Chart.js
- ✅ **Skills Analysis** - identify top 3 strong skills and weak areas
- ✅ **Resume Summary** - quick view of profile and skills
- ✅ **Admin Panel** - comprehensive admin dashboard for instructors
- ✅ **Student Management** - view all students' interview results in table format
- ✅ **Analytics Dashboard** - charts for score distribution, weaknesses, and role statistics
- ✅ **Question Template Management** - add, edit, and delete interview question templates
- ✅ **Resume-Based Dynamic Interview** - personalized questions based on uploaded resume
- ✅ **Resume Keyword Extraction** - extracts technologies, tools, job titles, and projects
- ✅ **Context-Aware Question Generation** - AI generates questions referencing specific resume content
- ✅ **Multiple Interview Modes** - Text Mode, Timed Mode, and Auto Mode
- ✅ **Auto Mode** - Random mix of HR, Technical, and Problem-solving questions
- ✅ **Deployment Ready** - Configurations for Vercel (frontend), Render/Railway (backend)
- ✅ Environment variable configuration
- ✅ CORS middleware for frontend-backend communication

## Setup Instructions

### Prerequisites

- Python 3.8 or higher
- pip (Python package manager)
- A web browser
- OpenAI API key (for future AI features)
- Supabase account (for future database/auth features)
- **Tesseract OCR** (optional but recommended for LaTeX/scanned PDF resume parsing)

### Backend Setup

1. Navigate to the backend directory:
```bash
cd backend
```

2. Create a virtual environment (recommended):
```bash
python -m venv venv
```

3. Activate the virtual environment:
   - On Windows:
   ```bash
   venv\Scripts\activate
   ```
   - On macOS/Linux:
   ```bash
   source venv/bin/activate
   ```

4. Install dependencies:
```bash
pip install -r requirements.txt
```

5. **Install Tesseract OCR** (Required for OCR fallback when parsing LaTeX-generated or scanned PDFs):

   **Windows:**
   - Download the installer from: https://github.com/UB-Mannheim/tesseract/wiki
   - Run the installer and install to the default location: `C:\Program Files\Tesseract-OCR\`
   - The application will automatically detect Tesseract at this location
   - If installed elsewhere, the app will try to find it automatically

   **Linux (Ubuntu/Debian):**
   ```bash
   sudo apt-get update
   sudo apt-get install tesseract-ocr
   ```

   **macOS:**
   ```bash
   brew install tesseract
   ```

   **Note:** Tesseract OCR is optional but highly recommended. Without it, the application cannot parse LaTeX-generated PDFs (like those from Overleaf) or scanned/image-based resumes. The application will automatically detect and configure Tesseract if installed.

6. Create a `.env` file in the backend directory:
```bash
# Copy the example file
cp env.example .env
# Or on Windows PowerShell:
copy env.example .env
```

7. Edit the `.env` file and add your API keys:
```
OPENAI_API_KEY=your_openai_api_key_here
SUPABASE_URL=your_supabase_project_url
SUPABASE_KEY=your_supabase_anon_key
SUPABASE_SERVICE_KEY=your_supabase_service_role_key
```

8. Run the backend server:
```bash
python main.py
```

The backend will be available at `http://localhost:8000`

### Frontend Setup

1. Navigate to the frontend directory:
```bash
cd frontend
```

2. Open `index.html` in a web browser, or use a local server:

   **Option 1: Using Python's built-in server**
   ```bash
   python -m http.server 5500
   ```
   Then open `http://localhost:5500` in your browser.

   **Option 2: Using VS Code Live Server extension**
   - Install the "Live Server" extension
   - Right-click on `index.html` and select "Open with Live Server"

   **Option 3: Direct file opening**
   - Simply open `index.html` in your browser (may have CORS limitations)

## Testing the Connection

1. Start the backend server (see Backend Setup step 7)
2. Open the frontend in a browser
3. Click the "Test Backend Connection" button
4. You should see a success message if the connection is working

## API Endpoints

### Health Check
- `GET /api/health` - Check backend health status

### Connection Test
- `GET /api/test` - Test frontend-backend communication

### Authentication
- `POST /api/auth/signup` - User registration
- `POST /api/auth/login` - User login
- `POST /api/auth/logout` - User logout

### Profile
- `GET /api/profile/{user_id}` - Get user profile
- `POST /api/profile/` - Create user profile
- `PUT /api/profile/{user_id}` - Update user profile
- `POST /api/profile/{user_id}/upload-resume` - Upload and parse resume

### Interview
- `POST /api/interview/setup` - Setup interview and generate topics
- `POST /api/interview/generate` - Generate interview questions using AI
- `POST /api/interview/start` - Start mock interview session
- `POST /api/interview/submit-answer` - Submit answer and get AI evaluation
- `POST /api/interview/evaluate` - Generate comprehensive evaluation report after interview
- `GET /api/interview/session/{session_id}/question/{question_number}` - Get specific question
- `GET /api/interview/session/{session_id}/next-question/{current_question_number}` - Get next question
- `GET /api/interview/session/{session_id}/questions` - Get all questions for a session
- `GET /api/interview/roles` - Get available roles
- `GET /api/interview/experience-levels` - Get experience levels

### Dashboard
- `GET /api/dashboard/performance/{user_id}` - Get performance dashboard data
- `GET /api/dashboard/trends/{user_id}` - Get trends and score progression data

### Admin
- `GET /api/admin/students` - Get all students' interview results
- `GET /api/admin/analytics` - Get analytics data (scores, weaknesses, etc.)
- `GET /api/admin/questions` - Get all question templates
- `POST /api/admin/questions` - Create a new question template
- `PUT /api/admin/questions/{template_id}` - Update a question template
- `DELETE /api/admin/questions/{template_id}` - Delete a question template

### Root
- `GET /` - API information

## Development

### Backend Development
- Main application: `backend/main.py`
- Configuration: `backend/config.py`
- Add new endpoints in `main.py`

### Frontend Development
- HTML: `frontend/index.html`
- Styles: `frontend/styles.css`
- JavaScript: `frontend/app.js`
- API base URL is configured in `app.js` (default: `http://localhost:8000`)

## Next Steps

- [x] Implement Supabase authentication
- [x] Add resume upload and parsing
- [x] Add user profile management
- [x] Add interview setup with topic generation
- [x] Add OpenAI integration with LangChain for interview question generation
- [x] Create interview session and question storage
- [x] Build text-based mock interview interface
- [x] Implement real-time answer evaluation with scoring
- [x] Add timed interview mode with countdown
- [x] Build AI evaluation and feedback engine
- [x] Create performance dashboard with charts
- [x] Add skills analysis and resume summary
- [x] Build admin panel with student management
- [x] Add analytics dashboard with charts
- [x] Implement question template management
- [x] Integrate resume context into question generation
- [x] Add interview mode selection (Text, Timed, Auto)
- [x] Implement Auto Mode with random question mix
- [x] Create deployment configurations
- [ ] Add interview review and replay functionality
- [ ] Implement proper admin authentication

## Technologies Used

- **Backend**: FastAPI, Python
- **Frontend**: HTML5, CSS3, JavaScript (ES6+)
- **Database/Auth**: Supabase (Authentication & PostgreSQL)
- **Storage**: Supabase Storage (for resume files)
- **Resume Parsing**: PyMuPDF (for PDF), python-docx (for DOCX)
- **AI**: LangChain, OpenAI API (GPT-3.5-turbo for question generation)
- **Charts**: Chart.js (for analytics and trends)
- **Environment Management**: python-dotenv
- **Deployment**: Vercel (frontend), Render/Railway (backend)

## Documentation

For detailed deployment instructions, see [DEPLOYMENT.md](DEPLOYMENT.md)

## License

This project is for educational purposes.

