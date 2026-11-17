import { createSampleData } from "./sampleData.js";

const previewMessage = "This preview uses sample data. Changes are disabled.";

function filterOrders(records, params) {
  return records.filter(({ order, booking }) => {
    const status =
      booking?.status ||
      (order.status === "pending_review" ? "pending" : order.status);
    const total = booking?.total_minor ?? order.pricing.total_cents;
    const paid = booking?.paid_minor || 0;
    const payment = !paid ? "unpaid" : paid >= total ? "paid" : "partial";
    const q = (params.get("q") || "").toLowerCase();
    return (
      (!q ||
        `${order.id} ${order.customer.name} ${order.customer.email}`
          .toLowerCase()
          .includes(q)) &&
      (!params.get("status") || status === params.get("status")) &&
      (!params.get("payment_status") ||
        payment === params.get("payment_status")) &&
      (!params.get("service_type") ||
        order.catering_request.service_type === params.get("service_type")) &&
      (!params.get("event_from") ||
        Date.parse(booking?.start || order.event.starts_at) >=
          Date.parse(params.get("event_from"))) &&
      (!params.get("event_to") ||
        Date.parse(booking?.start || order.event.starts_at) <
          Date.parse(params.get("event_to")))
    );
  });
}

export function adminPreviewPlugin() {
  const sample = createSampleData();
  return {
    name: "local-admin-sample-preview",
    apply: "serve",
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const url = new URL(request.url, "http://127.0.0.1");
        if (!url.pathname.startsWith("/api/v1/")) return next();
        response.setHeader("Cache-Control", "no-store");
        response.setHeader("X-Admin-Preview", "sample-data");
        const send = (data, status = 200) => {
          response.statusCode = status;
          response.setHeader("Content-Type", "application/json");
          response.end(JSON.stringify({ data }));
        };
        const fail = (code, message, status) => {
          response.statusCode = status;
          response.setHeader("Content-Type", "application/json");
          response.end(JSON.stringify({ error: { code, message } }));
        };
        // This server never proxies API requests, accepts credentials, sets an
        // auth cookie, or writes to the real application's database/providers.
        if (request.method !== "GET") {
          return fail("preview_read_only", previewMessage, 403);
        }
        const path = url.pathname.slice("/api/v1".length);
        if (path === "/admin/session") {
          const expires = new Date(Date.now() + 3600000).toISOString();
          return send({
            administrator: {
              id: "sample-preview-owner",
              name: "Sample Owner",
              email: "preview@example.invalid",
              role: "owner",
              permissions: [
                "bookings:read",
                "bookings:contacts",
                "bookings:notes",
                "bookings:fulfill",
                "bookings:confirm",
                "bookings:cancel",
                "bookings:price",
                "payments:manage",
                "customers:export",
              ],
            },
            csrf_token: "sample-preview-not-a-real-credential",
            expires_at: expires,
            idle_expires_at: expires,
          });
        }
        if (path === "/customer/session")
          return fail("unauthenticated", "No sample customer session.", 401);
        if (path === "/live") return send({ status: "ok" });
        if (path === "/health")
          return send(
            {
              status: "degraded",
              database: "unavailable",
              authentication: "disabled",
            },
            503,
          );
        if (path === "/admin/dashboard") return send(sample.dashboard);
        if (path === "/admin/dashboard/export") {
          const cell = (value) =>
            `"${String(value ?? "").replaceAll('"', '""')}"`;
          const csv = [
            ["ADMIN DASHBOARD - GENERAL INFORMATION REPORT (SAMPLE PREVIEW)"],
            ["Generated At (UTC)", new Date().toISOString()],
            ["Storage Mode", "preview-sample-data"],
            [],
            ["--- KEY OPERATIONAL METRICS ---"],
            ["Metric", "Value", "Notes"],
            [
              "New Catering Requests",
              sample.dashboard.requests,
              "Awaiting availability review",
            ],
            [
              "Upcoming Confirmed Events",
              sample.dashboard.upcoming_count,
              "Scheduled in next 30 days",
            ],
            [
              "Upcoming Paletas Required",
              sample.dashboard.upcoming_quantity,
              "Total units for next 30 days",
            ],
            [
              "Outstanding Balances",
              sample.dashboard.balances
                ?.map(
                  (b) =>
                    `${b.currency} ${(b.remaining_cents / 100).toFixed(2)}`,
                )
                .join(" / ") || "None",
              "Remaining on confirmed bookings",
            ],
            [
              "Awaiting Deposits",
              sample.dashboard.awaiting_deposit,
              "Requests approved, deposit pending",
            ],
            [
              "Bookings Needing Review",
              sample.dashboard.owner_review,
              "Special attention required",
            ],
            [
              "Low-Stock Flavor Items",
              sample.dashboard.low_stock ?? "N/A",
              "Available below minimum threshold",
            ],
            [],
            ["--- UPCOMING CONFIRMED EVENTS (NEXT 30 DAYS) ---"],
            [
              "Event / Ref ID",
              "Customer",
              "Start Time",
              "Service Type",
              "Quantity",
              "Venue",
              "Status",
            ],
            ...(sample.dashboard.upcoming || []).map((ev) => [
              ev.id,
              ev.customer,
              ev.start,
              ev.service_type,
              ev.quantity,
              ev.venue,
              ev.status,
            ]),
            [],
            ["--- RECENT ORDERS & CATERING REQUESTS ---"],
            [
              "Order ID",
              "Customer Name",
              "Event Date / Start",
              "Service Type",
              "Quantity",
              "Status",
            ],
            ...(sample.dashboard.recent_orders || []).map((rec) => {
              const order = rec.order || rec;
              return [
                order.id,
                order.customer?.name,
                order.event?.starts_at || "",
                order.catering_request?.service_type || "",
                order.catering_request?.quantity || "",
                order.status,
              ];
            }),
          ]
            .map((row) => row.map(cell).join(","))
            .join("\r\n");
          response.setHeader("Content-Type", "text/csv; charset=utf-8");
          response.setHeader(
            "Content-Disposition",
            'attachment; filename="admin_dashboard_report_preview.csv"',
          );
          return response.end(csv);
        }
        if (path === "/admin/inventory")
          return send({ items: sample.inventory });
        const historyMatch = /^\/admin\/inventory\/([^/]+)\/history$/.exec(
          path,
        );
        if (historyMatch) {
          const history = sample.history[historyMatch[1]];
          if (!history)
            return fail("not_found", "Sample inventory item not found.", 404);
          const page = Math.max(1, Number(url.searchParams.get("page")) || 1);
          return send({
            history: history.slice((page - 1) * 25, page * 25),
            page,
            page_size: 25,
            total: history.length,
          });
        }
        const allocationsMatch =
          /^\/admin\/inventory\/bookings\/([^/]+)\/allocations$/.exec(path);
        if (allocationsMatch) {
          if (!sample.bookingDetails[allocationsMatch[1]])
            return fail("not_found", "Sample booking not found.", 404);
          return send({ items: sample.allocations[allocationsMatch[1]] || [] });
        }
        if (path === "/admin/calendar") {
          const year = Number(url.searchParams.get("year"));
          const month = Number(url.searchParams.get("month"));
          const events = sample.events.filter((event) => {
            return (
              event.status !== "cancelled" &&
              event.start.slice(0, 7) ===
                `${year}-${String(month).padStart(2, "0")}`
            );
          });
          return send({
            events,
            timezone: "America/Chicago",
            stats: {
              confirmed: events.filter((event) => event.status === "confirmed")
                .length,
              pending: events.filter((event) =>
                ["pending", "awaiting_deposit"].includes(event.status),
              ).length,
              confirmed_quantity: events
                .filter((event) => event.status === "confirmed")
                .reduce((sum, event) => sum + event.quantity, 0),
            },
          });
        }
        if (path === "/admin/automation/google")
          return send({
            status: "disconnected",
            configured: false,
            setup_message: "Sample preview. Google Calendar is not connected.",
          });
        if (path === "/admin/automation/requests")
          return send(sample.notifications);
        if (path === "/admin/automation/orders")
          return send(
            sample.records
              .filter(({ booking }) => !booking)
              .map(({ order }) => order),
          );
        if (path === "/admin/automation/bookings")
          return send(
            sample.records.flatMap(({ booking }) => (booking ? [booking] : [])),
          );
        const bookingMatch = /^\/admin\/automation\/bookings\/([^/]+)$/.exec(
          path,
        );
        if (bookingMatch) {
          const detail = sample.bookingDetails[bookingMatch[1]];
          return detail
            ? send(detail)
            : fail("not_found", "Sample booking not found.", 404);
        }
        const orderMatch = /^\/admin\/orders\/([^/]+?)(\/export)?$/.exec(path);
        const exporting =
          path === "/admin/orders/export" || Boolean(orderMatch?.[2]);
        if (exporting) {
          const rows = orderMatch?.[2]
            ? sample.records.filter(({ order }) => order.id === orderMatch[1])
            : filterOrders(sample.records, url.searchParams);
          const cell = (value) => `"${String(value).replaceAll('"', '""')}"`;
          const csv = [
            ["Sample data", "Order", "Customer", "Quantity", "Total cents"],
            ...rows.map(({ order }) => [
              "PREVIEW",
              order.id,
              order.customer.name,
              order.catering_request.quantity,
              order.pricing.total_cents,
            ]),
          ]
            .map((row) => row.map(cell).join(","))
            .join("\r\n");
          response.setHeader("Content-Type", "text/csv");
          response.setHeader(
            "Content-Disposition",
            'attachment; filename="sample-orders.csv"',
          );
          return response.end(csv);
        }
        if (path === "/admin/orders") {
          const rows = filterOrders(sample.records, url.searchParams);
          const page = Math.max(1, Number(url.searchParams.get("page")) || 1);
          const size = Math.min(
            100,
            Math.max(1, Number(url.searchParams.get("page_size")) || 25),
          );
          return send({
            items: rows.slice((page - 1) * size, page * size),
            total: rows.length,
            page,
            page_size: size,
            storage: "preview",
          });
        }
        if (orderMatch) {
          const record = sample.records.find(
            ({ order }) => order.id === orderMatch[1],
          );
          return record
            ? send(record)
            : fail("not_found", "Sample order not found.", 404);
        }
        return fail(
          "preview_unavailable",
          "This screen is not included in the sample preview.",
          404,
        );
      });
    },
  };
}
