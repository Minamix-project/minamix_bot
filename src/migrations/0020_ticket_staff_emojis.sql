CREATE TABLE IF NOT EXISTS ticket_staff_preferences (
    guild_id BIGINT UNSIGNED NOT NULL,
    user_id BIGINT UNSIGNED NOT NULL,
    emoji VARCHAR(32) NOT NULL,
    PRIMARY KEY (guild_id, user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

ALTER TABLE tickets ADD COLUMN channel_base_name VARCHAR(100) NULL;

UPDATE tickets SET channel_base_name = claim_base_name WHERE claimed_by IS NOT NULL;
