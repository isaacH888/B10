-- Durable catalog, append-only stock history, replay protection and explicit allocations.
CREATE TABLE IF NOT EXISTS inventory_items (
    id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    category VARCHAR(40) NOT NULL,
    shape VARCHAR(40) NOT NULL,
    on_hand BIGINT UNSIGNED NOT NULL,
    minimum BIGINT UNSIGNED NOT NULL,
    notes VARCHAR(2000) NOT NULL,
    version INT UNSIGNED NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    INDEX inventory_active_name (active, name),
    CONSTRAINT inventory_count_limit CHECK (on_hand <= 1000000000),
    CONSTRAINT inventory_minimum_limit CHECK (minimum BETWEEN 1 AND 1000000000)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS inventory_actions (
    action_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    request_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    response_json JSON NULL,
    created_at DATETIME(6) NOT NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS inventory_history (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    item_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    type VARCHAR(20) CHARACTER SET ascii NOT NULL,
    quantity BIGINT UNSIGNED NOT NULL,
    before_count BIGINT UNSIGNED NOT NULL,
    after_count BIGINT UNSIGNED NOT NULL,
    reason VARCHAR(100) NOT NULL,
    note VARCHAR(2000) NOT NULL,
    actor VARCHAR(128) NOT NULL,
    created_at DATETIME(6) NOT NULL,
    INDEX inventory_item_history (item_id, id),
    CONSTRAINT inventory_history_item_fk FOREIGN KEY (item_id) REFERENCES inventory_items(id) ON DELETE RESTRICT
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS inventory_reservations (
    booking_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    item_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    quantity BIGINT UNSIGNED NOT NULL,
    active BOOLEAN NOT NULL,
    PRIMARY KEY (booking_id, item_id),
    INDEX inventory_item_reservations (item_id, active),
    CONSTRAINT inventory_reservation_booking_fk FOREIGN KEY (booking_id) REFERENCES automation_bookings(id) ON DELETE RESTRICT,
    CONSTRAINT inventory_reservation_item_fk FOREIGN KEY (item_id) REFERENCES inventory_items(id) ON DELETE RESTRICT,
    CONSTRAINT inventory_reservation_positive CHECK (quantity > 0)
) ENGINE=InnoDB;
