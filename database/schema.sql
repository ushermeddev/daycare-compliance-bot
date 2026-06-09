-- ============================================================
-- 托嬰合規助理 — Supabase Schema
-- Run in: Supabase Dashboard > SQL Editor
--
-- Security model:
--   RLS is ENABLED on all tables (blocks direct anon/browser access).
--   The FastAPI backend uses the service_role key, which bypasses RLS.
--   Never expose the service_role key to clients.
-- ============================================================

-- Centers
CREATE TABLE IF NOT EXISTS centers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    line_group_id TEXT,          -- LINE group ID for admin alerts
    city TEXT DEFAULT '桃園市',
    created_at TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE centers ENABLE ROW LEVEL SECURITY;

-- Staff (auto-registered on first LINE message)
CREATE TABLE IF NOT EXISTS staff (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    line_user_id TEXT UNIQUE NOT NULL,
    role TEXT NOT NULL DEFAULT 'staff' CHECK (role IN ('staff', 'admin')),
    center_id UUID REFERENCES centers(id),
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE staff ENABLE ROW LEVEL SECURITY;

-- Babies
CREATE TABLE IF NOT EXISTS babies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    nickname TEXT,               -- short name used by staff (e.g. 小明)
    dob DATE,
    room TEXT,
    center_id UUID REFERENCES centers(id),
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE babies ENABLE ROW LEVEL SECURITY;

-- Compliance records (core table)
CREATE TABLE IF NOT EXISTS compliance_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    center_id UUID REFERENCES centers(id),
    baby_id UUID REFERENCES babies(id),   -- NULL for environment records
    record_type TEXT NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    recorded_by UUID REFERENCES staff(id),
    data JSONB NOT NULL DEFAULT '{}',
    raw_input TEXT,
    ai_confidence FLOAT,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE compliance_records ENABLE ROW LEVEL SECURITY;

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_records_type_center
    ON compliance_records(record_type, center_id);
CREATE INDEX IF NOT EXISTS idx_records_baby_type
    ON compliance_records(baby_id, record_type);
CREATE INDEX IF NOT EXISTS idx_records_recorded_at
    ON compliance_records(recorded_at DESC);

-- Compliance rules (configurable per center)
CREATE TABLE IF NOT EXISTS compliance_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    center_id UUID REFERENCES centers(id),
    record_type TEXT NOT NULL,
    max_interval_minutes INTEGER,           -- e.g. 180 for diaper_change
    alert_threshold_minutes INTEGER DEFAULT 30, -- warn this many mins before deadline
    applies_to TEXT DEFAULT 'baby' CHECK (applies_to IN ('baby', 'environment')),
    UNIQUE(center_id, record_type)
);
ALTER TABLE compliance_rules ENABLE ROW LEVEL SECURITY;

-- Alert log
CREATE TABLE IF NOT EXISTS alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    center_id UUID REFERENCES centers(id),
    baby_id UUID REFERENCES babies(id),
    record_type TEXT,
    alerted_at TIMESTAMPTZ DEFAULT now(),
    resolved_at TIMESTAMPTZ,
    resolved_by UUID REFERENCES staff(id)
);
ALTER TABLE alerts ENABLE ROW LEVEL SECURITY;

-- ============================================================
-- RPC: get latest record per baby per record_type
-- Used by compliance engine and todo_list query
-- ============================================================
CREATE OR REPLACE FUNCTION get_last_records_per_baby(
    p_record_type TEXT,
    p_center_id UUID
)
RETURNS TABLE (
    baby_id UUID,
    baby_name TEXT,
    zone TEXT,
    staff_name TEXT,
    recorded_at TIMESTAMPTZ,
    data JSONB,
    notes TEXT
)
LANGUAGE sql STABLE AS $$
    SELECT DISTINCT ON (cr.baby_id)
        cr.baby_id,
        COALESCE(b.nickname, b.name)          AS baby_name,
        cr.data->>'zone'                       AS zone,
        s.name                                 AS staff_name,
        cr.recorded_at,
        cr.data,
        cr.notes
    FROM compliance_records cr
    LEFT JOIN babies b ON b.id = cr.baby_id
    LEFT JOIN staff s  ON s.id = cr.recorded_by
    WHERE cr.record_type = p_record_type
      AND cr.center_id   = p_center_id
    ORDER BY cr.baby_id, cr.recorded_at DESC;
$$;

-- ============================================================
-- Seed: default compliance rules (桃園市 standard)
-- Replace <YOUR_CENTER_ID> with actual UUID after inserting a center
-- ============================================================
-- INSERT INTO compliance_rules (center_id, record_type, max_interval_minutes, alert_threshold_minutes) VALUES
--   ('<YOUR_CENTER_ID>', 'diaper_change',   180, 30),
--   ('<YOUR_CENTER_ID>', 'temperature',     720, 60),
--   ('<YOUR_CENTER_ID>', 'decontamination', 480, 60);
