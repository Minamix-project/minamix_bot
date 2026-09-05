CREATE TABLE IF NOT EXISTS guild_work_cooldowns (
    guild_id BIGINT UNSIGNED NOT NULL, user_id BIGINT UNSIGNED NOT NULL, last_work BIGINT NOT NULL DEFAULT 0, PRIMARY KEY (guild_id, user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
