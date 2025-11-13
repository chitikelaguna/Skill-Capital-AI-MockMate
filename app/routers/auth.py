"""
Authentication routes
Handles user signup, login, and logout operations
"""

from fastapi import APIRouter, HTTPException, Depends
from supabase import Client
from app.db.client import get_supabase_client
from app.schemas.user import AuthRequest, AuthResponse
from app.utils.exceptions import ValidationError, DatabaseError

router = APIRouter(prefix="/api/auth", tags=["authentication"])


@router.post("/signup", response_model=AuthResponse)
async def signup(
    auth_data: AuthRequest, 
    supabase: Client = Depends(get_supabase_client)
):
    """
    User signup endpoint
    Time Complexity: O(1) - Single database operation
    Space Complexity: O(1) - Returns user object
    Optimization: Direct Supabase auth call, no additional queries
    """
    try:
        response = supabase.auth.sign_up({
            "email": auth_data.email,
            "password": auth_data.password
        })
        
        if response.user is None:
            raise ValidationError("Failed to create user")
        
        # Extract user data safely
        user_data = {
            "id": response.user.id,
            "email": response.user.email
        }
        
        return AuthResponse(
            access_token=response.session.access_token if response.session else "",
            refresh_token=response.session.refresh_token if response.session else None,
            user=user_data,
            message="User created successfully"
        )
    except ValidationError:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Signup failed: {str(e)}")


@router.post("/login", response_model=AuthResponse)
async def login(
    auth_data: AuthRequest, 
    supabase: Client = Depends(get_supabase_client)
):
    """
    User login endpoint
    Time Complexity: O(1) - Single authentication operation
    Space Complexity: O(1) - Returns session and user data
    Optimization: Direct Supabase auth call
    """
    try:
        response = supabase.auth.sign_in_with_password({
            "email": auth_data.email,
            "password": auth_data.password
        })
        
        if response.user is None or response.session is None:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        
        return AuthResponse(
            access_token=response.session.access_token,
            refresh_token=response.session.refresh_token,
            user={
                "id": response.user.id,
                "email": response.user.email
            },
            message="Login successful"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Login failed: {str(e)}")


@router.post("/logout")
async def logout(supabase: Client = Depends(get_supabase_client)):
    """
    User logout endpoint
    Time Complexity: O(1) - Single auth operation
    Space Complexity: O(1) - Constant space
    """
    try:
        supabase.auth.sign_out()
        return {"message": "Logged out successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Logout failed: {str(e)}")
