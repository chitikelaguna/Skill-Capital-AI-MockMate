-- User Profiles Table
-- Run this SQL in your Supabase SQL Editor

CREATE TABLE IF NOT EXISTS user_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL UNIQUE REFERENCES auth.users(id) ON DELETE CASCADE,
    name TEXT,
    email TEXT NOT NULL,
    skills TEXT[], -- Array of skills
    experience_level TEXT, -- Fresher, 1yrs, 2yrs, 3yrs, etc.
    resume_url TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Enable Row Level Security
ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY;

-- Create policy to allow users to read their own profile
CREATE POLICY "Users can view own profile"
    ON user_profiles FOR SELECT
    USING (auth.uid() = user_id);

-- Create policy to allow users to insert their own profile
CREATE POLICY "Users can insert own profile"
    ON user_profiles FOR INSERT
    WITH CHECK (auth.uid() = user_id);

-- Create policy to allow users to update their own profile
CREATE POLICY "Users can update own profile"
    ON user_profiles FOR UPDATE
    USING (auth.uid() = user_id);

-- Create policy to allow service role to manage all profiles (for backend)
CREATE POLICY "Service role can manage all profiles"
    ON user_profiles FOR ALL
    USING (auth.jwt()->>'role' = 'service_role');

-- Create function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Create trigger to automatically update updated_at
CREATE TRIGGER update_user_profiles_updated_at
    BEFORE UPDATE ON user_profiles
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Interview Sessions Table
CREATE TABLE IF NOT EXISTS interview_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    experience_level TEXT NOT NULL,
    skills TEXT[], -- Array of skills used for question generation
    session_status TEXT DEFAULT 'active', -- active, completed, cancelled
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Interview Questions Table
CREATE TABLE IF NOT EXISTS interview_questions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES interview_sessions(id) ON DELETE CASCADE,
    question_type TEXT NOT NULL, -- HR, Technical, Problem-solving
    question TEXT NOT NULL,
    question_number INTEGER NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Enable Row Level Security for interview_sessions
ALTER TABLE interview_sessions ENABLE ROW LEVEL SECURITY;

-- Create policy to allow users to read their own sessions
CREATE POLICY "Users can view own interview sessions"
    ON interview_sessions FOR SELECT
    USING (auth.uid() = user_id);

-- Create policy to allow users to insert their own sessions
CREATE POLICY "Users can insert own interview sessions"
    ON interview_sessions FOR INSERT
    WITH CHECK (auth.uid() = user_id);

-- Create policy to allow users to update their own sessions
CREATE POLICY "Users can update own interview sessions"
    ON interview_sessions FOR UPDATE
    USING (auth.uid() = user_id);

-- Create policy to allow service role to manage all sessions
CREATE POLICY "Service role can manage all interview sessions"
    ON interview_sessions FOR ALL
    USING (auth.jwt()->>'role' = 'service_role');

-- Enable Row Level Security for interview_questions
ALTER TABLE interview_questions ENABLE ROW LEVEL SECURITY;

-- Create policy to allow users to read questions from their own sessions
CREATE POLICY "Users can view own interview questions"
    ON interview_questions FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM interview_sessions
            WHERE interview_sessions.id = interview_questions.session_id
            AND interview_sessions.user_id = auth.uid()
        )
    );

-- Create policy to allow service role to manage all questions
CREATE POLICY "Service role can manage all interview questions"
    ON interview_questions FOR ALL
    USING (auth.jwt()->>'role' = 'service_role');

-- Create trigger to automatically update updated_at for interview_sessions
CREATE TRIGGER update_interview_sessions_updated_at
    BEFORE UPDATE ON interview_sessions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Interview Answers Table
CREATE TABLE IF NOT EXISTS interview_answers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES interview_sessions(id) ON DELETE CASCADE,
    question_id UUID NOT NULL REFERENCES interview_questions(id) ON DELETE CASCADE,
    question_number INTEGER NOT NULL,
    question_text TEXT NOT NULL,
    question_type TEXT NOT NULL,
    user_answer TEXT NOT NULL,
    relevance_score INTEGER, -- 0-100
    confidence_score INTEGER, -- 0-100
    technical_accuracy_score INTEGER, -- 0-100
    communication_score INTEGER, -- 0-100
    overall_score INTEGER, -- Average of all scores
    ai_feedback TEXT, -- AI-generated feedback
    response_time INTEGER, -- Response time in seconds
    answered_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    evaluated_at TIMESTAMP WITH TIME ZONE
);

-- Interview Transcript Log (stores Q&A for technical and coding interviews)
CREATE TABLE IF NOT EXISTS interview_transcripts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id TEXT NOT NULL,
    interview_type TEXT NOT NULL,
    question TEXT,
    user_answer TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Enable Row Level Security for interview_answers
ALTER TABLE interview_answers ENABLE ROW LEVEL SECURITY;

-- Create policy to allow users to read answers from their own sessions
CREATE POLICY "Users can view own interview answers"
    ON interview_answers FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM interview_sessions
            WHERE interview_sessions.id = interview_answers.session_id
            AND interview_sessions.user_id = auth.uid()
        )
    );

-- Create policy to allow users to insert answers to their own sessions
CREATE POLICY "Users can insert own interview answers"
    ON interview_answers FOR INSERT
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM interview_sessions
            WHERE interview_sessions.id = interview_answers.session_id
            AND interview_sessions.user_id = auth.uid()
        )
    );

-- Create policy to allow service role to manage all answers
CREATE POLICY "Service role can manage all interview answers"
    ON interview_answers FOR ALL
    USING (auth.jwt()->>'role' = 'service_role');

-- Question Templates Table (for admin to manage)
CREATE TABLE IF NOT EXISTS question_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    question_text TEXT NOT NULL,
    question_type TEXT NOT NULL CHECK (question_type IN ('HR', 'Technical', 'Problem-solving')),
    role TEXT, -- Specific role or NULL for general
    experience_level TEXT, -- Specific level or NULL for all
    category TEXT, -- e.g., "Python", "System Design"
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create updated_at trigger for question_templates
CREATE TRIGGER update_question_templates_updated_at
    BEFORE UPDATE ON question_templates
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Enable RLS for question_templates (admin only access)
ALTER TABLE question_templates ENABLE ROW LEVEL SECURITY;

-- Policy: Allow service role to manage all templates
CREATE POLICY "Service role can manage question templates"
    ON question_templates FOR ALL
    USING (auth.jwt()->>'role' = 'service_role');

-- Coding Interview Results Table
CREATE TABLE IF NOT EXISTS coding_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    question_number INTEGER NOT NULL,
    question_text TEXT NOT NULL,
    user_code TEXT NOT NULL,
    correct_solution TEXT,
    execution_output TEXT,
    correctness BOOLEAN DEFAULT FALSE,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    difficulty_level TEXT CHECK (difficulty_level IN ('Easy', 'Medium', 'Hard')),
    programming_language TEXT NOT NULL,
    ai_feedback TEXT,
    final_score INTEGER DEFAULT 0,
    execution_time FLOAT,
    test_cases_passed INTEGER DEFAULT 0,
    total_test_cases INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create index for faster queries
CREATE INDEX IF NOT EXISTS idx_coding_results_user_id ON coding_results(user_id);
CREATE INDEX IF NOT EXISTS idx_coding_results_session_id ON coding_results(session_id);
CREATE INDEX IF NOT EXISTS idx_coding_results_timestamp ON coding_results(timestamp DESC);

-- Enable RLS for coding_results
ALTER TABLE coding_results ENABLE ROW LEVEL SECURITY;

-- Policy: Allow service role to manage all coding results
CREATE POLICY "Service role can manage all coding results"
    ON coding_results FOR ALL
    USING (auth.jwt()->>'role' = 'service_role');
