import { useId, useRef } from "react";
import { formatEventTime } from "../eventTime.js";
import { useDialogAccessibility } from "./useDialogAccessibility.js";

const decisions = {
  confirm: {
    title: "Confirm availability?",
    description:
      "Are you sure you want to accept this request? This reserves availability and queues a deposit request. The booking is confirmed after a verified deposit.",
    button: "Yes, confirm availability",
  },
  conditionally_confirm: {
    title: "Conditionally confirm this request?",
    description:
      "Are you sure you want to send these conditions? This queues your message to the customer. Availability is not reserved and no deposit is requested.",
    button: "Yes, send conditions",
  },
  deny: {
    title: "Deny this request?",
    description:
      "Are you sure you want to deny this request? This cancels the request and queues a customer email. Any payment history is retained.",
    button: "Yes, deny request",
  },
};

export function DecisionConfirmation({ pending, onCancel, onConfirm }) {
  const id = useId();
  const dialogRef = useRef(null);
  useDialogAccessibility(dialogRef, onCancel);
  const copy = decisions[pending.body.decision];

  return (
    <div className="od-decision-overlay">
      <div
        className="od-decision-backdrop"
        data-dialog-backdrop
        aria-hidden="true"
        onClick={onCancel}
      />
      <div
        className="od-decision-dialog"
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${id}-title`}
        aria-describedby={`${id}-description`}
      >
        <p className="od-decision-dialog__eyebrow">REVIEW YOUR DECISION</p>
        <h2 id={`${id}-title`}>{copy.title}</h2>
        <p id={`${id}-description`}>{copy.description}</p>
        <div className="od-decision-dialog__summary">
          <strong>{pending.customer}</strong>
          <p>Starts {formatEventTime(pending.start)}</p>
          {pending.body.decision === "confirm" && (
            <p>Ends {formatEventTime(pending.body.end)}</p>
          )}
          {pending.body.message && <p>{pending.body.message}</p>}
        </div>
        <div className="od-decision-dialog__actions">
          <button
            type="button"
            className="adm-btn adm-btn--outline"
            onClick={onCancel}
          >
            Go back
          </button>
          <button
            type="button"
            className="adm-btn adm-btn--primary"
            onClick={onConfirm}
          >
            {copy.button}
          </button>
        </div>
      </div>
    </div>
  );
}
