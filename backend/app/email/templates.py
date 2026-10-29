"""A fixed sample order; callers cannot supply recipients, subjects, or HTML content."""

import re
from html import escape

REFERENCE = re.compile(r"[A-Za-z0-9-]{1,80}\Z")


def render_confirmation(name, reference):
    if not isinstance(reference, str) or not REFERENCE.fullmatch(reference):
        raise ValueError("Invalid test email reference")
    # Profile names are display text, never email headers or HTML markup.
    name = " ".join(str(name or "there").split())[:120] or "there"
    subject = f"[TEST] Popssibilities order confirmation - {reference}"
    text = (
        f"Hi {name},\n\n"
        "Thank you for trying Popssibilities. Here is your sample order confirmation.\n\n"
        f"Sample order reference: {reference}\n"
        "Order: Sample catering package\n"
        "Guests: 50 (sample)\n"
        "Status: Demonstration only\n\n"
        "This is a test email you requested from your customer account. "
        "No real order has been placed, no booking has been confirmed, and no payment has been processed.\n\n"
        "Popssibilities\n"
    )
    html = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        "<title>Sample order confirmation</title></head><body>"
        f"<p>Hi {escape(name)},</p>"
        "<h1>Sample order confirmation</h1>"
        "<p>Thank you for trying Popssibilities.</p>"
        f"<p><strong>Sample order reference:</strong> {escape(reference)}</p>"
        "<ul><li>Order: Sample catering package</li><li>Guests: 50 (sample)</li>"
        "<li>Status: Demonstration only</li></ul>"
        "<p>This is a test email you requested from your customer account. "
        "No real order has been placed, no booking has been confirmed, and no payment has been processed.</p>"
        "<p>Popssibilities</p></body></html>"
    )
    return {"subject": subject, "text": text, "html": html}
