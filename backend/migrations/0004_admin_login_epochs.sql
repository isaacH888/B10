-- Fence in-flight native administrator logins after private access changes/revocation.
CREATE TABLE IF NOT EXISTS auth_admin_login_epochs (
    identity_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    version BIGINT UNSIGNED NOT NULL DEFAULT 0,
    updated_at BIGINT UNSIGNED NOT NULL,
    CONSTRAINT auth_native_epoch_identity_fk FOREIGN KEY (identity_id)
        REFERENCES auth_identities (id) ON DELETE RESTRICT
) ENGINE=InnoDB;
