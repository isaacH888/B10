import { useLayoutEffect, useRef } from "react";

const dialogs = [];
const isolatedElements = new Map();
let previousOverflow;

const focusableSelector =
  'a[href], button, input, select, textarea, [tabindex], [contenteditable="true"]';

function focusableElements(dialog) {
  return [...dialog.querySelectorAll(focusableSelector)].filter(
    (element) =>
      element.tabIndex >= 0 &&
      !element.matches(":disabled") &&
      !element.closest("[inert], [hidden], [aria-hidden='true']") &&
      element.getClientRects().length > 0 &&
      getComputedStyle(element).visibility !== "hidden",
  );
}

function focusFirst(dialog) {
  (focusableElements(dialog)[0] || dialog).focus({ preventScroll: true });
}

function isolateBackground() {
  for (const [element, wasInert] of isolatedElements) {
    element.inert = wasInert;
  }
  isolatedElements.clear();
  const top = dialogs.at(-1);
  if (!top) return;

  // Walk outwards so this also works for dialogs nested inside page layouts.
  // A marked backdrop stays clickable; it is already hidden from assistive tech.
  let current = top.dialog;
  while (current.parentElement) {
    for (const sibling of current.parentElement.children) {
      if (
        sibling === current ||
        sibling.hasAttribute("data-dialog-backdrop") ||
        ["SCRIPT", "STYLE", "LINK"].includes(sibling.tagName)
      ) {
        continue;
      }
      isolatedElements.set(sibling, sibling.inert);
      sibling.inert = true;
    }
    if (current.parentElement === document.body) break;
    current = current.parentElement;
  }
}

/** Manage focus and background isolation for a mounted modal dialog. */
export function useDialogAccessibility(dialogRef, onClose) {
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useLayoutEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const trigger = document.activeElement;
    const entry = { dialog };
    if (dialogs.length === 0) {
      previousOverflow = document.body.style.overflow;
      document.body.style.overflow = "hidden";
    }
    dialogs.push(entry);
    const hadTabIndex = dialog.hasAttribute("tabindex");
    if (!hadTabIndex) dialog.tabIndex = -1;
    // A new nested dialog may currently inherit its parent's isolation.
    isolateBackground();
    focusFirst(dialog);

    function onKeyDown(event) {
      if (dialogs.at(-1) !== entry) return;
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const elements = focusableElements(dialog);
      const first = elements[0];
      const last = elements.at(-1);
      const active = document.activeElement;
      if (!first) {
        event.preventDefault();
        dialog.focus();
      } else if (
        event.shiftKey &&
        (active === first || !elements.includes(active))
      ) {
        event.preventDefault();
        last.focus();
      } else if (
        !event.shiftKey &&
        (active === last || !elements.includes(active))
      ) {
        event.preventDefault();
        first.focus();
      }
    }

    function onFocusIn(event) {
      if (dialogs.at(-1) === entry && !dialog.contains(event.target)) {
        focusFirst(dialog);
      }
    }

    document.addEventListener("keydown", onKeyDown, true);
    document.addEventListener("focusin", onFocusIn, true);
    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      document.removeEventListener("focusin", onFocusIn, true);
      const wasTop = dialogs.at(-1) === entry;
      const index = dialogs.indexOf(entry);
      if (index !== -1) dialogs.splice(index, 1);
      isolateBackground();
      if (dialogs.length === 0) document.body.style.overflow = previousOverflow;
      if (wasTop) {
        if (trigger?.isConnected && !trigger.closest("[inert]")) {
          trigger.focus({ preventScroll: true });
        } else if (dialogs.at(-1)) {
          focusFirst(dialogs.at(-1).dialog);
        }
      }
      if (!hadTabIndex) dialog.removeAttribute("tabindex");
    };
  }, [dialogRef]);
}
