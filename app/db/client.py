"""
Supabase database client management
Optimized with singleton pattern to reuse connections
"""

from supabase import create_client, Client
from typing import Optional
from app.config.settings import settings


# Singleton pattern for database client
_supabase_client: Optional[Client] = None
_supabase_anon_client: Optional[Client] = None


def get_supabase_client() -> Client:
    """
    Get or create Supabase client instance (service role)
    Uses singleton pattern to reuse connection
    Time Complexity: O(1) - Returns cached instance or creates once
    Space Complexity: O(1) - Single client instance
    Optimization: Singleton pattern prevents multiple client creation
    """
    global _supabase_client
    
    if _supabase_client is None:
        if not settings.supabase_url or not settings.supabase_service_key:
            raise ValueError(
                "Supabase URL and Service Key must be set in environment variables"
            )
        _supabase_client = create_client(
            settings.supabase_url, 
            settings.supabase_service_key
        )
    
    return _supabase_client


def get_supabase_client_anon() -> Client:
    """
    Get or create Supabase client with anon key (for frontend use)
    Time Complexity: O(1)
    Space Complexity: O(1)
    Optimization: Singleton pattern with separate anon client
    """
    global _supabase_anon_client
    
    if _supabase_anon_client is None:
        if not settings.supabase_url or not settings.supabase_key:
            raise ValueError(
                "Supabase URL and Anon Key must be set in environment variables"
            )
        _supabase_anon_client = create_client(
            settings.supabase_url, 
            settings.supabase_key
        )
    
    return _supabase_anon_client