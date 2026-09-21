-- ==============================================================================
-- TalentIQ - Multi-Tenant Isolation & Row Level Security (RLS) Migration
-- Run this in your Supabase Project Dashboard -> SQL Editor
-- ==============================================================================

-- 1. Add user_id column to core tables if not present
ALTER TABLE public.requisitions 
    ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE;

ALTER TABLE public.candidates 
    ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE;

ALTER TABLE public.interview_guides 
    ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE;

ALTER TABLE public.email_logs 
    ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE;

-- 2. Create indices on user_id and req_id for high performance queries
CREATE INDEX IF NOT EXISTS idx_requisitions_user_id ON public.requisitions(user_id);
CREATE INDEX IF NOT EXISTS idx_candidates_user_id ON public.candidates(user_id);
CREATE INDEX IF NOT EXISTS idx_candidates_req_id ON public.candidates(req_id);
CREATE INDEX IF NOT EXISTS idx_interview_guides_user_id ON public.interview_guides(user_id);
CREATE INDEX IF NOT EXISTS idx_email_logs_user_id ON public.email_logs(user_id);

-- 3. Enable Row Level Security (RLS) on all tables
ALTER TABLE public.requisitions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.interview_guides ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.email_logs ENABLE ROW LEVEL SECURITY;

-- 4. Requisitions Policies
DROP POLICY IF EXISTS "Users can view own requisitions" ON public.requisitions;
CREATE POLICY "Users can view own requisitions" ON public.requisitions
    FOR SELECT USING (auth.uid() = user_id OR auth.uid() IS NULL);

DROP POLICY IF EXISTS "Users can insert own requisitions" ON public.requisitions;
CREATE POLICY "Users can insert own requisitions" ON public.requisitions
    FOR INSERT WITH CHECK (auth.uid() = user_id OR auth.uid() IS NULL);

DROP POLICY IF EXISTS "Users can update own requisitions" ON public.requisitions;
CREATE POLICY "Users can update own requisitions" ON public.requisitions
    FOR UPDATE USING (auth.uid() = user_id OR auth.uid() IS NULL);

DROP POLICY IF EXISTS "Users can delete own requisitions" ON public.requisitions;
CREATE POLICY "Users can delete own requisitions" ON public.requisitions
    FOR DELETE USING (auth.uid() = user_id OR auth.uid() IS NULL);

-- 5. Candidates Policies
DROP POLICY IF EXISTS "Users can view own candidates" ON public.candidates;
CREATE POLICY "Users can view own candidates" ON public.candidates
    FOR SELECT USING (auth.uid() = user_id OR auth.uid() IS NULL);

DROP POLICY IF EXISTS "Users can insert own candidates" ON public.candidates;
CREATE POLICY "Users can insert own candidates" ON public.candidates
    FOR INSERT WITH CHECK (auth.uid() = user_id OR auth.uid() IS NULL);

DROP POLICY IF EXISTS "Users can update own candidates" ON public.candidates;
CREATE POLICY "Users can update own candidates" ON public.candidates
    FOR UPDATE USING (auth.uid() = user_id OR auth.uid() IS NULL);

DROP POLICY IF EXISTS "Users can delete own candidates" ON public.candidates;
CREATE POLICY "Users can delete own candidates" ON public.candidates
    FOR DELETE USING (auth.uid() = user_id OR auth.uid() IS NULL);

-- 6. Interview Guides Policies
DROP POLICY IF EXISTS "Users can manage own interview guides" ON public.interview_guides;
CREATE POLICY "Users can manage own interview guides" ON public.interview_guides
    FOR ALL USING (auth.uid() = user_id OR auth.uid() IS NULL);

-- 7. Email Logs Policies
DROP POLICY IF EXISTS "Users can manage own email logs" ON public.email_logs;
CREATE POLICY "Users can manage own email logs" ON public.email_logs
    FOR ALL USING (auth.uid() = user_id OR auth.uid() IS NULL);
