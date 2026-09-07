CREATE TABLE rp_character_history (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    character_id INT NULL,
    guild_id BIGINT UNSIGNED NOT NULL,
    actor_id BIGINT UNSIGNED NOT NULL,
    action VARCHAR(30) NOT NULL,
    snapshot JSON NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_rp_history_character (guild_id, character_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE rp_message_cooldowns (
    guild_id BIGINT UNSIGNED NOT NULL,
    user_id BIGINT UNSIGNED NOT NULL,
    character_id INT NOT NULL,
    last_sent BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id, character_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
