"""
Application settings and configuration management
Uses pydantic-settings for type-safe environment variable handling
"""

import os
from pathlib import Path
from typing import Optional, Union, Any
from pydantic_settings import BaseSettings
from pydantic import Field, field_validator, model_validator, computed_field
from dotenv import load_dotenv

# Ensure .env is loaded before Settings initialization
# Get project root (parent of app/)
# Path resolution: app/config/settings.py -> app/config/ -> app/ -> project_root/
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ENV_PATH = PROJECT_ROOT / ".env"

# Load .env file with explicit path
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH, override=True)
else:
    # Try current directory as fallback
    current_dir_env = Path.cwd() / ".env"
    if current_dir_env.exists():
        load_dotenv(dotenv_path=current_dir_env, override=True)
    else:
        # Last resort: try default location
        load_dotenv(override=True)

class Settings(BaseSettings):
    """
    Application settings loaded from environment variables
    Time Complexity: O(1) - Settings initialization
    Space Complexity: O(1) - Constant space for settings
    """
    
    # OpenAI Configuration
    openai_api_key: str = Field(default="", env="OPENAI_API_KEY")
    
    # Supabase Configuration
    supabase_url: str = Field(default="", env="SUPABASE_URL")
    supabase_key: str = Field(default="", env="SUPABASE_KEY")  # Anon key
    supabase_service_key: str = Field(default="", env="SUPABASE_SERVICE_KEY")
    
    # Database Configuration (Optional)
    database_url: Optional[str] = Field(default=None, env="DATABASE_URL")
    
    # Backend Configuration
    backend_port: int = Field(default=8000, env="BACKEND_PORT")
    environment: str = Field(default="development", env="ENVIRONMENT")
    frontend_url: Optional[str] = Field(default=None, env="FRONTEND_URL")
    tech_backend_url: Optional[str] = Field(default=None, env="TECH_BACKEND_URL")  # Backend URL for technical interview audio generation
    
    # CORS Configuration - Use computed field to avoid pydantic-settings JSON parsing
    @computed_field
    @property
    def cors_origins(self) -> list[str]:
        """Get CORS origins as a list, parsing from environment variable"""
        
        # Read directly from environment to avoid pydantic-settings JSON parsing
        cors_val = os.getenv('CORS_ORIGINS')
        
        if cors_val:
            # Remove any trailing backticks or whitespace
            cors_val = cors_val.rstrip('`').strip()
            if cors_val:
                # Parse comma-separated values
                parsed = [origin.strip() for origin in cors_val.split(",") if origin.strip()]
                if parsed:
                    return parsed
        
        # Return defaults - include common development ports
        default_origins = [
            "http://localhost:3000",
            "http://127.0.0.1:5500",
            "http://localhost:5500",
            "http://localhost:5173",  
            "http://127.0.0.1:5173",
            "http://localhost:8000",
            "http://127.0.0.1:8000",  
            "http://localhost:8080",
            "http://127.0.0.1:8080"
        ]
        return default_origins
    
    # AI & API Configuration (Optional)
    langchain_api_key: Optional[str] = Field(default=None, env="LANGCHAIN_API_KEY")
    whisper_api_key: Optional[str] = Field(default=None, env="WHISPER_API_KEY")
    
    # Auth & Security (Optional)
    jwt_secret: Optional[str] = Field(default=None, env="JWT_SECRET")
    access_token_expire_minutes: int = Field(default=60, env="ACCESS_TOKEN_EXPIRE_MINUTES")
    
    # Email Configuration (Optional)
    email_server: Optional[str] = Field(default=None, env="EMAIL_SERVER")
    email_port: Optional[int] = Field(default=None, env="EMAIL_PORT")
    email_user: Optional[str] = Field(default=None, env="EMAIL_USER")
    email_password: Optional[str] = Field(default=None, env="EMAIL_PASSWORD")
    email_from: Optional[str] = Field(default=None, env="EMAIL_FROM")
    
    # Logging Configuration
    log_level: str = Field(default="INFO", env="LOG_LEVEL")
    
    # Storage Configuration (Optional)
    storage_type: str = Field(default="supabase", env="STORAGE_TYPE")
    
    # Rate Limiting (Optional)
    rate_limit_enabled: bool = Field(default=False, env="RATE_LIMIT_ENABLED")
    rate_limit_requests: int = Field(default=100, env="RATE_LIMIT_REQUESTS")
    rate_limit_window: int = Field(default=60, env="RATE_LIMIT_WINDOW")
    
    # LangChain Tracing (Optional)
    langchain_tracing_v2: bool = Field(default=False, env="LANGCHAIN_TRACING_V2")
    langchain_endpoint: Optional[str] = Field(default=None, env="LANGCHAIN_ENDPOINT")
    langchain_project: Optional[str] = Field(default=None, env="LANGCHAIN_PROJECT")
    
    class Config:
        # Use explicit path to .env file
        env_file = str(ENV_PATH) if ENV_PATH.exists() else str(Path.cwd() / ".env")
        env_file_encoding = "utf-8"
        case_sensitive = False
        # Allow extra fields to be ignored (for flexibility)
        extra = "ignore"
        # Don't parse list fields as JSON automatically
        json_schema_extra = {
            "properties": {
                "cors_origins": {
                    "type": "array",
                    "items": {"type": "string"}
                }
            }
        }


# Create global settings instance
settings = Settings()


def get_settings() -> Settings:
    """
    Get application settings instance
    Time Complexity: O(1)
    Space Complexity: O(1)
    """
    return settings


def get_cors_origins() -> list[str]:
    """
    Get CORS allowed origins
    Time Complexity: O(1)
    Space Complexity: O(n) where n = number of origins
    """
    # cors_origins is already a list after validation
    origins = list(settings.cors_origins) if settings.cors_origins else []
    
    # Add frontend URL if set
    if settings.frontend_url:
        origins.append(settings.frontend_url)
    
    # Remove duplicates while preserving order
    seen = set()
    unique_origins = []
    for origin in origins:
        if origin not in seen:
            seen.add(origin)
            unique_origins.append(origin)
    
    # If no origins specified, allow all in development (but without credentials)
    if not unique_origins and settings.environment == "development":
        return ["*"]
    
    return unique_origins

