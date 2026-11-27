-- The composite character key makes the guild boundary enforceable by the foreign key.
-- Check for it before adding it so a retry after interrupted MySQL DDL is safe.
SET @rp_character_key_ddl = IF(
    EXISTS (SELECT 1 FROM information_schema.statistics
            WHERE table_schema = DATABASE() AND table_name = 'rp_characters'
              AND index_name = 'uq_rp_character_guild_id'),
    'SELECT 1',
    'ALTER TABLE rp_characters ADD UNIQUE KEY uq_rp_character_guild_id (guild_id, id)'
);
PREPARE rp_character_key_statement FROM @rp_character_key_ddl;
EXECUTE rp_character_key_statement;
DEALLOCATE PREPARE rp_character_key_statement;

CREATE TABLE IF NOT EXISTS rp_role_settings (
    guild_id BIGINT UNSIGNED PRIMARY KEY,
    revision BIGINT UNSIGNED NOT NULL DEFAULT 0,
    imported BOOLEAN NOT NULL DEFAULT FALSE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS rp_role_categories (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    guild_id BIGINT UNSIGNED NOT NULL,
    name VARCHAR(80) NOT NULL,
    position INT UNSIGNED NOT NULL,
    mode ENUM('single', 'multiple') NOT NULL,
    UNIQUE KEY uq_rp_category_name (guild_id, name),
    UNIQUE KEY uq_rp_category_guild_id (guild_id, id),
    UNIQUE KEY uq_rp_category_mode (guild_id, id, mode),
    INDEX idx_rp_category_position (guild_id, position, id),
    FOREIGN KEY (guild_id) REFERENCES rp_role_settings (guild_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS rp_category_roles (
    guild_id BIGINT UNSIGNED NOT NULL,
    category_id BIGINT UNSIGNED NOT NULL,
    role_id BIGINT UNSIGNED NOT NULL,
    PRIMARY KEY (guild_id, category_id, role_id),
    UNIQUE KEY uq_rp_linked_role (guild_id, role_id),
    FOREIGN KEY (guild_id, category_id)
        REFERENCES rp_role_categories (guild_id, id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS rp_character_roles (
    guild_id BIGINT UNSIGNED NOT NULL,
    character_id INT NOT NULL,
    category_id BIGINT UNSIGNED NOT NULL,
    role_id BIGINT UNSIGNED NOT NULL,
    mode ENUM('single', 'multiple') NOT NULL,
    single_slot TINYINT GENERATED ALWAYS AS (CASE WHEN mode = 'single' THEN 1 END) VIRTUAL,
    PRIMARY KEY (guild_id, character_id, category_id, role_id),
    UNIQUE KEY uq_rp_single_slot (guild_id, character_id, category_id, single_slot),
    FOREIGN KEY (guild_id, character_id)
        REFERENCES rp_characters (guild_id, id) ON DELETE CASCADE,
    FOREIGN KEY (guild_id, category_id, role_id)
        REFERENCES rp_category_roles (guild_id, category_id, role_id) ON DELETE CASCADE,
    FOREIGN KEY (guild_id, category_id, mode)
        REFERENCES rp_role_categories (guild_id, id, mode) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS rp_role_validators (
    guild_id BIGINT UNSIGNED NOT NULL,
    role_id BIGINT UNSIGNED NOT NULL,
    PRIMARY KEY (guild_id, role_id),
    FOREIGN KEY (guild_id) REFERENCES rp_role_settings (guild_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
