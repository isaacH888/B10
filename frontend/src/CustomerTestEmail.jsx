import { useRef, useState } from "react";
import { useAuth } from "./auth/AuthContext.jsx";
import { apiRequest } from "./auth/api.js";

function failureMessage(error) {
  if (error?.code === "email_delivery_uncertain") {
    return "The email may already have been sent. Check your inbox and spam folder before trying again later.";
  }
  if (error?.code === "email_rate_limited" || error?.status === 429) {
    return "Please wait before sending another test email.";
  }
  if (error?.code === "email_unavailable") {
    return "Test email is unavailable. The email service needs to be configured.";
  }
  if (error?.code === "email_rejected") {
    return "The email service did not accept this test email. Please try again after the service configuration is checked.";
  }
  if ([401, 403].includes(error?.status)) {
    return "Your session could not be verified. Sign in again before sending a test email.";
  }
  return "We could not confirm the send. You can retry safely using the same email request.";
}

export function CustomerTestEmail({ csrfToken, email }) {
  const { refresh } = useAuth();
  const [phase, setPhase] = useState("ready");
  const [message, setMessage] = useState("");
  const actionKey = useRef(null);
  const inFlight = useRef(false);
  const disabled = ["sending", "accepted", "uncertain", "session"].includes(phase);

  async function sendTestEmail() {
    if (inFlight.current || disabled) return;
    inFlight.current = true;
    setPhase("sending");
    setMessage("");
    try {
      // Keep the same key after network failures so a retry cannot send twice.
      actionKey.current ||= crypto.randomUUID();
      const result = await apiRequest("/customer/test-email", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken,
          "Idempotency-Key": actionKey.current,
        },
        body: JSON.stringify({}),
      });
      if (result?.status !== "accepted" || typeof result.reference !== "string" || !result.reference.startsWith("TEST-")) {
        throw new Error("Invalid email response");
      }
      setPhase("accepted");
      setMessage("Test order confirmation accepted for sending. Check your inbox and spam folder.");
    } catch (error) {
      const sessionError = [401, 403].includes(error?.status);
      // These explicit failures confirm no send; an intentional retry may start
      // a new request after configuration is repaired. Unknown failures retain the key.
      if (error?.status === 503 && ["email_rejected", "email_unavailable"].includes(error.code)) {
        actionKey.current = null;
      }
      setPhase(error?.code === "email_delivery_uncertain" ? "uncertain" : sessionError ? "session" : "ready");
      setMessage(failureMessage(error));
      if (sessionError) await refresh("customer", { force: true });
    } finally {
      inFlight.current = false;
    }
  }

  return <section aria-labelledby="test-email-heading">
    <h2 id="test-email-heading">Test order confirmation</h2>
    <p>Send a sample order confirmation to {email}. This is a test email; it does not place an order or charge you.</p>
    <button type="button" onClick={sendTestEmail} disabled={disabled}>
      {phase === "sending" ? "Sending test email…" : "Send test order confirmation"}
    </button>
    {message && <p role={phase === "accepted" ? "status" : "alert"}>{message}</p>}
  </section>;
}
