CREATE TABLE IF NOT EXISTS ticket_categories (
    guild_id BIGINT UNSIGNED NOT NULL,
    category_key VARCHAR(32) NOT NULL,
    name VARCHAR(100) NOT NULL,
    emoji VARCHAR(100) NOT NULL,
    description VARCHAR(100) NOT NULL,
    welcome VARCHAR(2000) NOT NULL,
    staff_role_ids JSON NOT NULL,
    version INT UNSIGNED NOT NULL DEFAULT 1,
    position INT UNSIGNED NOT NULL,
    PRIMARY KEY (guild_id, category_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

ALTER TABLE tickets
    ADD COLUMN category_version INT UNSIGNED NOT NULL DEFAULT 0,
    ADD COLUMN welcome_message_id BIGINT UNSIGNED NULL,
    ADD INDEX idx_tickets_category (guild_id, category);

ALTER TABLE ticket_panels DROP COLUMN staff_role_ids;
