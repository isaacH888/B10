import { Link, useParams } from "react-router-dom";
import { useAuth } from "../auth/AuthContext.jsx";
import { AutomationDashboard } from "../automation/AutomationDashboard.jsx";
import { AdminShell } from "./AdminShell.jsx";

export function BookingWorkspacePage() {
  const { bookingId } = useParams();
  const { sessions } = useAuth();
  const session = sessions.admin.data;
  const identity = session.administrator;
  const owner =
    identity.role === "owner" && identity.permissions.includes("bookings:read");

  return (
    <AdminShell
      activeRoute="/admin/automation"
      title={bookingId ? "Bookings / Booking details" : "Bookings"}
    >
      <div className="adm-booking-workspace">
        {bookingId && (
          <Link
            to="/admin/automation"
            className="adm-card__link adm-back-link adm-workspace-back-link"
          >
            ← Back to all bookings
          </Link>
        )}
        <h1 className="adm-hero-row__heading">
          {bookingId ? "BOOKING DETAILS" : "MANAGE CATERING BOOKINGS."}
        </h1>
        {owner ? (
          <AutomationDashboard
            identity={identity}
            csrfToken={session.csrf_token}
          />
        ) : (
          <section className="adm-card">
            <h2>Owner access required</h2>
            <p>Only the owner can operate booking automation.</p>
          </section>
        )}
      </div>
    </AdminShell>
  );
}
