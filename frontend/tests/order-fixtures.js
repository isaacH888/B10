import { readFileSync } from "node:fs";

const spec = JSON.parse(
  readFileSync(new URL("../../docs/api/openapi.json", import.meta.url), "utf8"),
);

export function savedOrder() {
  return structuredClone(
    spec.paths["/orders/{order_id}"].get.responses["200"].content[
      "application/json"
    ].examples.synthetic.value.data,
  );
}

export function linkedBooking(order = savedOrder()) {
  return {
    id: "0123456789abcdef0123456789abcdef",
    reference: "POP-SYNTHETIC",
    status: "confirmed",
    revision: 2,
    start: "2099-01-16T18:00:00-06:00",
    end: "2099-01-16T20:00:00-06:00",
    timezone: "America/Chicago",
    venue: "200 Updated Example Street, Houston, TX",
    service_type: "delivery",
    quantity: 50,
    currency: "USD",
    total_minor: order.pricing.total_cents,
    deposit_minor: order.pricing.deposit_due_cents,
    paid_minor: order.pricing.deposit_due_cents,
    remaining_minor:
      order.pricing.total_cents - order.pricing.deposit_due_cents,
    overpaid_minor: 0,
    payment_status: "deposit_paid",
    calendar_status: "synced",
  };
}

export function calendarEvent(overrides = {}) {
  return {
    id: "order_example_001",
    reference: "order_example_001",
    order_id: "order_example_001",
    booking_id: null,
    customer: "Example Customer",
    email: "customer@example.invalid",
    phone: "+1-202-555-0100",
    start: "2026-11-21T17:00:00Z",
    end: "2026-11-21T19:00:00Z",
    timezone: "America/Chicago",
    venue: "100 Example Street, Houston, TX",
    service_type: "delivery",
    quantity: 50,
    status: "pending",
    calendar_status: "not_linked",
    currency: "USD",
    total_cents: 20000,
    paid_cents: 0,
    remaining_cents: 20000,
    ...overrides,
  };
}

export function dashboardData() {
  return {
    requests: 1,
    awaiting_deposit: 0,
    owner_review: 0,
    balances: [],
    low_stock: 0,
    reserved_units: 0,
    upcoming_count: 0,
    upcoming_quantity: 0,
    upcoming: [],
    window_end: "2026-12-11T00:00:00Z",
    recent_orders: [{ order: savedOrder(), booking: null }],
    storage: "database",
  };
}
