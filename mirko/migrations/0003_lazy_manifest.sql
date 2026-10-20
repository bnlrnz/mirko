ALTER TABLE remote_entry
    ADD COLUMN fetch_state TEXT NOT NULL DEFAULT 'cached';
