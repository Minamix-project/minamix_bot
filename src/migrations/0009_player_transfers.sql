CREATE TABLE guild_player_transfers (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    guild_id BIGINT UNSIGNED NOT NULL,
    currency ENUM('money', 'nax') NOT NULL,
    sender_id BIGINT UNSIGNED NOT NULL,
    recipient_id BIGINT UNSIGNED NOT NULL,
    sender_character_id INT NULL,
    recipient_character_id INT NULL,
    amount BIGINT NOT NULL,
    reason VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_transfer_sender_date (guild_id, sender_id, currency, created_at),
    INDEX idx_transfer_recipient_date (guild_id, recipient_id, currency, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE guild_transfer_daily_totals (
    guild_id BIGINT UNSIGNED NOT NULL,
    user_id BIGINT UNSIGNED NOT NULL,
    currency ENUM('money', 'nax') NOT NULL,
    transfer_date DATE NOT NULL,
    amount BIGINT NOT NULL DEFAULT 0,
    last_transfer_at BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id, currency, transfer_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
