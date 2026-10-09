-- Browser-bound native Cognito challenges. Payloads never contain passwords or codes.
CREATE TABLE IF NOT EXISTS auth_admin_native_flows (
    token_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    binding_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    created_at BIGINT UNSIGNED NOT NULL,
    expires_at BIGINT UNSIGNED NOT NULL,
    attempts TINYINT UNSIGNED NOT NULL DEFAULT 0,
    encrypted_payload TEXT CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    KEY auth_native_flow_binding (binding_hash),
    KEY auth_native_flow_expiry (expires_at),
    CONSTRAINT auth_native_flow_expiry CHECK (
        expires_at > created_at AND expires_at <= created_at + 300
    ),
    CONSTRAINT auth_native_flow_attempts CHECK (attempts <= 5)
) ENGINE=InnoDB;
