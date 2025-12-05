/**
 * Skill Capital AI MockMate - Frontend
 * Lightweight JavaScript for simple, clean interface
 * 
 * NOTE: This file requires api-config.js to be loaded first
 * api-config.js provides: getApiBase(), ensureApiBaseReady(), API_BASE
 */

// API configuration is provided by api-config.js
// Use getApiBase() function to get the API base URL
// Use ensureApiBaseReady() to wait for API config to be ready

// ============================================================================
// FIX 3 & FIX 6: CRITICAL - Initialize user_id state at script start
// We will check sessionStorage in initializeSession() to determine if it's a new session
// ============================================================================
// Force currentUserId to null at the very start (will be restored if valid session exists)
let currentUserId = null;
if (typeof window !== 'undefined') {
    window.CURRENT_USER_ID = null;
}

// DO NOT clear sessionStorage here - let initializeSession() handle it based on session marker
// This allows user_id to persist when navigating between pages in the same session

// State (after clearing user_id)
let currentSessionId = null;
let currentQuestionNum = 0;
let totalQuestions = 0;
let interviewMode = 'text';
let timerInterval = null;
let timeRemaining = 60;

// FIX 3 & FIX 6: Session management - create session marker and preserve user_id within same session
// Only clear user_id if it's a NEW session (no session marker exists)
// This allows user_id to persist when navigating between pages in the same session
function initializeSession() {
    // Check if this is a new session (no session marker exists)
    const sessionMarker = sessionStorage.getItem('app_session_id');
    const existingUserId = sessionStorage.getItem('session_user_id') || sessionStorage.getItem('resume_user_id');
    
    if (!sessionMarker) {
        // NEW SESSION - Clear ALL user_id data to prevent stale data from previous sessions
        if (existingUserId) {
            console.log('[SESSION] 🔥 NEW SESSION: Clearing stale sessionStorage user_id from previous session:', existingUserId);
            sessionStorage.removeItem('session_user_id');
            sessionStorage.removeItem('resume_user_id');
        }
        
        // Also clear localStorage user_id
        if (localStorage.getItem('user_id')) {
            console.log('[SESSION] 🔥 NEW SESSION: Clearing stale localStorage user_id');
            localStorage.removeItem('user_id');
        }
        
        // Generate unique session ID for new session
        const newSessionId = `session_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
        sessionStorage.setItem('app_session_id', newSessionId);
        console.log('[SESSION] ✅ New session created:', newSessionId);
        
        // Reset currentUserId for new session
        currentUserId = null;
        if (typeof window !== 'undefined') {
            window.CURRENT_USER_ID = null;
        }
    } else {
        // EXISTING SESSION - Preserve user_id if it exists (user may be returning from resume-analysis page)
        console.log('[SESSION] ✅ Existing session marker found:', sessionMarker);
        if (existingUserId) {
            console.log('[SESSION] ✅ Preserving user_id from current session:', existingUserId);
            // Restore currentUserId from sessionStorage for this session
            currentUserId = existingUserId;
            if (typeof window !== 'undefined') {
                window.CURRENT_USER_ID = existingUserId;
            }
        } else {
            // No user_id in existing session - reset currentUserId
            currentUserId = null;
            if (typeof window !== 'undefined') {
                window.CURRENT_USER_ID = null;
            }
        }
    }
    
    // Always clear localStorage user_id (we only use sessionStorage)
    if (localStorage.getItem('user_id')) {
        console.log('[SESSION] Clearing localStorage user_id (we only use sessionStorage)');
        localStorage.removeItem('user_id');
    }
    
    return sessionStorage.getItem('app_session_id');
}

// FIX 2: Validate user_id belongs to current session - STRICT validation
// Returns false if sessionStorage is empty or userId doesn't match stored user
function validateUserIdForSession(userId) {
    const sessionMarker = sessionStorage.getItem('app_session_id');
    const sessionUserId = sessionStorage.getItem('session_user_id');
    const resumeUserId = sessionStorage.getItem('resume_user_id');
    
    // FIX 2: No session marker = invalid
    if (!sessionMarker) {
        console.log('[VALIDATE] ❌ No session marker found - user_id invalid');
        return false;
    }
    
    // FIX 2: No userId provided = invalid
    if (!userId) {
        console.log('[VALIDATE] ❌ No userId provided - invalid');
        return false;
    }
    
    // FIX 2: If sessionStorage has NO user_id stored, return false (prevents stale user_ids from passing)
    // This is CRITICAL - we must have a user_id in sessionStorage that matches
    if (!sessionUserId && !resumeUserId) {
        console.log('[VALIDATE] ❌ No user_id in sessionStorage - stale user_id rejected:', userId);
        return false;
    }
    
    // FIX 2: user_id MUST match the stored session_user_id or resume_user_id
    // If there's a mismatch, it's a stale user_id from a previous session
    if (sessionUserId && sessionUserId !== userId) {
        console.log('[VALIDATE] ❌ user_id mismatch with session:', userId, 'vs', sessionUserId);
        return false;
    }
    
    if (resumeUserId && resumeUserId !== userId) {
        console.log('[VALIDATE] ❌ user_id mismatch with resume_user_id:', userId, 'vs', resumeUserId);
        return false;
    }
    
    // Only return true if userId matches the stored user_id in sessionStorage
    console.log('[VALIDATE] ✅ user_id validated:', userId);
    return true;
}

// BUG FIX #1 & #4: Store user_id with session marker
function storeUserIdWithSession(userId) {
    if (!userId) return;
    
    const sessionMarker = sessionStorage.getItem('app_session_id');
    if (!sessionMarker) {
        // Create session if it doesn't exist
        initializeSession();
    }
    
    // CRITICAL FIX: ONLY store in sessionStorage - NEVER localStorage
    // localStorage persists across sessions and causes stale data (e.g., haripriya-chintagunti)
    // We ONLY use sessionStorage which is session-scoped and cleared on new sessions
    sessionStorage.setItem('session_user_id', userId);
    sessionStorage.setItem('resume_user_id', userId);
    
    console.log('[SESSION] Stored user_id in sessionStorage only (session-scoped):', userId);
}

// BUG FIX #1 & #4: Clear user_id and session data
function clearUserSession() {
    localStorage.removeItem('user_id');
    sessionStorage.removeItem('session_user_id');
    sessionStorage.removeItem('resume_user_id');
    currentUserId = null;
    window.CURRENT_USER_ID = null;
    console.log('[SESSION] Cleared user session data');
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    // BUG FIX #1 & #4: Initialize session first
    initializeSession();
    init();
});

// FIX 4: visibilitychange handler - MUST do nothing if currentUserId is null
// This prevents dashboard/profile loads on initial page load
document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
        // FIX 4: Only reload if currentUserId exists AND was set in THIS page load (after resume upload)
        // If currentUserId is null, do NOTHING (prevents loading stale data on initial page load)
        if (!currentUserId) {
            console.log('[VISIBILITY] ❌ BLOCKED: No currentUserId - skipping reload (user must upload resume first)');
            return; // Exit early - do nothing
        }
        
        // FIX 2: Validate user_id belongs to current session before reloading
        if (!validateUserIdForSession(currentUserId)) {
            console.log('[VISIBILITY] ❌ BLOCKED: Invalid user_id - skipping reload');
            clearUserSession();
            return; // Exit early - do nothing
        }
        
        // Only reload if we have a valid, session-scoped user_id
        console.log('[VISIBILITY] ✅ Valid user_id found (from resume upload) - reloading profile and dashboard');
        loadProfile();
        loadDashboard();
    }
});

// FIX 1: Get current authenticated user - ONLY called after resume upload
// This function MUST NOT be called automatically on page load
// It will ONLY be called after a successful resume upload sets a user_id
async function getCurrentUser() {
    // FIX 1: Block execution if no user_id exists (prevents automatic calls on page load)
    if (!currentUserId) {
        console.log('[AUTH] ❌ BLOCKED: getCurrentUser() called without currentUserId - no API call made');
        return null;
    }
    
    try {
        // FIX 2: Validate user_id belongs to current session before making API call
        if (!validateUserIdForSession(currentUserId)) {
            console.log('[AUTH] ❌ user_id does not belong to current session, clearing stale data');
            clearUserSession();
            return null;
        }
        
        // FIX 5: Pass session_id to backend for validation
        const sessionMarker = sessionStorage.getItem('app_session_id');
        const apiBase = getApiBase();
        const sessionParam = sessionMarker ? `&session_id=${encodeURIComponent(sessionMarker)}` : '';
        const res = await fetch(`${apiBase}/api/profile/current?user_id=${encodeURIComponent(currentUserId)}${sessionParam}`, {
            cache: 'no-store',
            headers: {
                'Cache-Control': 'no-cache, no-store, must-revalidate',
                'Pragma': 'no-cache'
            }
        });
        
        if (!res.ok) {
            if (res.status === 404) {
                // Profile not found for this user_id - user needs to upload resume
                console.log(`[AUTH] Profile not found for user_id: ${currentUserId} - user needs to upload resume`);
                clearUserSession();
                return null;
            }
            throw new Error(`Failed to get current user: ${res.status}`);
        }
        
        const user = await res.json();
        
        // CRITICAL: Verify the returned user_id matches the requested user_id
        if (user.user_id !== currentUserId) {
            console.error(`[AUTH] ❌ SECURITY: User ID mismatch! Requested: ${currentUserId}, Received: ${user.user_id}`);
            clearUserSession();
            throw new Error('User ID mismatch - received wrong user profile');
        }
        
        console.log('[AUTH] Current authenticated user:', currentUserId);
        return user;
    } catch (e) {
        // Network error or other issue - don't throw, just log
        console.error('[AUTH] Error fetching current user:', e.message);
        return null;
    }
}

// FIX 4 & FIX 5: Initialize app - load profile/dashboard if valid user_id exists in current session
async function init() {
    console.log('[INIT] Initializing app...');
    
    // Always set up event listeners first - this is critical for upload to work
    // Use setTimeout to ensure DOM is fully ready
    setTimeout(() => {
        console.log('[INIT] Setting up event listeners after DOM ready...');
        setupEventListeners();
    }, 100);
    
    // FIX 4 & FIX 5: Check if we have a valid user_id from current session (set after resume upload)
    // initializeSession() preserves user_id if it belongs to the current session
    // If user_id exists and is valid, load profile and dashboard
    const sessionUserId = sessionStorage.getItem('session_user_id') || sessionStorage.getItem('resume_user_id');
    
    if (sessionUserId && validateUserIdForSession(sessionUserId)) {
        // Valid user_id found in current session - restore it and load data
        console.log('[INIT] ✅ Valid user_id found in current session:', sessionUserId);
        currentUserId = sessionUserId;
        if (typeof window !== 'undefined') {
            window.CURRENT_USER_ID = sessionUserId;
        }
        
        // FIX 4 & FIX 5: Load profile and dashboard with the valid user_id
        console.log('[INIT] ✅ Loading profile and dashboard for user:', sessionUserId);
        await loadProfile();
        await loadDashboard();
            } else {
        // No valid user_id - show empty state
        console.log('[INIT] ❌ No valid user_id found - showing empty state. User must upload resume first.');
        const profileContent = document.getElementById('profileContent');
        if (profileContent) {
            profileContent.innerHTML = '<p style="color: #666; padding: 20px; text-align: center;">No profile found yet. Upload your resume below to create your profile and get started!</p>';
        }
        
        // Clear any invalid user_id
        if (sessionUserId) {
            console.log('[INIT] ❌ Invalid user_id detected, clearing:', sessionUserId);
            clearUserSession();
        }
    }
}

// CRITICAL: Track if event listeners are already attached to prevent duplicates
let eventListenersAttached = false;

function setupEventListeners() {
    // CRITICAL FIX: Prevent duplicate event listeners
    // If listeners are already attached, don't attach them again
    if (eventListenersAttached) {
        console.log('[SETUP] Event listeners already attached, skipping to prevent duplicates');
        return;
    }
    
    // File upload - check if elements exist before attaching listeners
    const fileInput = document.getElementById('fileInput');
    const uploadBtn = document.getElementById('uploadBtn');
    const uploadArea = document.getElementById('uploadArea');

    console.log('Setting up event listeners...');
    console.log('fileInput found:', !!fileInput);
    console.log('uploadBtn found:', !!uploadBtn);
    console.log('uploadArea found:', !!uploadArea);

    if (fileInput && uploadBtn) {
        // CRITICAL DIAGNOSTIC: Check for duplicate elements in DOM
        const allFileInputs = document.querySelectorAll('input[type="file"][id="fileInput"]');
        const allLabels = document.querySelectorAll('label[for="fileInput"]');
        console.log('[DIAG] Total fileInput elements in DOM:', allFileInputs.length);
        console.log('[DIAG] Total labels with for="fileInput" in DOM:', allLabels.length);
        
        if (allFileInputs.length > 1) {
            console.error('[DIAG] ❌ DUPLICATE FILE INPUT ELEMENTS DETECTED! Removing duplicates.');
            // Remove duplicates, keep only the first one
            for (let i = 1; i < allFileInputs.length; i++) {
                console.log('[DIAG] Removing duplicate fileInput #' + i);
                allFileInputs[i].remove();
            }
            // Re-get the fileInput after removing duplicates
            const fileInput = document.getElementById('fileInput');
        }
        
        if (allLabels.length > 1) {
            console.error('[DIAG] ❌ DUPLICATE LABELS DETECTED! Removing duplicates.');
            // Remove duplicates, keep only the first one
            for (let i = 1; i < allLabels.length; i++) {
                console.log('[DIAG] Removing duplicate label #' + i);
                allLabels[i].remove();
            }
            // Re-get the uploadBtn after removing duplicates
            const uploadBtn = document.getElementById('uploadBtn');
        }
        
        // Ensure file input is accessible and not disabled
            fileInput.disabled = false;
            fileInput.removeAttribute('disabled');
            fileInput.style.display = 'none'; // Hide but keep accessible
        console.log('[DIAG] File input is ready, disabled:', fileInput.disabled);
        
        // CRITICAL FIX: Label's for="fileInput" automatically triggers fileInput when clicked
        // Do NOT add any event listener to uploadBtn - it interferes with label's native behavior
        // The label's for="fileInput" attribute handles the click automatically
        console.log('[DIAG] Upload button uses label\'s native for="fileInput" behavior (no event listener)');
        
        // CRITICAL FIX: Prevent file input from being triggered multiple times
        // Use a flag to block rapid successive clicks
        let fileInputClickBlocked = false;
        
        // CRITICAL FIX: Override fileInput.click() to prevent double triggers
        const originalClick = fileInput.click.bind(fileInput);
        fileInput.click = function() {
            if (fileInputClickBlocked) {
                console.log('[DIAG] fileInput.click() blocked - already triggered recently');
                return;
            }
            fileInputClickBlocked = true;
            console.log('[DIAG] fileInput.click() called - allowing');
            originalClick();
            // Unblock after a short delay to allow file selection
            setTimeout(() => {
                fileInputClickBlocked = false;
            }, 1000);
        };
        
        // CRITICAL FIX: Define change handler as named function stored globally
        // This allows us to check if it's already attached and prevent duplicates
        if (!window.handleFileInputChange) {
            window.handleFileInputChange = function(e) {
                console.log('[DIAG] === FILE INPUT CHANGED EVENT FIRED ===');
                console.log('[DIAG] Event target:', e.target);
                console.log('[DIAG] Event target ID:', e.target.id);
                console.log('[DIAG] Files:', e.target.files);
                console.log('[DIAG] File count:', e.target.files ? e.target.files.length : 0);
                
                // Unblock immediately when file is selected
                fileInputClickBlocked = false;
            
            if (e.target.files && e.target.files.length > 0) {
                const selectedFile = e.target.files[0];
                    console.log('[DIAG] File selected:', {
                    name: selectedFile.name,
                    size: selectedFile.size,
                    type: selectedFile.type
                });
                    console.log('[DIAG] Calling handleFileUpload...');
                handleFileUpload(e);
            } else {
                    console.warn('[DIAG] No files selected - user may have cancelled');
                }
            };
        }
        
        // CRITICAL FIX: Check if change listener is already attached using data attribute
        // This prevents duplicate listeners without breaking the label's for="fileInput" binding
        if (!fileInput.hasAttribute('data-change-listener-attached')) {
            fileInput.addEventListener('change', window.handleFileInputChange);
            fileInput.setAttribute('data-change-listener-attached', 'true');
            console.log('[DIAG] File input change listener attached (first time)');
        } else {
            console.log('[DIAG] File input change listener already attached, skipping duplicate');
        }
        
        // CRITICAL FIX: Do NOT attach any click handler to uploadArea
        // The label's for="fileInput" handles button clicks automatically via native browser behavior
        // Any click handler on uploadArea can interfere with label's native behavior and cause double triggers
        // The label's native behavior is sufficient - no JavaScript click handler needed
        console.log('[SETUP] Upload area click handler NOT attached - relying on label\'s native for="fileInput" behavior');
        
        // Mark listeners as attached
        eventListenersAttached = true;
        console.log('[SETUP] Event listeners attached successfully');
    } else {
        console.error('File upload elements not found. Required IDs: fileInput, uploadBtn');
        if (!fileInput) console.error('Missing: #fileInput');
        if (!uploadBtn) console.error('Missing: #uploadBtn');
    }

    // Drag and drop - check if upload area exists
    if (uploadArea) {
        uploadArea.addEventListener('dragover', (e) => {
            e.preventDefault();
            e.stopPropagation();
            uploadArea.style.borderColor = '#64B5F6';
        });
        
        uploadArea.addEventListener('dragleave', (e) => {
            e.preventDefault();
            e.stopPropagation();
            uploadArea.style.borderColor = '#E0E0E0';
        });
        
        uploadArea.addEventListener('drop', (e) => {
            e.preventDefault();
            e.stopPropagation();
            uploadArea.style.borderColor = '#E0E0E0';
            if (e.dataTransfer.files.length > 0 && fileInput) {
                fileInput.files = e.dataTransfer.files;
                handleFileUpload({ target: fileInput });
            }
        });
    }

    // Chat buttons - check if elements exist
    const submitBtn = document.getElementById('submitBtn');
    const endBtn = document.getElementById('endBtn');
    
    if (submitBtn) {
        submitBtn.addEventListener('click', submitAnswer);
    }
    if (endBtn) {
        endBtn.addEventListener('click', endInterview);
    }
}

// FIX 1 & FIX 6: loadProfile - ONLY runs after resume upload sets currentUserId
async function loadProfile() {
    const content = document.getElementById('profileContent');
    if (!content) {
        console.warn('Profile content element not found');
        return;
    }

    // FIX 1 & FIX 6: ONLY use currentUserId set after resume upload - NEVER read from storage
    // sessionStorage is cleared on every page load, so we only use currentUserId from this page load
    const userId = currentUserId; // Only use local variable set after resume upload

    // FIX 1 & FIX 6: If no user_id found, show empty state and return immediately - BLOCK API CALLS
    if (!userId) {
        console.log('[PROFILE] ❌ BLOCKED: No user_id found - showing empty state. User must upload resume first.');
        content.innerHTML = '<p style="color: #666; padding: 20px; text-align: center;">No profile found yet. Upload your resume below to create your profile and get started!</p>';
        return; // Exit early - no API calls
    }

    // FIX 2: Validate user_id belongs to current session BEFORE making API call
    if (!validateUserIdForSession(userId)) {
        console.log('[PROFILE] ❌ BLOCKED: user_id does not belong to current session, clearing stale data');
        clearUserSession();
        content.innerHTML = '<p style="color: #666; padding: 20px; text-align: center;">No profile found yet. Upload your resume below to create your profile and get started!</p>';
        return; // Exit early - no API calls
    }

    // Ensure API_BASE is configured before making requests
    await ensureApiBaseReady();

    // FIX 2 & FIX 3: Always fetch fresh profile data from server (no cache)
    console.log('[PROFILE] ✅ Loading fresh profile data from server (no cache)');

    // FIX 2: Only fetch profile if user_id is valid for current session (already validated above)
        try {
            // Ensure API_BASE is set before making request
            const apiBase = getApiBase();
        // BUG FIX #2: Add cache-busting parameter and session_id for validation
        const timestamp = Date.now();
        const sessionMarker = sessionStorage.getItem('app_session_id');
        const sessionParam = sessionMarker ? `&session_id=${encodeURIComponent(sessionMarker)}` : '';
        const profileUrl = `${apiBase}/api/profile/${userId}?_t=${timestamp}${sessionParam}`;
        
        console.log('[PROFILE] Fetching profile from:', profileUrl);
            
            // Make request with timeout and better error handling
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 30000); // 30 second timeout
            
            let res;
            try {
            // BUG FIX #2: Ensure no caching at all levels
                res = await fetch(profileUrl, {
                    method: 'GET',
                    headers: {
                        'Content-Type': 'application/json',
                    'Cache-Control': 'no-cache, no-store, must-revalidate',
                    'Pragma': 'no-cache',
                    'Expires': '0'
                    },
                    signal: controller.signal,
                    mode: 'cors', // Explicitly set CORS mode
                credentials: 'omit', // Don't send credentials for CORS
                cache: 'no-store' // Ensure no caching
                });
                clearTimeout(timeoutId);
            } catch (fetchError) {
                clearTimeout(timeoutId);
                
                // Handle different types of fetch errors
                if (fetchError.name === 'AbortError') {
                    throw new Error('Request timeout - server took too long to respond. Please check if the backend server is running.');
                } else if (fetchError.message.includes('Failed to fetch') || fetchError.message.includes('NetworkError')) {
                    throw new Error('Cannot connect to server. Please ensure the backend server is running and accessible. Check console for details.');
                } else {
                    throw new Error(`Network error: ${fetchError.message}`);
                }
            }
            
            if (res.status === 404) {
                content.innerHTML = '<p style="color: #666; padding: 20px; text-align: center;">No profile found. Upload a resume to create your profile.</p>';
                return;
            }
            
            if (!res.ok) {
                // Try to get error message from response
                let errorMessage = `Failed to load profile: ${res.status} ${res.statusText}`;
                try {
                    const errorData = await res.json();
                    errorMessage = errorData.detail || errorData.error || errorMessage;
                } catch (parseError) {
                    // Response might not be JSON - try to get text
                    try {
                        const errorText = await res.text();
                        if (errorText) {
                            errorMessage = errorText.substring(0, 200); // Limit length
                        }
                    } catch (textError) {
                        // Can't read response at all
                    }
                }
                console.error('[PROFILE] Error response:', errorMessage);
                throw new Error(errorMessage);
            }
            
            const profile = await res.json();
        console.log('[PROFILE] Fresh profile data received:', {
            name: profile.name,
            email: profile.email,
            experience: profile.experience_level,
            skills_count: profile.skills?.length || 0,
            has_resume: !!(profile.resume_url || profile.resume_text)
        });
            displayProfile(profile);
        } catch (e) {
            console.error('[PROFILE] Error loading profile:', e);
            console.error('[PROFILE] Error name:', e.name);
            console.error('[PROFILE] Error message:', e.message);
            console.error('[PROFILE] Error stack:', e.stack);
            
            // Show more specific error message based on error type
            let errorMsg = e.message || 'Unknown error';
            
            // Provide helpful guidance based on error
            if (errorMsg.includes('timeout') || errorMsg.includes('too long')) {
                errorMsg = 'Server timeout. Please check if the backend server is running.';
            } else if (errorMsg.includes('Cannot connect') || errorMsg.includes('Failed to fetch') || errorMsg.includes('NetworkError')) {
                errorMsg = 'Cannot connect to server. Please ensure the backend server is running at ' + getApiBase();
            } else if (errorMsg.includes('CORS')) {
                errorMsg = 'CORS error. Please check backend CORS configuration.';
            }
            
            content.innerHTML = `<p style="color: #999; padding: 20px; text-align: center;">Unable to load profile: ${errorMsg}. <br><small>Check browser console (F12) for more details.</small></p>`;
        }
}

function displayProfile(profile) {
    // CRITICAL: Display only resume-extracted data
    // Show empty values if no resume uploaded (no hard-coded defaults)
    const skills = profile.skills || [];
    const skillsHtml = skills.length > 0
        ? skills.map(s => `<span class="skill-tag">${s}</span>`).join('')
        : '<p style="color: #999; font-size: 13px;">No skills extracted from resume yet.</p>';

    // Check if profile has resume data
    const hasResumeData = profile.resume_url || profile.resume_text;
    
    // Display profile data - show empty/not set if no resume uploaded
    document.getElementById('profileContent').innerHTML = `
        <div style="display: grid; gap: 15px;">
            <div><strong>Name:</strong> ${profile.name || (hasResumeData ? 'Not extracted' : 'Not set - upload resume')}</div>
            <div><strong>Email:</strong> ${profile.email || (hasResumeData ? 'Not extracted' : 'Not set - upload resume')}</div>
            <div><strong>Experience:</strong> ${profile.experience_level || (hasResumeData ? 'Not extracted' : 'Not set - upload resume')}</div>
            <div>
                <strong>Skills:</strong>
                <div class="skills-list" style="margin-top: 8px;">${skillsHtml}</div>
            </div>
        </div>
    `;
}

async function handleFileUpload(e) {
    console.log('=== handleFileUpload CALLED ===');
    console.log('Event:', e);
    console.log('Event target:', e.target);
    console.log('Files:', e.target?.files);
    console.log('File count:', e.target?.files ? e.target.files.length : 0);
    
    const file = e.target?.files?.[0];
    if (!file) {
        console.warn('No file selected in handleFileUpload');
        return;
    }
    
    console.log('File found:', {
        name: file.name,
        size: file.size,
        type: file.type
    });

    // Validate file extension
    const fileName = file.name || '';
    const ext = '.' + fileName.split('.').pop().toLowerCase();
    if (!['.pdf', '.docx', '.doc'].includes(ext)) {
        alert('Please upload a PDF or DOCX file. Your file: ' + fileName);
        e.target.value = ''; // Reset file input
        return;
    }

    // Validate file size (2MB = 2 * 1024 * 1024 bytes)
    const maxSize = 2 * 1024 * 1024; // 2MB
    if (file.size > maxSize) {
        const fileSizeMB = (file.size / (1024 * 1024)).toFixed(2);
        alert(`File size (${fileSizeMB} MB) exceeds 2MB limit. Please upload a smaller file.`);
        e.target.value = ''; // Reset file input
        return;
    }

    // Show scanning state
    const uploadContent = document.getElementById('uploadContent');
    const uploadScanning = document.getElementById('uploadScanning');
    
    if (uploadContent) uploadContent.classList.add('hidden');
    if (uploadScanning) uploadScanning.classList.remove('hidden');

    // CRITICAL FIX: ONLY use sessionStorage - NEVER localStorage or window.CURRENT_USER_ID (contains stale data)
    // window.CURRENT_USER_ID can persist across page reloads and contain old user data
    // Backend generates user_id from resume name
    let userId = currentUserId || 
                 sessionStorage.getItem('session_user_id') ||
                 sessionStorage.getItem('resume_user_id');
    
    if (!userId) {
        console.warn('No user_id found in storage. Backend will generate one from resume name.');
        // Don't generate UUID - backend will create user_id from extracted name
    }

    const formData = new FormData();
    formData.append('file', file);

    try {
        // Backend now generates stable user_id from name - no need to pass user_id
        const uploadUrl = `${getApiBase()}/api/profile/upload-resume`;
        
        console.log('=== UPLOAD START ===');
        console.log('Upload URL:', uploadUrl);
        console.log('File:', fileName, 'Size:', file.size, 'bytes', 'Type:', file.type);
        console.log('FormData entries:', Array.from(formData.entries()).map(([k, v]) => [k, v instanceof File ? `${v.name} (${v.size} bytes)` : v]));
        
        const res = await fetch(uploadUrl, {
            method: 'POST',
            body: formData,
            // Don't set Content-Type header - browser will set it with boundary for FormData
        });
        
        console.log('Response received:', {
            status: res.status,
            statusText: res.statusText,
            ok: res.ok,
            contentType: res.headers.get('content-type')
        });

        // Read response as text first (can only read once)
        const responseText = await res.text();
        console.log('Response text length:', responseText.length);
        console.log('Response text (first 500 chars):', responseText.substring(0, 500));

        if (!res.ok) {
            console.error('Upload failed - Response text:', responseText);
            let errorData;
            try {
                errorData = JSON.parse(responseText);
                console.error('Parsed error data:', errorData);
            } catch (parseErr) {
                console.error('Failed to parse error response:', parseErr);
                errorData = { error: responseText || `Server error: ${res.status}` };
            }
            throw new Error(errorData.error || errorData.detail || `Upload failed: ${res.status} ${res.statusText}`);
        }

        // Parse JSON response
        let data;
        try {
            data = JSON.parse(responseText);
            console.log('Upload successful! Response data:', data);
            console.log('Session ID:', data.session_id);
        } catch (parseErr) {
            console.error('Failed to parse JSON response:', parseErr);
            console.error('Response text was:', responseText);
            throw new Error('Invalid response from server. Please try again.');
        }

        // Always redirect to analysis page, even on error
        const sessionId = data.session_id || data.sessionId || 'new';
        
        if (!sessionId || sessionId === 'new') {
            console.warn('No session_id in response, generating one');
            const fallbackSessionId = 'upload_' + Date.now();
            data.session_id = fallbackSessionId;
        }
        
        // Store analysis data in sessionStorage (including errors)
        sessionStorage.setItem('resume_analysis_data', JSON.stringify(data));
        sessionStorage.setItem('resume_analysis_session', sessionId);
        
        // BUG FIX #1 & #4: Store stable user_id from backend response with session marker
        // Note: user_id may be null for error responses, which is OK
        const stableUserId = data.user_id;
        if (data.success === true && !stableUserId) {
            console.error('Backend did not return user_id in success response!', data);
            throw new Error('Backend did not return user_id. Please try uploading again.');
        }
        // For error responses, user_id can be null - don't throw
        
        // BUG FIX #1 & #4: Store user_id with session marker (only after successful upload)
        // Only store user_id if it exists (not for error responses)
        if (stableUserId) {
            storeUserIdWithSession(stableUserId);
            
            // Update global user_id
            currentUserId = stableUserId;
            window.CURRENT_USER_ID = stableUserId;
            
            // CRITICAL: Clear any cached profile data to force fresh fetch
            // This ensures the profile section shows the newly uploaded resume data
            sessionStorage.removeItem('cached_profile_data');
            localStorage.removeItem('cached_profile_data');
        }
        
        console.log('Stored stable user_id from backend with session:', stableUserId);
        console.log('Cleared cached profile data to force fresh fetch');
        
        console.log('Stored in sessionStorage:', {
            session_id: sessionId,
            user_id: stableUserId,
            interview_session_id: data.interview_session_id,
            has_data: !!sessionStorage.getItem('resume_analysis_data')
        });
        
        console.log('Redirecting to resume-analysis.html?session=' + sessionId);
        // Redirect to resume analysis page (will show error state if failed)
        window.location.href = `resume-analysis.html?session=${sessionId}`;
    } catch (e) {
        console.error('=== UPLOAD ERROR ===');
        console.error('Error type:', e.constructor.name);
        console.error('Error message:', e.message);
        console.error('Error stack:', e.stack);
        
        // On network/parsing error, still redirect with error state
        const errorData = {
            success: false,
            error: e.message || 'Failed to upload resume. Please try again.',
            session_id: 'error_' + Date.now()
        };
        sessionStorage.setItem('resume_analysis_data', JSON.stringify(errorData));
        sessionStorage.setItem('resume_analysis_session', errorData.session_id);
        // Don't store invalid user_id - wait for successful upload
        // sessionStorage.setItem('resume_user_id', userId || 'unknown');
        
        console.log('Stored error in sessionStorage, redirecting...');
        window.location.href = `resume-analysis.html?session=${errorData.session_id}`;
    } finally {
        // Reset file input
        if (e.target) {
            e.target.value = '';
        }
        console.log('=== UPLOAD COMPLETE ===');
    }
}

async function startInterview(mode) {
    interviewMode = mode;
    currentQuestionNum = 0;
    document.getElementById('chatSection').classList.remove('hidden');
    
    // Start interview session
    try {
        const res = await fetch(`${getApiBase()}/api/interview/start`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: currentSessionId })
        });
        
        if (res.ok) {
            const data = await res.json();
            currentQuestionNum = data.question_number;
            totalQuestions = data.total_questions;
            
            window.currentQuestion = {
                id: 0,
                text: data.current_question.question,
                type: data.current_question.type
            };
            
            displayQuestion(data.current_question.question);
            updateProgress();
            
            if (interviewMode === 'timed') {
                startTimer();
            }
        }
    } catch (e) {
        console.error('Start interview error:', e);
        fetchNextQuestion();
    }
}

async function fetchNextQuestion() {
    if (!currentSessionId) return;

    try {
        const res = await fetch(`${getApiBase()}/api/interview/session/${currentSessionId}/next-question/${currentQuestionNum}`);
        
        if (res.status === 204 || res.status === 404) {
            endInterview(true);
            return;
        }

        const data = await res.json();
        
        if (!data.has_next) {
            endInterview(true);
            return;
        }

        currentQuestionNum = data.question_number;
        
        // Store question info for submission
        window.currentQuestion = {
            id: data.question_id,
            text: data.question,
            type: data.question_type || 'Technical'
        };

        displayQuestion(data.question);
        updateProgress();

        if (interviewMode === 'timed') {
            startTimer();
        }
    } catch (e) {
        console.error('Fetch question error:', e);
    }
}

function displayQuestion(question) {
    const container = document.getElementById('chatContainer');
    const div = document.createElement('div');
    div.className = 'chat-message bot';
    div.innerHTML = `<p><strong>Question ${currentQuestionNum}:</strong> ${question}</p>`;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

function updateProgress() {
    document.getElementById('progressText').textContent = `Question ${currentQuestionNum} of ${totalQuestions}`;
}

function startTimer() {
    timeRemaining = 60;
    document.getElementById('timerDisplay').classList.remove('hidden');
    updateTimer();

    timerInterval = setInterval(() => {
        timeRemaining--;
        updateTimer();
        if (timeRemaining <= 0) {
            clearInterval(timerInterval);
            submitAnswer(true);
        }
    }, 1000);
}

function updateTimer() {
    const timer = document.getElementById('timerDisplay');
    timer.textContent = `${timeRemaining}s`;
    if (timeRemaining <= 10) {
        timer.style.background = '#EF5350';
    }
}

async function submitAnswer(timeout = false) {
    const input = document.getElementById('answerInput');
    const answer = timeout ? '[Time expired]' : input.value.trim();

    if (!answer && !timeout) {
        alert('Please enter an answer.');
        return;
    }

    // Add user answer to chat
    const container = document.getElementById('chatContainer');
    const div = document.createElement('div');
    div.className = 'chat-message';
    div.innerHTML = `<p><strong>You:</strong> ${answer}</p>`;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;

    input.value = '';
    input.disabled = true;
    document.getElementById('submitBtn').disabled = true;

    try {
        const currentQuestion = window.currentQuestion || { id: 0, text: '', type: 'Technical' };
        
        const res = await fetch(`${getApiBase()}/api/interview/submit-answer`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                session_id: currentSessionId,
                question_id: currentQuestion.id || 0,
                question_number: currentQuestionNum,
                question_text: currentQuestion.text || '',
                question_type: currentQuestion.type || 'Technical',
                user_answer: answer,
                response_time: timeout ? 60 : null
            })
        });

        const data = await res.json();
        
        // Show scores
        const scoreDiv = document.createElement('div');
        scoreDiv.className = 'chat-message bot';
        scoreDiv.innerHTML = `
            <p><strong>Score:</strong> ${data.scores.overall}/100</p>
            <p style="font-size: 13px; color: #666; margin-top: 5px;">${data.scores.feedback}</p>
        `;
        container.appendChild(scoreDiv);

        // Next question
        setTimeout(() => {
            fetchNextQuestion();
            input.disabled = false;
            document.getElementById('submitBtn').disabled = false;
            if (timerInterval) {
                clearInterval(timerInterval);
                document.getElementById('timerDisplay').classList.add('hidden');
            }
        }, 1500);
    } catch (e) {
        console.error('Submit error:', e);
        input.disabled = false;
        document.getElementById('submitBtn').disabled = false;
    }
}

function endInterview(completed = false) {
    if (timerInterval) {
        clearInterval(timerInterval);
    }

    document.getElementById('chatSection').classList.add('hidden');
    document.getElementById('chatContainer').innerHTML = '';
    document.getElementById('answerInput').value = '';

    if (completed) {
        alert('Interview completed!');
        loadDashboard();
    }
}

// FIX 1 & FIX 6: loadDashboard - ONLY runs after resume upload sets currentUserId
async function loadDashboard() {
    // FIX 1 & FIX 6: ONLY use currentUserId set after resume upload - NEVER read from storage
    // sessionStorage is cleared on every page load, so we only use currentUserId from this page load
    const userId = currentUserId; // Only use local variable set after resume upload
    
    // FIX 1 & FIX 6: If no user_id found, return immediately - BLOCK API CALLS
    if (!userId) {
        console.log('[DASHBOARD] ❌ BLOCKED: No user_id found - skipping dashboard load. User must upload resume first.');
        return; // Exit early - no API calls
    }
    
    // FIX 2: Validate user_id belongs to current session BEFORE making API call
    if (!validateUserIdForSession(userId)) {
        console.log('[DASHBOARD] ❌ BLOCKED: user_id does not belong to current session, clearing stale data');
        clearUserSession();
        return; // Exit early - no API calls
    }
    
    // BUG FIX #6: Reload profile data when dashboard loads
    // This ensures profile section shows fresh resume data after interviews
    // Uses the authenticated user's user_id from session storage
    console.log('[DASHBOARD] Reloading profile data for authenticated user:', userId);
    loadProfile();

    try {
        // BUG FIX #2: Add cache-busting and ensure no caching
        const timestamp = Date.now();
        const sessionMarker = sessionStorage.getItem('app_session_id');
        const sessionParam = sessionMarker ? `&session_id=${encodeURIComponent(sessionMarker)}` : '';
        const dashboardUrl = `${getApiBase()}/api/dashboard/performance/${userId}?_t=${timestamp}${sessionParam}`;
        
        const res = await fetch(dashboardUrl, {
            cache: 'no-store',
            headers: {
                'Cache-Control': 'no-cache, no-store, must-revalidate',
                'Pragma': 'no-cache',
                'Expires': '0'
            }
        });
        const data = await res.json();

        // Update Total Interviews
        const totalInterviews = data.total_interviews || 0;
        document.getElementById('totalInterviews').textContent = totalInterviews;
        
        // Update Average Score with progress bar
        const avgScore = Math.round(data.average_score || 0);
        document.getElementById('avgScore').textContent = avgScore;
        const avgScorePercent = Math.min(avgScore, 100);
        document.getElementById('avgScoreFill').style.width = `${avgScorePercent}%`;
        document.getElementById('avgScoreText').textContent = `${avgScorePercent}%`;
        
        // Update Completion Rate with progress bar
        const completionRate = data.completion_rate || 0;
        const completionPercent = Math.round(completionRate);
        document.getElementById('completionRate').textContent = `${completionPercent}%`;
        document.getElementById('completionFill').style.width = `${completionPercent}%`;

        // Update Skills
        const strong = data.skill_analysis?.strong_skills || [];
        const weak = data.skill_analysis?.weak_areas || [];

        document.getElementById('strongSkillsCount').textContent = strong.length;
        document.getElementById('strongSkills').innerHTML = strong.length > 0
            ? strong.map(s => `<span class="skill-tag">${s}</span>`).join('')
            : '<p style="color: #999; font-size: 13px; padding: 10px;">No data yet. Complete interviews to see your strengths!</p>';

        document.getElementById('weakSkillsCount').textContent = weak.length;
        document.getElementById('weakSkills').innerHTML = weak.length > 0
            ? weak.map(s => `<span class="skill-tag">${s}</span>`).join('')
            : '<p style="color: #999; font-size: 13px; padding: 10px;">No data yet. Complete interviews to identify areas for improvement!</p>';

        // Update Recent Interviews with better formatting
        const interviews = data.recent_interviews || [];
        const list = document.getElementById('pastInterviews');
        if (interviews.length > 0) {
            list.innerHTML = interviews.map(i => {
                const date = new Date(i.completed_at);
                const formattedDate = date.toLocaleDateString('en-US', { 
                    month: 'short', 
                    day: 'numeric', 
                    year: 'numeric' 
                });
                const score = Math.round(i.overall_score || 0);
                return `
                    <div class="interview-item">
                        <div class="interview-item-info">
                            <div class="interview-item-role">${i.role || 'Interview'}</div>
                            <div class="interview-item-meta">
                                <span>${i.experience_level || 'N/A'}</span>
                                <span>•</span>
                                <span>${i.answered_questions || 0}/${i.total_questions || 0} questions</span>
                                <span>•</span>
                                <span>${formattedDate}</span>
                            </div>
                        </div>
                        <div class="interview-item-score">
                            <span class="score-badge">${score}</span>
                            <span>/100</span>
                        </div>
                    </div>
                `;
            }).join('');
        } else {
            list.innerHTML = '<p style="color: #999; text-align: center; padding: 30px; font-size: 14px;">No interviews yet. Start practicing to see your progress here!</p>';
        }
    } catch (e) {
        console.error('Dashboard load error:', e);
        // Show error message
        document.getElementById('totalInterviews').textContent = '—';
        document.getElementById('avgScore').textContent = '—';
        document.getElementById('completionRate').textContent = '—';
    }
}

