ALTER TABLE ticket_panels
    ADD COLUMN logs_channel_id BIGINT UNSIGNED NULL;

ALTER TABLE tickets
    ADD COLUMN logs_channel_id BIGINT UNSIGNED NULL,
    DROP INDEX unique_open_ticket,
    ADD UNIQUE KEY unique_open_ticket (guild_id, active_creator, category);
