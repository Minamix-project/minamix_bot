ALTER TABLE ticket_panels
    ADD COLUMN title VARCHAR(256) NULL,
    ADD COLUMN description TEXT NULL;

ALTER TABLE tickets ADD COLUMN ticket_number BIGINT UNSIGNED NULL;

UPDATE tickets SET ticket_number = id;

ALTER TABLE tickets
    MODIFY COLUMN ticket_number BIGINT UNSIGNED NOT NULL,
    ADD UNIQUE KEY unique_ticket_number (guild_id, ticket_number);

CREATE TABLE IF NOT EXISTS ticket_sequences (
    guild_id BIGINT UNSIGNED PRIMARY KEY,
    next_number BIGINT UNSIGNED NOT NULL DEFAULT 1
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO ticket_sequences (guild_id, next_number)
SELECT guild_id, MAX(ticket_number) + 1 FROM tickets GROUP BY guild_id;
