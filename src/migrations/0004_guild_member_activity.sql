CREATE TABLE guild_member_activity (
    guild_id BIGINT UNSIGNED NOT NULL,
    user_id BIGINT UNSIGNED NOT NULL,
    last_seen TIMESTAMP NULL,
    PRIMARY KEY (guild_id, user_id),
    INDEX idx_activity_guild_seen (guild_id, last_seen)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
