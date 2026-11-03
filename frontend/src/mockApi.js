// DEV ONLY - synthetic responses for building the catering form without a live backend.
// When Anh's API endpoints are ready, replace the calls in CateringModal.jsx:
//   import { mockGetQuote, mockSubmitOrder } from "./mockApi.js";
// with:
//   import { apiRequest } from "./auth/api.js";
// and call apiRequest("/quotes", { method: "POST", ... }) directly.

// Simulates network latency so loading states are visible during development.
function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// Returns a priced quote - the happy path.
// Use this to test the price summary and Place Order button.
export async function mockGetQuote(_requestBody) {
  await delay(800);
  return {
    id: "quote_example_001",
    status: "priced",
    expires_at: new Date(Date.now() + 15 * 60 * 1000).toISOString(),
    pricing: {
      currency: "USD",
      line_items: [
        {
          code: "synthetic_fixture",
          description: "Synthetic total only - not a client rate or pricing tier.",
          amount_cents: 20000,
        },
      ],
      total_cents: 20000,
      deposit_due_cents: 10000,
    },
    pricing_revision: "synthetic_fixture_v1",
    unresolved_decisions: [],
    next_action: null,
  };
}

// Returns a requires_review quote - pricing is pending manual review.
// Swap this in place of mockGetQuote to test the review UI state.
export async function mockGetQuoteRequiresReview(_requestBody) {
  await delay(800);
  return {
    id: "quote_example_002",
    status: "requires_review",
    expires_at: new Date(Date.now() + 15 * 60 * 1000).toISOString(),
    pricing: null,
    pricing_revision: null,
    unresolved_decisions: ["D01", "D04", "D06", "D07"],
    next_action: null,
  };
}

// Returns an outside-radius quote - delivery not available, inquiry required.
// Swap this in place of mockGetQuote to test the inquiry UI state.
export async function mockGetQuoteOutsideRadius(_requestBody) {
  await delay(800);
  return {
    id: "quote_example_003",
    status: "requires_review",
    expires_at: new Date(Date.now() + 15 * 60 * 1000).toISOString(),
    pricing: null,
    pricing_revision: null,
    unresolved_decisions: ["D04"],
    next_action: {
      type: "contact_inquiry",
      reason_code: "outside_delivery_radius",
      message: "Delivery beyond 30 miles requires a custom event inquiry.",
      inquiry_url: "https://example.invalid/contact",
    },
  };
}

// Returns a successful order submission.
export async function mockSubmitOrder(_requestBody) {
  await delay(1000);
  return {
    id: "order_example_001",
    version: 1,
    status: "pending_review",
    customer: _requestBody.customer,
    catering_request: _requestBody.catering_request,
    event: _requestBody.event,
    quote_id: _requestBody.quote_id,
    pricing_revision: "synthetic_fixture_v1",
    pricing: {
      currency: "USD",
      line_items: [
        {
          code: "synthetic_fixture",
          description: "Synthetic total only - not a client rate or pricing tier.",
          amount_cents: 20000,
        },
      ],
      total_cents: 20000,
      deposit_due_cents: 10000,
    },
    deposit: {
      status: "pending",
      amount_due_cents: 10000,
      amount_confirmed_cents: 0,
    },
    payment_links: [],
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
}
