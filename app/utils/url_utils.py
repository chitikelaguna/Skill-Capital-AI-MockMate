"""
URL utility functions for Vercel and localhost compatibility
"""

import os
from typing import Optional
from app.config.settings import settings


def get_api_base_url(request: Optional[object] = None) -> str:
    """
    Get the API base URL dynamically based on environment.
    Works for both localhost and Vercel deployments.
    
    Priority:
    1. TECH_BACKEND_URL (explicitly configured backend URL for audio generation)
    2. VERCEL_URL (Vercel automatically provides this)
    3. FRONTEND_URL (manually configured)
    4. Request host (from incoming request)
    5. Localhost fallback (development only)
    
    Args:
        request: FastAPI Request object (optional)
    
    Returns:
        API base URL string (e.g., "https://app.vercel.app" or "http://localhost:8000")
    """
    # Priority 1: TECH_BACKEND_URL (explicitly configured for audio generation)
    if settings.tech_backend_url:
        tech_url = settings.tech_backend_url.strip()
        if tech_url:
            # Ensure it has protocol
            if not tech_url.startswith("http"):
                return f"https://{tech_url}"
            return tech_url
    
    # Priority 2: Vercel URL (automatically set by Vercel)
    vercel_url = os.getenv("VERCEL_URL")
    if vercel_url:
        # Vercel provides just the domain (e.g., "app.vercel.app")
        # We need to add https://
        if not vercel_url.startswith("http"):
            return f"https://{vercel_url}"
        return vercel_url
    
    # Also check settings
    if settings.vercel_url:
        vercel_url = settings.vercel_url
        if not vercel_url.startswith("http"):
            return f"https://{vercel_url}"
        return vercel_url
    
    # Priority 3: Configured frontend URL
    if settings.frontend_url:
        return settings.frontend_url
    
    # Priority 4: Try to get from request
    if request and hasattr(request, "url"):
        try:
            scheme = request.url.scheme
            host = request.url.hostname
            port = request.url.port
            
            # Build URL
            if port and port not in [80, 443]:
                return f"{scheme}://{host}:{port}"
            else:
                return f"{scheme}://{host}"
        except Exception:
            pass
    
    # Priority 5: Fallback to localhost (development only)
    return f"http://127.0.0.1:{settings.backend_port}"

