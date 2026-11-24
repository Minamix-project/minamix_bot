ALTER TABLE guild_reminders
    ADD COLUMN personal_number BIGINT UNSIGNED NULL,
    ADD COLUMN generation BIGINT UNSIGNED NOT NULL DEFAULT 0,
    ADD COLUMN timezone VARCHAR(64) NOT NULL DEFAULT 'Europe/Brussels',
    ADD COLUMN parent_id BIGINT UNSIGNED NULL,
    ADD UNIQUE KEY unique_reminder_report (parent_id);

UPDATE guild_reminders r
JOIN (
    SELECT id, ROW_NUMBER() OVER (PARTITION BY guild_id, user_id ORDER BY id) AS number
    FROM guild_reminders
) numbered ON numbered.id = r.id
SET r.personal_number = numbered.number;

ALTER TABLE guild_reminders
    MODIFY COLUMN personal_number BIGINT UNSIGNED NOT NULL,
    ADD UNIQUE KEY unique_personal_reminder (guild_id, user_id, generation, personal_number);

CREATE TABLE reminder_preferences (
    guild_id BIGINT UNSIGNED NOT NULL,
    user_id BIGINT UNSIGNED NOT NULL,
    timezone VARCHAR(64) NOT NULL DEFAULT 'Europe/Brussels',
    next_number BIGINT UNSIGNED NOT NULL DEFAULT 1,
    generation BIGINT UNSIGNED NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO reminder_preferences (guild_id, user_id, next_number)
SELECT guild_id, user_id, MAX(personal_number) + 1 FROM guild_reminders GROUP BY guild_id, user_id;
