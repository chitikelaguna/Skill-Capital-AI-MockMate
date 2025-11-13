"""
File utility functions for file operations
"""

import os
import tempfile
from pathlib import Path
from typing import Tuple, Optional


ALLOWED_FILE_EXTENSIONS = {'.pdf', '.docx', '.doc'}


def validate_file_type(file_extension: str) -> bool:
    """
    Validate if file extension is allowed
    Time Complexity: O(1) - Set lookup
    Space Complexity: O(1) - Constant space
    Optimization: Uses set for O(1) lookup instead of list
    """
    return file_extension.lower() in ALLOWED_FILE_EXTENSIONS


def extract_file_extension(filename: str) -> str:
    """
    Extract file extension from filename
    Time Complexity: O(1) - Path operation
    Space Complexity: O(1) - Returns extension string
    """
    return Path(filename).suffix.lower()


async def save_temp_file(file_content: bytes, file_extension: str) -> str:
    """
    Save file content to temporary file
    Time Complexity: O(n) where n = file size (write operation)
    Space Complexity: O(n) - Temporary file on disk
    Returns: Path to temporary file
    """
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=file_extension, mode='wb')
    try:
        temp_file.write(file_content)
        temp_file.flush()  # Ensure data is written to disk
        os.fsync(temp_file.fileno())  # Force write to disk
        return temp_file.name
    finally:
        temp_file.close()


def cleanup_temp_file(file_path: str) -> None:
    """
    Delete temporary file
    Time Complexity: O(1) - File deletion
    Space Complexity: O(1) - No additional space
    """
    try:
        if os.path.exists(file_path):
            os.unlink(file_path)
    except Exception:
        # Silently fail if file doesn't exist or can't be deleted
        pass

