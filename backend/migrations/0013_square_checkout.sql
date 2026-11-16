-- Persist creation intent before Square requests. Issued Square links are single
-- use; a scheduled outbox sweep deletes expired or superseded unpaid links.
CREATE TABLE IF NOT EXISTS square_checkouts (
    id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    booking_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    provider_link_id VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin NULL UNIQUE,
    provider_order_id VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin NULL UNIQUE,
    status VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    expires_at BIGINT NOT NULL,
    data JSON NOT NULL,
    INDEX square_checkout_booking (booking_id),
    INDEX square_checkout_expiry (status, expires_at),
    CONSTRAINT square_checkout_booking_fk FOREIGN KEY (booking_id)
        REFERENCES automation_bookings (id) ON DELETE RESTRICT
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS square_events (
    id VARCHAR(255) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    data JSON NOT NULL
) ENGINE=InnoDB;
