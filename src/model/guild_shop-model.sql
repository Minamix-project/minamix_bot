CREATE TABLE IF NOT EXISTS guild_boutique_roles (
    id INT AUTO_INCREMENT PRIMARY KEY,
    guild_id BIGINT UNSIGNED NOT NULL,
    role_id BIGINT NOT NULL,
    prix INT NOT NULL,
    nom VARCHAR(255) NOT NULL,
    description TEXT,
    exclusif TINYINT(1) NOT NULL DEFAULT 0,
    INDEX idx_guild_items (guild_id, exclusif, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
