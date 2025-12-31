"""
Skill Capital AI MockMate - Backend
FastAPI application entry point

Optimized for:
- Clean architecture
- Efficient CORS handling
- Proper error handling
- Scalable structure
- RESTful API service
"""

import os
import sys
import logging
import webbrowser
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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

# Lifespan event handler (replaces deprecated @app.on_event)
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize services on application startup and cleanup on shutdown"""
    # Startup
    
    # Validate Supabase configuration at startup (non-blocking for Vercel)
    logger.info("[STARTUP] Validating Supabase configuration...")
    try:
        from app.db.client import validate_supabase_config, get_supabase_client
        
        # Validate config (non-raising for Vercel compatibility)
        config_valid = validate_supabase_config(raise_on_missing=False)
        if not config_valid:
            logger.warning("[STARTUP] ⚠️  Supabase configuration incomplete - some operations may fail")
        
        # Test Supabase connection on startup
        logger.info("[STARTUP] Testing Supabase connection...")
        
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
    # Check database connection status
    db_status = "unknown"
    try:
        from app.db.client import get_supabase_client
        if settings.supabase_url and settings.supabase_service_key:
            supabase = get_supabase_client()
            # Perform a simple query: select 1 row from user_profiles
            supabase.table("user_profiles").select("id").limit(1).execute()
            db_status = "connected"
        else:
            db_status = "not_configured"
    except Exception:
        db_status = "disconnected"

    return {
        "status": "healthy",
        "service": "Skill Capital AI MockMate Backend",
        "database": db_status
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
    Get API configuration (Supabase public credentials)
    This endpoint exposes only public-safe credentials for client applications
    Time Complexity: O(1)
    Space Complexity: O(1)
    """
    # Validate that Supabase credentials are set and not empty
    supabase_url = settings.supabase_url or ""
    supabase_key = settings.supabase_key or ""
    
    # Determine API base URL dynamically based on environment
    # Priority: TECH_BACKEND_URL > Backend host:port
    api_base_url = None
    
    # Priority 1: Use TECH_BACKEND_URL if explicitly set
    if settings.tech_backend_url:
        api_base_url = settings.tech_backend_url.rstrip('/')
    else:
        # Local/Render: Always use backend address
        # CRITICAL: Always use 127.0.0.1:8000 for local, or configured host/port
        if settings.environment == "development":
             api_base_url = f"http://127.0.0.1:{settings.backend_port}"
        else:
             # For production (Render), rely on TECH_BACKEND_URL or external URL
             # If not set, default to relative path behavior (empty string)
             api_base_url = settings.tech_backend_url or ""

    
    # Check if values are actually set (not just empty strings)
    if not supabase_url.strip() or not supabase_key.strip():
        return {
            "error": "Supabase configuration missing",
            "message": "SUPABASE_URL and SUPABASE_KEY must be set in .env file. Please check your .env file in the project root.",
            "supabase_url": "",
            "supabase_anon_key": "",
            "api_base_url": api_base_url,
            "tech_backend_url": settings.tech_backend_url or api_base_url,
            "help": "Get your credentials from Supabase Dashboard → Settings → API"
        }
    
    return {
        "supabase_url": supabase_url,
        "supabase_anon_key": supabase_key,
        "api_base_url": api_base_url,
        "tech_backend_url": settings.tech_backend_url or api_base_url
    }

# Root endpoint - API information
@app.get("/")
async def root():
    """
    Root endpoint - API information
    Time Complexity: O(1)
    Space Complexity: O(1)
    """
    return {
        "message": "Skill Capital AI MockMate API",
        "status": "running",
        "version": "1.0.0",
        "docs": "/docs",
        "api_base": "/api",
        "note": "This is a backend-only API service. Frontend is hosted separately."
    }


if __name__ == "__main__":
    import uvicorn
    import threading
    import time
    from app.utils.url_utils import get_api_base_url
    
    # Auto-open browser to API docs after a short delay (only in development)
    def open_browser():
        """Open browser to API docs after server starts (development only)"""
        if settings.environment == "development":
            time.sleep(1.5)  # Wait for server to start
            # Use dynamic URL instead of hardcoded localhost
            base_url = get_api_base_url()
            docs_url = f"{base_url}/docs"
            logger.info(f" Opening browser at {docs_url}")
            try:
                webbrowser.open(docs_url)
            except Exception as e:
                logger.warning(f"Could not open browser: {str(e)}")
    
    # Start browser opening in background thread (only in development)
    if settings.environment == "development":
        browser_thread = threading.Thread(target=open_browser, daemon=True)
        browser_thread.start()
    
    # Use dynamic URL for logging
    base_url = get_api_base_url()
    logger.info(f" Starting Skill Capital AI MockMate Backend...")
    logger.info(f" Backend API: {base_url}")
    logger.info(f" API Docs: {base_url}/docs")
    logger.info(f" OpenAPI Schema: {base_url}/openapi.json")
    logger.info("Press CTRL+C to stop the server")
    
    # Determine host based on environment
    # For local development, bind to 127.0.0.1 explicitly
    # For production/Vercel, use 0.0.0.0 to accept connections from all interfaces
    if settings.environment == "development":
        server_host = "127.0.0.1"  # Explicit localhost binding for development
    else:
        server_host = "0.0.0.0"  # Accept all interfaces for production
    
    logger.info(f"Server binding to: {server_host}:{settings.backend_port}")
    
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
