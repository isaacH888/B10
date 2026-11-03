-- JSON payloads preserve the evolving workflow; indexed identifiers and immutable
-- monetary columns enforce durable payment and delivery identities.
CREATE TABLE IF NOT EXISTS automation_mutex (
    id TINYINT UNSIGNED PRIMARY KEY
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS automation_bookings (
    id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    status VARCHAR(32) CHARACTER SET ascii NOT NULL,
    revision BIGINT UNSIGNED NOT NULL,
    start_at VARCHAR(40) CHARACTER SET ascii NOT NULL,
    end_at VARCHAR(40) CHARACTER SET ascii NOT NULL,
    data JSON NOT NULL,
    INDEX automation_booking_status (status)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS automation_payments (
    reference VARCHAR(190) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin PRIMARY KEY,
    booking_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    amount_minor BIGINT UNSIGNED NOT NULL,
    currency CHAR(3) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    verified_by VARCHAR(128) NOT NULL,
    verified_at VARCHAR(40) CHARACTER SET ascii NOT NULL,
    data JSON NOT NULL,
    INDEX automation_payment_booking (booking_id),
    CONSTRAINT automation_payment_booking_fk FOREIGN KEY (booking_id)
        REFERENCES automation_bookings (id) ON DELETE RESTRICT,
    CONSTRAINT automation_payment_positive CHECK (amount_minor > 0 AND amount_minor <= 1000000000000)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS automation_outbox (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    job_key VARCHAR(190) CHARACTER SET ascii COLLATE ascii_bin NOT NULL UNIQUE,
    booking_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    status VARCHAR(32) CHARACTER SET ascii NOT NULL,
    data JSON NOT NULL,
    INDEX automation_outbox_booking (booking_id),
    INDEX automation_outbox_status (status,id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS automation_deliveries (
    delivery_key VARCHAR(190) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    data JSON NOT NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS automation_connections (
    owner_id VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    data JSON NOT NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS automation_oauth_states (
    state_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    session_id CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    expires_at BIGINT UNSIGNED NOT NULL,
    data JSON NOT NULL,
    INDEX automation_state_expiry (expires_at)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS automation_audit (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    event VARCHAR(80) CHARACTER SET ascii NOT NULL,
    actor VARCHAR(128) NULL,
    created_at VARCHAR(40) CHARACTER SET ascii NOT NULL,
    detail JSON NOT NULL
) ENGINE=InnoDB;
