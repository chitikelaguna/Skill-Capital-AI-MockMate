/**
 * HR Interview - Frontend JavaScript
 * Handles voice recording, audio playback, and interview flow
 * 
 * NOTE: This file requires api-config.js to be loaded first
 * api-config.js provides: getApiBase(), ensureApiBaseReady(), API_BASE
 * 
 * VERSION: 2.0 - Custom Modal Implementation (2025-01-12)
 * 
 * FIX: Ensured clean file start (no BOM), fixed DOMContentLoaded syntax error
 * The "Unexpected token ':'" error on Vercel was caused by missing document.addEventListener
 * wrapper around the DOMContentLoaded arrow function, which made the parser see invalid syntax
 */
// ✅ CRITICAL: Top-level console.log for Vercel build verification - proves file parsed successfully
// This MUST execute if the file is parsed correctly - if you don't see this, the file failed to parse
console.log("[HR INTERVIEW] JS parsed and executing");
console.log("HR Interview JS loaded on Vercel");
console.log("[HR INTERVIEW] ✅ HR JS LOADED - File is being served");

// Build verification log (dev-only)
if (typeof console !== 'undefined' && console.debug) {
    console.debug('[HR INTERVIEW] HR script loaded - Build verification');
}
console.log('[HR INTERVIEW] Script loaded - Version 2.0 with Custom Modal');

// State
let currentUserId = null;
let interviewSessionId = null;
let conversationHistory = [];
let isRecording = false;
let mediaRecorder = null;
let audioChunks = [];
let currentQuestion = null;
let interviewActive = false;
let currentAudio = null; // Track current audio playback to prevent overlap
let isAudioPlaying = false; // Track if audio is currently playing
let hrAudioQueue = []; // Queue for HR interview audio (follow-up → question sequence)
let currentHRAudio = null; // Global HR audio manager - ONLY ONE audio can exist at a time

// Simple FIFO queue for HR interview audio to ensure sequential playback
function enqueueHRAudio(audioUrlOrText) {
    if (!audioUrlOrText) {
        return;
    }
    console.log('[HR INTERVIEW TTS] Enqueue audio:', String(audioUrlOrText).substring(0, 80) + '...');
    hrAudioQueue.push(audioUrlOrText);

    // If nothing is currently playing, start immediately
    if (!isAudioPlaying) {
        playNextFromHRAudio();
    }
}

function playNextFromHRAudio() {
    // ✅ CRITICAL: Check both isAudioPlaying AND currentHRAudio to ensure no overlap
    if (isAudioPlaying || currentHRAudio !== null) {
        console.log('[HR INTERVIEW TTS] ⏸️ Cannot play next audio - current audio still active');
        console.debug('[HR INTERVIEW TTS] isAudioPlaying:', isAudioPlaying);
        console.debug('[HR INTERVIEW TTS] currentHRAudio exists:', currentHRAudio !== null);
        // Current audio still playing; wait for onended/onerror to advance the queue
        return;
    }
    if (hrAudioQueue.length === 0) {
        console.log('[HR INTERVIEW TTS] ✅ Queue is empty, no more audio to play');
        return;
    }

    const next = hrAudioQueue.shift();
    console.log('[HR INTERVIEW TTS] ========== DEQUEUE AND PLAY NEXT AUDIO ==========');
    console.log('[HR INTERVIEW TTS] Dequeue and play next audio:', String(next).substring(0, 80) + '...');
    console.log('[HR INTERVIEW TTS] Queue remaining items:', hrAudioQueue.length);

    // Fire-and-forget; playAudio will manage onended/onerror and will call playNextFromHRAudio when done
    playAudio(next).catch(err => {
        console.warn('[HR INTERVIEW TTS] Queue item playback failed:', err);
        // Move on to the next item to avoid getting stuck
        setTimeout(() => playNextFromHRAudio(), 100);
    });
}

// Loading state management to prevent double submission
let isLoading = {
    startInterview: false,
    submitAnswer: false,
    getNextQuestion: false,
    generateFeedback: false,
    playAudio: false
};

// Get current authenticated user from user_profiles
async function getCurrentUser() {
    try {
        // First, try to get from localStorage (persistent) or sessionStorage
        const storedUserId = localStorage.getItem('user_id') || 
                            sessionStorage.getItem('resume_user_id') || 
                            window.CURRENT_USER_ID;
        if (storedUserId) {
            currentUserId = storedUserId;
            window.CURRENT_USER_ID = storedUserId;
            return { user_id: storedUserId };
        }
        
        // If not in storage, fetch from API
        const API_BASE = typeof window.getApiBase === 'function' ? window.getApiBase() : getApiBase();
        const res = await fetch(`${API_BASE}/api/profile/current`).catch(networkError => {
            console.error('[HR INTERVIEW] Network error fetching current user:', networkError);
            throw new Error('Network error: Unable to connect to server. Please check your internet connection.');
        });
        if (!res.ok) {
            throw new Error(`Failed to get current user: ${res.status}`);
        }
        const user = await res.json();
        currentUserId = user.user_id;
        
        // Store in both localStorage (persistent) and sessionStorage
        if (currentUserId) {
            localStorage.setItem('user_id', currentUserId);
            sessionStorage.setItem('resume_user_id', currentUserId);
            window.CURRENT_USER_ID = currentUserId;
        }
        
        return user;
    } catch (e) {
        console.error('Error getting current user:', e);
        // Try one more fallback: check storage
        const fallbackUserId = localStorage.getItem('user_id') || 
                               sessionStorage.getItem('resume_user_id') || 
                               window.CURRENT_USER_ID;
        if (fallbackUserId) {
            currentUserId = fallbackUserId;
            window.CURRENT_USER_ID = fallbackUserId;
            return { user_id: fallbackUserId };
        }
        throw new Error('No authenticated user found. Please ensure you have uploaded a resume and have a valid user profile.');
    }
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    console.log("[HR INTERVIEW] ✅ DOMContentLoaded fired - Page is ready");
    init();
});

async function init() {
    console.log("[HR INTERVIEW] ✅ HR INIT RUNNING - init() function called");
    try {
        // ✅ CRITICAL: On execution page, interviewSection is already visible
        // setupSection only exists on guidelines page (hr-interview.html)
        // This matches Technical Interview lifecycle: execution page auto-starts
        const setupSection = document.getElementById('setupSection');
        const interviewSection = document.getElementById('interviewSection');
        console.log("[HR INTERVIEW] UI elements found:", {
            setupSection: !!setupSection,
            interviewSection: !!interviewSection,
            pageType: setupSection ? 'guidelines' : 'execution'
        });
        
        // Only hide setupSection if it exists (guidelines page)
        if (setupSection) {
            setupSection.classList.add('hidden');
        }
        
        // Ensure interviewSection is visible (execution page)
        if (interviewSection) {
            interviewSection.classList.remove('hidden');
        }
        
        // Get current user first
        console.log("[HR INTERVIEW] Getting current user...");
        await getCurrentUser();
        console.log("[HR INTERVIEW] Current user ID:", currentUserId);
        
        // Setup event listeners
        setupEventListeners();

        // ✅ CRITICAL: Auto-start interview on page load (matches Technical Interview pattern)
        // This eliminates dependency on button click event binding, making it work reliably on Vercel
        console.log("[HR INTERVIEW] ✅ HR startInterview CALLED - About to call startInterview()");
        await startInterview();
    } catch (e) {
        console.error('[HR INTERVIEW] ❌ Initialization failed:', e);
        console.error('[HR INTERVIEW] Error details:', {
            name: e.name,
            message: e.message,
            stack: e.stack
        });
        // Show error in setupSection if interview section is not available
        const setupSection = document.getElementById('setupSection');
        if (setupSection) {
            setupSection.classList.remove('hidden');
            setupSection.innerHTML = `
                <div class="error-message">
                    <h3>Failed to Start Interview</h3>
                    <p>${e.message || 'Please ensure you have uploaded a resume and have a valid user profile.'}</p>
                    <button class="btn btn-primary" onclick="window.location.reload()" style="margin-top: 15px;">
                        Retry
                    </button>
                </div>
            `;
        } else {
            alert(`Error: ${e.message}`);
        }
    }
}

function setupEventListeners() {
    // ✅ CRITICAL: All event listeners are defensive - elements may not exist at init time
    // Interview auto-starts on page load, so button listeners are optional
    
    // Start Interview button (optional - interview auto-starts anyway)
    const startBtn = document.getElementById('startInterviewBtn');
    if (startBtn) {
        startBtn.addEventListener('click', startInterview);
    }
    
    // End Interview button (only exists when interview is active)
    const endBtn = document.getElementById('endInterviewBtn');
    if (endBtn) {
        endBtn.addEventListener('click', endInterview);
    }
    
    // Voice recording button (only exists when interview is active)
    const voiceBtn = document.getElementById('voiceButton');
    if (voiceBtn) {
        voiceBtn.addEventListener('click', toggleRecording);
    }
    
    // Restart Interview button (only exists in feedback section)
    const restartBtn = document.getElementById('restartInterviewBtn');
    if (restartBtn) {
        restartBtn.addEventListener('click', () => {
            window.location.reload();
        });
    }
}

// Auto-hides after specified duration (default 4s for errors)
function showToast(message, type = 'error', duration = 4000) {
    // Remove existing toast if any
    const existingToast = document.getElementById('hrToast');
    if (existingToast) {
        existingToast.remove();
    }
    
    // Create toast element
    const toast = document.createElement('div');
    toast.id = 'hrToast';
    toast.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        background: ${type === 'error' ? '#ef5350' : type === 'success' ? '#4caf50' : '#2196f3'};
        color: white;
        padding: 16px 24px;
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        z-index: 10000;
        max-width: 400px;
        font-size: 14px;
        font-weight: 500;
        animation: slideIn 0.3s ease;
    `;
    toast.textContent = message;
    
    // Add animation
    const style = document.createElement('style');
    style.textContent = `
        @keyframes slideIn {
            from { transform: translateX(100%); opacity: 0; }
            to { transform: translateX(0); opacity: 1; }
        }
    `;
    if (!document.getElementById('hrToastStyle')) {
        style.id = 'hrToastStyle';
        document.head.appendChild(style);
    }
    
    document.body.appendChild(toast);
    
    // Auto-remove after duration
    setTimeout(() => {
        toast.style.animation = 'slideIn 0.3s ease reverse';
        setTimeout(() => {
            if (toast.parentNode) {
                toast.remove();
            }
        }, 300);
    }, duration);
}

async function startInterview() {
    console.log("[HR INTERVIEW] ✅ startInterview() function executing");
    try {
        // Ensure we have current user
        if (!currentUserId) {
            console.log("[HR INTERVIEW] currentUserId missing, fetching user...");
            await getCurrentUser();
        }
        
        // Validate userId is available
        if (!currentUserId) {
            const errorMsg = 'userId is not defined. Please ensure you have uploaded a resume and have a valid user profile.';
            console.error('[HR INTERVIEW] ❌ Start error:', errorMsg);
            console.error('[HR INTERVIEW] currentUserId is:', currentUserId);
            alert('Failed to start HR interview. Check console.');
            throw new Error(errorMsg);
        }
        
        // ✅ CRITICAL: Verify api-config.js is loaded before making API call
        if (typeof getApiBase !== 'function') {
            const errorMsg = 'api-config.js not loaded. getApiBase() is not available.';
            console.error('[HR INTERVIEW] ❌', errorMsg);
            console.error('[HR INTERVIEW] window.getApiBase:', typeof window.getApiBase);
            console.error('[HR INTERVIEW] getApiBase:', typeof getApiBase);
            alert('Configuration error: API config not loaded. Please refresh the page.');
            throw new Error(errorMsg);
        }
        
        // ✅ CRITICAL: Log API call details before making request
        const apiBase = getApiBase();
        const apiUrl = `${apiBase}/api/interview/hr/start`;
        const payload = { user_id: currentUserId };
        console.log("[HR INTERVIEW] ✅ About to make API call:", {
            url: apiUrl,
            method: 'POST',
            payload: payload,
            apiBase: apiBase,
            getApiBaseAvailable: typeof getApiBase === 'function'
        });
        
        let response;
        try {
            response = await fetch(apiUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            console.log("[HR INTERVIEW] ✅ API call completed:", {
                status: response.status,
                statusText: response.statusText,
                ok: response.ok
            });
        } catch (fetchError) {
            // ✅ CRITICAL: Fail-fast on network errors (matches Technical Interview pattern)
            console.error('[HR INTERVIEW] Fetch error:', fetchError);
            console.error('[HR INTERVIEW] Error details:', {
                name: fetchError.name,
                message: fetchError.message,
                stack: fetchError.stack
            });
            alert('Failed to start HR interview. Check console.');
            throw new Error(`Network error: ${fetchError.message || 'Unable to connect to server'}`);
        }

        if (!response.ok) {
            // ✅ CRITICAL: Fail-fast on non-OK responses (matches Technical Interview pattern)
            const errorText = await response.text();
            const errorMsg = `Failed to start interview: ${response.status} - ${errorText}`;
            console.error('[HR INTERVIEW] Response not OK:', {
                status: response.status,
                statusText: response.statusText,
                errorText: errorText
            });
            alert('Failed to start HR interview. Check console.');
            throw new Error(errorMsg);
        }

        let data;
        try {
            data = await response.json();
        } catch (jsonError) {
            // ✅ CRITICAL: Fail-fast on JSON parse errors
            console.error('[HR INTERVIEW] JSON parse error:', jsonError);
            alert('Failed to start HR interview. Check console.');
            throw new Error('Invalid response format from server');
        }
        
        // ✅ CRITICAL: Log the response (matches Technical Interview pattern)
        console.log("HR start response:", data);
        
        // ✅ CRITICAL: Validate session_id is present (matches Technical Interview pattern)
        if (!data.session_id) {
            const errorMsg = 'Session ID missing from response. Please try again.';
            console.error('[HR INTERVIEW] Missing session_id:', data);
            alert('Failed to start HR interview. Check console.');
            throw new Error(errorMsg);
        }
        
        interviewSessionId = data.session_id;
        interviewActive = true;
        conversationHistory = [];  // Start with empty history (like Technical Interview)

        // ✅ CRITICAL: Ensure UI is in interview state (setupSection already hidden in init())
        // Interview section should already be visible from init(), but ensure it's shown
        // This matches Technical Interview pattern: loadingState → interviewInterface
        const setupSection = document.getElementById('setupSection');
        const interviewSection = document.getElementById('interviewSection');
        if (setupSection) {
            setupSection.classList.add('hidden');
        }
        if (interviewSection) {
            interviewSection.classList.remove('hidden');
        }

        // Update status
        const statusEl = document.getElementById('interviewStatus');
        if (statusEl) {
            statusEl.textContent = 'Interview Active';
            statusEl.classList.add('active');
        }

        // Clear container and prepare for messages
        const container = document.getElementById('conversationContainer');
        if (container) {
            container.innerHTML = '';
        }

        // ✅ CONVERSATIONAL FLOW: Display first question if available (like Technical Interview)
        // Normalize response: support both 'question' and 'first_question' fields
        const firstQuestion = data.question || data.first_question;
        const audioUrl = data.audio_url;
        
        if (firstQuestion) {
            currentQuestion = firstQuestion;
            conversationHistory.push({
                role: 'ai',
                content: firstQuestion,
                audio_url: audioUrl
            });
            // Display question with audio URL
            displayMessage('ai', firstQuestion, audioUrl);
            
            // Play audio if available (matches Technical Interview pattern)
            if (audioUrl) {
                setTimeout(() => {
                    enqueueHRAudio(audioUrl).catch(err => {
                        // Audio playback failed, manual play button will be shown
                    });
                }, 100);
            } else {
                console.error('[HR INTERVIEW] ❌ No audio_url received for first question');
            }
        } else {
            showError('No question received. Please try again.');
        }

    } catch (error) {
        // ✅ CRITICAL: Fail-fast error handling (matches Technical Interview pattern)
        console.error('[HR INTERVIEW] Start error:', error);
        console.error('[HR INTERVIEW] Error stack:', error.stack);
        
        // Show user-visible alert
        alert('Failed to start HR interview. Check console.');
        
        // Display error in UI (matches Technical Interview pattern)
        document.getElementById('setupSection').innerHTML = `
            <div class="error-message">
                <h3>Failed to Start Interview</h3>
                <p>${error.message || 'Please ensure you have uploaded a resume and have a valid user profile.'}</p>
                <button class="btn btn-primary" onclick="window.location.reload()" style="margin-top: 15px;">
                    Retry
                </button>
            </div>
        `;
    }
}

// ✅ CRITICAL: Expose startInterview globally for Vercel compatibility (matches Technical Interview pattern)
window.startHRInterview = startInterview;
window.startInterview = startInterview; // Also expose as startInterview for compatibility

async function toggleRecording() {
    if (!interviewActive) return;
    
    // Prevent recording while audio is playing (same as technical interview behavior)
    if (isAudioPlaying) {
        console.log('[HR INTERVIEW] Cannot record while audio is playing');
        document.getElementById('voiceStatus').textContent = 'Please wait for the question to finish...';
        return;
    }

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
            
            // ✅ If user clicked record but did not speak, treat as 'No Answer'
            if (audioBlob.size === 0) {
                const noAnswerText = 'No Answer';
                document.getElementById('voiceStatus').textContent = 'No answer captured. Sending "No Answer".';
                
                // Display 'No Answer' as the user's response
                displayMessage('user', noAnswerText);
                conversationHistory.push({
                    role: 'user',
                    content: noAnswerText
                });
                
                // Submit 'No Answer' to the backend
                await submitAnswer(noAnswerText);
                
                // Stop all tracks
                stream.getTracks().forEach(track => track.stop());
                return;
            }
            
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
        const errorMsg = 'Microphone access denied. Please allow microphone access and try again.';
        showError(errorMsg);
        // Show alert but don't redirect
        alert(errorMsg);
        // Keep interview section visible
        document.getElementById('voiceStatus').textContent = 'Microphone access required. Please allow access and try again.';
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

/**
 * Detect if STT result should be classified as "No Answer"
 * Returns {isNoAnswer: boolean, reason: string} if it's a no-answer case
 */
function detectNoAnswer(sttText) {
    if (!sttText || !sttText.trim()) {
        return { isNoAnswer: true, reason: 'empty_or_whitespace' };
    }
    
    const trimmed = sttText.trim();
    const upper = trimmed.toUpperCase();
    
    // List of known garbage phrases (case-insensitive)
    const garbagePhrases = [
        'THANK YOU',
        'THANKS',
        'THANK YOU FOR WATCHING',
        'SHOWCASING VIDEO',
        'THANKS FOR WATCHING',
        'THANK YOU FOR WATCHING THIS VIDEO',
        'THANKS FOR WATCHING THIS',
        'THANK YOU FOR WATCHING!',
        'THANKS FOR WATCHING!'
    ];
    
    // Check for exact garbage phrase matches
    for (const phrase of garbagePhrases) {
        if (upper === phrase || upper.startsWith(phrase + ' ') || upper.endsWith(' ' + phrase)) {
            return { isNoAnswer: true, reason: `garbage_phrase: ${trimmed}` };
        }
    }
    
    // Check for single-word fillers with no semantic content
    const words = trimmed.split(/\s+/);
    if (words.length === 1) {
        const singleWord = upper;
        // Common single-word fillers that indicate no real answer
        const fillerWords = ['UM', 'UH', 'ER', 'AH', 'OH', 'WELL', 'SO', 'LIKE', 'YEAH', 'YEP', 'NOPE', 'OK', 'OKAY', 'SURE'];
        if (fillerWords.includes(singleWord)) {
            return { isNoAnswer: true, reason: `single_word_filler: ${trimmed}` };
        }
    }
    
    // Very short responses (less than 3 characters) are likely not real answers
    if (trimmed.length < 3) {
        return { isNoAnswer: true, reason: `too_short: ${trimmed}` };
    }
    
    // ✅ FIX: Detect hallucinated/irrelevant answers that are clearly not interview responses
    // These are answers that don't relate to interview questions at all
    const hallucinatedPatterns = [
        /see you in the car/i,
        /take care of yourself/i,
        /look after yourself/i,
        /see you later/i,
        /goodbye/i,
        /farewell/i,
        /see you soon/i,
        /have a good day/i,
        /have a nice day/i,
        /take care/i,
        /bye/i,
        /good night/i,
        /good morning/i,
        /good afternoon/i,
        /thanks for watching/i,
        /thank you for watching/i,
        /showcasing video/i,
        /end of video/i,
        /video ended/i,
        /recording ended/i,
        /test test/i,
        /testing testing/i,
        /one two three/i,
        /hello hello/i,
        /can you hear me/i,
        /is this working/i,
        /microphone test/i
    ];
    
    // Check if answer matches any hallucinated pattern
    for (const pattern of hallucinatedPatterns) {
        if (pattern.test(trimmed)) {
            return { isNoAnswer: true, reason: `hallucinated_pattern: ${trimmed}` };
        }
    }
    
    // ✅ FIX: Detect URLs, website references, and other clearly irrelevant text
    // Check for URL patterns (www., http://, https://, .com, .co.uk, .org, etc.)
    const urlPatterns = [
        /www\./i,
        /http:\/\//i,
        /https:\/\//i,
        /\.com/i,
        /\.co\.uk/i,
        /\.org/i,
        /\.net/i,
        /\.io/i,
        /\.edu/i,
        /\.gov/i,
        /subs by/i,
        /subtitle/i,
        /caption/i
    ];
    
    for (const pattern of urlPatterns) {
        if (pattern.test(trimmed)) {
            return { isNoAnswer: true, reason: `url_or_website_reference: ${trimmed}` };
        }
    }
    
    // ✅ FIX: Detect answers that are clearly not related to interview context
    // If answer contains phrases that suggest it's not an interview answer
    const irrelevantPhrases = [
        'see you',
        'take care',
        'goodbye',
        'farewell',
        'bye',
        'later',
        'watching',
        'video',
        'recording',
        'test',
        'testing',
        'microphone',
        'can you hear',
        'is this working',
        'subs by',
        'subtitle',
        'caption',
        'www',
        'website',
        'url'
    ];
    
    const lowerTrimmed = trimmed.toLowerCase();
    // If answer contains multiple irrelevant phrases, it's likely hallucinated
    let irrelevantCount = 0;
    for (const phrase of irrelevantPhrases) {
        if (lowerTrimmed.includes(phrase)) {
            irrelevantCount++;
        }
    }
    
    // If answer contains 2+ irrelevant phrases, classify as "No Answer"
    if (irrelevantCount >= 2) {
        return { isNoAnswer: true, reason: `multiple_irrelevant_phrases: ${trimmed}` };
    }
    
    // ✅ FIX: STRICT RULE - Detect parenthetical descriptions FIRST (highest priority)
    // These are clearly not interview answers - they describe background audio
    // Check for various parenthetical patterns - if text contains (* or *) or starts with ( or *
    if (trimmed.startsWith('(*') || 
        trimmed.startsWith('(') || 
        trimmed.startsWith('*') ||
        trimmed.includes('(*') || 
        trimmed.includes('*)') ||
        trimmed.includes('( *') ||
        trimmed.includes('* )') ||
        (trimmed.startsWith('*') && trimmed.endsWith('*')) ||
        /^\([^)]*[Ss]ong|[Mm]usic|[Ss]ound|[Aa]udio|[Pp]laying[^)]*\)/i.test(trimmed) ||
        /\([^)]*[Ss]ong|[Mm]usic|[Ss]ound|[Aa]udio|[Pp]laying[^)]*\)/i.test(trimmed)) {
        return { isNoAnswer: true, reason: `parenthetical_description: ${trimmed}` };
    }
    
    // ✅ FIX: Detect single irrelevant phrase if it's clearly not an answer
    // If answer contains "subs by" or similar, it's definitely not an interview answer
    if (lowerTrimmed.includes('subs by') || lowerTrimmed.includes('subtitle') || lowerTrimmed.includes('caption')) {
        return { isNoAnswer: true, reason: `subtitle_or_caption_text: ${trimmed}` };
    }
    
    // ✅ FIX: Detect answers that describe what's happening rather than answering the question
    // If text contains words that describe actions/events rather than personal information
    const descriptivePhrases = [
        'playing',
        'song',
        'music',
        'sound',
        'audio',
        'noise',
        'background',
        'effect',
        'twinkle',
        'peel'
    ];
    
    let descriptiveCount = 0;
    for (const phrase of descriptivePhrases) {
        if (lowerTrimmed.includes(phrase)) {
            descriptiveCount++;
        }
    }
    
    // If answer contains 2+ descriptive phrases about audio/music, it's not an interview answer
    if (descriptiveCount >= 2) {
        return { isNoAnswer: true, reason: `audio_description_text: ${trimmed}` };
    }
    
    // ✅ FIX: STRICT RULE - Detect answers that are clearly describing background content
    // If answer contains "playing" + any music/song reference, it's describing audio, not answering
    // Also check for positional patterns (starts/ends with "playing") and specific phrases
    if (lowerTrimmed.includes('background music') || lowerTrimmed.includes('background sound')) {
        return { isNoAnswer: true, reason: `background_audio_description: ${trimmed}` };
    }
    
    // Check for "playing" combined with music/audio words, or positional patterns
    if (lowerTrimmed.includes('playing') && 
        (lowerTrimmed.includes('song') || lowerTrimmed.includes('music') || 
         lowerTrimmed.includes('sound') || lowerTrimmed.includes('audio'))) {
        return { isNoAnswer: true, reason: `background_audio_description: ${trimmed}` };
    }
    
    // Check for text that ends with "playing" or starts with "playing" (describing audio)
    if (lowerTrimmed.endsWith(' playing') || lowerTrimmed.startsWith('playing ')) {
        return { isNoAnswer: true, reason: `background_audio_description: ${trimmed}` };
    }
    
    // ✅ FIX: STRICT RULE - If answer contains song title patterns, it's not an interview answer
    // Common patterns: "twinkle", "star", "peel" (from song titles), etc.
    if (lowerTrimmed.includes('twinkle') || 
        (lowerTrimmed.includes('star') && lowerTrimmed.includes('little')) ||
        (lowerTrimmed.includes('foot') && lowerTrimmed.includes('peel'))) {
        return { isNoAnswer: true, reason: `song_title_reference: ${trimmed}` };
    }
    
    // ✅ FIX: Detect answers that don't contain any interview-relevant keywords
    // If answer is long enough but doesn't contain any professional/personal keywords, it might be irrelevant
    const interviewKeywords = [
        'i am', 'i have', 'i work', 'i do', 'my', 'me', 'myself', 'experience', 'skill', 'project',
        'job', 'career', 'education', 'degree', 'company', 'team', 'work', 'professional', 'background',
        'strength', 'weakness', 'goal', 'interest', 'motivation', 'hire', 'position', 'role'
    ];
    
    // Only apply this check for longer answers (more than 20 characters)
    // Short answers might be valid (e.g., "Yes", "No", "I agree")
    if (trimmed.length > 20) {
        let hasInterviewKeyword = false;
        for (const keyword of interviewKeywords) {
            if (lowerTrimmed.includes(keyword)) {
                hasInterviewKeyword = true;
                break;
            }
        }
        
        // If long answer has no interview keywords AND contains descriptive/audio words, it's likely irrelevant
        if (!hasInterviewKeyword && descriptiveCount >= 1) {
            return { isNoAnswer: true, reason: `no_interview_relevance: ${trimmed}` };
        }
    }
    
    return { isNoAnswer: false, reason: null };
}

async function processAudioAnswer(audioBlob) {
    try {
        // Convert audio to text using speech-to-text endpoint
        const formData = new FormData();
        formData.append('audio', audioBlob, 'recording.webm');

        const API_BASE = typeof window.getApiBase === 'function' ? window.getApiBase() : getApiBase();
        const sttResponse = await fetch(`${API_BASE}/api/interview/speech-to-text`, {
            method: 'POST',
            body: formData
        }).catch(networkError => {
            console.error('[HR INTERVIEW] Network error in speech-to-text:', networkError);
            throw new Error('Network error: Unable to connect to server. Please check your internet connection.');
        });

        if (!sttResponse.ok) {
            const errorText = await sttResponse.text().catch(() => 'Unknown error');
            console.error('[HR INTERVIEW] STT API error:', sttResponse.status, errorText);
            throw new Error(`STT API failed with status: ${sttResponse.status} - ${errorText}`);
        }

        const sttData = await sttResponse.json();
        let rawUserAnswer = sttData.text || sttData.transcript || ''; // Use a temporary variable for clarity
        
        // ✅ If user did not speak or transcription is empty, treat as 'No Answer'
        if (!rawUserAnswer || rawUserAnswer.trim() === '') {
            rawUserAnswer = 'No Answer';
        }
        
        // ✅ FIX: Detect "No Answer" cases (empty, garbage phrases, low confidence)
        const noAnswerCheck = detectNoAnswer(rawUserAnswer);
        
        let userAnswer;
        if (noAnswerCheck.isNoAnswer || rawUserAnswer === 'No Answer') {
            // Log the detection reason (debug level)
            console.log(`[HR INTERVIEW] No Answer detected: ${noAnswerCheck.reason || 'Empty transcription'}`);
            userAnswer = 'No Answer'; // Record exactly as "No Answer"
        } else {
            userAnswer = rawUserAnswer.trim(); // Use the cleaned answer
        }

        // Display user's answer (show "No Answer" if detected, otherwise show actual text)
        displayMessage('user', userAnswer);

        // Submit answer to backend (will be "No Answer" or actual answer)
        await submitAnswer(userAnswer);

    } catch (error) {
        console.error('Process audio error:', error);
        
        // If STT fails completely, treat as "No Answer"
        console.log('[HR INTERVIEW] STT failed, treating as No Answer');
        const userAnswer = 'No Answer';
        displayMessage('user', userAnswer);
        await submitAnswer(userAnswer);
    }
}

async function submitAnswer(answer) {
    // ✅ FIX: Allow "No Answer" as a valid answer (exactly this string)
    // Empty answers are still rejected, but "No Answer" is accepted
    if (!answer || (!answer.trim() && answer !== 'No Answer')) {
        showUserFriendlyError(
            { message: 'I could not hear your answer. Please speak again.', originalError: new Error('Empty answer') },
            'submitAnswer',
            false
        );
        return;
    }

    if (!interviewSessionId || !currentQuestion) {
        showUserFriendlyError(new Error('No active interview session or question'), 'submitAnswer', false);
        return;
    }

    // Prevent double submission
    if (isLoading.submitAnswer) {
        console.warn('[SUBMIT ANSWER] Submit answer already in progress, ignoring duplicate call');
        return;
    }

    try {
        setLoadingState('submitAnswer', true);
        console.log('[SUBMIT ANSWER] Submitting HR answer to backend...');
        
        // Get API base URL using helper function
        const API_BASE = typeof window.getApiBase === 'function' ? window.getApiBase() : getApiBase();
        
        // Use HR-specific submit answer endpoint
        const response = await fetch(`${API_BASE}/api/interview/hr/${interviewSessionId}/submit-answer`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                question: currentQuestion,
                answer: answer,
                response_time: null  // Can be calculated if needed
            })
        }).catch(networkError => {
            const errorMsg = 'Network error: Unable to submit answer. Please check your internet connection.';
            console.error('[HR INTERVIEW] Network error submitting answer:', networkError);
            showToast(errorMsg, 'error');
            throw new Error(errorMsg);
        });

        if (!response.ok) {
            let errorText = '';
            let errorData = null;
            try {
                errorText = await response.text();
                try {
                    errorData = JSON.parse(errorText);
                    errorText = errorData.detail || errorData.error || errorText;
                } catch {
                    // Not JSON, use text as-is
                }
            } catch (parseError) {
                errorText = `HTTP ${response.status}`;
            }
            
            const errorMsg = `Failed to submit answer: ${response.status} - ${errorText}`;
            console.error('[HR INTERVIEW] Submit answer error:', response.status, errorText);
            console.error('[HR INTERVIEW] Error data:', errorData);
            showToast(errorMsg, 'error');
            
            const errorObj = {
                message: errorMsg,
                status: response.status,
                responseText: errorText,
                originalError: new Error(`HTTP ${response.status}: ${errorText}`)
            };
            throw errorObj;
        }

        const data = await response.json();
        
        console.log('[SUBMIT ANSWER] ✅ HR answer submitted successfully');
        console.log('[SUBMIT ANSWER] HR scores:', {
            communication: data.scores?.communication,
            cultural_fit: data.scores?.cultural_fit,
            motivation: data.scores?.motivation,
            clarity: data.scores?.clarity,
            overall: data.scores?.overall
        });
        
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
                console.log('[HR INTERVIEW] Enqueueing AI response audio:', data.audio_url);
                enqueueHRAudio(data.audio_url);
            }
        }

        // Check if interview is complete (10 questions for HR)
        const aiQuestionsCount = conversationHistory.filter(m => m.role === 'ai').length;
        if (data.interview_completed || aiQuestionsCount >= 10) {
            console.log(`[SUBMIT ANSWER] Interview completed: ${aiQuestionsCount} questions asked`);
            await completeInterview();
        } else {
            // FIX 10: Get next question after a short delay with race condition check
            // Pass the user's answer so backend can save it and use it for context-aware next question
            setTimeout(() => {
                // FIX 10: Check if getNextQuestion is already in progress to prevent duplicate calls
                if (!isLoading.getNextQuestion) {
                    getNextHRQuestion(answer);  // Pass the answer for context-aware question generation
                } else {
                    console.warn('[SUBMIT ANSWER] getNextHRQuestion already in progress, ignoring duplicate call');
                }
            }, 2000);
        }

        document.getElementById('voiceStatus').textContent = 'Click the microphone to record your answer';

    } catch (error) {
        const errorMessage = error.message || 'Failed to submit answer. Please try again.';
        console.error('[HR INTERVIEW] Submit answer error:', error);
        if (!error.message || !error.message.includes('Network error')) {
            // Only show toast if not already shown (network errors already show toast)
            showToast(errorMessage, 'error');
        }
        
        const errorObj = {
            message: errorMessage,
            status: error.status,
            originalError: error
        };
        showUserFriendlyError(errorObj, 'submitAnswer', true);
        document.getElementById('voiceStatus').textContent = 'Error submitting answer. Click the microphone to try again.';
        // Don't redirect - keep interview active
    } finally {
        setLoadingState('submitAnswer', false);
    }
}

async function getNextHRQuestion(userAnswer = null) {
    if (!interviewSessionId) {
        console.error('[HR INTERVIEW] No session ID available');
        showError('No interview session found. Please start the interview again.');
        return;
    }

    // Prevent double submission
    if (isLoading.getNextQuestion) {
        console.warn('[HR INTERVIEW] Get next question already in progress, ignoring duplicate call');
        return;
    }

    try {
        setLoadingState('getNextQuestion', true);
        
        // Hide loading message if still visible
        const loadingMsg = document.getElementById('loadingMessage');
        if (loadingMsg) {
            loadingMsg.classList.add('hidden');
        }
        
        console.log('[HR INTERVIEW] Fetching next question from backend...');
        if (userAnswer) {
            console.log('[HR INTERVIEW] Sending user answer for context-aware question generation');
        }
        
        // Get API base URL using helper function
        const API_BASE = typeof window.getApiBase === 'function' ? window.getApiBase() : getApiBase();
        
        // Call backend endpoint to get next AI-generated HR question
        // Send user_answer if provided so backend can save it and use it for context-aware generation
        const requestBody = {};
        if (userAnswer) {
            requestBody.user_answer = userAnswer;
        }
        
        const response = await fetch(`${API_BASE}/api/interview/hr/${interviewSessionId}/next-question`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(requestBody)
        }).catch(networkError => {
            const errorMsg = 'Network error: Unable to fetch next question. Please check your internet connection.';
            console.error('[HR INTERVIEW] Network error fetching next question:', networkError);
            showToast(errorMsg, 'error');
            throw new Error(errorMsg);
        });

        if (!response.ok) {
            let errorText = '';
            let errorData = null;
            try {
                errorText = await response.text();
                try {
                    errorData = JSON.parse(errorText);
                    errorText = errorData.detail || errorData.error || errorText;
                } catch {
                    // Not JSON, use text as-is
                }
            } catch (parseError) {
                errorText = `HTTP ${response.status}`;
            }
            
            const errorMsg = `Backend error: ${response.status} - ${errorText}`;
            console.error('[HR INTERVIEW] Get next question error:', response.status, errorText);
            console.error('[HR INTERVIEW] Error data:', errorData);
            showToast(errorMsg, 'error');
            throw new Error(errorMsg);
        }

        const data = await response.json();
        
        // ✅ DEBUG: Log next-question response received
        console.debug('[HR DEBUG Q2+] ========== NEXT QUESTION RESPONSE RECEIVED ==========');
        console.debug('[HR DEBUG Q2+] Response status:', response.status);
        console.debug('[HR DEBUG Q2+] Response data keys:', Object.keys(data));
        console.debug('[HR DEBUG Q2+] question_text:', data.question ? data.question.substring(0, 100) + '...' : 'MISSING');
        console.debug('[HR DEBUG Q2+] audio_url (direct):', data.audio_url);
        console.debug('[HR DEBUG Q2+] audioUrl (camelCase):', data.audioUrl);
        console.debug('[HR DEBUG Q2+] question_number:', data.question_number);
        console.debug('[HR DEBUG Q2+] Full response data:', JSON.stringify(data, null, 2));
        console.debug('[HR DEBUG Q2+] ====================================================');
        
        // Check if interview is completed
        if (data.interview_completed) {
            console.log('[HR INTERVIEW] Interview completed:', data.message);
            await completeInterview();
            return;
        }
        
        // Extract question data from response
        const nextQuestion = data.question;
        const audioUrl = data.audio_url || data.audioUrl; // Try both possible field names
        const questionNumber = data.question_number || conversationHistory.filter(m => m.role === 'ai').length + 1;
        
        // ✅ DEBUG: Log extracted values
        console.debug('[HR DEBUG Q2+] Extracted nextQuestion:', nextQuestion ? nextQuestion.substring(0, 50) + '...' : 'NULL/UNDEFINED');
        console.debug('[HR DEBUG Q2+] Extracted audioUrl:', audioUrl || 'NULL/UNDEFINED');
        console.debug('[HR DEBUG Q2+] Extracted questionNumber:', questionNumber);
        
        if (!nextQuestion) {
            throw new Error('No question received from backend');
        }
        
        console.log('[HR INTERVIEW] Received question:', nextQuestion.substring(0, 50) + '...');
        console.log('[HR INTERVIEW] Audio URL from response:', audioUrl);
        console.log('[HR INTERVIEW] Full response data keys:', Object.keys(data));
        
        // Update current question
        currentQuestion = nextQuestion;
        
        // Update local conversation history to reflect backend's source of truth
        // Note: If user_answer was sent, it's already saved in backend and included in conversation history
        // We only need to add the newly received question to local history
        conversationHistory.push({
            role: 'ai',
            content: nextQuestion,
            audio_url: audioUrl,
            question_number: questionNumber
        });
        
        console.log('[HR INTERVIEW] ✅ Updated local conversation history with new question');
        
        // Display question with audio URL
        displayMessage('ai', nextQuestion, audioUrl);
        
        // ✅ FIX: ALWAYS play audio for every question (match Technical Interview's simple approach)
        // For Q2-Q10, browser may block autoplay, so we need to handle this gracefully
        // ✅ FIX: Use simple setTimeout like Technical Interview (no requestAnimationFrame wrapper)
        setTimeout(() => {
            // ✅ DEBUG: Log before attempting audio playback
            console.debug('[HR DEBUG Q2+] ========== ATTEMPTING AUDIO PLAYBACK ==========');
            console.debug('[HR DEBUG Q2+] audioUrl value:', audioUrl);
            console.debug('[HR DEBUG Q2+] audioUrl truthy check:', !!audioUrl);
            console.debug('[HR DEBUG Q2+] audioUrl type:', typeof audioUrl);
            console.debug('[HR DEBUG Q2+] audioUrl.trim() check:', audioUrl ? audioUrl.trim() : 'N/A');
            console.debug('[HR DEBUG Q2+] nextQuestion value:', nextQuestion ? nextQuestion.substring(0, 50) + '...' : 'NULL');
            console.debug('[HR DEBUG Q2+] isLoading.getNextQuestion:', isLoading.getNextQuestion);
            console.debug('[HR DEBUG Q2+] isLoading.playAudio:', isLoading.playAudio);
            console.debug('[HR DEBUG Q2+] ===============================================');
            
            // ✅ FIX: Check if audioUrl is valid (not null, not undefined, not empty string)
            const hasValidAudioUrl = audioUrl && typeof audioUrl === 'string' && audioUrl.trim().length > 0;
            
                if (hasValidAudioUrl) {
                    console.log('[HR INTERVIEW] ✅ Enqueueing next question audio:', audioUrl);
                    console.debug('[HR DEBUG Q2+] EnqueueHRAudio() with audioUrl:', audioUrl);
                    enqueueHRAudio(audioUrl);
                } else {
                    // Fallback - generate TTS from question text if audio_url is missing
                    console.warn('[HR INTERVIEW] ⚠️ No audioUrl provided, enqueueing TTS from question text');
                    console.debug('[HR DEBUG Q2+] audioUrl is invalid, using fallback TTS from question text');
                    if (nextQuestion && nextQuestion.trim()) {
                        enqueueHRAudio(nextQuestion);
                    } else {
                        console.error('[HR INTERVIEW] ❌ No question text available for TTS fallback');
                        const voiceStatus = document.getElementById('voiceStatus');
                        if (voiceStatus) {
                            voiceStatus.textContent = 'Click the microphone to record your answer';
                        }
                        // Show manual play button even if we have nothing reliable
                        if (audioUrl) {
                            showManualPlayButton(audioUrl);
                        }
                    }
                }
        }, 100); // Small delay to ensure UI is updated (match Technical Interview)

    } catch (error) {
        console.error('[HR INTERVIEW] ❌ Get question error:', error);
        const errorMsg = `Failed to get question from backend: ${error.message || 'Please try again.'}`;
        showError(errorMsg);
        document.getElementById('voiceStatus').textContent = 'Error occurred. Please try recording again or start a new interview.';
        
        // No fallback to hardcoded questions - all questions must come from backend
        // If backend fails, we can only complete the interview if we have enough questions
        const questionCount = conversationHistory.filter(m => m.role === 'ai').length;
        if (questionCount >= 5) {
            console.log('[HR INTERVIEW] Interview completed due to question count (5 questions reached)');
            await completeInterview();
        } else {
            // Show error but don't try to continue with hardcoded questions
            console.error('[HR INTERVIEW] Cannot continue: Backend question generation failed and interview is incomplete');
            alert('Unable to get next question from the server. Please try refreshing the page or starting a new interview.');
        }
    } finally {
        // FIX: Ensure loading state is always reset
        setLoadingState('getNextQuestion', false);
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
    if (!interviewSessionId) {
        const error = new Error('No interview session found. Cannot generate feedback.');
        showUserFriendlyError(error, 'generateFeedback', false);
        generateBasicFeedback();
        return;
    }

    // Prevent double submission
    if (isLoading.generateFeedback) {
        console.warn('[FEEDBACK] Generate feedback already in progress, ignoring duplicate call');
        return;
    }

    try {
        setLoadingState('generateFeedback', true);
        console.log('[FEEDBACK] Requesting HR feedback from backend...');
        
        // Get API base URL using helper function
        const API_BASE = typeof window.getApiBase === 'function' ? window.getApiBase() : getApiBase();
        
        // Use HR-specific feedback endpoint
        const response = await fetch(`${API_BASE}/api/interview/hr/${interviewSessionId}/feedback`, {
            method: 'GET'
        }).catch(networkError => {
            const errorMsg = 'Network error: Unable to fetch feedback. Please check your internet connection.';
            console.error('[HR INTERVIEW] Network error fetching feedback:', networkError);
            showToast(errorMsg, 'error');
            throw new Error(errorMsg);
        });

        if (!response.ok) {
            let errorText = '';
            let errorData = null;
            try {
                errorText = await response.text();
                try {
                    errorData = JSON.parse(errorText);
                    errorText = errorData.detail || errorData.error || errorText;
                } catch {
                    // Not JSON, use text as-is
                }
            } catch (parseError) {
                errorText = `HTTP ${response.status}`;
            }
            
            const errorMsg = `Failed to generate feedback: ${response.status} - ${errorText}`;
            console.error('[FEEDBACK] HR feedback endpoint error:', response.status, errorText);
            console.error('[FEEDBACK] Error data:', errorData);
            showToast(errorMsg, 'error');
            
            const errorObj = {
                message: errorMsg,
                status: response.status,
                responseText: errorText,
                originalError: new Error(`HTTP ${response.status}: ${errorText}`)
            };
            
            // Log error but fallback to basic feedback
            showUserFriendlyError(errorObj, 'generateFeedback', true);
            
            // Fallback to basic feedback if endpoint fails
            console.warn('[FEEDBACK] HR feedback endpoint failed, generating basic feedback');
            generateBasicFeedback();
            return;
        }

        const feedback = await response.json();

        if (!feedback) {
            console.warn('[FEEDBACK] No feedback data received, generating basic feedback');
            generateBasicFeedback();
            return;
        }

        console.log('[FEEDBACK] ✅ HR feedback received successfully');
        console.log('[FEEDBACK] Feedback data:', {
            overall_score: feedback.overall_score,
            communication_score: feedback.communication_score,
            cultural_fit_score: feedback.cultural_fit_score,
            motivation_score: feedback.motivation_score,
            clarity_score: feedback.clarity_score,
            question_count: feedback.question_count
        });

        // Display feedback
        document.getElementById('overallScore').textContent = Math.round(feedback.overall_score || 0);
        
        // Display HR-specific scores if UI elements exist
        const communicationScoreEl = document.getElementById('communicationScore');
        if (communicationScoreEl && feedback.communication_score !== undefined) {
            communicationScoreEl.textContent = Math.round(feedback.communication_score);
        }
        
        const culturalFitScoreEl = document.getElementById('culturalFitScore');
        if (culturalFitScoreEl && feedback.cultural_fit_score !== undefined) {
            culturalFitScoreEl.textContent = Math.round(feedback.cultural_fit_score);
        }
        
        const motivationScoreEl = document.getElementById('motivationScore');
        if (motivationScoreEl && feedback.motivation_score !== undefined) {
            motivationScoreEl.textContent = Math.round(feedback.motivation_score);
        }
        
        const clarityScoreEl = document.getElementById('clarityScore');
        if (clarityScoreEl && feedback.clarity_score !== undefined) {
            clarityScoreEl.textContent = Math.round(feedback.clarity_score);
        }
        
        const strengthsList = document.getElementById('strengthsList');
        if (strengthsList) {
        strengthsList.innerHTML = (feedback.strengths || []).map(s => `<li>${s}</li>`).join('');
        }

        const improvementsList = document.getElementById('improvementsList');
        if (improvementsList) {
        improvementsList.innerHTML = (feedback.areas_for_improvement || []).map(a => `<li>${a}</li>`).join('');
        }

        const recommendationsList = document.getElementById('recommendationsList');
        if (recommendationsList) {
        recommendationsList.innerHTML = (feedback.recommendations || []).map(r => `<li>${r}</li>`).join('');
        }

        const feedbackSummaryEl = document.getElementById('feedbackSummary');
        if (feedbackSummaryEl) {
            feedbackSummaryEl.textContent = feedback.feedback_summary || 'No summary available.';
        }

        const feedbackLoading = document.getElementById('feedbackLoading');
        const feedbackContent = document.getElementById('feedbackContent');
        if (feedbackLoading) feedbackLoading.classList.add('hidden');
        if (feedbackContent) feedbackContent.classList.remove('hidden');

    } catch (error) {
        const errorObj = {
            message: error.message || 'Failed to generate feedback. Please try again.',
            status: error.status,
            originalError: error
        };
        showUserFriendlyError(errorObj, 'generateFeedback', true);
        
        // Fallback to basic feedback on error
        generateBasicFeedback();
    } finally {
        setLoadingState('generateFeedback', false);
    }
}

function generateBasicFeedback() {
    // Generate a simple, data-driven fallback based on the actual conversation
    // This is only used when the backend HR feedback endpoint is unavailable.
    const userMessages = conversationHistory.filter(m => m.role === 'user');
    const answerCount = userMessages.length;
    
    // ✅ FIX: Check if answers are valid (not empty, not "No Answer", and have at least 3 meaningful words)
    function isValidAnswer(answerText) {
        if (!answerText || typeof answerText !== 'string') return false;
        const trimmed = answerText.trim();
        if (trimmed === '' || trimmed === 'No Answer') return false;
        // Count meaningful words (exclude very short words)
        const words = trimmed.split(/\s+/).filter(w => w.length > 2);
        return words.length >= 3;
    }
    
    const validAnswers = userMessages.filter(m => isValidAnswer(m.content));
    const validAnswerCount = validAnswers.length;
    
    // ✅ FIX: If NO valid answers, return 0 score with appropriate feedback
    if (validAnswerCount === 0) {
        document.getElementById('overallScore').textContent = '0';
        document.getElementById('strengthsList').innerHTML = '<li>No valid response detected.</li>';
        document.getElementById('improvementsList').innerHTML = '<li>Please provide spoken answers to receive accurate feedback.</li>';
        document.getElementById('recommendationsList').innerHTML = '<li>Try answering all HR questions with clear, structured responses.</li>';
        document.getElementById('feedbackSummary').textContent = 'Interview ended early with no valid responses.';
        document.getElementById('feedbackLoading').classList.add('hidden');
        document.getElementById('feedbackContent').classList.remove('hidden');
        return;
    }
    
    // Calculate word count only for valid answers
    const totalWords = validAnswers.reduce((sum, m) => {
        if (!m.content) return sum;
        return sum + m.content.split(/\s+/).filter(Boolean).length;
    }, 0);
    const avgWords = validAnswerCount > 0 ? totalWords / validAnswerCount : 0;

    // ✅ FIX: Heuristic score based on valid answers only (start from 0, not 60)
    let score = 0;
    if (validAnswerCount >= 4) score += 20;
    else if (validAnswerCount >= 2) score += 10;
    if (avgWords >= 40) score += 25;
    else if (avgWords >= 20) score += 15;
    else if (avgWords >= 10) score += 5;
    // Ensure score is reasonable but never artificially high for empty answers
    score = Math.max(0, Math.min(85, Math.round(score)));

    const strengths = [];
    const improvements = [];
    const recommendations = [];

    if (validAnswerCount > 0) {
        strengths.push(`You completed ${validAnswerCount} question${validAnswerCount > 1 ? 's' : ''} and stayed engaged throughout the interview.`);
    }
    if (avgWords >= 35) {
        strengths.push('Your answers showed good depth and you provided reasonably detailed explanations.');
    } else if (avgWords >= 10) {
        improvements.push('Some answers were quite short; adding more specific examples would make them stronger.');
    }

    improvements.push('Try to structure answers clearly (Situation → Task → Action → Result) so your stories are easy to follow.');

    recommendations.push('Pick 3–5 common HR questions and practice answering them out loud using real examples from your experience.');

    document.getElementById('overallScore').textContent = String(score);
    document.getElementById('strengthsList').innerHTML = strengths.map(s => `<li>${s}</li>`).join('');
    document.getElementById('improvementsList').innerHTML = improvements.map(a => `<li>${a}</li>`).join('');
    document.getElementById('recommendationsList').innerHTML = recommendations.map(r => `<li>${r}</li>`).join('');
    document.getElementById('feedbackSummary').textContent =
        'We could not load the full AI report, so this quick summary is based on how many questions you answered and how detailed your responses were. For a richer, fully personalized report, please try the interview again when your connection is stable.';
    
    document.getElementById('feedbackLoading').classList.add('hidden');
    document.getElementById('feedbackContent').classList.remove('hidden');
}

function displayMessage(role, content, audioUrl = null) {
    const container = document.getElementById('conversationContainer');
    if (!container) {
        console.error('[HR INTERVIEW] Conversation container not found');
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
    
}

// Helper function to stop and destroy current HR audio completely
function stopAndDestroyCurrentHRAudio() {
    if (currentHRAudio) {
        console.log('[HR INTERVIEW TTS] 🛑 STOPPING AND DESTROYING current HR audio');
        console.debug('[HR INTERVIEW TTS] Previous audio src:', currentHRAudio.src?.substring(0, 100));
        console.debug('[HR INTERVIEW TTS] Previous audio paused:', currentHRAudio.paused);
        console.debug('[HR INTERVIEW TTS] Previous audio ended:', currentHRAudio.ended);
        
        // Pause and reset
        try {
            currentHRAudio.pause();
            currentHRAudio.currentTime = 0;
        } catch (e) {
            console.warn('[HR INTERVIEW TTS] Error pausing previous audio:', e);
        }
        
        // Remove all event listeners to prevent memory leaks
        currentHRAudio.onerror = null;
        currentHRAudio.onended = null;
        currentHRAudio.onloadeddata = null;
        currentHRAudio.onloadstart = null;
        currentHRAudio.onloadedmetadata = null;
        currentHRAudio.oncanplaythrough = null;
        currentHRAudio.onplay = null;
        currentHRAudio.onpause = null;
        currentHRAudio.onplaying = null;
        
        // Revoke blob URL if it exists
        if (currentHRAudio.src && currentHRAudio.src.startsWith('blob:')) {
            try {
                URL.revokeObjectURL(currentHRAudio.src);
                console.log('[HR INTERVIEW TTS] ✅ Revoked blob URL for previous audio');
            } catch (e) {
                console.warn('[HR INTERVIEW TTS] Error revoking blob URL:', e);
            }
        }
        
        // Clear src to fully release the audio element
        try {
            currentHRAudio.src = '';
            currentHRAudio.load(); // Reset the audio element
        } catch (e) {
            console.warn('[HR INTERVIEW TTS] Error clearing audio src:', e);
        }
        
        console.log('[HR INTERVIEW TTS] ✅ Previous HR audio destroyed');
        currentHRAudio = null;
        isAudioPlaying = false;
    }
    
    // Also clear the old currentAudio reference for compatibility
    if (currentAudio && currentAudio !== currentHRAudio) {
        try {
            currentAudio.pause();
            currentAudio.currentTime = 0;
            if (currentAudio.src && currentAudio.src.startsWith('blob:')) {
                URL.revokeObjectURL(currentAudio.src);
            }
            currentAudio = null;
        } catch (e) {
            console.warn('[HR INTERVIEW TTS] Error clearing old currentAudio:', e);
        }
    }
}

async function playAudio(audioUrl, retryCount = 0) {
    const MAX_RETRIES = 2;
    if (!audioUrl) {
        console.warn('[HR INTERVIEW TTS] No audio URL provided');
        console.debug('[HR DEBUG TTS] Early return: no audioUrl provided');
        return;
    }
    
    // ✅ CRITICAL FIX: ALWAYS stop and destroy any existing HR audio BEFORE starting new one
    console.log('[HR INTERVIEW TTS] ========== STARTING NEW AUDIO PLAYBACK ==========');
    console.log('[HR INTERVIEW TTS] Audio URL/Text:', String(audioUrl).substring(0, 80) + '...');
    console.log('[HR INTERVIEW TTS] Current HR audio exists:', currentHRAudio !== null);
    
    stopAndDestroyCurrentHRAudio();
    
    console.log('[HR INTERVIEW TTS] ✅ Previous audio stopped and destroyed, proceeding with new audio');
    
    try {
        console.log('[HR INTERVIEW TTS] Starting audio playback:', audioUrl);
        isAudioPlaying = true;
        
        // Update UI to show audio is playing
        const voiceStatus = document.getElementById('voiceStatus');
        const voiceButton = document.getElementById('voiceButton');
        if (voiceStatus) voiceStatus.textContent = 'Question is being spoken...';
        if (voiceButton) voiceButton.classList.add('listening');
        
        // Construct full URL if relative
        let fullUrl = audioUrl.startsWith('http') ? audioUrl : `${getApiBase()}${audioUrl}`;
        
        // ✅ DEBUG: Log before TTS endpoint call
        console.debug('[HR DEBUG TTS] ========== TTS ENDPOINT CALL ==========');
        console.debug('[HR DEBUG TTS] Original audioUrl:', audioUrl);
        console.debug('[HR DEBUG TTS] Constructed fullUrl:', fullUrl);
        console.debug('[HR DEBUG TTS] fullUrl includes text=:', fullUrl.includes('text='));
        console.debug('[HR DEBUG TTS] =======================================');
        
        // If URL contains text parameter, we need to fetch it via POST instead
        if (fullUrl.includes('text=')) {
            try {
                const url = new URL(fullUrl);
                const textParam = url.searchParams.get('text');
                if (textParam) {
                    const text = decodeURIComponent(textParam);
                    console.log('[HR INTERVIEW TTS] Fetching TTS audio for text:', text.substring(0, 50) + '...');
                    console.debug('[HR DEBUG TTS] About to call POST /api/interview/generate-audio');
                    console.debug('[HR DEBUG TTS] Text to convert:', text.substring(0, 100) + '...');
                    
                    // Use TECH_BACKEND_URL for audio generation (supports separate backend deployment)
                    const techBackendUrl = typeof window.getTechBackendUrl === 'function' 
                        ? window.getTechBackendUrl() 
                        : (typeof getTechBackendUrl !== 'undefined' ? getTechBackendUrl() : getApiBase());
                    const audioApiUrl = `${techBackendUrl}/api/interview/generate-audio`;
                    
                    // Use POST endpoint instead
                    const response = await fetch(audioApiUrl, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({ text: text.trim() })
                    });
                    
                    if (!response.ok) {
                        const errorText = await response.text();
                        console.error('[HR INTERVIEW TTS] TTS endpoint error:', response.status, errorText);
                        throw new Error(`TTS failed: ${response.status} - ${errorText}`);
                    }
                    
                    const audioBlob = await response.blob();
                    console.debug('[HR DEBUG TTS] TTS response status:', response.status);
                    console.debug('[HR DEBUG TTS] TTS response Content-Type:', response.headers.get('Content-Type'));
                    console.debug('[HR DEBUG TTS] Audio blob size:', audioBlob.size, 'bytes');
                    
                    if (audioBlob.size === 0) {
                        console.error('[HR INTERVIEW TTS] Empty audio blob received');
                        throw new Error('Empty audio blob received from TTS endpoint');
                    }
                    
                    console.log('[HR INTERVIEW TTS] ✅ Audio blob received, size:', audioBlob.size, 'bytes');
                    fullUrl = URL.createObjectURL(audioBlob);
                    console.log('[HR INTERVIEW TTS] Created blob URL:', fullUrl.substring(0, 50) + '...');
                    console.debug('[HR DEBUG TTS] Blob URL created:', fullUrl);
                }
            } catch (e) {
                console.error('[HR INTERVIEW TTS] ❌ Error fetching TTS audio:', e);
                throw e; // Re-throw to be caught by outer catch
            }
        }
        
        const audio = new Audio(fullUrl);
        // ✅ CRITICAL: Assign to global currentHRAudio - this is the ONLY audio that should exist
        currentHRAudio = audio;
        currentAudio = audio; // Also update for compatibility
        
        console.log('[HR INTERVIEW TTS] ✅ New Audio element created and assigned to currentHRAudio');
        console.debug('[HR INTERVIEW TTS] Audio src:', audio.src?.substring(0, 100));
        
        // ✅ DEBUG: Log before setting audio.src
        console.debug('[HR DEBUG TTS] ========== CREATING AUDIO ELEMENT ==========');
        console.debug('[HR DEBUG TTS] fullUrl before audio.src:', fullUrl);
        console.debug('[HR DEBUG TTS] Audio element created, about to set src');
        
        // ✅ DEBUG: Log after setting audio.src (implicitly set via Audio constructor)
        console.debug('[HR DEBUG TTS] audio.src after creation:', audio.src);
        console.debug('[HR DEBUG TTS] ============================================');
        
        // Set up event handlers BEFORE attempting to play
        audio.onerror = (error) => {
            console.error('[HR INTERVIEW TTS] ❌ Audio playback error:', error);
            console.error('[HR INTERVIEW TTS] ========== AUDIO ERROR EVENT ==========');
            console.error('[HR INTERVIEW TTS] Audio error details:', {
                code: audio.error?.code,
                message: audio.error?.message,
                src: audio.src?.substring(0, 100)
            });
            console.error('[HR INTERVIEW TTS] currentHRAudio === audio:', currentHRAudio === audio);
            
            isAudioPlaying = false;
            if (voiceButton) voiceButton.classList.remove('listening');
            if (voiceStatus) voiceStatus.textContent = 'Click the microphone to record your answer';
            
            if (fullUrl.startsWith('blob:')) {
                try {
                    URL.revokeObjectURL(fullUrl);
                    console.log('[HR INTERVIEW TTS] ✅ Revoked blob URL after error');
                } catch (e) {
                    console.warn('[HR INTERVIEW TTS] Error revoking blob URL:', e);
                }
            }
            
            // ✅ CRITICAL: Clear currentHRAudio on error
            if (currentHRAudio === audio) {
                console.log('[HR INTERVIEW TTS] 🧹 Clearing currentHRAudio (audio error)');
                currentHRAudio = null;
                currentAudio = null;
            }
            
            // Retry on error
            if (retryCount < MAX_RETRIES) {
                console.log(`[HR INTERVIEW TTS] Retrying audio playback (attempt ${retryCount + 1}/${MAX_RETRIES})...`);
                setTimeout(() => playAudio(audioUrl, retryCount + 1), 1000 * (retryCount + 1));
            } else {
                // Show manual play button if all retries failed
                showManualPlayButton(audioUrl);
                // After a terminal error on this item, advance the queue
                setTimeout(() => playNextFromHRAudio(), 100);
            }
        };
        
        audio.onended = () => {
            console.log('[HR INTERVIEW TTS] ✅ Audio playback completed');
            console.log('[HR INTERVIEW TTS] ========== AUDIO ENDED EVENT ==========');
            console.debug('[HR INTERVIEW TTS] Audio src:', audio.src?.substring(0, 100));
            console.debug('[HR INTERVIEW TTS] currentHRAudio === audio:', currentHRAudio === audio);
            
            isAudioPlaying = false;
            if (voiceButton) voiceButton.classList.remove('listening');
            if (voiceStatus) voiceStatus.textContent = 'Click the microphone to record your answer';
            
            if (fullUrl.startsWith('blob:')) {
                try {
                    URL.revokeObjectURL(fullUrl);
                    console.log('[HR INTERVIEW TTS] ✅ Revoked blob URL after playback completed');
                } catch (e) {
                    console.warn('[HR INTERVIEW TTS] Error revoking blob URL:', e);
                }
            }
            
            // ✅ CRITICAL: Clear currentHRAudio when audio ends
            if (currentHRAudio === audio) {
                console.log('[HR INTERVIEW TTS] 🧹 Clearing currentHRAudio (audio ended)');
                currentHRAudio = null;
                currentAudio = null;
            }

            // Audio finished successfully; play next queued item if any
            console.log('[HR INTERVIEW TTS] Checking queue for next audio...');
            setTimeout(() => playNextFromHRAudio(), 100);
        };
        
        audio.onloadeddata = () => {
            console.log('[HR INTERVIEW TTS] ✅ Audio data loaded, ready to play');
        };
        
        audio.onloadstart = () => {
            console.log('[HR INTERVIEW TTS] Audio loading started');
        };
        
        // ✅ FIX: Add additional event listeners for reliable playback verification
        audio.onloadedmetadata = () => {
            console.log('[HR INTERVIEW TTS] ✅ Audio metadata loaded');
        };
        
        audio.oncanplaythrough = () => {
            console.log('[HR INTERVIEW TTS] ✅ Audio can play through');
        };
        
        // ✅ FIX: Verify audio actually starts playing
        audio.onplay = () => {
            console.log('[HR INTERVIEW TTS] ✅ Audio actually started playing');
            console.log('[HR INTERVIEW TTS] ========== AUDIO PLAY EVENT ==========');
            console.debug('[HR INTERVIEW TTS] currentHRAudio === audio:', currentHRAudio === audio);
            console.debug('[HR INTERVIEW TTS] Only one audio should be playing now');
            isAudioPlaying = true;
            if (voiceStatus) voiceStatus.textContent = 'Question is being spoken...';
        };
        
        // ✅ FIX: Detect unexpected pauses
        audio.onpause = () => {
            console.log('[HR INTERVIEW TTS] ⚠️ Audio was paused');
            // If paused unexpectedly (not by user and not ended), show manual play button
            if (isAudioPlaying && !audio.ended && audio.currentTime > 0) {
                console.warn('[HR INTERVIEW TTS] Audio paused unexpectedly');
                isAudioPlaying = false;
                showManualPlayButton(audioUrl);
            }
        };
        
        // ✅ FIX: Detect when audio is actually playing (not just started)
        audio.onplaying = () => {
            console.log('[HR INTERVIEW TTS] ✅ Audio is now playing');
            isAudioPlaying = true;
        };
        
        // Attempt to play audio with Promise-based verification
        try {
            console.log('[HR INTERVIEW TTS] Attempting to play audio...');
            console.debug('[HR DEBUG TTS] ========== CALLING audio.play() ==========');
            console.debug('[HR DEBUG TTS] audio.src:', audio.src);
            console.debug('[HR DEBUG TTS] audio.readyState:', audio.readyState);
            console.debug('[HR DEBUG TTS] audio.paused:', audio.paused);
            console.debug('[HR DEBUG TTS] ==========================================');
            
            const playPromise = audio.play();
            
            // ✅ FIX: Handle play promise with proper error catching
            if (playPromise !== undefined) {
                await playPromise.catch(err => {
                    console.debug('[HR DEBUG TTS] audio.play() promise rejected in catch:', err);
                    console.debug('[HR DEBUG TTS] Error name:', err.name);
                    console.debug('[HR DEBUG TTS] Error message:', err.message);
                    // ✅ FIX: Catch ALL autoplay-related errors (not just NotAllowedError)
                    if (err.name === 'NotAllowedError' || 
                        err.name === 'NotSupportedError' ||
                        err.message.includes('autoplay') ||
                        err.message.includes('user interaction') ||
                        err.message.includes('play() request') ||
                        err.message.includes('not allowed')) {
                        console.warn('[HR INTERVIEW TTS] ⚠️ Autoplay blocked by browser policy:', err.message);
                        isAudioPlaying = false;
                        if (voiceButton) voiceButton.classList.remove('listening');
                        if (voiceStatus) {
                            voiceStatus.textContent = 'Click the play button below to hear the question';
                        }
                        // Show manual play button immediately
                        showManualPlayButton(audioUrl);
                        throw err; // Re-throw to be caught by outer catch
                    }
                    throw err; // Re-throw other errors
                });
                
                console.log('[HR INTERVIEW TTS] ✅ Audio play() promise resolved');
                console.debug('[HR DEBUG TTS] audio.play() promise resolved successfully');
                console.debug('[HR DEBUG TTS] audio.paused after resolve:', audio.paused);
                console.debug('[HR DEBUG TTS] isAudioPlaying after resolve:', isAudioPlaying);
                
                // ✅ FIX: Verify audio actually started playing after promise resolves
                await new Promise(resolve => setTimeout(resolve, 100));
                console.debug('[HR DEBUG TTS] After 100ms delay - audio.paused:', audio.paused);
                console.debug('[HR DEBUG TTS] After 100ms delay - isAudioPlaying:', isAudioPlaying);
                
                if (audio.paused || !isAudioPlaying) {
                    console.warn('[HR INTERVIEW TTS] ⚠️ Audio play() succeeded but audio is paused or not playing');
                    console.debug('[HR DEBUG TTS] Audio verification failed - showing manual play button');
                    isAudioPlaying = false;
                    showManualPlayButton(audioUrl);
                } else {
                    console.debug('[HR DEBUG TTS] ✅ Audio verification passed - audio is playing');
                }
            }
        } catch (playError) {
            console.debug('[HR DEBUG TTS] ========== audio.play() CATCH BLOCK ==========');
            console.debug('[HR DEBUG TTS] playError name:', playError.name);
            console.debug('[HR DEBUG TTS] playError message:', playError.message);
            console.debug('[HR DEBUG TTS] playError stack:', playError.stack);
            console.debug('[HR DEBUG TTS] =============================================');
            // ✅ FIX: Handle autoplay policy violation with comprehensive error detection
            if (playError.name === 'NotAllowedError' || 
                playError.name === 'NotSupportedError' ||
                playError.message.includes('autoplay') ||
                playError.message.includes('user interaction') ||
                playError.message.includes('play() request') ||
                playError.message.includes('not allowed')) {
                console.warn('[HR INTERVIEW TTS] ⚠️ Autoplay blocked by browser policy:', playError.message);
                isAudioPlaying = false;
                if (voiceButton) voiceButton.classList.remove('listening');
                if (voiceStatus) {
                    voiceStatus.textContent = 'Click the play button below to hear the question';
                }
                // Show manual play button
                showManualPlayButton(audioUrl);
                return; // Don't retry for autoplay errors
            } else {
                // Re-throw other errors
                throw playError;
            }
        }
        
    } catch (error) {
        console.error('[HR INTERVIEW TTS] ❌ Error in playAudio:', error);
        console.error('[HR INTERVIEW TTS] ========== PLAY AUDIO CATCH BLOCK ==========');
        console.error('[HR INTERVIEW TTS] Error details:', {
            name: error.name,
            message: error.message,
            stack: error.stack
        });
        console.error('[HR INTERVIEW TTS] currentHRAudio exists:', currentHRAudio !== null);
        
        isAudioPlaying = false;
        
        // ✅ CRITICAL: Clear currentHRAudio on error
        if (currentHRAudio) {
            console.log('[HR INTERVIEW TTS] 🧹 Clearing currentHRAudio (error in playAudio)');
            stopAndDestroyCurrentHRAudio();
        }
        
        const voiceButton = document.getElementById('voiceButton');
        const voiceStatus = document.getElementById('voiceStatus');
        if (voiceButton) voiceButton.classList.remove('listening');
        if (voiceStatus) voiceStatus.textContent = 'Click the microphone to record your answer';
        
        // ✅ FIX: Check if this is an autoplay error (don't retry)
        const isAutoplayError = error.name === 'NotAllowedError' || 
                                error.name === 'NotSupportedError' ||
                                error.message.includes('autoplay') ||
                                error.message.includes('user interaction') ||
                                error.message.includes('play() request') ||
                                error.message.includes('not allowed');
        
        if (isAutoplayError) {
            console.warn('[HR INTERVIEW TTS] Autoplay blocked, showing manual play button');
            showManualPlayButton(audioUrl);
            return;
        }
        
        // Retry on network/loading errors (but not autoplay errors)
        if (retryCount < MAX_RETRIES && 
            (error.message.includes('fetch') || 
             error.message.includes('network') || 
             error.message.includes('Failed to load') ||
             error.message.includes('NetworkError'))) {
            console.log(`[HR INTERVIEW TTS] Retrying due to network error (attempt ${retryCount + 1}/${MAX_RETRIES})...`);
            setTimeout(() => playAudio(audioUrl, retryCount + 1), 1000 * (retryCount + 1));
        } else {
            // ✅ FIX: Show manual play button after all retries exhausted or on non-retryable errors
            showManualPlayButton(audioUrl);
            // After we give up on this item, advance the queue
            setTimeout(() => playNextFromHRAudio(), 100);
        }
    }
    // ✅ FIX: Remove finally block - no loading state to reset (match Technical Interview)
}

// ✅ FIX: Helper function to show manual play button when autoplay fails
// This ensures users can always play audio even if autoplay is blocked
function showManualPlayButton(audioUrl) {
    // ✅ DEBUG: Log when manual play button is created
    console.debug('[HR DEBUG TTS] ========== SHOWING MANUAL PLAY BUTTON ==========');
    console.debug('[HR DEBUG TTS] audioUrl for manual button:', audioUrl);
    console.debug('[HR DEBUG TTS] ===============================================');
    
    const container = document.getElementById('conversationContainer');
    if (!container) {
        console.warn('[HR INTERVIEW TTS] Cannot show manual play button: container not found');
        return;
    }
    
    // ✅ FIX: Remove any existing manual play button first to avoid duplicates
    const existingButton = document.getElementById('manualPlayButton');
    if (existingButton) {
        console.debug('[HR DEBUG TTS] Removing existing manual play button');
        existingButton.remove();
    }
    
    // Create manual play button
    const playButton = document.createElement('button');
    playButton.id = 'manualPlayButton';
    playButton.className = 'btn btn-primary';
    playButton.style.cssText = 'margin: 10px auto; display: block; padding: 12px 24px; font-size: 15px; font-weight: 500; cursor: pointer; border-radius: 8px; background: var(--primary); color: white; border: none;';
    playButton.textContent = '▶ Play Question Audio';
    playButton.onclick = async () => {
        console.log('[HR INTERVIEW TTS] Manual play button clicked');
        try {
            // Enqueue manual audio so it still respects sequential playback
            enqueueHRAudio(audioUrl);
            // Remove button after enqueue
            setTimeout(() => {
                if (playButton.parentNode) {
                    playButton.remove();
                }
            }, 500);
        } catch (err) {
            console.error('[HR INTERVIEW TTS] Manual play enqueue failed:', err);
            // Keep button visible if enqueue fails
        }
    };
    
    // ✅ FIX: Insert after last AI message (question) for better UX
    const messages = container.querySelectorAll('.message.ai');
    const lastAiMessage = messages.length > 0 ? messages[messages.length - 1] : null;
    
    if (lastAiMessage) {
        lastAiMessage.appendChild(playButton);
    } else {
        // Fallback: append to container
        container.appendChild(playButton);
    }
    
    // Scroll to show the button
    container.scrollTop = container.scrollHeight;
    
    console.log('[HR INTERVIEW TTS] ✅ Manual play button displayed');
}

/**
 * Show user-friendly error message
 * Maps technical errors to clear, actionable messages for users
 * @param {Error|string} error - The error object or error message
 * @param {string} context - Context where the error occurred (e.g., 'startInterview', 'submitAnswer')
 * @param {boolean} showRetry - Whether to show a retry button for recoverable errors
 */
function showUserFriendlyError(error, context = 'unknown', showRetry = false) {
    // Log technical error to console for developers
    console.error(`[HR INTERVIEW ERROR] Context: ${context}`, error);
    
    let userMessage = 'An unexpected error occurred. Please try again.';
    let isRecoverable = false;
    
    // Extract error message
    const errorMessage = error?.message || error?.toString() || String(error);
    const errorStatus = error?.status || error?.response?.status;
    
    // Map technical errors to user-friendly messages
    if (errorMessage.includes('NetworkError') || 
        errorMessage.includes('Failed to fetch') || 
        errorMessage.includes('network') ||
        errorMessage.includes('Network request failed')) {
        userMessage = 'Network connection error. Please check your internet connection and try again.';
        isRecoverable = true;
    } else if (errorStatus === 404 || errorMessage.includes('404') || errorMessage.includes('not found')) {
        if (context === 'startInterview') {
            userMessage = 'User profile not found. Please upload a resume first to create your profile.';
        } else if (context === 'getNextQuestion' || context === 'submitAnswer') {
            userMessage = 'Interview session not found. Please start a new interview.';
        } else {
            userMessage = 'Resource not found. Please try starting a new interview.';
        }
        isRecoverable = false;
    } else if (errorStatus === 400 || errorMessage.includes('400') || errorMessage.includes('Bad Request')) {
        userMessage = 'Invalid request. Please check your input and try again.';
        isRecoverable = true;
    } else if (errorStatus === 500 || errorMessage.includes('500') || errorMessage.includes('Internal Server Error')) {
        userMessage = 'Server error occurred. Please try again in a moment.';
        isRecoverable = true;
    } else if (errorMessage.includes('microphone') || errorMessage.includes('Microphone')) {
        userMessage = 'Microphone access denied. Please allow microphone access in your browser settings and try again.';
        isRecoverable = true;
    } else if (errorMessage.includes('session') || errorMessage.includes('Session')) {
        userMessage = 'Interview session expired. Please start a new interview.';
        isRecoverable = false;
    } else if (errorMessage.includes('user_id') || errorMessage.includes('user profile')) {
        userMessage = 'User profile not found. Please upload a resume first.';
        isRecoverable = false;
    } else if (errorMessage) {
        // Use error message if it's already user-friendly
        userMessage = errorMessage;
    }
    
    // Display error in UI
    // If showing retry button, it will display the error message, so don't show it twice
    if (showRetry && isRecoverable) {
        // Retry button will display the error message, so skip showError()
        showRetryButton(context, userMessage);
    } else {
        // No retry button, so show the error message directly
        showError(userMessage);
    }
    
    return { userMessage, isRecoverable };
}

/**
 * Show retry button for recoverable errors
 */
function showRetryButton(context, errorMessage) {
    const container = document.getElementById('conversationContainer');
    if (!container) return;
    
    // Check if retry button already exists
    let retryContainer = document.getElementById('retryErrorContainer');
    if (!retryContainer) {
        retryContainer = document.createElement('div');
        retryContainer.id = 'retryErrorContainer';
        retryContainer.className = 'error-retry-container';
        retryContainer.style.cssText = 'margin: 15px 0; padding: 15px; background: #fff3cd; border: 1px solid #ffc107; border-radius: 4px;';
        container.appendChild(retryContainer);
    }
    
    retryContainer.innerHTML = `
        <div style="margin-bottom: 10px;">
            <strong>⚠️ ${errorMessage}</strong>
        </div>
        <button id="retryButton" style="background: #ff9800; color: white; border: none; padding: 8px 16px; border-radius: 4px; cursor: pointer;">
            🔄 Retry
        </button>
    `;
    
    // Add retry handler
    const retryButton = document.getElementById('retryButton');
    retryButton.onclick = () => {
        retryContainer.remove();
        retryAction(context);
    };
    
    container.scrollTop = container.scrollHeight;
}

/**
 * Retry action based on context
 */
async function retryAction(context) {
    try {
        switch (context) {
            case 'startInterview':
                await startInterview();
                break;
            case 'submitAnswer':
                // Re-enable submit button, user can try again
                setLoadingState('submitAnswer', false);
                document.getElementById('voiceStatus').textContent = 'Click the microphone to record your answer';
                break;
            case 'getNextQuestion':
                await getNextHRQuestion();
                break;
            case 'generateFeedback':
                await generateFeedback();
                break;
            case 'playAudio':
                // Audio retry is handled within playAudio function
                break;
            default:
                console.warn(`[HR INTERVIEW] Unknown retry context: ${context}`);
        }
    } catch (error) {
        showUserFriendlyError(error, context, true);
    }
}

/**
 * Set loading state for a specific operation
 */
function setLoadingState(operation, loading) {
    isLoading[operation] = loading;
    
    // Update UI based on operation
    switch (operation) {
        case 'startInterview':
            const startBtn = document.getElementById('startInterviewBtn');
            if (startBtn) {
                startBtn.disabled = loading;
                startBtn.textContent = loading ? 'Starting...' : 'Start HR Interview';
            }
            break;
        case 'submitAnswer':
            const voiceBtn = document.getElementById('voiceButton');
            if (voiceBtn) {
                voiceBtn.disabled = loading;
            }
            const voiceStatus = document.getElementById('voiceStatus');
            if (voiceStatus && loading) {
                voiceStatus.textContent = 'Processing...';
            }
            break;
        case 'getNextQuestion':
            // No specific button for this, but we can show loading in status
            break;
        case 'generateFeedback':
            const feedbackLoading = document.getElementById('feedbackLoading');
            if (feedbackLoading) {
                if (loading) {
                    feedbackLoading.classList.remove('hidden');
                } else {
                    feedbackLoading.classList.add('hidden');
                }
            }
            break;
    }
}

function showError(message) {
    const container = document.getElementById('conversationContainer');
    if (!container) {
        // Fallback to alert if container not found
        alert(message);
        return;
    }
    const errorDiv = document.createElement('div');
    errorDiv.className = 'error-message';
    errorDiv.textContent = message;
    container.appendChild(errorDiv);
    container.scrollTop = container.scrollHeight;
}

// Modal confirmation function (replaces browser confirm)
function showConfirmation(title, message) {
    console.log('[HR INTERVIEW] showConfirmation called with:', { title, message });
    return new Promise((resolve) => {
        const modal = document.getElementById('confirmationModal');
        const modalTitle = document.getElementById('modalTitle');
        const modalMessage = document.getElementById('modalMessage');
        const confirmBtn = document.getElementById('modalConfirmBtn');
        const cancelBtn = document.getElementById('modalCancelBtn');

        // Error check: ensure all elements exist
        if (!modal || !modalTitle || !modalMessage || !confirmBtn || !cancelBtn) {
            console.error('[HR INTERVIEW] Modal elements not found:', {
                modal: !!modal,
                modalTitle: !!modalTitle,
                modalMessage: !!modalMessage,
                confirmBtn: !!confirmBtn,
                cancelBtn: !!cancelBtn
            });
            // DO NOT fallback to browser confirm - this is the old behavior we're replacing
            // Instead, show error and resolve false
            alert('Error: Modal elements not found. Please refresh the page.');
            resolve(false);
            return;
        }

        // Set modal content
        modalTitle.textContent = title;
        modalMessage.textContent = message;

        // Show modal
        modal.classList.add('show');

        // Handle confirm - use once: true to auto-remove after first click
        const handleConfirm = (e) => {
            e.preventDefault();
            e.stopPropagation();
            modal.classList.remove('show');
            resolve(true);
        };

        // Handle cancel - use once: true to auto-remove after first click
        const handleCancel = (e) => {
            e.preventDefault();
            e.stopPropagation();
            modal.classList.remove('show');
            resolve(false);
        };

        // Remove any existing listeners by cloning and replacing buttons
        const newConfirmBtn = confirmBtn.cloneNode(true);
        confirmBtn.parentNode.replaceChild(newConfirmBtn, confirmBtn);
        
        const newCancelBtn = cancelBtn.cloneNode(true);
        cancelBtn.parentNode.replaceChild(newCancelBtn, cancelBtn);
        
        // Get fresh references to the new buttons
        const finalConfirmBtn = document.getElementById('modalConfirmBtn');
        const finalCancelBtn = document.getElementById('modalCancelBtn');
        
        // Add event listeners to the new buttons
        finalConfirmBtn.addEventListener('click', handleConfirm, { once: true });
        finalCancelBtn.addEventListener('click', handleCancel, { once: true });

        // Prevent closing by clicking outside (as per requirements)
        // No event listener on overlay, so clicking outside won't close modal
    });
}

async function endInterview() {
    console.log('[HR INTERVIEW] endInterview called');
    
    const confirmed = await showConfirmation(
        'End Interview?',
        'Are you sure you want to end your HR Interview? Your progress will be saved.'
    );
    
    console.log('[HR INTERVIEW] User confirmed:', confirmed);
    
    if (confirmed) {
        interviewActive = false;
        
        if (isRecording) {
            stopRecording();
        }

        if (interviewSessionId) {
            try {
                // Get API base URL using helper function
                const API_BASE = typeof window.getApiBase === 'function' ? window.getApiBase() : getApiBase();
                
                // FIX: Use HR-specific endpoint instead of technical endpoint
                const response = await fetch(`${API_BASE}/api/interview/hr/${interviewSessionId}/end`, {
                    method: 'POST'
                }).catch(networkError => {
                    console.error('[HR INTERVIEW] Network error ending interview:', networkError);
                    // Don't show toast for end interview - it's not critical
                });
                
                if (response.ok) {
                    // Log successful attempt to end session
                    console.log(`[HR INTERVIEW] End signal sent for session: ${interviewSessionId}`);
                } else {
                    console.warn(`[HR INTERVIEW] End signal returned status: ${response.status}`);
                }
            } catch (error) {
                // Keep existing robust error logging
                console.error('[HR INTERVIEW] Error sending end signal to backend:', error);
                // NOTE: Consider adding showUserFriendlyError() here (Error 7 improvement)
            }
        }

        await completeInterview();
    }
}

