-- Block native sign-in durably while the private operator replaces credentials.
CREATE TABLE IF NOT EXISTS auth_admin_recoveries (
    identity_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    started_at BIGINT UNSIGNED NOT NULL,
    CONSTRAINT auth_admin_recovery_identity_fk FOREIGN KEY (identity_id)
        REFERENCES auth_identities (id) ON DELETE RESTRICT
) ENGINE=InnoDB;
