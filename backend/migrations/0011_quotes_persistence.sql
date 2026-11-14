-- Persist priced quotes so order submission can enforce expiry and payload binding.
CREATE TABLE IF NOT EXISTS quotes (
    id VARCHAR(255) PRIMARY KEY,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL,
    delivery_distance_miles DECIMAL(6,2) NOT NULL,
    total_minor INT NOT NULL,
    payload_json JSON NOT NULL,
    is_used BOOLEAN DEFAULT FALSE
) ENGINE=InnoDB;
