ALTER TABLE guild_economy_config
    ADD COLUMN transfer_cooldown_seconds INT NOT NULL DEFAULT 300,
    ADD COLUMN transfer_daily_limit BIGINT NOT NULL DEFAULT 10000,
    ADD COLUMN nax_transfer_cooldown_seconds INT NOT NULL DEFAULT 300,
    ADD COLUMN nax_transfer_daily_limit BIGINT NOT NULL DEFAULT 10000;
