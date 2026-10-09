-- Explicit local Google aliases. Canonical access remains in auth_admin_access.
CREATE TABLE IF NOT EXISTS auth_admin_google_links (
    provider_identity_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    admin_identity_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    google_subject VARBINARY(128) NOT NULL,
    provider_username VARCHAR(256) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
    created_at BIGINT UNSIGNED NOT NULL,
    UNIQUE KEY auth_google_canonical_identity (admin_identity_id),
    UNIQUE KEY auth_google_external_subject (google_subject),
    CONSTRAINT auth_google_provider_identity_fk FOREIGN KEY (provider_identity_id)
        REFERENCES auth_identities (id) ON DELETE RESTRICT,
    CONSTRAINT auth_google_canonical_identity_fk FOREIGN KEY (admin_identity_id)
        REFERENCES auth_identities (id) ON DELETE RESTRICT
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS auth_admin_totp (
    canonical_identity_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    encrypted_secret TEXT CHARACTER SET ascii COLLATE ascii_bin NULL,
    version BIGINT UNSIGNED NOT NULL DEFAULT 1,
    last_counter BIGINT NOT NULL DEFAULT -1,
    enrollment_challenge_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
    enrollment_expires_at BIGINT UNSIGNED NULL,
    CONSTRAINT auth_google_totp_identity_fk FOREIGN KEY (canonical_identity_id)
        REFERENCES auth_identities (id) ON DELETE RESTRICT
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS auth_admin_google_challenges (
    challenge_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    binding_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    identity_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    google_subject VARBINARY(128) NOT NULL,
    provider_username VARCHAR(256) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
    proof_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
    created_at BIGINT UNSIGNED NOT NULL,
    expires_at BIGINT UNSIGNED NOT NULL,
    encrypted_payload MEDIUMTEXT CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    attempts TINYINT UNSIGNED NOT NULL DEFAULT 0,
    UNIQUE KEY auth_google_challenge_proof (proof_hash),
    KEY auth_google_challenge_identity (identity_id),
    KEY auth_google_challenge_binding (binding_hash),
    KEY auth_google_challenge_expiry (expires_at),
    CONSTRAINT auth_google_challenge_identity_fk FOREIGN KEY (identity_id)
        REFERENCES auth_identities (id) ON DELETE RESTRICT,
    CONSTRAINT auth_google_challenge_attempts CHECK (attempts <= 5)
) ENGINE=InnoDB;
