const sampleBookings = [
  { id: "SAMPLE-001", event: "Demo office lunch", guests: 30, status: "Pending" },
  { id: "SAMPLE-002", event: "Demo birthday party", guests: 18, status: "Confirmed" },
  { id: "SAMPLE-003", event: "Demo community event", guests: 45, status: "Fulfilled" },
];

export function AdminDashboard({ identity }) {
  const permissions = new Set(identity.permissions);
  const canReadBookings = permissions.has("bookings:read");
  const canManageBookings = permissions.has("bookings:confirm") || permissions.has("bookings:cancel") || permissions.has("bookings:price");
  const canManagePayments = permissions.has("payments:manage");
  const canExportCustomers = permissions.has("customers:export");

  return <section aria-labelledby="sample-dashboard-heading" className="sample-dashboard">
    <h2 id="sample-dashboard-heading">Sample data</h2>
    <p>These fictional bookings demonstrate the dashboard layout. They are not live orders, and no booking or payment changes can be made here.</p>
    {canReadBookings ? <>
      <div className="summary-cards" aria-label="Sample booking overview">
        <section><h3>Total bookings</h3><p>{sampleBookings.length}</p></section>
        {["Pending", "Confirmed", "Fulfilled"].map((status) => <section key={status}>
          <h3>{status}</h3><p>{sampleBookings.filter((booking) => booking.status === status).length}</p>
        </section>)}
      </div>
      <div className="table-scroll" role="region" aria-label="Sample bookings" tabIndex={0}>
        <table>
          <caption>Sample bookings</caption>
          <thead><tr><th scope="col">Booking</th><th scope="col">Event</th><th scope="col">Guests</th><th scope="col">Status</th></tr></thead>
          <tbody>{sampleBookings.map((booking) => <tr key={booking.id}>
            <th scope="row">{booking.id}</th><td>{booking.event}</td><td>{booking.guests}</td><td>{booking.status}</td>
          </tr>)}</tbody>
        </table>
      </div>
    </> : <p>Booking access is not assigned to this account.</p>}
    {(permissions.has("bookings:notes") || permissions.has("bookings:fulfill")) && <section>
      <h3>Booking workspace</h3>
      <p>Your permissions include {[
        permissions.has("bookings:notes") && "booking notes",
        permissions.has("bookings:fulfill") && "fulfillment updates",
      ].filter(Boolean).join(" and ")}. This sample workspace is read-only.</p>
    </section>}
    {(canManageBookings || canManagePayments || canExportCustomers) && <section>
      <h3>Management workspace</h3>
      <ul>
        {canManageBookings && <li>Booking management preview</li>}
        {canManagePayments && <li>Payment management preview</li>}
        {canExportCustomers && <li>Customer export preview</li>}
      </ul>
      <p>Management tools will be connected when the business features are implemented. Sensitive actions will require fresh authentication.</p>
    </section>}
  </section>;
}
