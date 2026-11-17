import { readFileSync } from "node:fs";
import { centralTimeToIso, EVENT_TIME_ZONE } from "../src/eventTime.js";
import { DEMO_FLAVORS } from "../src/flavors.js";

// These fixtures belong only to the isolated, read-only admin preview.
const spec = JSON.parse(
  readFileSync(new URL("../../docs/api/openapi.json", import.meta.url), "utf8"),
);
const template =
  spec.paths["/orders/{order_id}"].get.responses["200"].content[
    "application/json"
  ].examples.synthetic.value.data;
const customers = [
  ["Elena Cruz", "pending", 150, 1, "full_service"],
  ["Jordan Lee", "awaiting_deposit", 100, 4, "delivery"],
  ["Avery Morgan", "confirmed", 250, 6, "full_service"],
  ["Taylor Brooks", "owner_review", 75, 8, "delivery"],
  ["Casey Nguyen", "fulfilled", 80, -8, "full_service"],
  ["Riley Patel", "confirmed", 200, 10, "delivery"],
];
const moreCustomers = [
  "Morgan Davis",
  "Sofia Ramirez",
  "Noah Bennett",
  "Isabella Chen",
  "Mateo Garcia",
  "Harper Wilson",
  "Camila Torres",
  "Ethan Robinson",
  "Luna Martinez",
  "Oliver Thompson",
  "Mia Anderson",
  "Lucas Rivera",
  "Amelia Scott",
  "Sebastian Flores",
  "Charlotte Kim",
  "Daniel Harris",
  "Aria Castillo",
  "James Walker",
  "Valentina Reyes",
  "Benjamin Clark",
  "Chloe Lewis",
  "Gabriel Ortiz",
  "Victoria Adams",
  "Henry Mitchell",
  "Penelope Wright",
  "Leo Hernandez",
  "Natalie Young",
  "Samuel Allen",
  "Zoe Parker",
  "David Santos",
  "Hannah King",
  "Julian Baker",
  "Layla Gonzalez",
  "William Nelson",
  "Grace Campbell",
  "Adrian Diaz",
  "Nora Phillips",
  "Anthony Evans",
  "Stella Collins",
  "Caleb Turner",
  "Audrey Morris",
  "Isaac Howard",
];
const statuses = [
  "pending",
  "confirmed",
  "confirmed",
  "awaiting_deposit",
  "conditionally_confirmed",
  "owner_review",
  "fulfilled",
  "cancelled",
  "pending",
  "confirmed",
];
const approvedRequests = new Set([
  "Elena Cruz",
  "Morgan Davis",
  "Mia Anderson",
]);
const eventTypes = [
  "Birthday celebration",
  "Office appreciation",
  "Wedding reception",
  "School fundraiser",
  "Baby shower",
  "Neighborhood festival",
  "Graduation party",
  "Holiday celebration",
];
const venues = [
  ["Sample Garden Hall", "100 Example Street", "Houston", "77002"],
  ["Sample Lakeside Pavilion", "200 Example Avenue", "Sugar Land", "77478"],
  ["Sample Community Center", "300 Example Lane", "Missouri City", "77459"],
  ["Sample Rooftop Terrace", "400 Example Boulevard", "Houston", "77006"],
  ["Sample Celebration Barn", "500 Example Drive", "Pearland", "77584"],
  ["Sample School Courtyard", "600 Example Way", "Houston", "77025"],
];
const notes = [
  "Covered serving area by the garden entrance. Venue contact will meet the team.",
  "Please use the loading entrance. Guest arrival is 30 minutes after setup.",
  "Outdoor celebration; reserve a shaded space for the cart and serving line.",
  "Individual ingredient labels requested for the school celebration.",
  "Coordinate arrival with the event planner. Guests will be seated on the patio.",
  "Family event with children. Please keep dry ice away from the guest area.",
];

export function createSampleData(now = new Date()) {
  const timestamp = new Date(now).getTime();
  const today = Object.fromEntries(
    new Intl.DateTimeFormat("en-US", {
      timeZone: EVENT_TIME_ZONE,
      year: "numeric",
      month: "numeric",
      day: "numeric",
    })
      .formatToParts(new Date(timestamp))
      .map((part) => [part.type, part.value]),
  );
  // Normalize civil days first, then apply Houston's actual offset, including DST.
  const stamp = (offset, hour = 16) => {
    const civil = new Date(
      Date.UTC(
        Number(today.year),
        Number(today.month) - 1,
        Number(today.day) + offset,
        hour,
      ),
    );
    return centralTimeToIso(civil.toISOString().slice(0, 16));
  };
  const rows = [
    ...customers,
    ...moreCustomers.map((name, index) => {
      const status = statuses[index % statuses.length];
      const offset =
        status === "fulfilled"
          ? -2 - (index % 15)
          : 1 + Math.floor(index / 2) * 2;
      return [
        name,
        status,
        [50, 75, 100, 125, 150, 200, 250, 300, 400][index % 9],
        offset,
        index % 3 === 0 ? "full_service" : "delivery",
      ];
    }),
  ];
  const records = rows.map(
    ([name, originalStatus, quantity, offset, service], index) => {
      const approved = approvedRequests.has(name);
      const status = approved ? "awaiting_deposit" : originalStatus;
      const order = structuredClone(template);
      const [venue, line1, city, postal_code] = venues[index % venues.length];
      const hour = [12, 14, 16, 18][index % 4];
      const duration = index % 3 === 0 ? 3 : 2;
      const heart = index > 5 && index % 7 === 0;
      const blocks = 3 * Math.ceil(quantity / 150);
      const line_items = [
        {
          code: "paletas",
          description: `${quantity} ${heart ? "heart-shaped" : "regular"} paletas (sample pricing)`,
          amount_cents: quantity * (heart ? 300 : 450),
        },
        {
          code: "dry_ice",
          description: `${blocks} dry ice blocks`,
          amount_cents: 4500 + (blocks - 3) * (quantity > 150 ? 1000 : 1500),
        },
        ...(service === "full_service"
          ? [
              {
                code: "full_service",
                description: "Full service fee",
                amount_cents: 15000,
              },
              {
                code: "staff",
                description: `One employee for ${duration} hours`,
                amount_cents: duration * 1500,
              },
            ]
          : [
              {
                code: "delivery",
                description: "Illustrative delivery fee",
                amount_cents: [2500, 4500, 6000, 7500][index % 4],
              },
            ]),
      ];
      const total = line_items.reduce(
        (sum, item) => sum + item.amount_cents,
        0,
      );
      const deposit = Math.ceil(total / 2);
      const paid =
        status === "fulfilled" || (status === "confirmed" && index % 3 === 2)
          ? total
          : status === "confirmed" ||
              (status === "owner_review" && index % 2 === 1)
            ? deposit
            : 0;
      order.id = `preview_order_${String(index + 1).padStart(3, "0")}`;
      order.version = approved ? 2 : 1;
      order.status = ["fulfilled", "cancelled", "confirmed"].includes(status)
        ? status
        : "pending_review";
      order.customer = {
        name: `Sample ${name}`,
        email: `sample${index + 1}@example.invalid`,
        phone: `+1-202-555-${String(100 + index).padStart(4, "0")}`,
      };
      order.catering_request = {
        ...order.catering_request,
        quantity,
        service_type: service,
        popsicle_shape: heart ? "heart" : "standard",
        dry_ice_blocks: blocks,
        flavor_requests:
          "Featured flavor mix; confirm seasonal availability before the event.",
        flavor_allocations: DEMO_FLAVORS.map((flavor, flavorIndex) => ({
          flavor,
          quantity:
            Math.floor(quantity / 5) + (flavorIndex < quantity % 5 ? 1 : 0),
        })),
        allergy_notes:
          index % 4 === 0
            ? "Please provide ingredient labels for guests with allergies."
            : "",
        add_ons: [],
      };
      order.event = {
        ...order.event,
        type: eventTypes[index % eventTypes.length],
        starts_at: stamp(offset, hour),
        ends_at: stamp(offset, hour + duration),
        timezone: EVENT_TIME_ZONE,
        location: {
          line1,
          city,
          region: "TX",
          postal_code,
          country_code: "US",
        },
        notes: `${notes[index % notes.length]} Fictional event at ${venue}; visual demonstration only.`,
      };
      order.pricing = {
        currency: "USD",
        total_cents: total,
        deposit_due_cents: deposit,
        line_items,
      };
      order.deposit = {
        status: paid >= deposit ? "confirmed" : "pending",
        amount_due_cents: deposit,
        amount_confirmed_cents: Math.min(paid, deposit),
      };
      order.created_at = new Date(
        Math.min(
          timestamp - (index * 6 + 1) * 3600000,
          Date.parse(order.event.starts_at) - 14 * 86400000,
        ),
      ).toISOString();
      order.updated_at = approved
        ? new Date(timestamp).toISOString()
        : order.created_at;
      const calendar =
        status === "confirmed"
          ? index % 5 === 0
            ? "failed"
            : "synced"
          : status === "fulfilled"
            ? "synced"
            : "not_eligible";
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
              timezone: EVENT_TIME_ZONE,
              venue: `${venue}, ${line1}, ${city}, TX ${postal_code}`,
              service_type: service,
              quantity,
              currency: "USD",
              total_minor: total,
              deposit_minor: deposit,
              paid_minor: paid,
              remaining_minor: total - paid,
              overpaid_minor: 0,
              payment_status:
                paid >= total ? "paid" : paid ? "deposit_paid" : "unpaid",
              calendar_status: calendar,
              customer_email: order.customer.email,
              count_finalized: ["fulfilled", "confirmed"].includes(status),
              reservation_expires_at:
                status === "awaiting_deposit"
                  ? new Date(timestamp + 36 * 3600000).toISOString()
                  : null,
              last_synced_at:
                calendar === "synced"
                  ? new Date(timestamp - 3600000).toISOString()
                  : null,
              calendar_error:
                calendar === "failed"
                  ? "Simulated sync failure: review the calendar connection before retrying."
                  : null,
              owner_review_reason:
                status === "owner_review"
                  ? "Sample late deposit received after the reservation expired. Recheck event availability."
                  : null,
              customer_message: approved
                ? "Your sample event availability is approved. The next step is the 50% deposit; the booking is confirmed after payment verification."
                : status === "conditionally_confirmed"
                  ? "Please confirm the covered serving area before we approve this event."
                  : "",
              source_order: order,
            };
      return { order, booking };
    },
  );
  records.sort(
    (a, b) => Date.parse(b.order.created_at) - Date.parse(a.order.created_at),
  );

  const catalog = [
    ...DEMO_FLAVORS.map((name) => [
      name,
      name.includes("Cream") ? "Cream" : "Fruit",
      "Standard",
    ]),
    ...DEMO_FLAVORS.map((name) => [
      name,
      name.includes("Cream") ? "Cream" : "Fruit",
      "Heart",
    ]),
    ["Coconut", "Cream", "Standard"],
    ["Chocolate", "Chocolate", "Standard"],
    ["Pineapple Chili", "Fruit", "Standard"],
    ["Lime", "Fruit", "Standard"],
    ["Horchata", "Cream", "Standard"],
    ["Pumpkin Spice", "Seasonal", "Standard"],
    ["Peppermint Cocoa", "Seasonal", "Standard"],
    ["Mixed Berry", "Fruit", "Heart"],
  ];
  const allocations = {};
  const inventory = catalog.map(([name, category, shape], index) => {
    const item_id = `preview_inventory_${index + 1}`;
    let reserved = 0;
    for (const { order, booking } of records) {
      if (
        booking?.status !== "confirmed" ||
        Date.parse(booking.end) < timestamp ||
        (order.catering_request.popsicle_shape === "heart"
          ? "Heart"
          : "Standard") !== shape
      )
        continue;
      const quantity =
        order.catering_request.flavor_allocations.find(
          (row) => row.flavor === name,
        )?.quantity || 0;
      if (quantity) {
        reserved += quantity;
        (allocations[booking.id] ||= []).push({ item_id, quantity });
      }
    }
    const available = [
      280, 175, 30, 0, 15, 120, 80, 20, 0, 60, 180, 95, 140, 25, 70, 90, 45,
      110,
    ][index];
    return {
      id: item_id,
      name,
      category,
      shape,
      onHand: reserved + available,
      reserved,
      available,
      minimum: shape === "Heart" ? 30 : 50,
      notes:
        "Fictional stock for the admin demo. Flavor availability and counts are illustrative.",
      active: true,
      version: 1,
    };
  });
  const history = Object.fromEntries(
    inventory.map((item) => [
      item.id,
      [
        {
          type: "remove",
          qty: 20,
          reason: "Event fulfillment",
          note: "Sample catering event pickup.",
          date: stamp(-1, 11),
        },
        {
          type: "add",
          qty: item.onHand + 20,
          reason: "Production batch",
          note: "Sample freezer restock.",
          date: stamp(-3, 9),
        },
      ],
    ]),
  );
  const events = records
    .map(({ order, booking }) => ({
      id: order.id,
      reference: booking?.reference || order.id,
      order_id: order.id,
      booking_id: booking?.id || null,
      customer: order.customer.name,
      email: order.customer.email,
      phone: order.customer.phone,
      start: order.event.starts_at,
      end: order.event.ends_at,
      timezone: EVENT_TIME_ZONE,
      venue:
        booking?.venue ||
        [order.event.location.line1, order.event.location.city, "TX"].join(
          ", ",
        ),
      service_type: order.catering_request.service_type,
      quantity: order.catering_request.quantity,
      status: booking?.status || "pending",
      calendar_status: booking?.calendar_status || "not_linked",
      currency: "USD",
      total_cents: order.pricing.total_cents,
      paid_cents: booking?.paid_minor || 0,
      remaining_cents: booking?.remaining_minor ?? order.pricing.total_cents,
    }))
    .sort((a, b) => Date.parse(a.start) - Date.parse(b.start));
  const windowEnd = timestamp + 30 * 86400000;
  const upcoming = events.filter(
    (event) =>
      event.status === "confirmed" &&
      Date.parse(event.start) >= timestamp &&
      Date.parse(event.start) < windowEnd,
  );
  const count = (status) =>
    events.filter((event) => event.status === status).length;
  const balance = events
    .filter((event) => event.status === "confirmed")
    .reduce((sum, event) => sum + event.remaining_cents, 0);
  const dashboard = {
    requests: count("pending"),
    awaiting_deposit: count("awaiting_deposit"),
    owner_review: count("owner_review"),
    balances: balance ? [{ currency: "USD", remaining_cents: balance }] : [],
    low_stock: inventory.filter((item) => item.available < item.minimum).length,
    reserved_units: inventory.reduce((sum, item) => sum + item.reserved, 0),
    upcoming_count: upcoming.length,
    upcoming_quantity: upcoming.reduce((sum, event) => sum + event.quantity, 0),
    upcoming: upcoming.slice(0, 3),
    recent_orders: records.slice(0, 5),
    window_end: new Date(windowEnd).toISOString(),
    storage: "preview",
  };
  const bookingDetails = Object.fromEntries(
    records
      .filter((record) => record.booking)
      .map(({ booking }) => [
        booking.id,
        {
          booking,
          payments: booking.paid_minor
            ? [
                {
                  provider: "square",
                  square_environment: "sandbox",
                  reference: `SAMPLE-PAY-${booking.reference}`,
                  amount_minor: booking.paid_minor,
                  currency: "USD",
                },
              ]
            : [],
          jobs: [
            {
              key: `sample-job-${booking.id}`,
              kind:
                booking.status === "confirmed"
                  ? "booking_confirmation"
                  : booking.status === "awaiting_deposit"
                    ? "deposit_request"
                    : "request_review",
              status: "simulated",
              delivery: { status: "simulated" },
            },
          ],
          events: [],
          allocations: allocations[booking.id] || [],
        },
      ]),
  );
  const notifications = {
    enabled: false,
    recipient: "sample-owner@example.invalid",
    email_mode: "simulated",
    requests: records.slice(0, 6).map(({ order, booking }) => ({
      order_id: order.id,
      email_status: "simulated",
      calendar_status: booking ? "booking" : "synced",
    })),
  };
  return {
    records,
    inventory,
    history,
    allocations,
    events,
    dashboard,
    bookingDetails,
    notifications,
  };
}
