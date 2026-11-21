ALTER TABLE tickets ADD COLUMN admin_role_ids JSON NULL;

UPDATE ticket_categories SET version = version + 1;
