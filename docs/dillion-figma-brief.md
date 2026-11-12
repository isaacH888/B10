# Dillion's Figma handoff

Updated November 11, 2026. Keep the existing Popssibilities admin colors,
typography, navigation and rounded card/button style. Dashboard, Orders, Calendar
and Inventory already exist and now use saved data; they do not need replacement
pages. The main gap is bringing the functional booking and account workflows
into that visual system.

## Frames to deliver, in priority order

1. **Booking detail and customer-request intake.** Design a booking page inside
   the existing admin shell, plus the intake drawer or stepper. Show customer
   contact, event location/date/time/timezone, quantity/service, contract link,
   total, deposit due, verified payments and remaining balance. Include pending
   request, awaiting deposit, confirmed, owner review and cancelled variants.
   Intake collects the contract URL and any required end time, with the saved
   request and price visible. Make availability approval and deposit confirmation
   distinct steps. Start from `/admin/automation` and `/admin/bookings/:bookingId`.
2. **Booking action dialogs.** Design approve availability, verify external
   payment, reschedule, cancel, reopen, finalize quantity and Calendar recovery.
   Payment needs an amount in dollars, provider/reference and verification
   evidence; explain that the owner checks the actual provider account. Show
   the current total, verified amount and remaining balance. Scheduling needs
   date/time controls with an explicit timezone. Cancellation must explain the
   recorded refund requirement without implying an automatic provider refund.
   Include validation, pending, success, conflict and fresh-verification states.
3. **Flavor allocation panel.** On confirmed bookings, show each flavor's
   available stock, current allocation and quantity control, plus the booking's
   total and unallocated quantity. Design insufficient-stock and stale-data
   messages and a clear Save action. Cancelling releases allocations. Flavor
   requests are free text, so the owner explicitly chooses catalog items; avoid
   presenting guessed assignments as saved reservations. Stock adjustments and
   consumption remain explicit inventory actions.
4. **Team account and sign-in states, coordinated with Aneena.** Provide owner
   account, team login, invited-user password setup, MFA QR enrollment and code
   entry, invalid/expired access and re-verification frames. Existing auth logic
   works; it needs branded presentation. Show a route back to the originating
   booking after verification, with an explicit action to continue. Coordinate
   that navigation with Isaac; a payment must not automatically submit again.
5. **Shared states and responsive polish.** Provide loading, first-use empty,
   no search results, API failure/retry, permission denied, success and conflict
   components. Polish the working date-range/export controls, Calendar days with
   several events and the selected-event drawer. Include disconnected/pending/
   failed Calendar states, long real IDs/names/addresses and narrow-screen tables.

## Handoff requirements

- Supply Auto Layout frames at **375, 768 and 1440 px**, reusable components and
  variants, and named text/color/spacing styles matching the existing site.
- Prototype request → intake → approve → verify deposit → confirmed booking,
  plus reschedule, cancellation and re-verification paths.
- Label required/optional fields, validation text, disabled/busy behavior,
  drawer/dialog close behavior and the success destination.
- Display normal currency and local date/time inputs. Isaac's integration will
  translate dollars to integer cents and preserve revisions, CSRF, replay keys
  and backend decisions; these implementation details should not appear as form
  instructions to owners.
- Link the final Figma frames and components in the frontend handoff. Aneena can
  build shared account/auth and responsive components while Dillion owns booking
  workflows and action dialogs.

Design completion means a frontend developer can implement these frames against
the existing APIs without inventing missing interactions or payment rules. Live
provider setup and customer order history are separate work.
