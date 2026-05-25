-- Default monitoring targets. Edit to taste, or manage via Grafana.
INSERT INTO monitoring.targets (target_id, kind, endpoint, expected, interval_seconds, severity_on_fail, tags)
VALUES
  ('demo-website', 'http', 'http://website:80/', '<h1>NetworkChuck Coffee</h1>', 300, 'warn',
    '{"owner":"demo","env":"sandbox"}'::jsonb),
  ('n8n-self',     'http', 'http://n8n:5678/healthz', 'true', 60,  'crit',
    '{"owner":"platform","env":"prod"}'::jsonb),
  ('ollama-self',  'http', 'http://ollama:11434/api/tags', '{', 60,  'crit',
    '{"owner":"platform","env":"prod"}'::jsonb),
  ('postgres-self','tcp',  'postgres:5432', '', 60, 'crit',
    '{"owner":"platform","env":"prod"}'::jsonb),
  ('redis-self',   'tcp',  'redis:6379', '', 60, 'crit',
    '{"owner":"platform","env":"prod"}'::jsonb)
ON CONFLICT DO NOTHING;
