"""
Supabase database client management
Optimized with singleton pattern to reuse connections
"""

from supabase import create_client, Client
from typing import Optional
from app.config.settings import settings
from app.utils.exceptions import ConfigurationError
import logging

logger = logging.getLogger(__name__)

# Singleton pattern for database client
_supabase_client: Optional[Client] = None
_supabase_anon_client: Optional[Client] = None
_config_validated: bool = False


def validate_supabase_config(raise_on_missing: bool = False) -> bool:
    """
    Validate Supabase configuration at startup
    Logs presence/absence of required environment variables
    
    Args:
        raise_on_missing: If True, raise ConfigurationError when required keys are missing.
                         If False (default), only log warnings
    
    Returns:
        bool: True if all required keys are present, False otherwise
    
    Time Complexity: O(1)
    Space Complexity: O(1)
    """
    global _config_validated
    
    if _config_validated:
        return True
    
    # Check for required configuration
    supabase_url_present = bool(settings.supabase_url)
    supabase_key_present = bool(settings.supabase_key)  # Anon key
    supabase_service_key_present = bool(settings.supabase_service_key)
    
    # Log configuration status
    logger.info("[SUPABASE CONFIG] Configuration validation:")
    logger.info(f"[SUPABASE CONFIG]   SUPABASE_URL: {'✓ Present' if supabase_url_present else '✗ Missing'}")
    logger.info(f"[SUPABASE CONFIG]   SUPABASE_KEY (anon): {'✓ Present' if supabase_key_present else '✗ Missing'}")
    logger.info(f"[SUPABASE CONFIG]   SUPABASE_SERVICE_KEY: {'✓ Present' if supabase_service_key_present else '✗ Missing'}")
    
    # Check if any required key is missing
    missing_keys = []
    if not supabase_url_present:
        missing_keys.append("SUPABASE_URL")
    if not supabase_service_key_present:
        missing_keys.append("SUPABASE_SERVICE_KEY")
    # Note: SUPABASE_KEY (anon) is optional for service role operations
    
    if missing_keys:
        error_msg = f"Missing required Supabase configuration: {', '.join(missing_keys)}"
        logger.error(f"[SUPABASE CONFIG] {error_msg}")
    if missing_keys:
        error_msg = f"Missing required Supabase configuration: {', '.join(missing_keys)}"
        logger.error(f"[SUPABASE CONFIG] {error_msg}")
        
        if raise_on_missing:
            raise ConfigurationError(
                error_msg,
                details={"missing_keys": missing_keys}
            )
        
        _config_validated = True
        return False
    
    logger.info("[SUPABASE CONFIG] ✓ All required Supabase configuration present")
    _config_validated = True
    return True


def get_supabase_client() -> Client:
    """
    Get or create Supabase client instance (service role)
    Uses singleton pattern to reuse connection
    Time Complexity: O(1) - Returns cached instance or creates once
    Space Complexity: O(1) - Single client instance
    Optimization: Singleton pattern prevents multiple client creation
    """
    global _supabase_client
    
    # Log which client type is being used (service role)
    logger.debug("[SUPABASE CLIENT] Using service role client (bypasses RLS)")
    
    if _supabase_client is None:
        # Validate configuration
        if not settings.supabase_url:
            raise ValueError(
                "SUPABASE_URL environment variable is not set. "
                "Please add it to your .env file: SUPABASE_URL=https://your-project.supabase.co"
            )
        if not settings.supabase_service_key:
            raise ValueError(
                "SUPABASE_SERVICE_KEY environment variable is not set. "
                "Please add it to your .env file. "
                "You can find it in Supabase Dashboard → Settings → API → service_role key"
            )
        
        # Validate URL format
        if not settings.supabase_url.startswith("http"):
            raise ValueError(
                f"Invalid SUPABASE_URL format: {settings.supabase_url}. "
                "URL should start with https://"
            )
        
        try:
            _supabase_client = create_client(
                settings.supabase_url, 
                settings.supabase_service_key
            )
        except Exception as e:
            raise ValueError(
                f"Failed to create Supabase client: {str(e)}. "
                "Please verify your SUPABASE_URL and SUPABASE_SERVICE_KEY are correct."
            ) from e
    
    return _supabase_client


def get_supabase_client_anon() -> Client:
    """
    Get or create Supabase client with anon key (for frontend use)
    Time Complexity: O(1)
    Space Complexity: O(1)
    Optimization: Singleton pattern with separate anon client
    """
    global _supabase_anon_client
    
    # Log which client type is being used (anon key - respects RLS)
    logger.debug("[SUPABASE CLIENT] Using anon key client (respects RLS)")
    
    if _supabase_anon_client is None:
        # Validate configuration
        if not settings.supabase_url:
            raise ValueError(
                "SUPABASE_URL environment variable is not set. "
                "Please add it to your .env file: SUPABASE_URL=https://your-project.supabase.co"
            )
        if not settings.supabase_key:
            raise ValueError(
                "SUPABASE_KEY environment variable is not set. "
                "Please add it to your .env file. "
                "You can find it in Supabase Dashboard → Settings → API → anon/public key"
            )
        
        # Validate URL format
        if not settings.supabase_url.startswith("http"):
            raise ValueError(
                f"Invalid SUPABASE_URL format: {settings.supabase_url}. "
                "URL should start with https://"
            )
        
        try:
            _supabase_anon_client = create_client(
                settings.supabase_url, 
                settings.supabase_key
            )
        except Exception as e:
            raise ValueError(
                f"Failed to create Supabase anon client: {str(e)}. "
                "Please verify your SUPABASE_URL and SUPABASE_KEY are correct."
            ) from e
    
    return _supabase_anon_client