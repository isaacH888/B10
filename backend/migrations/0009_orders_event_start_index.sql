-- Speeds up list, export and upcoming events, which filter and sort on event start.
CREATE INDEX orders_event_start ON orders (event_starts_at);
