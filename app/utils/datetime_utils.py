"""
DateTime utility functions for consistent date handling
"""

from datetime import datetime
from typing import Optional


def parse_datetime(date_str: str) -> datetime:
    """
    Parse datetime string to datetime object
    Handles multiple formats including ISO format with/without timezone
    Time Complexity: O(1) - String parsing
    Space Complexity: O(1) - Returns single datetime object
    """
    if not date_str:
        return datetime.now()
    
    try:
        # Handle ISO format with 'Z' timezone
        if isinstance(date_str, str) and date_str.endswith('Z'):
            date_str = date_str.replace('Z', '+00:00')
        return datetime.fromisoformat(date_str)
    except (ValueError, AttributeError):
        # Fallback to current time if parsing fails
        return datetime.now()


def format_datetime(dt: datetime, format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
    """
    Format datetime object to string
    Time Complexity: O(1) - String formatting
    Space Complexity: O(1) - Returns formatted string
    """
    return dt.strftime(format_str)


def get_current_timestamp() -> datetime:
    """
    Get current UTC timestamp
    Time Complexity: O(1)
    Space Complexity: O(1)
    """
    return datetime.now()

