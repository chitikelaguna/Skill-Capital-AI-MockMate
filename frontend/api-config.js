/**
 * Shared API Configuration for all frontend files
 * This ensures consistent API base URL across all pages
 * Version: 2.0 - Single source of truth for API configuration
 */

// Configuration - Dynamic API base URL (works for both localhost and Vercel)
// CRITICAL: Use ONLY window object to prevent ANY redeclaration errors
// Never declare API_BASE as a local variable - always use window.API_BASE
// This prevents "already declared" errors from cached scripts
if (typeof window.API_BASE === 'undefined') {
    window.API_BASE = null; // Will be set by initApiBase
    window.API_BASE_READY = false; // Flag to track if API_BASE is configured
} else {
    // If already exists (from cached script), reset it
    window.API_BASE = null;
    window.API_BASE_READY = false;
}

// Determine default API base URL based on environment
function getDefaultApiBase() {
    // Check if we're on Vercel (production)
    if (window.location.hostname.includes('vercel.app') || window.location.hostname.includes('vercel.com')) {
        // On Vercel, frontend and backend are on the same domain
        return window.location.origin;
    }
    
    // Local development: ALWAYS use 127.0.0.1:8000 for backend
    // CRITICAL: Never use window.location.origin because it might be localhost:3000 or wrong port
    // The backend always runs on 127.0.0.1:8000 in local development
    return `http://127.0.0.1:8000`;
}

// Initialize API base URL
(async function initApiBase() {
    // Set default first (for immediate use)
    window.API_BASE = getDefaultApiBase();
    window.API_BASE_READY = true;
    
    // Then try to fetch from backend config endpoint for accurate URL
    try {
        const configUrl = `${window.API_BASE}/api/config`;
        
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 5000); // 5 second timeout for config
        
        const response = await fetch(configUrl, {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json',
            },
            signal: controller.signal,
            mode: 'cors',
            credentials: 'omit'
        });
        
        clearTimeout(timeoutId);
        
        if (response.ok) {
            const config = await response.json();
            if (config.api_base_url) {
                // Validate the URL from backend - for local dev, ensure it's 127.0.0.1:8000
                let backendUrl = config.api_base_url;
                
                // If we're in local development and backend returns localhost, convert to 127.0.0.1
                if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') {
                    // Replace localhost with 127.0.0.1 for consistency
                    backendUrl = backendUrl.replace('localhost', '127.0.0.1');
                }
                
                // CRITICAL: Validate backend URL before using it
                // For local dev: must be 127.0.0.1:8000 (never localhost:3000 or any other port)
                // For Vercel: must be vercel.app domain
                const isLocalDev = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
                const isVercel = window.location.hostname.includes('vercel.app') || window.location.hostname.includes('vercel.com');
                
                let shouldUseBackendUrl = false;
                
                if (isLocalDev) {
                    // Local dev: backend URL must be exactly 127.0.0.1:8000
                    // Reject localhost, reject port 3000, reject any other port
                    const normalizedUrl = backendUrl.replace('localhost', '127.0.0.1');
                    shouldUseBackendUrl = normalizedUrl === 'http://127.0.0.1:8000' || normalizedUrl === 'https://127.0.0.1:8000';
                } else if (isVercel) {
                    // Vercel: backend URL must be vercel domain
                    shouldUseBackendUrl = backendUrl.includes('vercel.app') || backendUrl.includes('vercel.com');
                }
                
                if (shouldUseBackendUrl) {
                    // Normalize localhost to 127.0.0.1 for consistency
                    if (isLocalDev) {
                        backendUrl = backendUrl.replace('localhost', '127.0.0.1');
                    }
                    window.API_BASE = backendUrl;
                } else {
                    // Backend returned invalid URL - keep our default (127.0.0.1:8000)
                    // Don't change window.API_BASE, it's already set to the correct default
                }
            }
        }
    } catch (error) {
        // Keep the default we set earlier
    }
})();

// Helper function to ensure API_BASE is ready before making requests
function ensureApiBaseReady() {
    if (!window.API_BASE_READY || !window.API_BASE) {
        // Wait a bit for config to load (max 2 seconds)
        return new Promise((resolve) => {
            const checkInterval = setInterval(() => {
                if (window.API_BASE_READY && window.API_BASE) {
                    clearInterval(checkInterval);
                    resolve();
                }
            }, 100);
            
            setTimeout(() => {
                clearInterval(checkInterval);
                // Set default if still not ready
                if (!window.API_BASE) {
                    window.API_BASE = getDefaultApiBase();
                    window.API_BASE_READY = true;
                }
                resolve();
            }, 2000);
        });
    }
    return Promise.resolve();
}

// Helper function to get API base URL (with fallback)
// CRITICAL: Always returns a valid URL, never returns port 3000 or wrong hostname
function getApiBase() {
    // Always get from window object, fallback to default if not set
    let apiBase = window.API_BASE || getDefaultApiBase();
    
    // CRITICAL: Multiple safety checks to prevent wrong URL
    const isLocalDev = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
    const isVercel = window.location.hostname.includes('vercel.app') || window.location.hostname.includes('vercel.com');
    
    // Safety check 1: NEVER return port 3000
    if (apiBase && apiBase.includes(':3000')) {
        return getDefaultApiBase();
    }
    
    // Safety check 2: For local dev, ensure it's 127.0.0.1:8000 (not localhost or wrong port)
    if (isLocalDev) {
        // Normalize localhost to 127.0.0.1
        apiBase = apiBase.replace('localhost', '127.0.0.1');
        // If it's not 127.0.0.1:8000, use default
        if (!apiBase.includes('127.0.0.1:8000')) {
            return getDefaultApiBase();
        }
    }
    
    // Safety check 3: For Vercel, ensure it's a vercel domain
    if (isVercel && !apiBase.includes('vercel.app') && !apiBase.includes('vercel.com')) {
        return window.location.origin;
    }
    
    return apiBase;
}

