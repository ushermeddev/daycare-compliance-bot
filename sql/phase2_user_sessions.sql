-- Phase 2 前置 SQL：建立 user_sessions 資料表
-- 在 Supabase → SQL Editor 執行此檔案

CREATE TABLE IF NOT EXISTS user_sessions (
  user_id       text PRIMARY KEY,
  session_type  text NOT NULL,
  payload       jsonb DEFAULT '{}',
  created_at    timestamptz DEFAULT now(),
  expires_at    timestamptz NOT NULL
);

-- 選擇性：啟用 pg_cron 自動清理過期 session（Supabase 付費方案才有 pg_cron）
-- SELECT cron.schedule('cleanup-sessions', '*/30 * * * *', $$
--   DELETE FROM user_sessions WHERE expires_at < now();
-- $$);

-- 確認資料表已建立：
SELECT table_name FROM information_schema.tables WHERE table_name = 'user_sessions';
