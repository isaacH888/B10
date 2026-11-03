-- Preserve the customer-order contract alongside the existing owner workflow.
-- The submission snapshot is immutable even when the administrative view changes.
CREATE TABLE IF NOT EXISTS customers (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    email VARCHAR(254) NOT NULL,
    phone VARCHAR(30) NOT NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS orders (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    public_id VARCHAR(100) CHARACTER SET ascii COLLATE ascii_bin NOT NULL UNIQUE,
    customer_id BIGINT UNSIGNED NOT NULL,
    status VARCHAR(32) CHARACTER SET ascii NOT NULL,
    version INT UNSIGNED NOT NULL,
    quote_id VARCHAR(100) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    pricing_revision VARCHAR(100) NOT NULL,
    total_cents BIGINT UNSIGNED NOT NULL,
    deposit_due_cents BIGINT UNSIGNED NOT NULL,
    event_starts_at DATETIME(6) NOT NULL,
    event_timezone VARCHAR(100) NOT NULL,
    idempotency_key VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL UNIQUE,
    request_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    response_json JSON NOT NULL,
    submission_json JSON NOT NULL,
    INDEX customer_order_status (status, id),
    CONSTRAINT customer_order_customer_fk FOREIGN KEY (customer_id)
        REFERENCES customers (id) ON DELETE RESTRICT,
    CONSTRAINT customer_order_deposit CHECK (deposit_due_cents <= total_cents)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS order_items (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    order_id BIGINT UNSIGNED NOT NULL,
    code VARCHAR(100) NOT NULL,
    description VARCHAR(1000) NOT NULL,
    amount_cents BIGINT NOT NULL,
    CONSTRAINT customer_order_item_fk FOREIGN KEY (order_id)
        REFERENCES orders (id) ON DELETE RESTRICT
) ENGINE=InnoDB;

-- One source order can enter the owner workflow once. Booking, link and audit
-- are written in the same transaction; a failed handoff leaves no partial record.
CREATE TABLE IF NOT EXISTS automation_order_links (
    order_id VARCHAR(100) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    booking_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL UNIQUE,
    data JSON NOT NULL,
    CONSTRAINT automation_order_source_fk FOREIGN KEY (order_id)
        REFERENCES orders (public_id) ON DELETE RESTRICT,
    CONSTRAINT automation_order_booking_fk FOREIGN KEY (booking_id)
        REFERENCES automation_bookings (id) ON DELETE RESTRICT
) ENGINE=InnoDB;
