"""
Configuration management module
"""

from .settings import Settings, get_settings

__all__ = ["Settings", "get_settings", "settings"]

# Export settings instance for backward compatibility
from .settings import settings

