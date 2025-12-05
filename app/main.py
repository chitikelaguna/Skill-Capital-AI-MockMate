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
import sys
import logging
import webbrowser
from pathlib import Path
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from dotenv import load_dotenv

# Configure logging
logger = logging.getLogger(__name__)

# Add project root to Python path to fix imports when running directly
# This allows the script to work whether run as: python app/main.py or python -m app.main
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Load environment variables with explicit path
# Note: Settings module already loads .env, but we ensure it's loaded here too
ENV_PATH = PROJECT_ROOT / ".env"
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH, override=True)
else:
    load_dotenv(override=True)

# Import routers
from app.routers import profile, interview, dashboard
from app.routers.speech import router as speech_router

# Import configuration
from app.config.settings import get_cors_origins, settings


# Get project root directory (parent of app/)
PROJECT_ROOT = Path(__file__).parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"

# Lifespan event handler (replaces deprecated @app.on_event)
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize services on application startup and cleanup on shutdown"""
    # Startup
    
    # Test Supabase connection on startup
    logger.info("[STARTUP] Testing Supabase connection...")
    try:
        from app.db.client import get_supabase_client
        
        # Check if credentials are set
        if not settings.supabase_url or not settings.supabase_service_key:
            logger.warning("[STARTUP] ⚠️  WARNING: Supabase credentials not configured!")
            logger.warning("[STARTUP]    Please set SUPABASE_URL and SUPABASE_SERVICE_KEY in .env file")
        else:
            # Test connection
            try:
                supabase = get_supabase_client()
                # Simple test query
                test_response = supabase.table("user_profiles").select("id").limit(1).execute()
                logger.info("[STARTUP] ✅ Supabase connection successful!")
                logger.info(f"[STARTUP]    URL: {settings.supabase_url[:30]}...")
            except Exception as conn_error:
                logger.error(f"[STARTUP] ❌ Supabase connection failed: {str(conn_error)}")
                logger.error("[STARTUP]    Please check your SUPABASE_URL and SUPABASE_SERVICE_KEY")
    except Exception as e:
        logger.warning(f"[STARTUP] ⚠️  Could not test Supabase connection: {str(e)}")
    
    logger.info("[STARTUP] Application startup complete.")
    
    yield  # Application runs here
    
    # Shutdown (if needed)
    logger.info("[SHUTDOWN] Application shutting down...")

# Initialize FastAPI app with lifespan
app = FastAPI(
    title="Skill Capital AI MockMate",
    description="Backend API for AI-powered interview preparation",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# Custom exception handler to standardize error responses to {'error': 'message'} format
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """
    Custom exception handler to standardize all HTTPException responses
    to {'error': 'message'} format instead of FastAPI's default {'detail': 'message'}
    """
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail}
    )

# Register health check endpoints FIRST (before routers) to ensure they're matched
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


@app.get("/api/health/database", tags=["health"])
async def database_health_check():
    """
    Database connection health check endpoint
    Tests Supabase connection by performing a simple query
    Returns: {status: 'connected'} when Supabase works, {status: 'failed'} when there's an issue
    Time Complexity: O(1)
    Space Complexity: O(1)
    """
    from app.db.client import get_supabase_client
    
    try:
        # Check if environment variables are loaded
        if not settings.supabase_url:
            return {
                "status": "failed",
                "error": "SUPABASE_URL environment variable is not set"
            }
        
        if not settings.supabase_service_key:
            return {
                "status": "failed",
                "error": "SUPABASE_SERVICE_KEY environment variable is not set"
            }
        
        # Test connection by performing a simple query
        try:
            supabase = get_supabase_client()
            
            # Perform a simple query: select 1 row from user_profiles
            test_response = supabase.table("user_profiles").select("id").limit(1).execute()
            
            # If we get here, connection is working
            return {
                "status": "connected",
                "message": "Supabase connection successful",
                "tables_tested": 1
            }
            
        except ValueError as ve:
            # Configuration error (missing credentials, invalid URL, etc.)
            return {
                "status": "failed",
                "error": f"Configuration error: {str(ve)}"
            }
        except Exception as conn_error:
            # Connection or query error
            return {
                "status": "failed",
                "error": f"Connection failed: {str(conn_error)}"
            }
            
    except Exception as e:
        # Unexpected error
        return {
            "status": "failed",
            "error": f"Health check failed: {str(e)}"
        }

# Configure CORS with dynamic origins
# For development, allow all origins without credentials for maximum compatibility
cors_origins = get_cors_origins()
use_wildcard = "*" in cors_origins or settings.environment == "development"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if use_wildcard else cors_origins,
    allow_credentials=False,  # Set to False to allow "*" origin in development
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],  # Explicitly include OPTIONS for CORS preflight
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=3600,  # Cache preflight requests for 1 hour
)

# Include routers (before static files to ensure API routes take precedence)
app.include_router(profile.router)
app.include_router(interview.router)
app.include_router(dashboard.router)
app.include_router(speech_router, prefix="/api/interview", tags=["speech"])


@app.get("/api/config")
async def get_frontend_config(request: Request):
    from app.utils.url_utils import get_api_base_url
    """
    Get frontend configuration (Supabase public credentials)
    This endpoint exposes only public-safe credentials to the frontend
    Time Complexity: O(1)
    Space Complexity: O(1)
    """
    # Validate that Supabase credentials are set and not empty
    supabase_url = settings.supabase_url or ""
    supabase_key = settings.supabase_key or ""
    
    # Determine API base URL dynamically based on environment
    # CRITICAL: Always return the BACKEND URL, not the frontend URL
    # Priority: VERCEL_URL > Backend host:port (for local dev)
    # NOTE: We do NOT use FRONTEND_URL because it might be wrong (e.g., localhost:3000)
    api_base_url = None
    
    if settings.vercel_url:
        # Vercel provides VERCEL_URL (e.g., "your-app.vercel.app")
        # On Vercel, frontend and backend are on the same domain
        api_base_url = f"https://{settings.vercel_url}"
    else:
        # Local development: Always use backend URL (127.0.0.1:8000)
        # CRITICAL: Always use 127.0.0.1:8000, never use request port (could be 3000, etc.)
        # Don't use request.host, request.url.hostname, or settings.frontend_url
        # because those might be the frontend port (3000) or wrong hostname
        api_base_url = f"http://127.0.0.1:{settings.backend_port}"
    
    # Check if values are actually set (not just empty strings)
    if not supabase_url.strip() or not supabase_key.strip():
        return {
            "error": "Supabase configuration missing",
            "message": "SUPABASE_URL and SUPABASE_KEY must be set in .env file. Please check your .env file in the project root.",
            "supabase_url": "",
            "supabase_anon_key": "",
            "api_base_url": api_base_url,
            "help": "Get your credentials from Supabase Dashboard → Settings → API"
        }
    
    return {
        "supabase_url": supabase_url,
        "supabase_anon_key": supabase_key,
        "api_base_url": api_base_url
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
    
    # Serve interview page
    @app.get("/interview.html", response_class=HTMLResponse, include_in_schema=False)
    async def serve_interview():
        """Serve interview page"""
        interview_path = FRONTEND_DIR / "interview.html"
        if interview_path.exists():
            return FileResponse(interview_path, media_type="text/html")
        else:
            return HTMLResponse(
                content="<h1>Interview Page Not Found</h1><p>interview.html not found in frontend directory.</p>",
                status_code=404
            )
    
    # Serve coding interview page
    @app.get("/coding-interview.html", response_class=HTMLResponse, include_in_schema=False)
    async def serve_coding_interview():
        """Serve coding interview page"""
        coding_path = FRONTEND_DIR / "coding-interview.html"
        if coding_path.exists():
            return FileResponse(coding_path, media_type="text/html")
        else:
            return HTMLResponse(
                content="<h1>Coding Interview Page Not Found</h1><p>coding-interview.html not found in frontend directory.</p>",
                status_code=404
            )

    @app.get("/coding-result.html", response_class=HTMLResponse, include_in_schema=False)
    async def serve_coding_result():
        """Serve coding result page"""
        result_path = FRONTEND_DIR / "coding-result.html"
        if result_path.exists():
            return FileResponse(result_path, media_type="text/html")
        else:
            return HTMLResponse(
                content="<h1>Coding Result Page Not Found</h1><p>coding-result.html not found in frontend directory.</p>",
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
                detail=f"API endpoint not found: {path}. Available endpoints: /api/test, /api/health, /api/health/database, /api/config, /api/profile/*, /api/interview/*, /api/dashboard/*"
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
    from app.utils.url_utils import get_api_base_url
    
    # Auto-open browser after a short delay (only in development)
    def open_browser():
        """Open browser after server starts (development only)"""
        if settings.environment == "development":
            time.sleep(1.5)  # Wait for server to start
            # Use dynamic URL instead of hardcoded localhost
            base_url = get_api_base_url()
            logger.info(f"🌐 Opening browser at {base_url}")
            try:
                webbrowser.open(base_url)
            except Exception as e:
                logger.warning(f"Could not open browser: {str(e)}")
    
    # Start browser opening in background thread (only in development)
    if settings.environment == "development":
        browser_thread = threading.Thread(target=open_browser, daemon=True)
        browser_thread.start()
    
    # Use dynamic URL for logging
    base_url = get_api_base_url()
    logger.info(f"🚀 Starting Skill Capital AI MockMate...")
    logger.info(f"📡 Backend API: {base_url}")
    logger.info(f"📚 API Docs: {base_url}/docs")
    logger.info(f"🌐 Frontend: {base_url}/")
    logger.info("Press CTRL+C to stop the server")
    
    # Determine host based on environment
    # For local development, bind to 127.0.0.1 explicitly
    # For production/Vercel, use 0.0.0.0 to accept connections from all interfaces
    if settings.environment == "development":
        server_host = "127.0.0.1"  # Explicit localhost binding for development
    else:
        server_host = "0.0.0.0"  # Accept all interfaces for production
    
    logger.info(f"🔧 Server binding to: {server_host}:{settings.backend_port}")
    
    # For reload to work properly, use app as import string
    # When reload=True, uvicorn needs the app as an import string, not the object
    if settings.environment == "development":
        uvicorn.run(
            "app.main:app",  # Use import string for reload to work
            host=server_host, 
            port=settings.backend_port,
            reload=True,
            log_level="info"
        )
    else:
        uvicorn.run(
            app,  # Use app object when not using reload
            host=server_host, 
            port=settings.backend_port,
            reload=False,
            log_level="info"
        )
