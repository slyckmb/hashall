-- Assign a default scan_session_id for legacy entries without one

INSERT INTO scan_sessions (scan_id, root_path)
SELECT 'retrofit-' || substr(hex(randomblob(16)), 1, 32), 'unknown'
WHERE NOT EXISTS (SELECT 1 FROM scan_sessions WHERE root_path = 'unknown');

UPDATE files
SET scan_session_id = (
    SELECT id FROM scan_sessions WHERE root_path = 'unknown'
)
WHERE scan_session_id IS NULL;
