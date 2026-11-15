-- Durable email/Calendar projections for submitted requests, before booking approval.
CREATE TABLE IF NOT EXISTS automation_requests (
    id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    order_id VARCHAR(100) CHARACTER SET ascii COLLATE ascii_bin NOT NULL UNIQUE,
    data JSON NOT NULL,
    CONSTRAINT automation_request_order_fk FOREIGN KEY (order_id)
        REFERENCES orders (public_id) ON DELETE RESTRICT
) ENGINE=InnoDB;
