import { ApiError, apiRequest } from "../auth/api.js";
import { adaptOrder } from "./orderApi.js";

const pendingWrites = new Map();

async function write(path, method, body) {
  const encoded = JSON.stringify(body);
  const signature = `${method}:${path}:${encoded}`;
  const key = pendingWrites.get(signature) || crypto.randomUUID();
  pendingWrites.set(signature, key);
  const session = await apiRequest("/admin/session");
  try {
    const result = await apiRequest(path, {
      method,
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": session.csrf_token,
        "Idempotency-Key": key,
      },
      body: encoded,
    });
    pendingWrites.delete(signature);
    return result;
  } catch (error) {
    if (error.serverMessage) error.message = error.serverMessage;
    throw error;
  }
}

export const fetchInventory = () => apiRequest("/admin/inventory");
export const createInventoryItem = (data) =>
  write("/admin/inventory", "POST", data);
export const updateInventoryItem = (id, data) =>
  write(`/admin/inventory/${encodeURIComponent(id)}`, "PATCH", data);
export const adjustStock = (id, data) =>
  write(`/admin/inventory/${encodeURIComponent(id)}/adjust`, "POST", data);
export const deleteInventoryItem = (id, version) =>
  write(`/admin/inventory/${encodeURIComponent(id)}`, "DELETE", {
    expected_version: version,
  });
export const fetchBookingAllocations = (id) =>
  apiRequest(`/admin/inventory/bookings/${encodeURIComponent(id)}/allocations`);
export const saveBookingAllocations = (id, data) =>
  write(
    `/admin/inventory/bookings/${encodeURIComponent(id)}/allocations`,
    "POST",
    data,
  );
export async function fetchStockHistory(id, page = 1) {
  const result = await apiRequest(
    `/admin/inventory/${encodeURIComponent(id)}/history?page=${page}`,
  );
  return {
    ...result,
    history: result.history.map((entry) => ({
      ...entry,
      date: new Date(entry.date).toLocaleString(),
    })),
  };
}

const labels = {
  pending: "Pending request",
  awaiting_deposit: "Awaiting deposit",
  confirmed: "Confirmed",
  owner_review: "Owner review",
  fulfilled: "Fulfilled",
  cancelled: "Cancelled",
};
const format = (value, timezone, options) =>
  new Intl.DateTimeFormat("en-US", { timeZone: timezone, ...options }).format(
    new Date(value),
  );
const money = (value, currency) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency }).format(
    value / 100,
  );

export function adaptEvent(event, viewZone = "America/Chicago") {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: viewZone,
    day: "numeric",
  }).formatToParts(new Date(event.start));
  const href = event.order_id
    ? `/admin/orders/${encodeURIComponent(event.order_id)}`
    : `/admin/bookings/${encodeURIComponent(event.booking_id)}`;
  const date = format(event.start, viewZone, {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
  });
  const time = format(event.start, viewZone, {
    hour: "numeric",
    minute: "2-digit",
  });
  const sync =
    {
      synced: "Synced",
      failed: "Sync failed",
      pending: "Pending",
      disconnected: "Disconnected",
      not_linked: "Not linked",
    }[event.calendar_status] || event.calendar_status;
  return {
    ...event,
    day: Number(parts.find((part) => part.type === "day").value),
    orderId: event.order_id || event.reference,
    href,
    date,
    month: format(event.start, viewZone, { month: "short" }).toUpperCase(),
    time,
    service:
      event.service_type === "full_service" ? "Full Service" : "Delivery",
    qty: event.quantity,
    bookingStatus: event.status,
    booking: labels[event.status] || event.status,
    syncStatus: event.calendar_status,
    syncType: event.calendar_status,
    sync,
    color:
      event.status === "confirmed"
        ? event.calendar_status === "failed"
          ? "yellow"
          : "pink"
        : "cream",
    detail: {
      date: `${date} · ${time} (${viewZone})`,
      location: event.venue,
      bookingStatus: labels[event.status] || event.status,
      bookingStatusSub: "Current saved booking state",
      paymentStatus:
        event.paid_cents === 0
          ? "Unpaid"
          : event.remaining_cents === 0
            ? "Paid in full"
            : "Part paid",
      paymentStatusSub: `${money(event.remaining_cents, event.currency)} remaining`,
      syncType: event.calendar_status,
      syncError:
        event.calendar_status === "failed"
          ? {
              title: "Calendar sync needs review",
              body: "Open the saved booking for the recorded error and recovery controls.",
            }
          : null,
      contact: { email: event.email, phone: event.phone },
      orderSummary: `Total ${money(event.total_cents, event.currency)} · Verified ${money(event.paid_cents, event.currency)} · Remaining ${money(event.remaining_cents, event.currency)}`,
    },
  };
}

export async function fetchCalendar(year, month) {
  const [feed, connection] = await Promise.allSettled([
    apiRequest(
      `/admin/calendar?year=${year}&month=${month}&timezone=America%2FChicago`,
    ),
    apiRequest("/admin/automation/google"),
  ]);
  if (feed.status === "rejected") throw feed.reason;
  const events = {};
  for (const raw of feed.value.events) {
    const event = adaptEvent(raw, feed.value.timezone);
    (events[event.day] ||= []).push(event);
  }
  return {
    events,
    stats: feed.value.stats,
    connection:
      connection.status === "fulfilled"
        ? connection.value
        : {
            status: "unavailable",
            setup_message:
              "Google connection status is unavailable. Open the booking workspace to review setup.",
          },
  };
}

export async function fetchDashboard() {
  const data = await apiRequest("/admin/dashboard");
  return {
    ...data,
    upcoming: data.upcoming.map((event) => adaptEvent(event)),
    recent_orders: data.recent_orders.map(adaptOrder),
  };
}

export async function downloadOrders(filters = {}, id = null) {
  const query = new URLSearchParams(
    Object.entries(filters).filter(
      ([, value]) => value !== "" && value !== undefined,
    ),
  );
  const path = id
    ? `/admin/orders/${encodeURIComponent(id)}/export`
    : `/admin/orders/export?${query}`;
  const response = await fetch(`/api/v1${path}`, {
    credentials: "same-origin",
    cache: "no-store",
    headers: { Accept: "text/csv" },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const error = new ApiError(
      response.status,
      body?.error?.code || "request_failed",
    );
    error.message = body?.error?.message || "Export could not be completed.";
    throw error;
  }
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = id ? "order-summary.csv" : "orders.csv";
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
