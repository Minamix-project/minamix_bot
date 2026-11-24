ALTER TABLE guild_reminders
    ADD COLUMN advance_minutes TINYINT UNSIGNED NOT NULL DEFAULT 0,
    ADD COLUMN advance_status ENUM('disabled', 'pending', 'sent', 'failed', 'skipped') NOT NULL DEFAULT 'disabled',
    ADD COLUMN advance_last_error VARCHAR(255) NULL,
    ADD COLUMN advance_sent_at BIGINT NULL,
    ADD COLUMN delivery_kind ENUM('main', 'advance') NOT NULL DEFAULT 'main',
    ADD COLUMN next_delivery_at BIGINT GENERATED ALWAYS AS (
        CASE WHEN advance_status = 'pending' THEN CAST(due_at AS SIGNED) - advance_minutes * 60 ELSE due_at END
    ) STORED,
    ADD INDEX idx_reminder_next_delivery (status, next_delivery_at, next_attempt_at);
