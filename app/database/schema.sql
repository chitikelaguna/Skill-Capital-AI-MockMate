-- ============================================================
-- SKILL CAPITAL AI - COMPLETE DATABASE SCHEMA
-- ============================================================
-- Clean, organized schema with separate tables for each interview round
-- This script handles both NEW installations and EXISTING database migrations
-- Run this ENTIRE SQL in Supabase SQL Editor
-- ============================================================

-- ============================================================
-- MIGRATION: Fix Existing Databases (if needed)
-- ============================================================
-- This section handles migration from old schema to new schema
-- Safe to run multiple times - uses IF EXISTS checks
-- ============================================================

-- Step 1: Drop existing foreign key constraints (if they exist)
ALTER TABLE IF EXISTS interview_sessions DROP CONSTRAINT IF EXISTS interview_sessions_user_id_fkey;
ALTER TABLE IF EXISTS user_profiles DROP CONSTRAINT IF EXISTS user_profiles_user_id_fkey;

-- Step 1.5: Drop existing RLS policies (if they exist) to prevent conflicts
-- This makes the script idempotent - safe to run multiple times
DO $$
BEGIN
    -- Drop user_profiles policies
    DROP POLICY IF EXISTS "Users can view own profile" ON user_profiles;
    DROP POLICY IF EXISTS "Users can insert own profile" ON user_profiles;
    DROP POLICY IF EXISTS "Users can update own profile" ON user_profiles;
    DROP POLICY IF EXISTS "Service role can manage all profiles" ON user_profiles;
    
    -- Drop interview_sessions policies
    DROP POLICY IF EXISTS "Users can view own interview sessions" ON interview_sessions;
    DROP POLICY IF EXISTS "Users can insert own interview sessions" ON interview_sessions;
    DROP POLICY IF EXISTS "Users can update own interview sessions" ON interview_sessions;
    DROP POLICY IF EXISTS "Service role can manage all interview sessions" ON interview_sessions;
    
    -- Drop round table policies
    DROP POLICY IF EXISTS "Users can view own coding results" ON coding_round;
    DROP POLICY IF EXISTS "Service role can manage all coding results" ON coding_round;
    DROP POLICY IF EXISTS "Users can view own technical results" ON technical_round;
    DROP POLICY IF EXISTS "Service role can manage all technical results" ON technical_round;
    DROP POLICY IF EXISTS "Users can view own HR results" ON hr_round;
    DROP POLICY IF EXISTS "Service role can manage all HR results" ON hr_round;
    DROP POLICY IF EXISTS "Users can view own STAR results" ON star_round;
    DROP POLICY IF EXISTS "Service role can manage all STAR results" ON star_round;
    
    -- Drop other table policies
    DROP POLICY IF EXISTS "Service role can manage question templates" ON question_templates;
    DROP POLICY IF EXISTS "Service role can manage all transcripts" ON interview_transcripts;
    
    RAISE NOTICE '✓ Dropped existing RLS policies (if any)';
END $$;

-- Step 2: Migrate user_id from UUID to TEXT in user_profiles (if needed)
DO $$
BEGIN
    -- Check if column exists and is UUID type
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public'
        AND table_name = 'user_profiles' 
        AND column_name = 'user_id' 
        AND data_type = 'uuid'
    ) THEN
        -- Convert UUID to TEXT (preserving existing values as strings)
        ALTER TABLE user_profiles 
        ALTER COLUMN user_id TYPE TEXT USING user_id::TEXT;
        
        RAISE NOTICE '✓ Migrated user_profiles.user_id from UUID to TEXT';
    ELSE
        RAISE NOTICE '✓ user_profiles.user_id is already TEXT or table does not exist';
    END IF;
END $$;

-- Step 3: Migrate user_id from UUID to TEXT in interview_sessions (if needed)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public'
        AND table_name = 'interview_sessions' 
        AND column_name = 'user_id' 
        AND data_type = 'uuid'
    ) THEN
        ALTER TABLE interview_sessions 
        ALTER COLUMN user_id TYPE TEXT USING user_id::TEXT;
        
        RAISE NOTICE '✓ Migrated interview_sessions.user_id from UUID to TEXT';
    ELSE
        RAISE NOTICE '✓ interview_sessions.user_id is already TEXT or table does not exist';
    END IF;
END $$;

-- ============================================================
-- UTILITY FUNCTIONS
-- ============================================================

-- Function to automatically update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- ============================================================
-- 1. USER PROFILES TABLE (Enhanced with full resume data)
-- ============================================================

CREATE TABLE IF NOT EXISTS user_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL UNIQUE,  -- Stable user_id generated from name (slugified)
    
    -- Basic Information
    name TEXT,
    email TEXT NOT NULL,
    phone TEXT,
    location TEXT,
    
    -- Skills & Experience
    skills TEXT[], -- Array of skills
    experience_level TEXT, -- Fresher, 1yrs, 2yrs, 3yrs, etc.
    years_of_experience INTEGER DEFAULT 0,
    
    -- Projects (stored as JSONB for flexibility)
    -- Structure: [{"name": "...", "description": "...", "technologies": [...], "duration": "...", "role": "...", "achievements": [...]}]
    projects JSONB DEFAULT '[]'::jsonb,
    
    -- Education (stored as JSONB)
    -- Structure: [{"degree": "...", "institution": "...", "year": "...", "gpa": "...", "coursework": [...]}]
    education JSONB DEFAULT '[]'::jsonb,
    
    -- Work Experience (stored as JSONB)
    -- Structure: [{"company": "...", "role": "...", "start_date": "...", "end_date": "...", "responsibilities": [...], "achievements": [...]}]
    work_experience JSONB DEFAULT '[]'::jsonb,
    
    -- Certifications (stored as JSONB)
    -- Structure: [{"name": "...", "issuer": "...", "date": "...", "expiry_date": "...", "credential_id": "..."}]
    certifications JSONB DEFAULT '[]'::jsonb,
    
    -- Additional Information
    languages TEXT[], -- Spoken languages
    resume_url TEXT, -- URL to uploaded resume file
    resume_text TEXT, -- Full extracted text from resume
    
    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Enable Row Level Security for user_profiles
ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY;

-- RLS Policies for user_profiles
CREATE POLICY "Users can view own profile"
    ON user_profiles FOR SELECT
    USING (auth.uid()::text = user_id);

CREATE POLICY "Users can insert own profile"
    ON user_profiles FOR INSERT
    WITH CHECK (auth.uid()::text = user_id);

CREATE POLICY "Users can update own profile"
    ON user_profiles FOR UPDATE
    USING (auth.uid()::text = user_id);

CREATE POLICY "Service role can manage all profiles"
    ON user_profiles FOR ALL
    USING (auth.jwt()->>'role' = 'service_role');

-- Trigger to automatically update updated_at
DROP TRIGGER IF EXISTS update_user_profiles_updated_at ON user_profiles;
CREATE TRIGGER update_user_profiles_updated_at
    BEFORE UPDATE ON user_profiles
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Indexes for user_profiles
CREATE INDEX IF NOT EXISTS idx_user_profiles_user_id ON user_profiles(user_id);
CREATE INDEX IF NOT EXISTS idx_user_profiles_email ON user_profiles(email);
CREATE INDEX IF NOT EXISTS idx_user_profiles_skills ON user_profiles USING GIN(skills);

-- ============================================================
-- 2. INTERVIEW SESSIONS TABLE (Master table for all sessions)
-- ============================================================

CREATE TABLE IF NOT EXISTS interview_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL, -- Foreign key added at end of script
    
    -- Session Information
    interview_type TEXT NOT NULL CHECK (interview_type IN ('coding', 'technical', 'hr', 'star', 'full')),
    session_status TEXT DEFAULT 'active' CHECK (session_status IN ('active', 'completed', 'cancelled')),
    
    -- Session Metadata
    started_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE,
    total_rounds INTEGER DEFAULT 0,
    rounds_completed INTEGER DEFAULT 0,
    overall_score INTEGER, -- Average score across all rounds
    
    -- Context (for question generation)
    experience_level TEXT,
    skills TEXT[], -- Skills used for question generation
    role TEXT, -- Target role (if applicable)
    
    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Enable Row Level Security for interview_sessions
ALTER TABLE interview_sessions ENABLE ROW LEVEL SECURITY;

-- RLS Policies for interview_sessions
CREATE POLICY "Users can view own interview sessions"
    ON interview_sessions FOR SELECT
    USING (auth.uid()::text = user_id);

CREATE POLICY "Users can insert own interview sessions"
    ON interview_sessions FOR INSERT
    WITH CHECK (auth.uid()::text = user_id);

CREATE POLICY "Users can update own interview sessions"
    ON interview_sessions FOR UPDATE
    USING (auth.uid()::text = user_id);

CREATE POLICY "Service role can manage all interview sessions"
    ON interview_sessions FOR ALL
    USING (auth.jwt()->>'role' = 'service_role');

-- Trigger to automatically update updated_at
DROP TRIGGER IF EXISTS update_interview_sessions_updated_at ON interview_sessions;
CREATE TRIGGER update_interview_sessions_updated_at
    BEFORE UPDATE ON interview_sessions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Indexes for interview_sessions
CREATE INDEX IF NOT EXISTS idx_interview_sessions_user_id ON interview_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_interview_sessions_type ON interview_sessions(interview_type);
CREATE INDEX IF NOT EXISTS idx_interview_sessions_status ON interview_sessions(session_status);
CREATE INDEX IF NOT EXISTS idx_interview_sessions_created_at ON interview_sessions(created_at DESC);

-- ============================================================
-- 3. CODING ROUND TABLE
-- ============================================================

CREATE TABLE IF NOT EXISTS coding_round (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL, -- References interview_sessions.id (as TEXT for flexibility)
    
    -- Question Information
    question_number INTEGER NOT NULL,
    question_text TEXT NOT NULL,
    difficulty_level TEXT CHECK (difficulty_level IN ('Easy', 'Medium', 'Hard')),
    programming_language TEXT NOT NULL, -- Python, Java, JavaScript, C, C++, SQL, etc.
    
    -- User Submission
    user_code TEXT NOT NULL,
    
    -- Execution Results
    execution_output TEXT, -- Actual output from running the code
    execution_time FLOAT, -- Time taken to execute (in seconds)
    test_cases_passed INTEGER DEFAULT 0,
    total_test_cases INTEGER DEFAULT 0,
    
    -- Evaluation
    correct_solution TEXT, -- Correct/optimal solution generated by AI
    correctness BOOLEAN DEFAULT FALSE, -- Whether the answer is correct
    final_score INTEGER DEFAULT 0, -- Score out of 100
    ai_feedback TEXT, -- Comprehensive AI feedback
    
    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Enable Row Level Security for coding_round
ALTER TABLE coding_round ENABLE ROW LEVEL SECURITY;

-- RLS Policies for coding_round
CREATE POLICY "Users can view own coding results"
    ON coding_round FOR SELECT
    USING (auth.uid()::text = user_id OR auth.jwt()->>'role' = 'service_role');

CREATE POLICY "Service role can manage all coding results"
    ON coding_round FOR ALL
    USING (auth.jwt()->>'role' = 'service_role');

-- Indexes for coding_round
CREATE INDEX IF NOT EXISTS idx_coding_round_user_id ON coding_round(user_id);
CREATE INDEX IF NOT EXISTS idx_coding_round_session_id ON coding_round(session_id);
CREATE INDEX IF NOT EXISTS idx_coding_round_session_question ON coding_round(session_id, question_number);
CREATE INDEX IF NOT EXISTS idx_coding_round_created_at ON coding_round(created_at DESC);

-- ============================================================
-- 4. TECHNICAL ROUND TABLE
-- ============================================================

CREATE TABLE IF NOT EXISTS technical_round (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL, -- References interview_sessions.id
    
    -- Question Information
    question_number INTEGER NOT NULL,
    question_text TEXT NOT NULL,
    question_type TEXT, -- Technical, System Design, Architecture, etc.
    audio_url TEXT, -- TTS audio URL for the question
    
    -- User Answer
    user_answer TEXT NOT NULL,
    
    -- Evaluation Scores (0-100)
    relevance_score INTEGER, -- How relevant the answer is
    technical_accuracy_score INTEGER, -- Technical correctness
    communication_score INTEGER, -- Clarity of communication
    overall_score INTEGER, -- Average of all scores
    
    -- AI Feedback
    ai_feedback TEXT, -- Detailed feedback on the answer
    ai_response TEXT, -- Follow-up response from AI interviewer
    
    -- Metadata
    response_time INTEGER, -- Response time in seconds
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Enable Row Level Security for technical_round
ALTER TABLE technical_round ENABLE ROW LEVEL SECURITY;

-- RLS Policies for technical_round
CREATE POLICY "Users can view own technical results"
    ON technical_round FOR SELECT
    USING (auth.uid()::text = user_id OR auth.jwt()->>'role' = 'service_role');

CREATE POLICY "Service role can manage all technical results"
    ON technical_round FOR ALL
    USING (auth.jwt()->>'role' = 'service_role');

-- Indexes for technical_round
CREATE INDEX IF NOT EXISTS idx_technical_round_user_id ON technical_round(user_id);
CREATE INDEX IF NOT EXISTS idx_technical_round_session_id ON technical_round(session_id);
CREATE INDEX IF NOT EXISTS idx_technical_round_session_question ON technical_round(session_id, question_number);
CREATE INDEX IF NOT EXISTS idx_technical_round_created_at ON technical_round(created_at DESC);

-- ============================================================
-- 5. HR ROUND TABLE
-- ============================================================

CREATE TABLE IF NOT EXISTS hr_round (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL, -- References interview_sessions.id
    
    -- Question Information
    question_number INTEGER NOT NULL,
    question_text TEXT NOT NULL,
    question_category TEXT, -- Communication, Cultural Fit, Motivation, Career Goals, etc.
    audio_url TEXT, -- TTS audio URL for the question (added for consistency with technical_round)
    
    -- User Answer
    user_answer TEXT NOT NULL DEFAULT '', -- Allow empty string initially, will be updated when user submits answer
    
    -- Evaluation Scores (0-100)
    communication_score INTEGER, -- Clarity and effectiveness of communication
    cultural_fit_score INTEGER, -- Alignment with company values
    motivation_score INTEGER, -- Motivation and interest in the role
    clarity_score INTEGER, -- Clarity of expression
    overall_score INTEGER, -- Average of all scores
    
    -- AI Feedback
    ai_feedback TEXT, -- Detailed feedback on the answer
    
    -- Metadata
    response_time INTEGER, -- Response time in seconds
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Enable Row Level Security for hr_round
ALTER TABLE hr_round ENABLE ROW LEVEL SECURITY;

-- RLS Policies for hr_round
CREATE POLICY "Users can view own HR results"
    ON hr_round FOR SELECT
    USING (auth.uid()::text = user_id OR auth.jwt()->>'role' = 'service_role');

-- Service role can manage all HR results (INSERT, UPDATE, DELETE, SELECT)
CREATE POLICY "Service role can manage all HR results"
    ON hr_round FOR ALL
    USING (auth.jwt()->>'role' = 'service_role')
    WITH CHECK (auth.jwt()->>'role' = 'service_role');

-- Indexes for hr_round
CREATE INDEX IF NOT EXISTS idx_hr_round_user_id ON hr_round(user_id);
CREATE INDEX IF NOT EXISTS idx_hr_round_session_id ON hr_round(session_id);
CREATE INDEX IF NOT EXISTS idx_hr_round_session_question ON hr_round(session_id, question_number);
CREATE INDEX IF NOT EXISTS idx_hr_round_created_at ON hr_round(created_at DESC);

-- ============================================================
-- 6. STAR ROUND TABLE (Behavioral Interview)
-- ============================================================

CREATE TABLE IF NOT EXISTS star_round (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL, -- References interview_sessions.id
    
    -- Question Information
    question_number INTEGER NOT NULL,
    question_text TEXT NOT NULL,
    
    -- User Answer
    user_answer TEXT NOT NULL,
    
    -- STAR Method Breakdown (extracted from answer)
    situation_extracted TEXT, -- Situation extracted from answer
    task_extracted TEXT, -- Task extracted from answer
    action_extracted TEXT, -- Action extracted from answer
    result_extracted TEXT, -- Result extracted from answer
    
    -- Evaluation Scores (0-100)
    star_structure_score INTEGER, -- How well they followed STAR method
    situation_score INTEGER, -- Quality of situation description
    task_score INTEGER, -- Quality of task description
    action_score INTEGER, -- Quality of action description
    result_score INTEGER, -- Quality of result description
    overall_score INTEGER, -- Average of all scores
    
    -- AI Feedback
    ai_feedback TEXT, -- Detailed feedback on the answer
    star_guidance TEXT, -- Specific STAR method guidance
    improvement_suggestions TEXT, -- Suggestions for improvement
    
    -- Metadata
    response_time INTEGER, -- Response time in seconds
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Enable Row Level Security for star_round
ALTER TABLE star_round ENABLE ROW LEVEL SECURITY;

-- RLS Policies for star_round
CREATE POLICY "Users can view own STAR results"
    ON star_round FOR SELECT
    USING (auth.uid()::text = user_id OR auth.jwt()->>'role' = 'service_role');

CREATE POLICY "Service role can manage all STAR results"
    ON star_round FOR ALL
    USING (auth.jwt()->>'role' = 'service_role');

-- Indexes for star_round
CREATE INDEX IF NOT EXISTS idx_star_round_user_id ON star_round(user_id);
CREATE INDEX IF NOT EXISTS idx_star_round_session_id ON star_round(session_id);
CREATE INDEX IF NOT EXISTS idx_star_round_session_question ON star_round(session_id, question_number);
CREATE INDEX IF NOT EXISTS idx_star_round_created_at ON star_round(created_at DESC);

-- ============================================================
-- 7. QUESTION TEMPLATES TABLE (for admin to manage)
-- ============================================================

CREATE TABLE IF NOT EXISTS question_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    question_text TEXT NOT NULL,
    question_type TEXT NOT NULL CHECK (question_type IN ('HR', 'Technical', 'Coding', 'Behavioral', 'STAR')),
    role TEXT, -- Specific role or NULL for general
    experience_level TEXT, -- Specific level or NULL for all
    category TEXT, -- e.g., "Python", "System Design", "Communication"
    difficulty_level TEXT CHECK (difficulty_level IN ('Easy', 'Medium', 'Hard')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Enable RLS for question_templates (admin only access)
ALTER TABLE question_templates ENABLE ROW LEVEL SECURITY;

-- Policy: Allow service role to manage all templates
CREATE POLICY "Service role can manage question templates"
    ON question_templates FOR ALL
    USING (auth.jwt()->>'role' = 'service_role');

-- Create updated_at trigger for question_templates
DROP TRIGGER IF EXISTS update_question_templates_updated_at ON question_templates;
CREATE TRIGGER update_question_templates_updated_at
    BEFORE UPDATE ON question_templates
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Indexes for question_templates
CREATE INDEX IF NOT EXISTS idx_question_templates_type ON question_templates(question_type);
CREATE INDEX IF NOT EXISTS idx_question_templates_category ON question_templates(category);

-- ============================================================
-- 8. INTERVIEW TRANSCRIPTS TABLE (for analytics and logging)
-- ============================================================

CREATE TABLE IF NOT EXISTS interview_transcripts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id TEXT NOT NULL, -- References interview_sessions.id
    interview_type TEXT NOT NULL, -- coding, technical, hr, star
    question TEXT,
    user_answer TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Enable Row Level Security for interview_transcripts
ALTER TABLE interview_transcripts ENABLE ROW LEVEL SECURITY;

-- RLS Policies for interview_transcripts
CREATE POLICY "Service role can manage all transcripts"
    ON interview_transcripts FOR ALL
    USING (auth.jwt()->>'role' = 'service_role');

-- Indexes for interview_transcripts
CREATE INDEX IF NOT EXISTS idx_interview_transcripts_session_id ON interview_transcripts(session_id);
CREATE INDEX IF NOT EXISTS idx_interview_transcripts_type ON interview_transcripts(interview_type);
CREATE INDEX IF NOT EXISTS idx_interview_transcripts_created_at ON interview_transcripts(created_at DESC);

-- ============================================================
-- FINAL STEP: Add Foreign Key Constraint (after tables are created)
-- ============================================================

-- Add foreign key constraint from interview_sessions to user_profiles
-- This is done last to ensure both tables exist
DO $$
BEGIN
    -- Check if constraint already exists
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints 
        WHERE constraint_name = 'interview_sessions_user_id_fkey'
        AND table_schema = 'public'
    ) THEN
        ALTER TABLE interview_sessions
        ADD CONSTRAINT interview_sessions_user_id_fkey 
        FOREIGN KEY (user_id) REFERENCES user_profiles(user_id) ON DELETE CASCADE;
        
        RAISE NOTICE '✓ Added foreign key constraint: interview_sessions.user_id → user_profiles.user_id';
    ELSE
        RAISE NOTICE '✓ Foreign key constraint already exists';
    END IF;
END $$;

-- ============================================================
-- MIGRATION: Add missing columns to existing hr_round table
-- ============================================================
-- This section adds missing columns if they don't exist
-- Safe to run multiple times - uses IF NOT EXISTS checks
-- ============================================================

-- Add audio_url column to hr_round if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public'
        AND table_name = 'hr_round' 
        AND column_name = 'audio_url'
    ) THEN
        ALTER TABLE hr_round ADD COLUMN audio_url TEXT;
        RAISE NOTICE '✓ Added audio_url column to hr_round table';
    ELSE
        RAISE NOTICE '✓ audio_url column already exists in hr_round table';
    END IF;
END $$;

-- Modify user_answer to allow empty string as default
DO $$
BEGIN
    -- Check if user_answer has a default value
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public'
        AND table_name = 'hr_round' 
        AND column_name = 'user_answer'
        AND column_default IS NULL
    ) THEN
        -- Set default to empty string
        ALTER TABLE hr_round ALTER COLUMN user_answer SET DEFAULT '';
        RAISE NOTICE '✓ Set user_answer default to empty string in hr_round table';
    ELSE
        RAISE NOTICE '✓ user_answer already has a default value in hr_round table';
    END IF;
END $$;

-- Fix RLS policy to include WITH CHECK clause for proper UPDATE support
DO $$
BEGIN
    -- Drop existing policy if it exists
    DROP POLICY IF EXISTS "Service role can manage all HR results" ON hr_round;
    
    -- Create new policy with proper WITH CHECK clause
    CREATE POLICY "Service role can manage all HR results"
        ON hr_round FOR ALL
        USING (auth.jwt()->>'role' = 'service_role')
        WITH CHECK (auth.jwt()->>'role' = 'service_role');
    
    RAISE NOTICE '✓ Updated RLS policy for hr_round with WITH CHECK clause';
END $$;

-- ============================================================
-- SCHEMA CREATION COMPLETE
-- ============================================================
-- All tables, policies, indexes, triggers, and foreign keys have been created
-- 
-- VERIFICATION CHECKLIST:
-- 1. Go to Supabase Dashboard → Table Editor
-- 2. Verify these 8 tables exist:
--    ✓ user_profiles (user_id: TEXT)
--    ✓ interview_sessions (user_id: TEXT, FK to user_profiles)
--    ✓ coding_round (user_id: TEXT)
--    ✓ technical_round (user_id: TEXT, audio_url: TEXT)
--    ✓ hr_round (user_id: TEXT, audio_url: TEXT) ← VERIFY audio_url EXISTS
--    ✓ star_round (user_id: TEXT)
--    ✓ question_templates
--    ✓ interview_transcripts
-- 3. Verify foreign key: interview_sessions.user_id → user_profiles.user_id
-- 4. Verify storage bucket "resume-uploads" exists (create manually if needed)
-- 5. Verify hr_round.audio_url column exists (added in migration)
-- 6. Verify RLS policy "Service role can manage all HR results" has WITH CHECK clause
-- ============================================================
