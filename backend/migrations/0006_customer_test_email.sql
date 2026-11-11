-- Durable duplicate protection for customer-requested sample confirmations.
-- Keep this ledger independent of identity retention and authentication readiness.
CREATE TABLE IF NOT EXISTS email_test_messages (
    request_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    identity_id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    recipient_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    reference VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    status ENUM('sending', 'accepted', 'failed', 'uncertain') NOT NULL,
    provider_message_id VARCHAR(256) CHARACTER SET ascii COLLATE ascii_bin NULL,
    error_code VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
    created_at BIGINT UNSIGNED NOT NULL,
    updated_at BIGINT UNSIGNED NOT NULL,
    UNIQUE KEY email_test_reference (reference),
    KEY email_test_identity_time (identity_id, created_at),
    KEY email_test_time (created_at)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS email_test_budgets (
    bucket_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    window_start BIGINT UNSIGNED NOT NULL,
    attempts BIGINT UNSIGNED NOT NULL,
    expires_at BIGINT UNSIGNED NOT NULL
) ENGINE=InnoDB;
