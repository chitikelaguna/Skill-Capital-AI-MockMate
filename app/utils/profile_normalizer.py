"""
Profile data normalization utilities
Handles JSONB field validation, normalization, and error prevention
"""

import json
import logging
from typing import Dict, Any, Optional, List, Union
from datetime import datetime

logger = logging.getLogger(__name__)


def normalize_jsonb_field(value: Any, field_name: str, default: List = None) -> Union[List, Dict, None]:
    """
    Normalize a JSONB field value to ensure it's a Python list/dict, not a JSON string.
    
    Args:
        value: The value to normalize (can be list, dict, string, None)
        field_name: Name of the field for logging
        default: Default value if normalization fails (defaults to empty list)
    
    Returns:
        Normalized Python list or dict, or default if normalization fails
    """
    if default is None:
        default = []
    
    # If already a list or dict, return as-is
    if isinstance(value, (list, dict)):
        return value
    
    # If None, return default
    if value is None:
        return default
    
    # If it's a string, try to parse as JSON
    if isinstance(value, str):
        # Check if it's an empty string
        if not value.strip():
            return default
        
        try:
            parsed = json.loads(value)
            # Ensure parsed result is list or dict
            if isinstance(parsed, (list, dict)):
                logger.debug(f"[NORMALIZE] Successfully parsed JSONB field '{field_name}' from string")
                return parsed
            else:
                logger.warning(f"[NORMALIZE] JSONB field '{field_name}' parsed to non-list/dict type: {type(parsed)}, using default")
                return default
        except json.JSONDecodeError as e:
            logger.warning(f"[NORMALIZE] Failed to parse JSONB field '{field_name}' as JSON: {str(e)}, using default")
            return default
    
    # Unknown type, return default
    logger.warning(f"[NORMALIZE] JSONB field '{field_name}' has unexpected type: {type(value)}, using default")
    return default


def normalize_skills_field(value: Any) -> List[str]:
    """
    Normalize skills field to ensure it's a list of strings.
    
    Args:
        value: The skills value (can be list, string, None)
    
    Returns:
        List of strings, empty list if normalization fails
    """
    if value is None:
        return []
    
    if isinstance(value, list):
        # Ensure all items are strings
        return [str(item) for item in value if item]
    
    if isinstance(value, str):
        # Try to parse as JSON array, or split by comma
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(item) for item in parsed if item]
        except json.JSONDecodeError:
            # Not JSON, try comma-separated
            return [s.strip() for s in value.split(',') if s.strip()]
    
    return []


def normalize_datetime_field(value: Any) -> Optional[datetime]:
    """
    Normalize datetime field to ensure it's a datetime object or None.
    
    Args:
        value: The datetime value (can be datetime, string, None)
    
    Returns:
        datetime object or None
    """
    if value is None:
        return None
    
    if isinstance(value, datetime):
        return value
    
    if isinstance(value, str):
        # Try to parse common datetime formats
        try:
            # ISO format
            return datetime.fromisoformat(value.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            logger.debug(f"[NORMALIZE] Could not parse datetime string: {value}")
            return None
    
    return None


def validate_and_normalize_profile_data(profile_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate and normalize profile data before database insertion.
    Ensures JSONB fields are Python lists/dicts, not JSON strings.
    
    Args:
        profile_data: Raw profile data dictionary
    
    Returns:
        Normalized profile data dictionary ready for Supabase insertion
    """
    normalized = profile_data.copy()
    
    # Normalize JSONB fields - ensure they're Python lists/dicts, not strings
    jsonb_fields = ['projects', 'education', 'work_experience', 'certifications']
    for field in jsonb_fields:
        if field in normalized:
            normalized[field] = normalize_jsonb_field(
                normalized[field], 
                field_name=field,
                default=[]
            )
            logger.debug(f"[VALIDATE] Normalized JSONB field '{field}': type={type(normalized[field])}")
    
    # Normalize skills (TEXT[] array)
    if 'skills' in normalized:
        normalized['skills'] = normalize_skills_field(normalized['skills'])
    
    # Normalize datetime fields
    if 'created_at' in normalized:
        normalized['created_at'] = normalize_datetime_field(normalized['created_at'])
    if 'updated_at' in normalized:
        normalized['updated_at'] = normalize_datetime_field(normalized['updated_at'])
    
    return normalized


def prepare_profile_for_pydantic(profile: Dict[str, Any]) -> Dict[str, Any]:
    """
    Prepare profile data for Pydantic UserProfileResponse validation.
    Ensures all fields are in the correct format expected by the schema.
    Converts datetime objects to ISO format strings for JSON serialization.
    
    Args:
        profile: Raw profile dictionary from database
    
    Returns:
        Profile dictionary ready for Pydantic validation
    """
    prepared = profile.copy()
    
    # Ensure JSONB fields are lists/dicts (not strings)
    jsonb_fields = ['projects', 'education', 'work_experience', 'certifications']
    for field in jsonb_fields:
        if field in prepared:
            prepared[field] = normalize_jsonb_field(prepared[field], field_name=field, default=[])
    
    # Ensure skills is a list of strings
    if 'skills' in prepared:
        prepared['skills'] = normalize_skills_field(prepared['skills'])
    
    # CRITICAL FIX: Convert datetime objects to ISO format strings for JSON serialization
    # Pydantic/JSON cannot serialize datetime objects directly - they must be strings
    if 'created_at' in prepared:
        dt_value = normalize_datetime_field(prepared['created_at'])
        if dt_value is not None:
            # Convert datetime to ISO format string
            prepared['created_at'] = dt_value.isoformat()
        else:
            prepared['created_at'] = None
    
    if 'updated_at' in prepared:
        dt_value = normalize_datetime_field(prepared['updated_at'])
        if dt_value is not None:
            # Convert datetime to ISO format string
            prepared['updated_at'] = dt_value.isoformat()
        else:
            prepared['updated_at'] = None
    
    # Ensure required fields exist (no hard-coded defaults)
    if 'id' not in prepared:
        prepared['id'] = prepared.get('user_id', '')
    if 'email' not in prepared:
        prepared['email'] = ''
    if 'user_id' not in prepared:
        prepared['user_id'] = ''
    
    # Ensure optional fields are None if missing (no hard-coded defaults)
    optional_fields = ['name', 'experience_level', 'resume_url', 'access_role']
    for field in optional_fields:
        if field not in prepared:
            prepared[field] = None
    
    # CRITICAL: Do NOT set default access_role - use None if not present
    # User explicitly requested no default data
    
    return prepared

