ALTER TABLE ticket_categories
    ADD COLUMN claim_enabled TINYINT(1) NOT NULL DEFAULT 1;

ALTER TABLE tickets
    ADD COLUMN claimed_by BIGINT UNSIGNED NULL,
    ADD COLUMN claimed_at DATETIME NULL,
    ADD COLUMN claim_base_name VARCHAR(100) NULL;

UPDATE ticket_categories SET version = version + 1;
