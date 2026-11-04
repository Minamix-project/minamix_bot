CREATE TABLE IF NOT EXISTS guild_message_history_state (
    guild_id BIGINT UNSIGNED NOT NULL PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    retention_days SMALLINT UNSIGNED NOT NULL DEFAULT 30,
    max_entries INT UNSIGNED NOT NULL DEFAULT 5000,
    entry_count INT UNSIGNED NOT NULL DEFAULT 0,
    generation INT UNSIGNED NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS guild_message_history (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    guild_id BIGINT UNSIGNED NOT NULL,
    channel_id BIGINT UNSIGNED NOT NULL,
    message_id BIGINT UNSIGNED NOT NULL,
    author_id BIGINT UNSIGNED NULL,
    event_kind ENUM('created', 'imported', 'captured', 'edited', 'deleted') NOT NULL,
    recorded_at BIGINT UNSIGNED NOT NULL,
    retention_started_at BIGINT UNSIGNED NOT NULL,
    expires_at BIGINT UNSIGNED NOT NULL,
    payload MEDIUMBLOB NOT NULL,
    INDEX history_channel (guild_id, channel_id, id),
    INDEX history_message (guild_id, message_id, id),
    INDEX history_expiry (guild_id, expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
