import { apiRequest } from "../auth/api.js";

const STATUS_LABELS = {
  pending: "Pending request",
  awaiting_deposit: "Awaiting deposit",
  confirmed: "Confirmed",
  owner_review: "Owner review required",
  fulfilled: "Fulfilled",
  cancelled: "Cancelled",
};

function date(value, timezone, options) {
  if (!value) return "Not supplied";
  try {
    return new Intl.DateTimeFormat("en-US", {
      timeZone: timezone,
      ...options,
    }).format(new Date(value));
  } catch {
    return value;
  }
}

export function adaptOrder({ order, booking }) {
  const event = order.event;
  const catering = order.catering_request;
  const pricing = order.pricing;
  const currency = booking?.currency || pricing.currency;
  const money = (cents) =>
    new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
    }).format(cents / 100);
  const total = booking?.total_minor ?? pricing.total_cents;
  const paid = booking?.paid_minor ?? 0;
  const remaining = booking?.remaining_minor ?? total;
  const deposit = booking?.deposit_minor ?? pricing.deposit_due_cents;
  const rawStatus = booking?.status || order.status;
  const status = ["requested", "pending_review"].includes(rawStatus)
    ? "pending"
    : rawStatus;
  const start = booking?.start || event.starts_at;
  const end = booking?.end || event.ends_at;
  const zone = booking?.timezone || event.timezone;
  const paymentStatus =
    paid === 0 ? "unpaid" : paid >= total ? "paid" : "partial";
  const timeOptions = { hour: "numeric", minute: "2-digit" };
  const calendarStatus = booking?.calendar_status || "not_linked";
  const calendarLabels = {
    pending: "Pending",
    synced: "Synced",
    failed: "Failed",
    disconnected: "Disconnected",
    not_linked: "Not linked to a booking",
  };
  return {
    live: true,
    id: order.id,
    bookingId: booking?.id || null,
    managementHref: booking
      ? `/admin/bookings/${encodeURIComponent(booking.id)}`
      : "/admin/automation",
    customer: order.customer.name,
    email: order.customer.email,
    phone: order.customer.phone,
    date: date(start, zone, { dateStyle: "medium" }),
    service:
      (booking?.service_type || catering.service_type) === "full_service"
        ? "Full Service"
        : "Delivery",
    qty: booking?.quantity ?? catering.quantity,
    orderStatus: status,
    orderStatusLabel: STATUS_LABELS[status] || status,
    availabilityLabel: ["awaiting_deposit", "confirmed"].includes(status)
      ? "Availability approved"
      : "Review availability in the booking workspace",
    paymentStatus,
    paymentStatusLabel: {
      unpaid: "Unpaid",
      partial: "Part paid",
      paid: "Paid in full",
    }[paymentStatus],
    paymentSub: `${money(paid)} verified · ${money(remaining)} remaining`,
    calendarSync: calendarStatus,
    calendarSyncLabel: calendarLabels[calendarStatus] || calendarStatus,
    calendarSyncSub: booking
      ? "Open the booking workspace for sync details and recovery."
      : "Review and link this order before Calendar sync.",
    createdLabel: `Received ${date(order.created_at, zone, { dateStyle: "long" })}`,
    location: {
      name: event.type,
      address:
        booking?.venue ||
        [event.location.line1, event.location.line2].filter(Boolean).join(", "),
      city: booking
        ? ""
        : `${event.location.city}, ${event.location.region} ${event.location.postal_code}`,
    },
    arrivalWindow: `${date(start, zone, timeOptions)}${end ? ` – ${date(end, zone, timeOptions)}` : ""} (${zone})`,
    flavors: catering.flavor_requests || "No specific flavors requested",
    shapes: catering.popsicle_shape === "heart" ? "Heart" : "Standard",
    addOns: catering.add_ons.length ? catering.add_ons.join(", ") : "None",
    flavorRequests: catering.flavor_requests || "None",
    specialInstructions: event.notes || "None",
    lineItems: pricing.line_items.map((item) => ({
      desc: item.description,
      amount: money(item.amount_cents),
    })),
    total: money(total),
    deposit: money(deposit),
    verified: money(paid),
    remaining: money(remaining),
    payments: [],
    confirmBanner: {
      heading: STATUS_LABELS[status] || status,
      body: booking
        ? "This page shows the saved order and current booking status. Manage availability, payment verification and Calendar in the booking workspace."
        : "Review this customer request and supply its contract link and event end time in the booking workspace. No payment or availability is approved by viewing this page.",
    },
  };
}

export async function fetchOrders(filters = {}) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== "" && value !== undefined) query.set(key, String(value));
  }
  const data = await apiRequest(`/admin/orders?${query}`);
  return { ...data, orders: data.items.map(adaptOrder) };
}

export async function fetchOrder(id) {
  const record = await apiRequest(`/admin/orders/${encodeURIComponent(id)}`);
  return { order: adaptOrder(record) };
}
