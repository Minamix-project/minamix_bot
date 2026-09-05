CREATE TABLE guild_economy_config (
    guild_id BIGINT UNSIGNED NOT NULL PRIMARY KEY,
    work_gain_min INT NOT NULL DEFAULT 50,
    work_gain_max INT NOT NULL DEFAULT 250,
    work_cooldown_seconds INT NOT NULL DEFAULT 604800,
    message_gain_min INT NOT NULL DEFAULT 15,
    message_gain_max INT NOT NULL DEFAULT 25,
    message_gain_long_min INT NOT NULL DEFAULT 30,
    message_gain_long_max INT NOT NULL DEFAULT 50,
    starting_balance INT NOT NULL DEFAULT 0,
    balance_cap INT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
