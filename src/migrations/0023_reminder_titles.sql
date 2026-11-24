ALTER TABLE guild_reminders ADD COLUMN title VARCHAR(80) NOT NULL DEFAULT '';

UPDATE guild_reminders
SET title = COALESCE(NULLIF(LEFT(TRIM(REGEXP_REPLACE(message, '[[:space:]]+', ' ')), 80), ''), 'Rappel');
