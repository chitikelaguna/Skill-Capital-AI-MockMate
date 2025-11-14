"""
Skill Capital AI MockMate - Backend
FastAPI application entry point

Optimized for:
- Clean architecture
- Efficient CORS handling
- Proper error handling
- Scalable structure
- Static file serving for frontend
"""

import os
import webbrowser
from pathlib import Path
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from dotenv import load_dotenv

# Load environment variables with explicit path
# Note: Settings module already loads .env, but we ensure it's loaded here too
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH, override=True)
else:
    load_dotenv(override=True)

# Import routers (auth and admin removed - Student Dashboard only)
from app.routers import profile, interview, dashboard
# Temporary test router for parser verification
from app.routers import test_parser

# Import configuration
from app.config.settings import get_cors_origins, settings

# Import and configure Tesseract OCR at startup
from app.utils.resume_parser_util import configure_tesseract

# Get project root directory (parent of app/)
PROJECT_ROOT = Path(__file__).parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"

# Initialize FastAPI app
app = FastAPI(
    title="Skill Capital AI MockMate",
    description="Backend API for AI-powered interview preparation",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Configure Tesseract OCR at startup
@app.on_event("startup")
async def startup_event():
    """Initialize services on application startup"""
    print("[STARTUP] Configuring Tesseract OCR...")
    configure_tesseract()
    print("[STARTUP] Application startup complete.")

# Configure CORS with dynamic origins
# For development, allow all origins without credentials for maximum compatibility
cors_origins = get_cors_origins()
use_wildcard = "*" in cors_origins or settings.environment == "development"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if use_wildcard else cors_origins,
    allow_credentials=False,  # Set to False to allow "*" origin in development
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers (before static files to ensure API routes take precedence)
# Auth and Admin routers removed - Student Dashboard only
app.include_router(profile.router)
app.include_router(interview.router)
app.include_router(dashboard.router)

# Temporary test router for parser verification (will be removed after testing)
app.include_router(test_parser.router)

# Register API endpoints BEFORE static file serving to ensure they take precedence
# These endpoints must be registered before the catch-all route for static files
@app.get("/api/health")
async def health_check():
    """
    Health check endpoint for monitoring
    Time Complexity: O(1)
    Space Complexity: O(1)
    """
    return {
        "status": "healthy",
        "service": "Skill Capital AI MockMate Backend"
    }


@app.get("/api/config")
async def get_frontend_config():
    """
    Get frontend configuration (Supabase public credentials and test user ID)
    This endpoint exposes only public-safe credentials to the frontend
    Time Complexity: O(1)
    Space Complexity: O(1)
    """
    # Validate that Supabase credentials are set and not empty
    supabase_url = settings.supabase_url or ""
    supabase_key = settings.supabase_key or ""
    
    # Check if values are actually set (not just empty strings)
    if not supabase_url.strip() or not supabase_key.strip():
        # Log for debugging
        print(f"[API] /api/config - Missing credentials")
        print(f"[API] SUPABASE_URL: {'SET' if supabase_url.strip() else 'EMPTY'}")
        print(f"[API] SUPABASE_KEY: {'SET' if supabase_key.strip() else 'EMPTY'}")
        
        return {
            "error": "Supabase configuration missing",
            "message": "SUPABASE_URL and SUPABASE_KEY must be set in .env file. Please check your .env file in the project root.",
            "supabase_url": "",
            "supabase_anon_key": "",
            "api_base_url": f"http://127.0.0.1:{settings.backend_port}",
            "test_user_id": settings.test_user_id,
            "help": "Get your credentials from Supabase Dashboard → Settings → API"
        }
    
    # Log successful config (only URL preview for security)
    print(f"[API] /api/config - Returning configuration")
    print(f"[API] SUPABASE_URL: {supabase_url[:30]}...")
    print(f"[API] SUPABASE_KEY: {'SET' if supabase_key else 'EMPTY'}")
    print(f"[API] TEST_USER_ID: {settings.test_user_id}")
    
    return {
        "supabase_url": supabase_url,
        "supabase_anon_key": supabase_key,
        "api_base_url": f"http://127.0.0.1:{settings.backend_port}",
        "test_user_id": settings.test_user_id
    }

# Serve static files from frontend directory
if FRONTEND_DIR.exists():
    # Serve root - return index.html (must be after API routes)
    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def serve_index():
        """Serve frontend index.html at root"""
        index_path = FRONTEND_DIR / "index.html"
        if index_path.exists():
            return FileResponse(index_path, media_type="text/html")
        else:
            return HTMLResponse(
                content="<h1>Frontend Not Found</h1><p>index.html not found in frontend directory.</p>",
                status_code=404
            )
    
    # Serve resume analysis page
    @app.get("/resume-analysis.html", response_class=HTMLResponse, include_in_schema=False)
    async def serve_resume_analysis():
        """Serve resume analysis page"""
        analysis_path = FRONTEND_DIR / "resume-analysis.html"
        if analysis_path.exists():
            return FileResponse(analysis_path, media_type="text/html")
        else:
            return HTMLResponse(
                content="<h1>Resume Analysis Page Not Found</h1><p>resume-analysis.html not found in frontend directory.</p>",
                status_code=404
            )
    
    # Serve technical interview page
    @app.get("/technical-interview.html", response_class=HTMLResponse, include_in_schema=False)
    async def serve_technical_interview():
        """Serve technical interview page"""
        interview_path = FRONTEND_DIR / "technical-interview.html"
        if interview_path.exists():
            return FileResponse(interview_path, media_type="text/html")
        else:
            return HTMLResponse(
                content="<h1>Technical Interview Page Not Found</h1><p>technical-interview.html not found in frontend directory.</p>",
                status_code=404
            )
    
    # Serve static files (CSS, JS, etc.) - catch-all for frontend files
    # Note: FastAPI matches routes in order, and API routes from routers above
    # will be matched before this catch-all route
    @app.get("/{file_path:path}", include_in_schema=False)
    async def serve_static_files(request: Request, file_path: str):
        """
        Serve static frontend files (CSS, JS, etc.)
        API routes are handled by routers above and take precedence
        Time Complexity: O(1)
        Space Complexity: O(1)
        """
        # FastAPI should match API routes first, but add explicit check for safety
        # IMPORTANT: This catch-all route should NEVER catch API routes if they're properly registered
        # If we reach here for an API route, it means the route wasn't registered correctly
        path = request.url.path
        
        # Skip API routes - they should be handled by routers/endpoints defined above
        if path.startswith("/api/"):
            # This should not happen - API routes are registered before this catch-all
            # Return 404 with helpful message
            from fastapi import HTTPException
            raise HTTPException(
                status_code=404, 
                detail=f"API endpoint not found: {path}. Available endpoints: /api/test, /api/health, /api/config, /api/profile/*, /api/interview/*, /api/dashboard/*"
            )
        
        # Skip FastAPI docs routes
        if (path.startswith("/docs") or
            path.startswith("/redoc") or
            path == "/openapi.json"):
            # These should be handled by FastAPI automatically
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Not Found")
        
        # Build file path
        file_path_clean = file_path.lstrip("/")
        full_path = FRONTEND_DIR / file_path_clean
        
        # Security: Ensure file is within frontend directory
        try:
            full_path.resolve().relative_to(FRONTEND_DIR.resolve())
        except ValueError:
            # Path outside frontend directory - return 404
            return HTMLResponse(content="<h1>404 Not Found</h1>", status_code=404)
        
        # Check if file exists
        if full_path.exists() and full_path.is_file():
            # Determine content type based on extension
            if file_path_clean.endswith(".html"):
                return FileResponse(full_path, media_type="text/html")
            elif file_path_clean.endswith(".css"):
                return FileResponse(full_path, media_type="text/css")
            elif file_path_clean.endswith(".js"):
                return FileResponse(full_path, media_type="application/javascript")
            elif file_path_clean.endswith(".json"):
                return FileResponse(full_path, media_type="application/json")
            elif file_path_clean.endswith(".png"):
                return FileResponse(full_path, media_type="image/png")
            elif file_path_clean.endswith(".jpg") or file_path_clean.endswith(".jpeg"):
                return FileResponse(full_path, media_type="image/jpeg")
            elif file_path_clean.endswith(".svg"):
                return FileResponse(full_path, media_type="image/svg+xml")
            else:
                return FileResponse(full_path)
        else:
            # File not found - for SPA routing, serve index.html
            index_path = FRONTEND_DIR / "index.html"
            if index_path.exists():
                return FileResponse(index_path, media_type="text/html")
            else:
                return HTMLResponse(content="<h1>404 Not Found</h1>", status_code=404)
else:
    # Fallback if frontend directory doesn't exist
    @app.get("/")
    async def root():
        """
        Root endpoint - API information (fallback when frontend not found)
        Time Complexity: O(1)
        Space Complexity: O(1)
        """
        return {
            "message": "Skill Capital AI MockMate API",
            "status": "running",
            "version": "1.0.0",
            "docs": "/docs",
            "note": "Frontend directory not found. Please ensure frontend/ directory exists."
    }


if __name__ == "__main__":
    import uvicorn
    import threading
    import time
    
    # Auto-open browser after a short delay
    def open_browser():
        """Open browser after server starts"""
        time.sleep(1.5)  # Wait for server to start
        url = f"http://127.0.0.1:{settings.backend_port}"
        print(f"\n🌐 Opening browser at {url}")
        webbrowser.open(url)
    
    # Start browser opening in background thread
    browser_thread = threading.Thread(target=open_browser, daemon=True)
    browser_thread.start()
    
    print(f"\n🚀 Starting Skill Capital AI MockMate...")
    print(f"📡 Backend API: http://127.0.0.1:{settings.backend_port}")
    print(f"📚 API Docs: http://127.0.0.1:{settings.backend_port}/docs")
    print(f"🌐 Frontend: http://127.0.0.1:{settings.backend_port}/")
    print(f"\nPress CTRL+C to stop the server\n")
    
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=settings.backend_port,
        reload=True
    )
