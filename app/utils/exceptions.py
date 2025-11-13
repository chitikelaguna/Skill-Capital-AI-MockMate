"""
Custom exception classes for better error handling
Time Complexity: O(1) - Exception creation
Space Complexity: O(1) - Constant space
"""

from typing import Optional, Dict, Any


class AppException(Exception):
    """
    Base exception class for application errors
    Time Complexity: O(1)
    Space Complexity: O(1)
    """
    def __init__(self, message: str, status_code: int = 500, details: Optional[Dict[str, Any]] = None):
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)


class ValidationError(AppException):
    """
    Exception for validation errors
    Time Complexity: O(1)
    Space Complexity: O(1)
    """
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, status_code=400, details=details)


class NotFoundError(AppException):
    """
    Exception for resource not found errors
    Time Complexity: O(1)
    Space Complexity: O(1)
    """
    def __init__(self, resource: str, identifier: Optional[str] = None):
        message = f"{resource} not found"
        if identifier:
            message += f": {identifier}"
        super().__init__(message, status_code=404)


class DatabaseError(AppException):
    """
    Exception for database operation errors
    Time Complexity: O(1)
    Space Complexity: O(1)
    """
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, status_code=500, details=details)

