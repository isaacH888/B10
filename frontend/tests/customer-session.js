export const customerCsrf = "synthetic-customer-csrf";

export function customerSession(now = Date.now()) {
  return {
    customer: {
      id: "customer-test",
      email: "reviewer@example.invalid",
      name: "Synthetic Reviewer",
    },
    csrf_token: customerCsrf,
    expires_at: new Date(now + 3600000).toISOString(),
    idle_expires_at: new Date(now + 900000).toISOString(),
  };
}
