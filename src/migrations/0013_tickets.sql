CREATE TABLE IF NOT EXISTS ticket_panels (
    guild_id BIGINT UNSIGNED PRIMARY KEY,
    channel_id BIGINT UNSIGNED NOT NULL,
    message_id BIGINT UNSIGNED NOT NULL,
    category_id BIGINT UNSIGNED NOT NULL,
    staff_role_id BIGINT UNSIGNED NOT NULL,
    logs_channel_id BIGINT UNSIGNED NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS tickets (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    guild_id BIGINT UNSIGNED NOT NULL,
    channel_id BIGINT UNSIGNED NOT NULL UNIQUE,
    creator_id BIGINT UNSIGNED NOT NULL,
    category VARCHAR(32) NOT NULL,
    staff_role_id BIGINT UNSIGNED NOT NULL,
    logs_channel_id BIGINT UNSIGNED NULL,
    subject_id BIGINT UNSIGNED NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'open',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    closed_at DATETIME NULL,
    closed_by BIGINT UNSIGNED NULL,
    close_reason VARCHAR(1000) NULL,
    saved_overwrites JSON NULL,
    active_creator BIGINT UNSIGNED GENERATED ALWAYS AS (CASE WHEN status = 'open' THEN creator_id ELSE NULL END) STORED,
    UNIQUE KEY unique_open_ticket (guild_id, active_creator),
    INDEX idx_tickets_subject (guild_id, subject_id),
    INDEX idx_tickets_creator (guild_id, creator_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS ticket_staff (
    ticket_id BIGINT UNSIGNED NOT NULL,
    user_id BIGINT UNSIGNED NOT NULL,
    first_seen_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ticket_id, user_id),
    FOREIGN KEY (ticket_id) REFERENCES tickets(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS ticket_events (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    ticket_id BIGINT UNSIGNED NOT NULL,
    actor_id BIGINT UNSIGNED NOT NULL,
    action VARCHAR(32) NOT NULL,
    detail VARCHAR(1000) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (ticket_id) REFERENCES tickets(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS ticket_transcripts (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    ticket_id BIGINT UNSIGNED NOT NULL,
    created_by BIGINT UNSIGNED NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (ticket_id) REFERENCES tickets(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS ticket_transcript_parts (
    transcript_id BIGINT UNSIGNED NOT NULL,
    part_number INT NOT NULL,
    content MEDIUMBLOB NOT NULL,
    PRIMARY KEY (transcript_id, part_number),
    FOREIGN KEY (transcript_id) REFERENCES ticket_transcripts(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
