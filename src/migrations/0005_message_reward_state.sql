CREATE TABLE guild_message_reward_state (
    guild_id BIGINT UNSIGNED NOT NULL,
    user_id BIGINT UNSIGNED NOT NULL,
    last_reward BIGINT NOT NULL DEFAULT 0,
    last_content_hash CHAR(64) NULL,
    PRIMARY KEY (guild_id, user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
