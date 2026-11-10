ALTER TABLE ticket_panels
    DROP PRIMARY KEY,
    ADD COLUMN id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY FIRST,
    ADD INDEX idx_ticket_panels_guild (guild_id),
    ADD UNIQUE KEY unique_ticket_panel_message (guild_id, channel_id, message_id),
    ADD COLUMN name VARCHAR(80) NOT NULL DEFAULT 'Support',
    ADD COLUMN staff_role_ids JSON NULL,
    ADD COLUMN version INT UNSIGNED NOT NULL DEFAULT 1,
    CHANGE COLUMN logs_channel_id transcript_channel_id BIGINT UNSIGNED NULL;

UPDATE ticket_panels SET staff_role_ids = JSON_ARRAY(staff_role_id);

ALTER TABLE ticket_panels
    MODIFY COLUMN staff_role_ids JSON NOT NULL,
    DROP COLUMN staff_role_id;

ALTER TABLE tickets
    ADD COLUMN panel_id BIGINT UNSIGNED NULL,
    ADD COLUMN staff_role_ids JSON NULL,
    CHANGE COLUMN logs_channel_id transcript_channel_id BIGINT UNSIGNED NULL;

UPDATE tickets SET staff_role_ids = JSON_ARRAY(staff_role_id);

UPDATE tickets t JOIN ticket_panels p ON p.guild_id = t.guild_id SET t.panel_id = p.id;

ALTER TABLE tickets
    MODIFY COLUMN staff_role_ids JSON NOT NULL,
    DROP COLUMN staff_role_id,
    ADD FOREIGN KEY (panel_id) REFERENCES ticket_panels(id) ON DELETE SET NULL;
