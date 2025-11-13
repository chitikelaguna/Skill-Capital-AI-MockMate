/**
 * Skill Capital AI MockMate - Frontend
 * Lightweight JavaScript for simple, clean interface
 */

// Configuration
const API_BASE = 'http://127.0.0.1:8000';
const TEST_USER_ID = 'test_user_001'; // Default test user

// State
let currentSessionId = null;
let currentQuestionNum = 0;
let totalQuestions = 0;
let interviewMode = 'text';
let timerInterval = null;
let timeRemaining = 60;

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

    // Load profile
    loadProfile();

    // Setup event listeners
    setupEventListeners();

    // Load dashboard
    loadDashboard();
}

function setupEventListeners() {
    // File upload
    const fileInput = document.getElementById('fileInput');
    const uploadBtn = document.getElementById('uploadBtn');
    const uploadArea = document.getElementById('uploadArea');

    uploadBtn.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', handleFileUpload);

    // Drag and drop
    uploadArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadArea.style.borderColor = '#64B5F6';
    });
    uploadArea.addEventListener('dragleave', () => {
        uploadArea.style.borderColor = '#E0E0E0';
    });
    uploadArea.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadArea.style.borderColor = '#E0E0E0';
        if (e.dataTransfer.files.length > 0) {
            fileInput.files = e.dataTransfer.files;
            handleFileUpload({ target: fileInput });
        }
    });


    // Chat
    document.getElementById('submitBtn').addEventListener('click', submitAnswer);
    document.getElementById('endBtn').addEventListener('click', endInterview);
}

async function loadProfile() {
    const userId = window.TEST_USER_ID || TEST_USER_ID;
    const content = document.getElementById('profileContent');

    try {
        const res = await fetch(`${API_BASE}/api/profile/${userId}`);
        if (res.status === 404) {
            content.innerHTML = '<p style="color: #666;">No profile found. Upload a resume to create your profile.</p>';
            return;
        }
        const profile = await res.json();
        displayProfile(profile);
    } catch (e) {
        content.innerHTML = '<p style="color: #999;">Unable to load profile.</p>';
    }
}

function displayProfile(profile) {
    const skills = profile.skills || [];
    const skillsHtml = skills.length > 0
        ? skills.map(s => `<span class="skill-tag">${s}</span>`).join('')
        : '<p style="color: #999; font-size: 13px;">No skills yet. Upload your resume.</p>';

    document.getElementById('profileContent').innerHTML = `
        <div style="display: grid; gap: 15px;">
            <div><strong>Name:</strong> ${profile.name || 'Not set'}</div>
            <div><strong>Email:</strong> ${profile.email || 'Not set'}</div>
            <div><strong>Experience:</strong> ${profile.experience_level || 'Not set'}</div>
            <div>
                <strong>Skills:</strong>
                <div class="skills-list" style="margin-top: 8px;">${skillsHtml}</div>
            </div>
        </div>
    `;
}

async function handleFileUpload(e) {
    const file = e.target.files[0];
    if (!file) return;

    // Validate
    const ext = '.' + file.name.split('.').pop().toLowerCase();
    if (!['.pdf', '.docx', '.doc'].includes(ext)) {
        alert('Please upload a PDF or DOCX file.');
        return;
    }

    if (file.size > 2 * 1024 * 1024 * 1024) {
        alert('File size exceeds 2GB limit.');
        return;
    }

    // Show scanning
    document.getElementById('uploadContent').classList.add('hidden');
    document.getElementById('uploadScanning').classList.remove('hidden');

    const formData = new FormData();
    formData.append('file', file);

    try {
        const userId = window.TEST_USER_ID || TEST_USER_ID;
        const res = await fetch(`${API_BASE}/api/profile/${userId}/upload-resume`, {
            method: 'POST',
            body: formData
        });

        const data = await res.json();

        // Always redirect to analysis page, even on error
        const sessionId = data.session_id || 'new';
        
        // Store analysis data in sessionStorage (including errors)
        sessionStorage.setItem('resume_analysis_data', JSON.stringify(data));
        sessionStorage.setItem('resume_analysis_session', sessionId);
        // Store user_id for experience updates
        sessionStorage.setItem('resume_user_id', userId);
        
        // Redirect to resume analysis page (will show error state if failed)
        window.location.href = `resume-analysis.html?session=${sessionId}`;
    } catch (e) {
        // On network/parsing error, still redirect with error state
        const errorData = {
            success: false,
            error: e.message || 'Failed to upload resume. Please try again.',
            session_id: 'error_' + Date.now()
        };
        sessionStorage.setItem('resume_analysis_data', JSON.stringify(errorData));
        sessionStorage.setItem('resume_analysis_session', errorData.session_id);
        window.location.href = `resume-analysis.html?session=${errorData.session_id}`;
    } finally {
        // Don't reset UI here - we're redirecting anyway
        e.target.value = '';
    }
}

async function startInterview(mode) {
    interviewMode = mode;
    currentQuestionNum = 0;
    document.getElementById('chatSection').classList.remove('hidden');
    
    // Start interview session
    try {
        const res = await fetch(`${API_BASE}/api/interview/start`, {
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
        const res = await fetch(`${API_BASE}/api/interview/session/${currentSessionId}/next-question/${currentQuestionNum}`);
        
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
        
        const res = await fetch(`${API_BASE}/api/interview/submit-answer`, {
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

async function loadDashboard() {
    const userId = window.TEST_USER_ID || TEST_USER_ID;

    try {
        const res = await fetch(`${API_BASE}/api/dashboard/performance/${userId}`);
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

