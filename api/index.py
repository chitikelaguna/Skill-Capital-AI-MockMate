"""
Vercel serverless function entry point for FastAPI
This file is used by Vercel to handle all API routes as serverless functions
"""

import sys
from pathlib import Path

# Add project root to Python path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Import the FastAPI app
from app.main import app

# Export both 'app' and 'handler' for Vercel compatibility
# Vercel's Python runtime may look for either variable
# The app is an ASGI application that Vercel should auto-detect
handler = app
# Also export as 'app' in case Vercel looks for that
__all__ = ['handler', 'app']

