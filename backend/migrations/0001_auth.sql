-- Additive authentication schema. No application password or TOTP secrets.
CREATE TABLE IF NOT EXISTS auth_identities (
    id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    issuer VARBINARY(512) NOT NULL,
    subject VARBINARY(128) NOT NULL,
    area ENUM('customer', 'admin') NOT NULL,
    email VARCHAR(254) NOT NULL,
    name VARCHAR(150) NOT NULL,
    created_at BIGINT UNSIGNED NOT NULL,
    updated_at BIGINT UNSIGNED NOT NULL,
    UNIQUE KEY auth_identity_subject (issuer, subject),
    KEY auth_identity_email (email, area)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS auth_admin_access (
    identity_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    role ENUM('owner', 'staff') NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at BIGINT UNSIGNED NOT NULL,
    updated_at BIGINT UNSIGNED NOT NULL,
    CONSTRAINT auth_admin_identity_fk FOREIGN KEY (identity_id)
        REFERENCES auth_identities (id) ON DELETE RESTRICT
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS auth_sessions (
    token_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    login_binding_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
    identity_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    area ENUM('customer', 'admin') NOT NULL,
    created_at BIGINT UNSIGNED NOT NULL,
    last_seen BIGINT UNSIGNED NOT NULL,
    expires_at BIGINT UNSIGNED NOT NULL,
    auth_time BIGINT UNSIGNED NOT NULL,
    assurance JSON NOT NULL,
    encrypted_tokens MEDIUMTEXT CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    revoked_at BIGINT UNSIGNED NULL,
    KEY auth_session_identity (identity_id, revoked_at),
    KEY auth_session_login_binding (login_binding_hash, area),
    KEY auth_session_expiry (expires_at),
    CONSTRAINT auth_session_identity_fk FOREIGN KEY (identity_id)
        REFERENCES auth_identities (id) ON DELETE RESTRICT
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS auth_flows (
    state_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    binding_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    area ENUM('customer', 'admin') NOT NULL,
    created_at BIGINT UNSIGNED NOT NULL,
    expires_at BIGINT UNSIGNED NOT NULL,
    encrypted_payload TEXT CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    KEY auth_flow_expiry (expires_at)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS auth_flow_cancellations (
    binding_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    area ENUM('customer', 'admin') NOT NULL,
    expires_at BIGINT UNSIGNED NOT NULL,
    PRIMARY KEY (binding_hash, area),
    KEY auth_flow_cancel_expiry (expires_at)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS auth_audit_events (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    event VARCHAR(100) NOT NULL,
    identity_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NULL,
    request_id VARCHAR(100) NULL,
    created_at BIGINT UNSIGNED NOT NULL,
    detail JSON NOT NULL,
    KEY auth_audit_identity_time (identity_id, created_at),
    KEY auth_audit_time (created_at)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS auth_rate_limits (
    bucket_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    window_start BIGINT UNSIGNED NOT NULL,
    attempts BIGINT UNSIGNED NOT NULL,
    expires_at BIGINT UNSIGNED NOT NULL,
    KEY auth_rate_expiry (expires_at)
) ENGINE=InnoDB;
