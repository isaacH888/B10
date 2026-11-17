-- Account ownership comes from the verified customer session, never contact email.
-- Existing guest records stay unclaimed until an explicit ownership review.
CREATE TABLE IF NOT EXISTS customer_quote_accounts (
    quote_id VARCHAR(255) PRIMARY KEY,
    identity_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    CONSTRAINT customer_quote_account_quote_fk FOREIGN KEY (quote_id)
        REFERENCES quotes (id) ON DELETE RESTRICT
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS customer_order_accounts (
    order_id VARCHAR(100) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    identity_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    INDEX customer_account_orders (identity_id, order_id),
    CONSTRAINT customer_order_account_order_fk FOREIGN KEY (order_id)
        REFERENCES orders (public_id) ON DELETE RESTRICT
) ENGINE=InnoDB;
