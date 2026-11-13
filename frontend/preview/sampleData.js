import { readFileSync } from "node:fs";

// Start with the documented synthetic contract example, never the application DB.
const spec = JSON.parse(
  readFileSync(new URL("../../docs/api/openapi.json", import.meta.url), "utf8"),
);
const template =
  spec.paths["/orders/{order_id}"].get.responses["200"].content[
    "application/json"
  ].examples.synthetic.value.data;

export function createSampleData() {
  const today = new Date();
  const year = today.getFullYear();
  const month = today.getMonth() + 1;
  const stamp = (day, hour = 16) =>
    `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}T${hour}:00:00-06:00`;
  const customers = [
    ["Elena Cruz", "pending", 150, 18, "full_service"],
    ["Jordan Lee", "awaiting_deposit", 100, 21, "delivery"],
    ["Avery Morgan", "confirmed", 250, 23, "full_service"],
    ["Taylor Brooks", "owner_review", 75, 25, "delivery"],
    ["Casey Nguyen", "fulfilled", 80, 9, "full_service"],
    ["Riley Patel", "confirmed", 200, 27, "delivery"],
  ];
  const records = customers.map(
    ([name, status, quantity, day, service], index) => {
      const order = structuredClone(template);
      order.id = `preview_order_${String(index + 1).padStart(3, "0")}`;
      order.status = status === "pending" ? "pending_review" : status;
      order.customer = {
        name: `Sample ${name}`,
        email: `sample${index + 1}@example.invalid`,
        phone: `+1-202-555-010${index}`,
      };
      order.catering_request = {
        ...order.catering_request,
        quantity,
        service_type: service,
        flavor_requests: "Mango, strawberry, and coconut",
      };
      order.event = {
        ...order.event,
        type: ["Birthday celebration", "Office party", "Wedding reception"][
          index % 3
        ],
        starts_at: stamp(day),
        ends_at: stamp(day, 18),
        notes: "Sample event for exploring the admin screens.",
      };
      order.pricing.total_cents = quantity * 400;
      order.pricing.deposit_due_cents = quantity * 200;
      order.pricing.line_items = [
        {
          code: "preview_package",
          description: "Sample catering package (illustrative price)",
          amount_cents: quantity * 400,
        },
      ];
      order.created_at = stamp(Math.max(1, day - 7));
      order.updated_at = order.created_at;
      const paid = ["confirmed", "fulfilled"].includes(status)
        ? quantity * (index === 2 ? 200 : 400)
        : 0;
      const booking =
        status === "pending"
          ? null
          : {
              id: `preview_booking_${index + 1}`,
              reference: `PREVIEW-${String(index + 1).padStart(3, "0")}`,
              status,
              revision: 1,
              start: order.event.starts_at,
              end: order.event.ends_at,
              timezone: "America/Chicago",
              venue: "100 Example Street, Houston, TX",
              service_type: service,
              quantity,
              currency: "USD",
              total_minor: quantity * 400,
              deposit_minor: quantity * 200,
              paid_minor: paid,
              remaining_minor: quantity * 400 - paid,
              overpaid_minor: 0,
              payment_status: paid ? "deposit_paid" : "unpaid",
              calendar_status: status === "confirmed" ? "synced" : "pending",
              source_order: order,
            };
      return { order, booking };
    },
  );
  const inventory = [
    ["Mango", "Fruit", 260, 80, 50],
    ["Strawberry", "Fruit", 190, 60, 40],
    ["Coconut", "Cream", 140, 50, 40],
    ["Chocolate", "Chocolate", 44, 20, 40],
    ["Lime", "Fruit", 30, 15, 30],
    ["Pumpkin spice", "Seasonal", 90, 0, 20],
  ].map(([name, category, onHand, reserved, minimum], index) => ({
    id: `preview_inventory_${index + 1}`,
    name,
    category,
    shape: "Standard",
    onHand,
    reserved,
    available: onHand - reserved,
    minimum,
    notes: "Sample inventory. Changes are disabled in this preview.",
    active: true,
    version: 1,
  }));
  const events = records.map(({ order, booking }) => ({
    id: order.id,
    reference: booking?.reference || order.id,
    order_id: order.id,
    booking_id: booking?.id || null,
    customer: order.customer.name,
    email: order.customer.email,
    phone: order.customer.phone,
    start: order.event.starts_at,
    end: order.event.ends_at,
    timezone: "America/Chicago",
    venue: "100 Example Street, Houston, TX",
    service_type: order.catering_request.service_type,
    quantity: order.catering_request.quantity,
    status: booking?.status || "pending",
    calendar_status: booking?.calendar_status || "not_linked",
    currency: "USD",
    total_cents: order.pricing.total_cents,
    paid_cents: booking?.paid_minor || 0,
    remaining_cents: booking?.remaining_minor ?? order.pricing.total_cents,
  }));
  const upcoming = events.filter((event) => event.status === "confirmed");
  const dashboard = {
    requests: 1,
    awaiting_deposit: 1,
    owner_review: 1,
    balances: [{ currency: "USD", remaining_cents: 50000 }],
    low_stock: inventory.filter((item) => item.available < item.minimum).length,
    reserved_units: inventory.reduce((sum, item) => sum + item.reserved, 0),
    upcoming_count: upcoming.length,
    upcoming_quantity: upcoming.reduce((sum, event) => sum + event.quantity, 0),
    upcoming,
    recent_orders: records,
    window_end: new Date(year, month, 1).toISOString(),
    storage: "preview",
  };
  return { records, inventory, events, dashboard };
}
