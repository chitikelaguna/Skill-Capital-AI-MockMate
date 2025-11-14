/**
 * Technical Interview - Frontend JavaScript
 * Handles voice recording, audio playback, and interview flow
 */

// Configuration
const API_BASE = 'http://127.0.0.1:8000';
const TEST_USER_ID = 'test_user_001';

// State
let interviewSessionId = null;
let conversationHistory = [];
let isRecording = false;
let mediaRecorder = null;
let audioChunks = [];
let currentQuestion = null;
let interviewActive = false;

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    init();
});

async function init() {
    // Load config from backend
    try {
        const res = await fetch(`${API_BASE}/api/config`);
        const config = await res.json();
        if (config.test_user_id) {
            window.TEST_USER_ID = config.test_user_id;
        }
    } catch (e) {
        console.warn('Config load failed, using default');
    }

    // Setup event listeners
    setupEventListeners();
}

function setupEventListeners() {
    document.getElementById('startInterviewBtn').addEventListener('click', startInterview);
    document.getElementById('endInterviewBtn').addEventListener('click', endInterview);
    document.getElementById('voiceButton').addEventListener('click', toggleRecording);
    document.getElementById('restartInterviewBtn').addEventListener('click', () => {
        window.location.reload();
    });
}

async function startInterview() {
    const userId = window.TEST_USER_ID || TEST_USER_ID;
    
    console.log('[INTERVIEW] Starting interview for user:', userId);
    
    // Show loading
    document.getElementById('setupSection').classList.add('hidden');
    document.getElementById('interviewSection').classList.remove('hidden');
    document.getElementById('loadingMessage').classList.remove('hidden');
    document.getElementById('interviewStatus').textContent = 'Starting Interview...';
    document.getElementById('interviewStatus').classList.add('active');
    
    // Clear conversation container
    const container = document.getElementById('conversationContainer');
    container.innerHTML = '<div class="loading" id="loadingMessage">Initializing interview...</div>';

    try {
        // Start technical interview session
        console.log('[INTERVIEW] Calling API:', `${API_BASE}/api/interview/technical`);
        const response = await fetch(`${API_BASE}/api/interview/technical`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId })
        });

        console.log('[INTERVIEW] Response status:', response.status);
        
        if (!response.ok) {
            const errorText = await response.text();
            console.error('[INTERVIEW] Error response:', errorText);
            throw new Error(`Failed to start interview: ${response.status} - ${errorText}`);
        }

        const data = await response.json();
        console.log('[INTERVIEW] Session data:', data);
        
        interviewSessionId = data.session_id;
        interviewActive = true;
        conversationHistory = data.conversation_history || [];

        // Update status
        document.getElementById('interviewStatus').textContent = 'Interview Active';
        
        // Clear loading message
        const loadingMsg = document.getElementById('loadingMessage');
        if (loadingMsg) {
            loadingMsg.classList.add('hidden');
        }
        
        // Clear container and prepare for messages
        container.innerHTML = '';

        // Display conversation history if any
        if (conversationHistory.length > 0) {
            conversationHistory.forEach(msg => {
                displayMessage(msg.role, msg.content, msg.audio_url);
            });
        }

        // Get first question from AI
        console.log('[INTERVIEW] Getting first question...');
        await getNextQuestion();

    } catch (error) {
        console.error('[INTERVIEW] Start interview error:', error);
        const errorMsg = error.message || 'Failed to start interview. Please try again.';
        showError(errorMsg);
        
        // Show setup section again
        document.getElementById('setupSection').classList.remove('hidden');
        document.getElementById('interviewSection').classList.add('hidden');
        document.getElementById('interviewStatus').textContent = 'Ready to Start';
        document.getElementById('interviewStatus').classList.remove('active');
    }
}

async function getNextQuestion() {
    if (!interviewSessionId) {
        console.error('[INTERVIEW] No session ID available');
        return;
    }

    try {
        console.log('[INTERVIEW] Getting next question for session:', interviewSessionId);
        
        // Hide loading message if still visible
        const loadingMsg = document.getElementById('loadingMessage');
        if (loadingMsg) {
            loadingMsg.classList.add('hidden');
        }
        
        // Get next question from AI
        const response = await fetch(`${API_BASE}/api/interview/technical/${interviewSessionId}/next-question`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });

        console.log('[INTERVIEW] Next question response status:', response.status);
        
        if (!response.ok) {
            const errorText = await response.text();
            console.error('[INTERVIEW] Error getting question:', errorText);
            throw new Error(`Failed to get next question: ${response.status} - ${errorText}`);
        }

        const data = await response.json();
        console.log('[INTERVIEW] Question data:', data);
        
        if (data.interview_completed) {
            // Interview is complete
            console.log('[INTERVIEW] Interview completed');
            await completeInterview();
            return;
        }

        if (!data.question) {
            throw new Error('No question received from server');
        }

        currentQuestion = data.question;
        conversationHistory.push({
            role: 'ai',
            content: data.question,
            audio_url: data.audio_url
        });

        // Display question
        displayMessage('ai', data.question, data.audio_url);

        // Play audio if available
        if (data.audio_url) {
            playAudio(data.audio_url);
        }

        // Update status
        document.getElementById('voiceStatus').textContent = 'Click the microphone to record your answer';
        document.getElementById('voiceButton').classList.remove('listening');

    } catch (error) {
        console.error('[INTERVIEW] Get question error:', error);
        showError(`Failed to get question: ${error.message || 'Please try again.'}`);
    }
}

async function toggleRecording() {
    if (!interviewActive) return;

    if (!isRecording) {
        startRecording();
    } else {
        stopRecording();
    }
}

async function startRecording() {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        mediaRecorder = new MediaRecorder(stream);
        audioChunks = [];

        mediaRecorder.ondataavailable = (event) => {
            audioChunks.push(event.data);
        };

        mediaRecorder.onstop = async () => {
            const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
            await processAudioAnswer(audioBlob);
            
            // Stop all tracks
            stream.getTracks().forEach(track => track.stop());
        };

        mediaRecorder.start();
        isRecording = true;
        document.getElementById('voiceButton').classList.add('recording');
        document.getElementById('voiceStatus').textContent = 'Recording... Click again to stop';
    } catch (error) {
        console.error('Error accessing microphone:', error);
        showError('Microphone access denied. Please allow microphone access and try again.');
    }
}

function stopRecording() {
    if (mediaRecorder && isRecording) {
        mediaRecorder.stop();
        isRecording = false;
        document.getElementById('voiceButton').classList.remove('recording');
        document.getElementById('voiceStatus').textContent = 'Processing your answer...';
    }
}

async function processAudioAnswer(audioBlob) {
    try {
        // Convert audio to text using speech-to-text endpoint
        const formData = new FormData();
        formData.append('audio', audioBlob, 'recording.webm');

        const sttResponse = await fetch(`${API_BASE}/api/interview/speech-to-text`, {
            method: 'POST',
            body: formData
        });

        if (!sttResponse.ok) {
            throw new Error('Failed to convert speech to text');
        }

        const sttData = await sttResponse.json();
        const userAnswer = sttData.text;

        // Display user's answer
        displayMessage('user', userAnswer);

        // Submit answer to backend
        await submitAnswer(userAnswer);

    } catch (error) {
        console.error('Process audio error:', error);
        showError('Failed to process your answer. Please try again.');
        document.getElementById('voiceStatus').textContent = 'Click the microphone to record your answer';
    }
}

async function submitAnswer(answer) {
    if (!interviewSessionId || !currentQuestion) return;

    try {
        const response = await fetch(`${API_BASE}/api/interview/technical/${interviewSessionId}/submit-answer`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                question: currentQuestion,
                answer: answer
            })
        });

        if (!response.ok) {
            throw new Error('Failed to submit answer');
        }

        const data = await response.json();
        
        // Update conversation history
        conversationHistory.push({
            role: 'user',
            content: answer
        });

        // Display AI response if any
        if (data.ai_response) {
            conversationHistory.push({
                role: 'ai',
                content: data.ai_response,
                audio_url: data.audio_url
            });
            displayMessage('ai', data.ai_response, data.audio_url);
            
            if (data.audio_url) {
                playAudio(data.audio_url);
            }
        }

        // Check if interview is complete
        if (data.interview_completed) {
            await completeInterview();
        } else {
            // Get next question after a short delay
            setTimeout(() => {
                getNextQuestion();
            }, 2000);
        }

        document.getElementById('voiceStatus').textContent = 'Click the microphone to record your answer';

    } catch (error) {
        console.error('Submit answer error:', error);
        showError('Failed to submit answer. Please try again.');
    }
}

async function completeInterview() {
    interviewActive = false;
    document.getElementById('interviewStatus').textContent = 'Interview Completed';
    document.getElementById('interviewStatus').classList.remove('active');
    document.getElementById('interviewStatus').classList.add('completed');
    document.getElementById('interviewSection').classList.add('hidden');
    document.getElementById('feedbackSection').classList.remove('hidden');

    // Generate feedback
    await generateFeedback();
}

async function generateFeedback() {
    if (!interviewSessionId) return;

    try {
        const response = await fetch(`${API_BASE}/api/interview/technical/${interviewSessionId}/feedback`, {
            method: 'GET'
        });

        if (!response.ok) {
            throw new Error('Failed to generate feedback');
        }

        const feedback = await response.json();

        // Display feedback
        document.getElementById('overallScore').textContent = Math.round(feedback.overall_score || 0);
        
        const strengthsList = document.getElementById('strengthsList');
        strengthsList.innerHTML = (feedback.strengths || []).map(s => `<li>${s}</li>`).join('');

        const improvementsList = document.getElementById('improvementsList');
        improvementsList.innerHTML = (feedback.areas_for_improvement || []).map(a => `<li>${a}</li>`).join('');

        const recommendationsList = document.getElementById('recommendationsList');
        recommendationsList.innerHTML = (feedback.recommendations || []).map(r => `<li>${r}</li>`).join('');

        document.getElementById('feedbackSummary').textContent = feedback.feedback_summary || 'No summary available.';

        document.getElementById('feedbackLoading').classList.add('hidden');
        document.getElementById('feedbackContent').classList.remove('hidden');

    } catch (error) {
        console.error('Generate feedback error:', error);
        document.getElementById('feedbackLoading').textContent = 'Failed to generate feedback.';
    }
}

function displayMessage(role, content, audioUrl = null) {
    const container = document.getElementById('conversationContainer');
    if (!container) {
        console.error('[INTERVIEW] Conversation container not found');
        return;
    }
    
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;

    const header = role === 'ai' ? 'AI Interviewer' : 'You';
    messageDiv.innerHTML = `
        <div class="message-header">${header}</div>
        <div class="message-content">${content}</div>
        ${audioUrl ? `<audio class="audio-player" controls src="${audioUrl}"></audio>` : ''}
    `;

    container.appendChild(messageDiv);
    container.scrollTop = container.scrollHeight;
    
    console.log('[INTERVIEW] Message displayed:', role, content.substring(0, 50) + '...');
}

function playAudio(audioUrl) {
    if (!audioUrl) return;
    
    // Construct full URL if relative
    const fullUrl = audioUrl.startsWith('http') ? audioUrl : `${API_BASE}${audioUrl}`;
    
    const audio = new Audio(fullUrl);
    audio.play().catch(error => {
        console.error('Error playing audio:', error);
    });
}

function showError(message) {
    const container = document.getElementById('conversationContainer');
    const errorDiv = document.createElement('div');
    errorDiv.className = 'error-message';
    errorDiv.textContent = message;
    container.appendChild(errorDiv);
    container.scrollTop = container.scrollHeight;
}

async function endInterview() {
    if (confirm('Are you sure you want to end the interview? Your progress will be saved.')) {
        interviewActive = false;
        
        if (isRecording) {
            stopRecording();
        }

        if (interviewSessionId) {
            try {
                await fetch(`${API_BASE}/api/interview/technical/${interviewSessionId}/end`, {
                    method: 'POST'
                });
            } catch (error) {
                console.error('Error ending interview:', error);
            }
        }

        await completeInterview();
    }
}

