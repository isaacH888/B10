/**
 * Admin API layer — Popssibilities
 * =================================
 * All backend calls for the admin section go through this file.
 * The backend team should implement the endpoints listed below and update
 * the functions accordingly. Each function documents:
 *   - Expected HTTP method + path
 *   - Request body shape (where applicable)
 *   - Expected response shape
 *
 * During development, every function falls back to a mock that works
 * entirely in-memory so the UI can be built and demoed without a live API.
 *
 * To switch from mock → real API:
 *   1. Set  USE_MOCK_API = false
 *   2. Make sure the backend is running and the Vite proxy is configured
 *      (see vite.config.js — /api/v1 proxies to localhost:5000)
 */

const USE_MOCK_API = true; // ← flip to false when the API is ready

// ---------------------------------------------------------------------------
// Shared fetch helper (mirrors the existing apiRequest in src/auth/api.js)
// ---------------------------------------------------------------------------
async function adminRequest(path, options = {}) {
  const res = await fetch(`/api/v1${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const err = new Error(body.message || `Request failed: ${res.status}`);
    err.status = res.status;
    err.body = body;
    throw err;
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// In-memory mock store (used when USE_MOCK_API = true)
// ---------------------------------------------------------------------------
let MOCK_ITEMS = [
  {
    id: "PA-001",
    name: "Mango",
    category: "Fruit",
    shape: "Standard",
    onHand: 220,
    reserved: 180,
    minimum: 60,
    notes: "Bestseller in summer.",
  },
  {
    id: "PA-002",
    name: "Strawberry",
    category: "Fruit",
    shape: "Standard",
    onHand: 180,
    reserved: 150,
    minimum: 50,
    notes: "",
  },
  {
    id: "PA-003",
    name: "Coconut",
    category: "Cream",
    shape: "Standard",
    onHand: 140,
    reserved: 120,
    minimum: 40,
    notes: "Cream base, sensitive to temp.",
  },
  {
    id: "PA-004",
    name: "Lime",
    category: "Fruit",
    shape: "Standard",
    onHand: 240,
    reserved: 100,
    minimum: 60,
    notes: "",
  },
  {
    id: "PA-005",
    name: "Chocolate",
    category: "Cream",
    shape: "Dipped",
    onHand: 200,
    reserved: 80,
    minimum: 50,
    notes: "Chocolate dip adds 2 days.",
  },
  {
    id: "PA-006",
    name: "Pineapple",
    category: "Fruit",
    shape: "Standard",
    onHand: 220,
    reserved: 50,
    minimum: 60,
    notes: "",
  },
];

let MOCK_HISTORY = {
  "PA-001": [
    {
      date: "Nov 3, 2026",
      type: "add",
      qty: 120,
      reason: "Production batch",
      note: "Batch M-1103 · Freezer A",
    },
    {
      date: "Oct 28, 2026",
      type: "remove",
      qty: 20,
      reason: "Waste / damage",
      note: "Freezer malfunction",
    },
  ],
  "PA-002": [
    {
      date: "Nov 1, 2026",
      type: "add",
      qty: 100,
      reason: "Production batch",
      note: "",
    },
  ],
};

function mockDelay(ms = 400) {
  return new Promise((r) => setTimeout(r, ms));
}

function deriveAvailable(item) {
  return { ...item, available: item.onHand - item.reserved };
}

// ---------------------------------------------------------------------------
// Inventory API
// ---------------------------------------------------------------------------

/**
 * GET /api/v1/admin/inventory
 * Response: { items: InventoryItem[] }
 *
 * InventoryItem: { id, name, category, shape, onHand, reserved, available, minimum, notes }
 */
export async function fetchInventory() {
  if (USE_MOCK_API) {
    await mockDelay();
    return { items: MOCK_ITEMS.map(deriveAvailable) };
  }
  return adminRequest("/admin/inventory");
}

/**
 * POST /api/v1/admin/inventory
 * Body:    { name, category, shape, onHand, minimum, notes }
 * Response: { item: InventoryItem }
 */
export async function createInventoryItem(data) {
  if (USE_MOCK_API) {
    await mockDelay();
    const id = `PA-${String(MOCK_ITEMS.length + 1).padStart(3, "0")}`;
    const item = { id, reserved: 0, ...data };
    MOCK_ITEMS.push(item);
    return { item: deriveAvailable(item) };
  }
  return adminRequest("/admin/inventory", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

/**
 * PATCH /api/v1/admin/inventory/:id
 * Body:    { name?, category?, shape?, minimum?, notes? }
 * Response: { item: InventoryItem }
 */
export async function updateInventoryItem(id, data) {
  if (USE_MOCK_API) {
    await mockDelay();
    const idx = MOCK_ITEMS.findIndex((i) => i.id === id);
    if (idx === -1) throw new Error("Item not found");
    MOCK_ITEMS[idx] = { ...MOCK_ITEMS[idx], ...data };
    return { item: deriveAvailable(MOCK_ITEMS[idx]) };
  }
  return adminRequest(`/admin/inventory/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

/**
 * POST /api/v1/admin/inventory/:id/adjust
 * Body:    { type: "add" | "remove" | "set", quantity: number, reason: string, note?: string }
 * Response: { item: InventoryItem }
 *
 * Backend should:
 *   - "add"    → onHand += quantity
 *   - "remove" → onHand -= quantity  (reject if onHand - qty < 0)
 *   - "set"    → onHand = quantity   (reject if qty < reserved)
 *   - Append an entry to the item's stock_history table
 */
export async function adjustStock(id, { type, quantity, reason, note }) {
  if (USE_MOCK_API) {
    await mockDelay();
    const idx = MOCK_ITEMS.findIndex((i) => i.id === id);
    if (idx === -1) throw new Error("Item not found");
    const item = MOCK_ITEMS[idx];
    let newOnHand;
    if (type === "add") newOnHand = item.onHand + quantity;
    else if (type === "remove") newOnHand = item.onHand - quantity;
    else newOnHand = quantity; // "set"

    if (newOnHand < 0) throw new Error("Cannot reduce stock below 0.");
    if (newOnHand < item.reserved)
      throw new Error(
        `Cannot set stock below reserved amount (${item.reserved}).`,
      );

    MOCK_ITEMS[idx] = { ...item, onHand: newOnHand };
    if (!MOCK_HISTORY[id]) MOCK_HISTORY[id] = [];
    MOCK_HISTORY[id].unshift({
      date: new Date().toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
      }),
      type,
      qty: quantity,
      reason,
      note: note || "",
    });
    return { item: deriveAvailable(MOCK_ITEMS[idx]) };
  }
  return adminRequest(`/admin/inventory/${id}/adjust`, {
    method: "POST",
    body: JSON.stringify({ type, quantity, reason, note }),
  });
}

/**
 * GET /api/v1/admin/inventory/:id/history
 * Response: { history: StockHistoryEntry[] }
 *
 * StockHistoryEntry: { date, type, qty, reason, note }
 */
export async function fetchStockHistory(id) {
  if (USE_MOCK_API) {
    await mockDelay(200);
    return { history: MOCK_HISTORY[id] || [] };
  }
  return adminRequest(`/admin/inventory/${id}/history`);
}

/**
 * DELETE /api/v1/admin/inventory/:id
 * Response: { ok: true }
 */
export async function deleteInventoryItem(id) {
  if (USE_MOCK_API) {
    await mockDelay();
    MOCK_ITEMS = MOCK_ITEMS.filter((i) => i.id !== id);
    return { ok: true };
  }
  return adminRequest(`/admin/inventory/${id}`, { method: "DELETE" });
}

// ===========================================================================
// Orders API
// ===========================================================================

let MOCK_ORDERS = [
  {
    id: "#1048",
    customer: "Sofia Ramirez",
    email: "sofia.ramirez@example.com",
    phone: "(713) 555-0148",
    date: "Nov 21, 2026",
    dateIso: "2026-11-21",
    service: "Delivery",
    qty: 200,
    orderStatus: "pending",
    orderStatusLabel: "Pending request",
    paymentStatus: "unpaid",
    paymentStatusLabel: "Unpaid · Deposit due",
    paymentSub: "$620 minimum needed to confirm",
    calendarSync: "not_eligible",
    calendarSyncLabel: "Not eligible yet",
    calendarSyncSub: "Only confirmed bookings sync",
    createdLabel: "New request · Received November 3, 2026",
    location: {
      name: "The Celebration Room",
      address: "1201 Fannin St",
      city: "Houston, TX 77002",
    },
    arrivalWindow: "11:30 AM–12:00 PM",
    flavors: "Mango 80 · Strawberry 80 · Lime 40",
    shapes: "Classic 150 · Mini heart 50",
    addOns: "Custom wrappers · 200 × $0.50",
    flavorRequests: "Fruit flavors only; no cream paletas.",
    specialInstructions:
      "Call Sofia on arrival. Use the loading entrance on Fannin St. Provide labeled coolers and serving instructions.",
    lineItems: [
      { desc: "200 paletas × $5.00", amount: "$1,000" },
      { desc: "Full Service", amount: "$0" },
      { desc: "Delivery", amount: "$100" },
      { desc: "Dry ice", amount: "$40" },
      { desc: "Custom wrappers", amount: "$100" },
    ],
    total: "$1,240",
    deposit: "$620",
    verified: "$0",
    remaining: "$1,240",
    payments: [],
    confirmBanner: {
      heading: "NOT CONFIRMED YET",
      body: "Approve availability + verify at least $620 (50%). No calendar booking or stock reservation until both are met.",
    },
  },
  {
    id: "#1047",
    customer: "Oakwood PTA",
    email: "pta@oakwoodschool.org",
    phone: "(713) 555-0147",
    date: "Nov 20, 2026",
    dateIso: "2026-11-20",
    service: "Full Service",
    qty: 150,
    orderStatus: "pending",
    orderStatusLabel: "Pending request",
    paymentStatus: "unpaid",
    paymentStatusLabel: "Unpaid · Deposit due",
    paymentSub: "$750 minimum needed to confirm",
    calendarSync: "not_eligible",
    calendarSyncLabel: "Not eligible yet",
    calendarSyncSub: "Only confirmed bookings sync",
    createdLabel: "New request · Received November 2, 2026",
    location: {
      name: "Oakwood Elementary",
      address: "5765 Linkwood Dr",
      city: "Houston, TX 77025",
    },
    arrivalWindow: "12:00 PM–1:00 PM",
    flavors: "Mango 60 · Strawberry 50 · Lime 40",
    shapes: "Classic 150",
    addOns: "None",
    flavorRequests: "No coconut — nut allergies in the class.",
    specialInstructions:
      "Set up in the cafeteria. Contact the front office first.",
    lineItems: [
      { desc: "150 paletas × $6.00", amount: "$900" },
      { desc: "Full Service team", amount: "$300" },
      { desc: "Delivery", amount: "$60" },
      { desc: "Dry ice", amount: "$40" },
    ],
    total: "$1,500",
    deposit: "$750",
    verified: "$0",
    remaining: "$1,500",
    payments: [],
    confirmBanner: {
      heading: "NOT CONFIRMED YET",
      body: "Approve availability + verify at least $750 (50%). No calendar booking or stock reservation until both are met.",
    },
  },
  {
    id: "#1046",
    customer: "James Wilson",
    email: "james.wilson@example.com",
    phone: "(713) 555-0146",
    date: "Nov 18, 2026",
    dateIso: "2026-11-18",
    service: "Delivery",
    qty: 80,
    orderStatus: "pending",
    orderStatusLabel: "Pending request",
    paymentStatus: "unpaid",
    paymentStatusLabel: "Unpaid · Deposit due",
    paymentSub: "$260 minimum needed to confirm",
    calendarSync: "not_eligible",
    calendarSyncLabel: "Not eligible yet",
    calendarSyncSub: "Only confirmed bookings sync",
    createdLabel: "New request · Received November 2, 2026",
    location: {
      name: "Midtown Event Space",
      address: "3015 Main St",
      city: "Houston, TX 77002",
    },
    arrivalWindow: "1:30 PM",
    flavors: "Mango 40 · Lime 40",
    shapes: "Classic 80",
    addOns: "None",
    flavorRequests: "Equal mango and lime.",
    specialInstructions: "Park in the back lot. Text James before entering.",
    lineItems: [
      { desc: "80 paletas × $5.00", amount: "$400" },
      { desc: "Delivery", amount: "$80" },
      { desc: "Dry ice", amount: "$40" },
    ],
    total: "$520",
    deposit: "$260",
    verified: "$0",
    remaining: "$520",
    payments: [],
    confirmBanner: {
      heading: "NOT CONFIRMED YET",
      body: "Approve availability + verify at least $260 (50%). No calendar booking or stock reservation until both are met.",
    },
  },
  {
    id: "#1045",
    customer: "Elena Martinez",
    email: "elena.martinez@example.com",
    phone: "(713) 555-0145",
    date: "Nov 7, 2026",
    dateIso: "2026-11-07",
    service: "Full Service",
    qty: 150,
    orderStatus: "confirmed",
    orderStatusLabel: "Confirmed",
    paymentStatus: "partial",
    paymentStatusLabel: "Part paid · 50% verified",
    paymentSub: "$650 verified · $650 remaining",
    calendarSync: "failed",
    calendarSyncLabel: "Sync failed",
    calendarSyncSub: "Google Calendar · Retry sync →",
    createdLabel: "Confirmed booking · Created October 27, 2026",
    location: {
      name: "Hermann Park",
      address: "1500 Hermann Dr",
      city: "Houston, TX 77004",
    },
    arrivalWindow: "1:30 PM",
    flavors: "Mango 60 · Strawberry 50 · Coconut 40",
    shapes: "Classic 100 · Mini heart 50",
    addOns: "Custom wrappers · 100 × $0.50",
    flavorRequests: "Favor mango; keep coconut separate.",
    specialInstructions:
      "Set up near the picnic pavilion. Coconut contains dairy; label and serve separately. Contact Elena on arrival before unloading.",
    lineItems: [
      { desc: "150 paletas × $6.00", amount: "$900" },
      { desc: "Full Service team", amount: "$250" },
      { desc: "Delivery", amount: "$60" },
      { desc: "Dry ice", amount: "$40" },
      { desc: "Custom wrappers", amount: "$50" },
    ],
    total: "$1,300",
    deposit: "$650",
    verified: "$650",
    remaining: "$650",
    payments: [
      {
        method: "Venmo",
        amount: "$650",
        ref: "VM-1028-1045",
        date: "Oct 28, 2026",
        verifiedBy: "Owner",
        note: "Settled receipt matched to customer.",
      },
    ],
    confirmBanner: {
      heading: "BOOKING CONFIRMED — FULL PAYMENT IS NOT REQUIRED",
      body: "Availability approved + verified $650 deposit (50%). The remaining $650 does not block this booking.",
    },
  },
  {
    id: "#1044",
    customer: "Bayou Creative",
    email: "events@bayoucreative.com",
    phone: "(713) 555-0144",
    date: "Nov 8, 2026",
    dateIso: "2026-11-08",
    service: "Delivery",
    qty: 120,
    orderStatus: "confirmed",
    orderStatusLabel: "Confirmed",
    paymentStatus: "review",
    paymentStatusLabel: "Part paid · Review",
    paymentSub: "$480 unverified",
    calendarSync: "synced",
    calendarSyncLabel: "Synced",
    calendarSyncSub: "Google Calendar · owner@popssibilities.com",
    createdLabel: "Confirmed booking · Created October 25, 2026",
    location: {
      name: "Bayou Creative Studio",
      address: "2802 White Oak Dr",
      city: "Houston, TX 77007",
    },
    arrivalWindow: "10:30 AM",
    flavors: "Mango 50 · Strawberry 40 · Lime 30",
    shapes: "Classic 120",
    addOns: "None",
    flavorRequests: "Tropical focus.",
    specialInstructions:
      "Use the side entrance. Event starts promptly at 11 AM.",
    lineItems: [
      { desc: "120 paletas × $5.50", amount: "$660" },
      { desc: "Delivery", amount: "$80" },
      { desc: "Dry ice", amount: "$40" },
    ],
    total: "$960",
    deposit: "$480",
    verified: "$480",
    remaining: "$480",
    payments: [
      {
        method: "Zelle",
        amount: "$480",
        ref: "ZL-1025-1044",
        date: "Oct 25, 2026",
        verifiedBy: "Owner",
        note: "Transfer screenshot reviewed.",
      },
    ],
    confirmBanner: {
      heading: "BOOKING CONFIRMED — FULL PAYMENT IS NOT REQUIRED",
      body: "Availability approved + verified $480 deposit (50%). The remaining $480 does not block this booking.",
    },
  },
  {
    id: "#1043",
    customer: "Priya Patel",
    email: "priya.patel@example.com",
    phone: "(713) 555-0143",
    date: "Nov 10, 2026",
    dateIso: "2026-11-10",
    service: "Full Service",
    qty: 100,
    orderStatus: "confirmed",
    orderStatusLabel: "Confirmed",
    paymentStatus: "review",
    paymentStatusLabel: "Part paid · Review",
    paymentSub: "$250 unverified",
    calendarSync: "synced",
    calendarSyncLabel: "Synced",
    calendarSyncSub: "Google Calendar",
    createdLabel: "Confirmed booking · Created October 22, 2026",
    location: {
      name: "Rice University Faculty Club",
      address: "6100 Main St",
      city: "Houston, TX 77005",
    },
    arrivalWindow: "2:30 PM",
    flavors: "Coconut 40 · Mango 30 · Strawberry 30",
    shapes: "Classic 70 · Mini heart 30",
    addOns: "None",
    flavorRequests: "Tropical mix preferred.",
    specialInstructions:
      "Service entrance on University Blvd side. Valet will direct.",
    lineItems: [
      { desc: "100 paletas × $6.00", amount: "$600" },
      { desc: "Full Service team", amount: "$300" },
      { desc: "Delivery", amount: "$60" },
      { desc: "Dry ice", amount: "$40" },
    ],
    total: "$1,000",
    deposit: "$500",
    verified: "$500",
    remaining: "$500",
    payments: [
      {
        method: "PayPal",
        amount: "$500",
        ref: "PP-1022-1043",
        date: "Oct 22, 2026",
        verifiedBy: "Owner",
        note: "",
      },
    ],
    confirmBanner: {
      heading: "BOOKING CONFIRMED — FULL PAYMENT IS NOT REQUIRED",
      body: "Availability approved + verified $500 deposit (50%). The remaining $500 does not block this booking.",
    },
  },
  {
    id: "#1042",
    customer: "Northside School",
    email: "admin@northsideschool.edu",
    phone: "(713) 555-0142",
    date: "Nov 12, 2026",
    dateIso: "2026-11-12",
    service: "Delivery",
    qty: 100,
    orderStatus: "confirmed",
    orderStatusLabel: "Confirmed",
    paymentStatus: "partial",
    paymentStatusLabel: "50% verified",
    paymentSub: "$300 remaining",
    calendarSync: "synced",
    calendarSyncLabel: "Synced",
    calendarSyncSub: "Google Calendar",
    createdLabel: "Confirmed booking · Created October 20, 2026",
    location: {
      name: "Northside Elementary",
      address: "150 W Crosstimbers Rd",
      city: "Houston, TX 77018",
    },
    arrivalWindow: "9:30 AM",
    flavors: "Mango 50 · Lime 30 · Strawberry 20",
    shapes: "Classic 100",
    addOns: "None",
    flavorRequests: "No cream flavors — dairy restriction.",
    specialInstructions:
      "Coordinate with the cafeteria manager. Arrival no earlier than 9:30.",
    lineItems: [
      { desc: "100 paletas × $5.00", amount: "$500" },
      { desc: "Delivery", amount: "$60" },
      { desc: "Dry ice", amount: "$40" },
    ],
    total: "$600",
    deposit: "$300",
    verified: "$300",
    remaining: "$300",
    payments: [
      {
        method: "Check",
        amount: "$300",
        ref: "CHK-1020-1042",
        date: "Oct 20, 2026",
        verifiedBy: "Owner",
        note: "Mailed check deposited.",
      },
    ],
    confirmBanner: {
      heading: "BOOKING CONFIRMED — FULL PAYMENT IS NOT REQUIRED",
      body: "Availability approved + verified $300 deposit (50%). The remaining $300 does not block this booking.",
    },
  },
  {
    id: "#1041",
    customer: "Museum District",
    email: "events@museumdistrict.org",
    phone: "(713) 555-0141",
    date: "Nov 14, 2026",
    dateIso: "2026-11-14",
    service: "Delivery",
    qty: 100,
    orderStatus: "confirmed",
    orderStatusLabel: "Confirmed",
    paymentStatus: "partial",
    paymentStatusLabel: "50% verified",
    paymentSub: "$180 remaining",
    calendarSync: "synced",
    calendarSyncLabel: "Synced",
    calendarSyncSub: "Google Calendar",
    createdLabel: "Confirmed booking · Created October 18, 2026",
    location: {
      name: "Buffalo Bayou Park Cistern",
      address: "105 Sabine St",
      city: "Houston, TX 77007",
    },
    arrivalWindow: "11:30 AM",
    flavors: "Mango 50 · Coconut 30 · Lime 20",
    shapes: "Classic 100",
    addOns: "None",
    flavorRequests: "No strawberry.",
    specialInstructions:
      "Underground venue — coordinate with event staff. No outside food allowed otherwise.",
    lineItems: [
      { desc: "100 paletas × $5.00", amount: "$500" },
      { desc: "Delivery", amount: "$60" },
    ],
    total: "$360",
    deposit: "$180",
    verified: "$180",
    remaining: "$180",
    payments: [
      {
        method: "Venmo",
        amount: "$180",
        ref: "VM-1018-1041",
        date: "Oct 18, 2026",
        verifiedBy: "Owner",
        note: "",
      },
    ],
    confirmBanner: {
      heading: "BOOKING CONFIRMED — FULL PAYMENT IS NOT REQUIRED",
      body: "Availability approved + verified $180 deposit (50%). The remaining $180 does not block this booking.",
    },
  },
  {
    id: "#1040",
    customer: "Greenway Co.",
    email: "hr@greenwaycorp.com",
    phone: "(713) 555-0140",
    date: "Nov 15, 2026",
    dateIso: "2026-11-15",
    service: "Full Service",
    qty: 110,
    orderStatus: "confirmed",
    orderStatusLabel: "Confirmed",
    paymentStatus: "paid",
    paymentStatusLabel: "Paid in full",
    paymentSub: "$0 remaining",
    calendarSync: "synced",
    calendarSyncLabel: "Synced",
    calendarSyncSub: "Google Calendar",
    createdLabel: "Confirmed booking · Created October 15, 2026",
    location: {
      name: "Greenway Plaza",
      address: "3200 Southwest Fwy",
      city: "Houston, TX 77027",
    },
    arrivalWindow: "12:30 PM",
    flavors: "Mango 50 · Strawberry 30 · Lime 30",
    shapes: "Classic 80 · Mini heart 30",
    addOns: "Custom wrappers · 110 × $0.50",
    flavorRequests: "Festive mix — no restrictions.",
    specialInstructions: "Corporate HR event. Set up in the main atrium.",
    lineItems: [
      { desc: "110 paletas × $5.50", amount: "$605" },
      { desc: "Full Service team", amount: "$200" },
      { desc: "Delivery", amount: "$60" },
      { desc: "Custom wrappers", amount: "$55" },
    ],
    total: "$880",
    deposit: "$440",
    verified: "$880",
    remaining: "$0",
    payments: [
      {
        method: "Venmo",
        amount: "$440",
        ref: "VM-1015-1040",
        date: "Oct 15, 2026",
        verifiedBy: "Owner",
        note: "",
      },
      {
        method: "Venmo",
        amount: "$440",
        ref: "VM-1101-1040",
        date: "Nov 1, 2026",
        verifiedBy: "Owner",
        note: "Final payment received.",
      },
    ],
    confirmBanner: {
      heading: "BOOKING CONFIRMED — PAID IN FULL",
      body: "Availability approved + full payment verified. This booking is fully settled.",
    },
  },
];

/**
 * GET /api/v1/admin/orders
 * Response: { orders: Order[] }
 */
export async function fetchOrders() {
  if (USE_MOCK_API) {
    await mockDelay(300);
    return { orders: MOCK_ORDERS };
  }
  return adminRequest("/admin/orders");
}

/**
 * GET /api/v1/admin/orders/:id
 * Response: { order: Order }
 */
export async function fetchOrder(id) {
  if (USE_MOCK_API) {
    await mockDelay(200);
    const order = MOCK_ORDERS.find((o) => o.id === id);
    if (!order) {
      const e = new Error("Order not found");
      e.status = 404;
      throw e;
    }
    return { order };
  }
  return adminRequest(`/admin/orders/${encodeURIComponent(id)}`);
}

/**
 * POST /api/v1/admin/orders/:id/approve
 * Body: {}
 * Response: { order: Order }
 * Backend should: set order status to availability_approved, return updated order
 */
export async function approveOrder(id) {
  if (USE_MOCK_API) {
    await mockDelay(600);
    const idx = MOCK_ORDERS.findIndex((o) => o.id === id);
    if (idx === -1) throw new Error("Order not found");
    // Approval alone doesn't confirm — both approval + deposit required
    MOCK_ORDERS[idx] = {
      ...MOCK_ORDERS[idx],
      orderStatusLabel: "Availability approved",
    };
    return { order: MOCK_ORDERS[idx] };
  }
  return adminRequest(`/admin/orders/${encodeURIComponent(id)}/approve`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

/**
 * POST /api/v1/admin/orders/:id/payments
 * Body: { method, amount_cents, reference, note }
 * Response: { order: Order }
 * Backend should: record external payment, check if 50% threshold met → confirm booking
 */
export async function recordPayment(
  id,
  { method, amountDollars, reference, note },
) {
  if (USE_MOCK_API) {
    await mockDelay(600);
    const idx = MOCK_ORDERS.findIndex((o) => o.id === id);
    if (idx === -1) throw new Error("Order not found");
    const order = MOCK_ORDERS[idx];
    const payment = {
      method,
      amount: `$${amountDollars}`,
      ref: reference,
      date: new Date().toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
      }),
      verifiedBy: "Owner",
      note: note || "",
    };
    MOCK_ORDERS[idx] = {
      ...order,
      payments: [...order.payments, payment],
      paymentStatus: "partial",
      paymentStatusLabel: "Part paid · recorded",
      paymentSub: "Awaiting backend verification",
    };
    return { order: MOCK_ORDERS[idx] };
  }
  return adminRequest(`/admin/orders/${encodeURIComponent(id)}/payments`, {
    method: "POST",
    body: JSON.stringify({
      method,
      amount_cents: Math.round(parseFloat(amountDollars) * 100),
      reference,
      note,
    }),
  });
}

/**
 * POST /api/v1/admin/orders/:id/cancel
 * Body: { reason }
 * Response: { order: Order }
 */
export async function cancelOrder(id, reason) {
  if (USE_MOCK_API) {
    await mockDelay(600);
    const idx = MOCK_ORDERS.findIndex((o) => o.id === id);
    if (idx === -1) throw new Error("Order not found");
    MOCK_ORDERS[idx] = {
      ...MOCK_ORDERS[idx],
      orderStatus: "cancelled",
      orderStatusLabel: "Cancelled",
    };
    return { order: MOCK_ORDERS[idx] };
  }
  return adminRequest(`/admin/orders/${encodeURIComponent(id)}/cancel`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}

/**
 * POST /api/v1/admin/orders/:id/sync
 * Body: {}
 * Response: { order: Order }
 * Backend should: retry Google Calendar sync for this order
 */
export async function retryCalsync(id) {
  if (USE_MOCK_API) {
    await mockDelay(800);
    const idx = MOCK_ORDERS.findIndex((o) => o.id === id);
    if (idx === -1) throw new Error("Order not found");
    MOCK_ORDERS[idx] = {
      ...MOCK_ORDERS[idx],
      calendarSync: "synced",
      calendarSyncLabel: "Synced",
      calendarSyncSub: "Google Calendar",
    };
    return { order: MOCK_ORDERS[idx] };
  }
  return adminRequest(`/admin/orders/${encodeURIComponent(id)}/sync`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

// ===========================================================================
// Calendar API
// ===========================================================================

/**
 * GET /api/v1/admin/calendar?year=2026&month=11
 * Response: { events: CalendarEvent[], stats: { confirmed, pending, reserved } }
 *
 * CalendarEvent: { orderId, day, customer, time, service, qty, bookingStatus, syncStatus, color }
 * Backend derives events from confirmed + pending orders for the given month.
 */
export async function fetchCalendar(year, month) {
  if (USE_MOCK_API) {
    await mockDelay(300);
    // Derive from orders for the matching year/month
    const events = {};
    MOCK_ORDERS.forEach((o) => {
      const d = new Date(o.dateIso);
      if (d.getFullYear() === year && d.getMonth() + 1 === month) {
        const day = d.getDate();
        events[day] = {
          orderId: o.id,
          customer: o.customer,
          service: o.service,
          qty: o.qty,
          bookingStatus: o.orderStatus,
          syncStatus: o.calendarSync,
          color:
            o.orderStatus === "pending"
              ? "cream"
              : o.calendarSync === "failed"
                ? "yellow"
                : "pink",
        };
      }
    });
    const confirmed = MOCK_ORDERS.filter(
      (o) =>
        o.orderStatus === "confirmed" &&
        new Date(o.dateIso).getMonth() + 1 === month,
    ).length;
    const pending = MOCK_ORDERS.filter(
      (o) =>
        o.orderStatus === "pending" &&
        new Date(o.dateIso).getMonth() + 1 === month,
    ).length;
    const reserved = MOCK_ORDERS.filter(
      (o) =>
        o.orderStatus === "confirmed" &&
        new Date(o.dateIso).getMonth() + 1 === month,
    ).reduce((s, o) => s + o.qty, 0);
    return { events, stats: { confirmed, pending, reserved } };
  }
  return adminRequest(`/admin/calendar?year=${year}&month=${month}`);
}
