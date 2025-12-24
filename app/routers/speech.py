"""
Speech-related endpoints for text-to-speech and speech-to-text functionality
"""

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Query, Body
from fastapi import Request
from fastapi.responses import StreamingResponse, Response
from supabase import Client
from app.db.client import get_supabase_client
from app.services.technical_interview_engine import technical_interview_engine
from app.utils.request_validator import validate_request_size
from app.schemas.interview import SpeechToTextResponse
from typing import Dict, Any
import logging
import tempfile
import os
import io
import traceback

logger = logging.getLogger(__name__)

router = APIRouter(tags=["speech"])


@router.post("/speech-to-text", response_model=SpeechToTextResponse)
async def speech_to_text(
    http_request: Request,
    audio: UploadFile = File(...),
    supabase: Client = Depends(get_supabase_client)
):
    """
    Convert speech audio to text using OpenAI Whisper
    """
    try:
        # Check if OpenAI is available
        if not technical_interview_engine.openai_available or technical_interview_engine.client is None:
            raise HTTPException(status_code=503, detail="Speech-to-text service is not available. OpenAI API key is required.")
        
        # Read audio content into memory
        content = await audio.read()
        
        # Use tempfile (has filesystem access)
        file_extension = os.path.splitext(audio.filename)[1] if audio.filename else ".webm"
        tmp_file_path = None
        
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as tmp_file:
                tmp_file.write(content)
                tmp_file_path = tmp_file.name
            
            # Transcribe using OpenAI Whisper
            with open(tmp_file_path, "rb") as audio_file:
                transcript = technical_interview_engine.client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    language="en"
                )
            
            text = transcript.text
            return {"text": text, "language": "en"}
            
        finally:
            # Clean up temporary file
            if tmp_file_path and os.path.exists(tmp_file_path):
                try:
                    os.unlink(tmp_file_path)
                except Exception as e:
                    logger.warning(f"[SPEECH][SPEECH-TO-TEXT] Could not delete temp file: {str(e)}")
        
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error converting speech to text: {str(e)}")


# OPTIONS endpoints removed - CORS is handled by FastAPI CORS middleware in app/main.py


@router.post("/text-to-speech", responses={200: {"content": {"audio/mpeg": {}}}})
async def text_to_speech(
    http_request: Request,
    request_body: Dict[str, Any] = Body(...),
    supabase: Client = Depends(get_supabase_client),
    _: None = Depends(validate_request_size)
):
    """
    Convert text to speech using OpenAI TTS
    Accepts: {"text": "question text"}
    Returns audio file as streaming response
    """
    try:
        text = request_body.get("text", "")
        
        # Check if OpenAI is available
        if not technical_interview_engine.openai_available or technical_interview_engine.client is None:
            logger.error("[SPEECH][TEXT-TO-SPEECH] TTS service unavailable: OpenAI client not initialized")
            raise HTTPException(
                status_code=503, 
                detail="Text-to-speech service is not available. OpenAI API key is required."
            )
        
        if not text or not text.strip():
            raise HTTPException(status_code=400, detail="text parameter is required and cannot be empty")
        
        # Truncate text to reasonable length (OpenAI TTS limit is 4096 chars, but we'll use 2000 for safety)
        text_to_speak = text.strip()[:2000]
        logger.info(f"[SPEECH][TEXT-TO-SPEECH] Generating TTS audio for text (length: {len(text_to_speak)} chars)")
        
        # Generate speech using OpenAI TTS
        try:
            response = technical_interview_engine.client.audio.speech.create(
                model="tts-1",
                voice="alloy",  # Options: alloy, echo, fable, onyx, nova, shimmer
                input=text_to_speak
            )
            
            # Get audio data
            audio_data = response.content
            
            if not audio_data or len(audio_data) == 0:
                logger.error("[SPEECH][TEXT-TO-SPEECH] TTS returned empty audio data")
                raise HTTPException(status_code=500, detail="TTS service returned empty audio data")
            
            logger.info(f"[SPEECH][TEXT-TO-SPEECH] TTS generated audio successfully (size: {len(audio_data)} bytes)")
            
            # Return audio as streaming response with proper CORS headers
            return StreamingResponse(
                io.BytesIO(audio_data),
                media_type="audio/mpeg",
                headers={
                    "Content-Disposition": "inline; filename=speech.mp3",
                    "Content-Type": "audio/mpeg",
                    "Content-Length": str(len(audio_data)),
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                    "Access-Control-Allow-Headers": "*",
                    "Accept-Ranges": "bytes"
                }
            )
        except Exception as tts_error:
            logger.error(f"[SPEECH][TEXT-TO-SPEECH] OpenAI TTS API error: {str(tts_error)}")
            raise HTTPException(
                status_code=500, 
                detail=f"Failed to generate speech: {str(tts_error)}"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[SPEECH][TEXT-TO-SPEECH] Unexpected error in text_to_speech: {str(e)}")
        import traceback
        logger.error(f"[SPEECH][TEXT-TO-SPEECH] Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error converting text to speech: {str(e)}")



@router.get("/text-to-speech", responses={200: {"content": {"audio/mpeg": {}}}})
async def text_to_speech_get(
    text: str = Query(..., description="Text to convert to speech")
):
    """
    Convert text to speech using OpenAI TTS (GET endpoint for URL-based access)
    Returns audio file as streaming response
    """
    try:
        # Check if OpenAI is available
        if not technical_interview_engine.openai_available or technical_interview_engine.client is None:
            logger.error("[SPEECH][TEXT-TO-SPEECH] TTS service unavailable: OpenAI client not initialized")
            raise HTTPException(
                status_code=503, 
                detail="Text-to-speech service is not available. OpenAI API key is required."
            )
        
        if not text or not text.strip():
            raise HTTPException(status_code=400, detail="text parameter is required and cannot be empty")
        
        # Decode URL-encoded text
        import urllib.parse
        decoded_text = urllib.parse.unquote(text).strip()
        
        # Validate text length (max 500 characters)
        if len(decoded_text) > 500:
            raise HTTPException(
                status_code=400, 
                detail=f"text parameter must be 500 characters or less. Received {len(decoded_text)} characters."
            )
        
        # Truncate to reasonable length (OpenAI TTS limit is 4096 chars, but we'll use 2000 for safety)
        text_to_speak = decoded_text[:2000]
        logger.info(f"[SPEECH][TEXT-TO-SPEECH] Generating TTS audio via GET (length: {len(text_to_speak)} chars)")
        
        # Generate speech using OpenAI TTS
        try:
            response = technical_interview_engine.client.audio.speech.create(
                model="tts-1",
                voice="alloy",
                input=text_to_speak
            )
            
            audio_data = response.content
            
            if not audio_data or len(audio_data) == 0:
                logger.error("[SPEECH][TEXT-TO-SPEECH] TTS returned empty audio data")
                raise HTTPException(status_code=500, detail="TTS service returned empty audio data")
            
            logger.info(f"[SPEECH][TEXT-TO-SPEECH] TTS generated audio successfully via GET (size: {len(audio_data)} bytes)")
            
            return StreamingResponse(
                io.BytesIO(audio_data),
                media_type="audio/mpeg",
                headers={
                    "Content-Disposition": "inline; filename=speech.mp3",
                    "Content-Type": "audio/mpeg",
                    "Content-Length": str(len(audio_data)),
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                    "Access-Control-Allow-Headers": "*",
                    "Accept-Ranges": "bytes"
                }
            )
        except Exception as tts_error:
            logger.error(f"[SPEECH][TEXT-TO-SPEECH] OpenAI TTS API error (GET): {str(tts_error)}")
            raise HTTPException(
                status_code=500, 
                detail=f"Failed to generate speech: {str(tts_error)}"
            )
        
    except Exception as e:
        logger.error(f"[SPEECH][TEXT-TO-SPEECH] Unexpected error in text_to_speech_get: {str(e)}")
        import traceback
        logger.error(f"[SPEECH][TEXT-TO-SPEECH] Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error converting text to speech: {str(e)}")


@router.post("/generate-audio", responses={200: {"content": {"audio/mpeg": {}}}})
async def generate_audio(
    http_request: Request,
    request_body: Dict[str, Any] = Body(...),
    supabase: Client = Depends(get_supabase_client),
    _: None = Depends(validate_request_size)
):
    """
    Generate audio from text (Backward compatibility wrapper for text-to-speech)
    Required to support existing frontend implementation.
    DELEGATES to text_to_speech implementation.
    """
    try:
        # Validate request body first
        if not request_body or "text" not in request_body:
            raise HTTPException(status_code=400, detail="text parameter is required")
            
        # Call the implementation directly
        # Note: We pass the exact same arguments to ensure identical behavior
        return await text_to_speech(http_request, request_body, supabase, _)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[SPEECH] Error in generate_audio wrapper: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


