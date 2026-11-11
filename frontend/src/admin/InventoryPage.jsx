import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import "./admin-dashboard.css";
import "./inventory.css";
import logoSrc from "../assets/logo.png";
import iconDashboard from "../assets/admin/icon-dashboard.svg";
import iconOrders from "../assets/admin/icon-orders.svg";
import iconCalendar from "../assets/admin/icon-calendar.svg";
import iconInventory from "../assets/admin/icon-inventory.svg";
import {
  adjustStock,
  createInventoryItem,
  deleteInventoryItem,
  fetchInventory,
  fetchStockHistory,
  updateInventoryItem,
} from "./adminApi.js";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function statusOf(item) {
  if (item.available <= 0) return "out";
  if (item.available < item.minimum) return "low";
  return "ok";
}

const STATUS_LABEL = { ok: "In Stock", low: "Low Stock", out: "Out of Stock" };
const STATUS_CLASS = {
  ok: "inv-badge--ok",
  low: "inv-badge--low",
  out: "inv-badge--out",
};

const REASON_OPTIONS = [
  "Production batch",
  "Restock / purchase",
  "Waste / damage",
  "Correction / count",
  "Event fulfillment",
  "Other",
];

const NAV_ITEMS = [
  { label: "Dashboard", icon: iconDashboard, href: "/admin/dashboard" },
  { label: "Orders", icon: iconOrders, href: "/admin/orders" },
  { label: "Calendar", icon: iconCalendar, href: "/admin/calendar" },
  { label: "Inventory", icon: iconInventory, href: "/admin/inventory" },
];

// ---------------------------------------------------------------------------
// AdminNav (shared pattern)
// ---------------------------------------------------------------------------
function AdminNav({ activeRoute }) {
  return (
    <aside className="adm-nav" aria-label="Admin navigation">
      <div className="adm-nav__brand">
        <img
          src={logoSrc}
          alt="Popssibilities logo"
          className="adm-nav__logo"
          width={64}
          height={58}
        />
        <p className="adm-nav__site-name">POPSSIBILITIES</p>
        <p className="adm-nav__area">BUSINESS ADMIN</p>
      </div>
      <nav aria-label="Admin pages">
        <ul className="adm-nav__list" role="list">
          {NAV_ITEMS.map((item) => {
            const isActive = item.href === activeRoute;
            return (
              <li key={item.label}>
                <Link
                  to={item.href}
                  className={
                    isActive
                      ? "adm-nav__link adm-nav__link--active"
                      : "adm-nav__link"
                  }
                  aria-current={isActive ? "page" : undefined}
                >
                  <img
                    src={item.icon}
                    alt=""
                    aria-hidden="true"
                    className="adm-nav__icon"
                    width={24}
                    height={24}
                  />
                  {item.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
      <div className="adm-nav__note" aria-label="Workspace info">
        <p className="adm-nav__note-heading">
          A LITTLE ORDER.
          <br />A LOT OF JOY.
        </p>
        <p className="adm-nav__note-sub">
          Houston, TX
          <br />
          Owner workspace
        </p>
      </div>
    </aside>
  );
}

// ---------------------------------------------------------------------------
// Stock Adjustment Drawer (Figma: "Update stock panel")
// ---------------------------------------------------------------------------
function AdjustDrawer({ item, onClose, onSaved }) {
  const [adjType, setAdjType] = useState("add");
  const [qty, setQty] = useState("");
  const [reason, setReason] = useState("Production batch");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const firstFocusRef = useRef(null);

  // Trap focus inside drawer and restore on close
  useEffect(() => {
    firstFocusRef.current?.focus();
    const prev = document.activeElement;
    return () => prev?.focus();
  }, []);

  // Keyboard close
  useEffect(() => {
    function onKey(e) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const parsedQty = parseInt(qty, 10);
  const isValidQty = !isNaN(parsedQty) && parsedQty > 0;

  // Live preview
  let previewOnHand = item.onHand;
  if (isValidQty) {
    if (adjType === "add") previewOnHand = item.onHand + parsedQty;
    else if (adjType === "remove") previewOnHand = item.onHand - parsedQty;
    else previewOnHand = parsedQty;
  }
  const previewAvail = previewOnHand - item.reserved;

  async function handleSave(e) {
    e.preventDefault();
    if (!isValidQty) {
      setError("Enter a valid quantity greater than 0.");
      return;
    }
    setError("");
    setBusy(true);
    try {
      const result = await adjustStock(item.id, {
        type: adjType,
        quantity: parsedQty,
        reason,
        note,
      });
      onSaved(result.item);
    } catch (err) {
      setError(err.message || "Could not save adjustment. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  const qtyLabel =
    adjType === "add"
      ? "Quantity to add"
      : adjType === "remove"
        ? "Quantity to remove"
        : "New total count";

  return (
    <>
      {/* Backdrop */}
      <div
        className="inv-drawer-backdrop"
        aria-hidden="true"
        onClick={onClose}
      />

      {/* Panel */}
      <aside
        className="inv-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="adj-drawer-title"
      >
        <div className="inv-drawer__header">
          <div>
            <p className="inv-drawer__eyebrow">
              INVENTORY / {item.name.toUpperCase()}
            </p>
            <h2 className="inv-drawer__title" id="adj-drawer-title">
              UPDATE STOCK
            </h2>
            <p className="inv-drawer__subtitle">
              {item.name} · {item.id}
            </p>
          </div>
          <button
            type="button"
            className="inv-drawer__close"
            onClick={onClose}
            aria-label="Close drawer"
            ref={firstFocusRef}
          >
            Close ×
          </button>
        </div>

        {/* Current stock summary */}
        <div className="inv-drawer__stock-summary" aria-label="Current stock">
          <div className="inv-drawer__stock-row">
            <span className="inv-drawer__stock-label">ON HAND</span>
            <span className="inv-drawer__stock-label">RESERVED</span>
            <span className="inv-drawer__stock-label">AVAILABLE</span>
          </div>
          <div className="inv-drawer__stock-row">
            <span className="inv-drawer__stock-num">{item.onHand}</span>
            <span className="inv-drawer__stock-num">{item.reserved}</span>
            <span className="inv-drawer__stock-num">{item.available}</span>
          </div>
        </div>

        <form onSubmit={handleSave} noValidate>
          {/* Adjustment type */}
          <div className="inv-drawer__field">
            <p className="inv-drawer__field-label" id="adj-type-label">
              Adjustment type
            </p>
            <div
              className="inv-drawer__type-row"
              role="group"
              aria-labelledby="adj-type-label"
            >
              {["add", "remove", "set"].map((t) => (
                <button
                  key={t}
                  type="button"
                  className={`inv-type-btn${adjType === t ? " inv-type-btn--active" : ""}`}
                  onClick={() => setAdjType(t)}
                  aria-pressed={adjType === t}
                >
                  {t === "add"
                    ? "Add stock"
                    : t === "remove"
                      ? "Remove stock"
                      : "Set count"}
                </button>
              ))}
            </div>
          </div>

          {/* Quantity */}
          <div className="inv-drawer__field">
            <label htmlFor="adj-qty" className="inv-drawer__field-label">
              {qtyLabel}
            </label>
            <input
              id="adj-qty"
              type="number"
              min="1"
              className="inv-drawer__input"
              value={qty}
              onChange={(e) => {
                setQty(e.target.value);
                setError("");
              }}
              placeholder={adjType === "set" ? item.onHand : "0"}
              required
              aria-describedby={error ? "adj-error" : undefined}
            />
          </div>

          {/* Reason */}
          <div className="inv-drawer__field">
            <label htmlFor="adj-reason" className="inv-drawer__field-label">
              Reason
            </label>
            <select
              id="adj-reason"
              className="inv-drawer__input"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            >
              {REASON_OPTIONS.map((r) => (
                <option key={r}>{r}</option>
              ))}
            </select>
          </div>

          {/* Note */}
          <div className="inv-drawer__field">
            <label htmlFor="adj-note" className="inv-drawer__field-label">
              Note <span className="inv-drawer__optional">(optional)</span>
            </label>
            <input
              id="adj-note"
              type="text"
              className="inv-drawer__input"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="e.g. Batch M-1103 · Freezer A"
            />
          </div>

          {/* Live preview */}
          {isValidQty && (
            <div
              className={`inv-drawer__preview${previewAvail < 0 ? " inv-drawer__preview--warn" : ""}`}
              aria-live="polite"
              aria-label="Stock preview after saving"
            >
              <p className="inv-drawer__preview-heading">AFTER SAVING</p>
              <p className="inv-drawer__preview-body">
                {previewOnHand < 0
                  ? "Warning: Cannot reduce below 0."
                  : previewAvail < 0
                    ? `Warning: ${Math.abs(previewAvail)} short of reserved. Reduce removal or free up reservations first.`
                    : `${previewOnHand} on hand · ${item.reserved} reserved · ${previewAvail} available`}
              </p>
            </div>
          )}

          {/* Error */}
          {error && (
            <p id="adj-error" className="inv-drawer__error" role="alert">
              {error}
            </p>
          )}

          <p className="inv-drawer__hint">
            Preview only. Current stock stays unchanged until saved.
          </p>

          <div className="inv-drawer__actions">
            <button
              type="button"
              className="adm-btn adm-btn--outline"
              onClick={onClose}
              disabled={busy}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="adm-btn adm-btn--primary"
              disabled={
                busy || !isValidQty || previewOnHand < 0 || previewAvail < 0
              }
            >
              {busy ? "Saving…" : "Save adjustment"}
            </button>
          </div>
        </form>
      </aside>
    </>
  );
}

// ---------------------------------------------------------------------------
// Add / Edit Item Form (slide-in panel)
// ---------------------------------------------------------------------------
const EMPTY_FORM = {
  name: "",
  category: "Fruit",
  shape: "Standard",
  onHand: "",
  minimum: "",
  notes: "",
};

function ItemFormDrawer({ item, onClose, onSaved }) {
  const isEdit = Boolean(item);
  const [form, setForm] = useState(
    isEdit
      ? { ...item, onHand: item.onHand, minimum: item.minimum }
      : EMPTY_FORM,
  );
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState({});
  const [apiError, setApiError] = useState("");
  const firstRef = useRef(null);

  useEffect(() => {
    firstRef.current?.focus();
  }, []);
  useEffect(() => {
    function onKey(e) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  function set(field, value) {
    setForm((f) => ({ ...f, [field]: value }));
    setErrors((e) => {
      const n = { ...e };
      delete n[field];
      return n;
    });
  }

  function validate() {
    const e = {};
    if (!form.name.trim()) e.name = "Name is required.";
    const qty = parseInt(form.onHand, 10);
    if (isNaN(qty) || qty < 0) e.onHand = "Enter a valid quantity (0 or more).";
    const min = parseInt(form.minimum, 10);
    if (isNaN(min) || min < 1)
      e.minimum = "Enter a minimum threshold (at least 1).";
    return e;
  }

  async function handleSubmit(e) {
    e.preventDefault();
    const errs = validate();
    if (Object.keys(errs).length) {
      setErrors(errs);
      return;
    }
    setBusy(true);
    setApiError("");
    try {
      const payload = {
        name: form.name.trim(),
        category: form.category,
        shape: form.shape,
        minimum: parseInt(form.minimum, 10),
        notes: form.notes.trim(),
        ...(isEdit ? {} : { onHand: parseInt(form.onHand, 10) }),
      };
      const result = isEdit
        ? await updateInventoryItem(item.id, payload)
        : await createInventoryItem(payload);
      onSaved(result.item, isEdit);
    } catch (err) {
      setApiError(err.message || "Could not save. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div
        className="inv-drawer-backdrop"
        aria-hidden="true"
        onClick={onClose}
      />
      <aside
        className="inv-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="item-form-title"
      >
        <div className="inv-drawer__header">
          <div>
            <p className="inv-drawer__eyebrow">INVENTORY</p>
            <h2 className="inv-drawer__title" id="item-form-title">
              {isEdit ? `EDIT ${item.name.toUpperCase()}` : "ADD NEW ITEM"}
            </h2>
          </div>
          <button
            type="button"
            className="inv-drawer__close"
            onClick={onClose}
            aria-label="Close"
            ref={firstRef}
          >
            Close ×
          </button>
        </div>

        <form onSubmit={handleSubmit} noValidate>
          <div className="inv-drawer__field">
            <label htmlFor="itm-name" className="inv-drawer__field-label">
              Flavor / product name{" "}
              <span className="inv-drawer__required" aria-hidden="true">
                *
              </span>
            </label>
            <input
              id="itm-name"
              type="text"
              className={`inv-drawer__input${errors.name ? " inv-drawer__input--error" : ""}`}
              value={form.name}
              onChange={(e) => set("name", e.target.value)}
              placeholder="e.g. Tamarind"
              aria-describedby={errors.name ? "itm-name-err" : undefined}
            />
            {errors.name && (
              <p id="itm-name-err" className="inv-drawer__error" role="alert">
                {errors.name}
              </p>
            )}
          </div>

          <div className="inv-drawer__field-row">
            <div className="inv-drawer__field">
              <label htmlFor="itm-category" className="inv-drawer__field-label">
                Category
              </label>
              <select
                id="itm-category"
                className="inv-drawer__input"
                value={form.category}
                onChange={(e) => set("category", e.target.value)}
              >
                <option>Fruit</option>
                <option>Cream</option>
                <option>Chocolate</option>
                <option>Seasonal</option>
              </select>
            </div>
            <div className="inv-drawer__field">
              <label htmlFor="itm-shape" className="inv-drawer__field-label">
                Shape / variant
              </label>
              <select
                id="itm-shape"
                className="inv-drawer__input"
                value={form.shape}
                onChange={(e) => set("shape", e.target.value)}
              >
                <option>Standard</option>
                <option>Dipped</option>
                <option>Mini</option>
                <option>Custom</option>
              </select>
            </div>
          </div>

          {!isEdit && (
            <div className="inv-drawer__field">
              <label htmlFor="itm-onhand" className="inv-drawer__field-label">
                Initial on-hand quantity{" "}
                <span className="inv-drawer__required" aria-hidden="true">
                  *
                </span>
              </label>
              <input
                id="itm-onhand"
                type="number"
                min="0"
                className={`inv-drawer__input${errors.onHand ? " inv-drawer__input--error" : ""}`}
                value={form.onHand}
                onChange={(e) => set("onHand", e.target.value)}
                placeholder="0"
                aria-describedby={errors.onHand ? "itm-onhand-err" : undefined}
              />
              {errors.onHand && (
                <p
                  id="itm-onhand-err"
                  className="inv-drawer__error"
                  role="alert"
                >
                  {errors.onHand}
                </p>
              )}
            </div>
          )}

          <div className="inv-drawer__field">
            <label htmlFor="itm-min" className="inv-drawer__field-label">
              Low-stock threshold{" "}
              <span className="inv-drawer__required" aria-hidden="true">
                *
              </span>
            </label>
            <input
              id="itm-min"
              type="number"
              min="1"
              className={`inv-drawer__input${errors.minimum ? " inv-drawer__input--error" : ""}`}
              value={form.minimum}
              onChange={(e) => set("minimum", e.target.value)}
              placeholder="e.g. 50"
              aria-describedby={errors.minimum ? "itm-min-err" : undefined}
            />
            {errors.minimum && (
              <p id="itm-min-err" className="inv-drawer__error" role="alert">
                {errors.minimum}
              </p>
            )}
            <p className="inv-drawer__hint">
              Items below this threshold are flagged as Low Stock.
            </p>
          </div>

          <div className="inv-drawer__field">
            <label htmlFor="itm-notes" className="inv-drawer__field-label">
              Notes <span className="inv-drawer__optional">(optional)</span>
            </label>
            <textarea
              id="itm-notes"
              className="inv-drawer__textarea"
              rows={3}
              value={form.notes}
              onChange={(e) => set("notes", e.target.value)}
              placeholder="Storage notes, special handling, etc."
            />
          </div>

          {apiError && (
            <p className="inv-drawer__error" role="alert">
              {apiError}
            </p>
          )}

          <div className="inv-drawer__actions">
            <button
              type="button"
              className="adm-btn adm-btn--outline"
              onClick={onClose}
              disabled={busy}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="adm-btn adm-btn--primary"
              disabled={busy}
            >
              {busy ? "Saving…" : isEdit ? "Save changes" : "Add item"}
            </button>
          </div>
        </form>
      </aside>
    </>
  );
}

// ---------------------------------------------------------------------------
// Item Detail Drawer (stock history + orders)
// ---------------------------------------------------------------------------
function ItemDetailDrawer({ item, onClose, onEdit, onAdjust }) {
  const [history, setHistory] = useState(null);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [deleting, setDeleting] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const firstRef = useRef(null);

  useEffect(() => {
    firstRef.current?.focus();
  }, []);
  useEffect(() => {
    function onKey(e) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    setLoadingHistory(true);
    fetchStockHistory(item.id)
      .then((r) => setHistory(r.history))
      .catch(() => setHistory([]))
      .finally(() => setLoadingHistory(false));
  }, [item.id]);

  const status = statusOf(item);

  async function handleDelete() {
    setDeleting(true);
    try {
      await deleteInventoryItem(item.id);
      onClose(item.id); // pass id so parent can remove
    } catch {
      setDeleting(false);
      setConfirmDelete(false);
    }
  }

  return (
    <>
      <div
        className="inv-drawer-backdrop"
        aria-hidden="true"
        onClick={() => onClose()}
      />
      <aside
        className="inv-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="detail-drawer-title"
      >
        <div className="inv-drawer__header">
          <div>
            <p className="inv-drawer__eyebrow">
              INVENTORY / {item.name.toUpperCase()}
            </p>
            <h2 className="inv-drawer__title" id="detail-drawer-title">
              {item.name}
            </h2>
            <p className="inv-drawer__subtitle">
              {item.category} · {item.id} · {item.shape}
            </p>
          </div>
          <button
            type="button"
            className="inv-drawer__close"
            onClick={() => onClose()}
            aria-label="Close"
            ref={firstRef}
          >
            Close ×
          </button>
        </div>

        {/* Stock summary */}
        <div className="inv-drawer__stock-summary" aria-label="Current stock">
          <div className="inv-drawer__stock-row">
            <span className="inv-drawer__stock-label">ON HAND</span>
            <span className="inv-drawer__stock-label">RESERVED</span>
            <span className="inv-drawer__stock-label">AVAILABLE</span>
          </div>
          <div className="inv-drawer__stock-row">
            <span className="inv-drawer__stock-num">{item.onHand}</span>
            <span className="inv-drawer__stock-num">{item.reserved}</span>
            <span
              className={`inv-drawer__stock-num${status === "out" ? " inv-drawer__stock-num--warn" : status === "low" ? " inv-drawer__stock-num--low" : ""}`}
            >
              {item.available}
            </span>
          </div>
        </div>

        {/* Status + threshold */}
        <div className="inv-detail__meta">
          <span className={`inv-badge ${STATUS_CLASS[status]}`}>
            {STATUS_LABEL[status]}
          </span>
          <span className="inv-detail__threshold">
            Low-stock threshold: {item.minimum}
          </span>
        </div>

        {/* Shortage warning */}
        {item.available < 0 && (
          <div className="inv-detail__shortage" role="alert">
            Warning: This item is {Math.abs(item.available)} short of its
            reservations. Orders may be affected.
          </div>
        )}

        {/* Notes */}
        {item.notes && (
          <div className="inv-detail__notes">
            <p className="inv-drawer__field-label">Notes</p>
            <p className="inv-detail__notes-body">{item.notes}</p>
          </div>
        )}

        {/* Quick actions */}
        <div className="inv-detail__actions">
          <button
            type="button"
            className="adm-btn adm-btn--primary"
            onClick={() => onAdjust(item)}
          >
            Adjust stock
          </button>
          <button
            type="button"
            className="adm-btn adm-btn--outline"
            onClick={() => onEdit(item)}
          >
            Edit item
          </button>
        </div>

        {/* Stock history */}
        <section className="inv-detail__history" aria-labelledby="hist-heading">
          <h3 className="inv-detail__section-title" id="hist-heading">
            Stock history
          </h3>
          {loadingHistory ? (
            <p className="inv-detail__loading" role="status">
              Loading history…
            </p>
          ) : history && history.length ? (
            <ul className="inv-detail__history-list" role="list">
              {history.map((h, i) => (
                <li key={i} className="inv-detail__history-item">
                  <div className="inv-detail__history-row">
                    <span
                      className={`inv-detail__history-type inv-detail__history-type--${h.type}`}
                    >
                      {h.type === "add" ? "+" : h.type === "remove" ? "−" : "="}
                      {h.qty}
                    </span>
                    <span className="inv-detail__history-reason">
                      {h.reason}
                    </span>
                    <span className="inv-detail__history-date">{h.date}</span>
                  </div>
                  {h.note && (
                    <p className="inv-detail__history-note">{h.note}</p>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p className="inv-detail__empty">No adjustments recorded yet.</p>
          )}
        </section>

        {/* Danger zone */}
        <section
          className="inv-detail__danger"
          aria-labelledby="danger-heading"
        >
          <h3
            className="inv-detail__section-title inv-detail__section-title--danger"
            id="danger-heading"
          >
            Remove item
          </h3>
          {confirmDelete ? (
            <div
              className="inv-detail__confirm-delete"
              role="alertdialog"
              aria-label="Confirm deletion"
            >
              <p>
                Are you sure you want to remove <strong>{item.name}</strong>?
                This cannot be undone.
              </p>
              <div style={{ display: "flex", gap: "12px", marginTop: "12px" }}>
                <button
                  type="button"
                  className="adm-btn adm-btn--outline"
                  onClick={() => setConfirmDelete(false)}
                  disabled={deleting}
                >
                  Keep item
                </button>
                <button
                  type="button"
                  className="adm-btn adm-btn--danger"
                  onClick={handleDelete}
                  disabled={deleting}
                >
                  {deleting ? "Removing…" : "Yes, remove"}
                </button>
              </div>
            </div>
          ) : (
            <button
              type="button"
              className="adm-btn adm-btn--outline adm-btn--danger-outline"
              onClick={() => setConfirmDelete(true)}
            >
              Remove from inventory
            </button>
          )}
        </section>
      </aside>
    </>
  );
}

// ---------------------------------------------------------------------------
// Main Inventory Page
// ---------------------------------------------------------------------------
export function InventoryPage() {
  const [items, setItems] = useState([]);
  const [loadState, setLoadState] = useState("loading"); // loading | ready | error
  const [search, setSearch] = useState("");
  const [activeFilter, setActiveFilter] = useState("all");
  const [toast, setToast] = useState(null); // { message, type }

  // Drawer states
  const [adjItem, setAdjItem] = useState(null); // item to adjust
  const [editItem, setEditItem] = useState(null); // item to edit, or {} for new
  const [detailItem, setDetailItem] = useState(null); // item detail view

  // Load inventory
  const loadInventory = useCallback(async () => {
    setLoadState("loading");
    try {
      const { items: data } = await fetchInventory();
      setItems(data);
      setLoadState("ready");
    } catch {
      setLoadState("error");
    }
  }, []);

  useEffect(() => {
    loadInventory();
  }, [loadInventory]);

  // Toast helper
  function showToast(message, type = "success") {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3500);
  }

  // Computed stats
  const totalOnHand = items.reduce((s, i) => s + i.onHand, 0);
  const totalReserved = items.reduce((s, i) => s + i.reserved, 0);
  const totalAvail = items.reduce((s, i) => s + i.available, 0);
  const lowItems = items.filter((i) => statusOf(i) === "low");
  const outItems = items.filter((i) => statusOf(i) === "out");

  // Filtered list
  const filtered = items.filter((item) => {
    const q = search.toLowerCase();
    const matchSearch =
      !q ||
      item.name.toLowerCase().includes(q) ||
      item.id.toLowerCase().includes(q);
    const matchFilter =
      activeFilter === "all" ||
      (activeFilter === "low" && statusOf(item) === "low") ||
      (activeFilter === "out" && statusOf(item) === "out");
    return matchSearch && matchFilter;
  });

  // Update a single item in state
  function patchItem(updated) {
    setItems((prev) => prev.map((i) => (i.id === updated.id ? updated : i)));
  }

  function handleAdjustSaved(updated) {
    patchItem(updated);
    setAdjItem(null);
    // Update detail drawer too if open
    if (detailItem?.id === updated.id) setDetailItem(updated);
    showToast(`${updated.name} stock updated.`);
  }

  function handleItemSaved(saved, wasEdit) {
    if (wasEdit) {
      patchItem(saved);
      if (detailItem?.id === saved.id) setDetailItem(saved);
    } else {
      setItems((prev) => [...prev, saved]);
    }
    setEditItem(null);
    showToast(`${saved.name} ${wasEdit ? "updated" : "added"}.`);
  }

  function handleDetailClose(deletedId) {
    if (deletedId) {
      setItems((prev) => prev.filter((i) => i.id !== deletedId));
      showToast("Item removed from inventory.");
    }
    setDetailItem(null);
  }

  const hasAlerts = lowItems.length > 0 || outItems.length > 0;
  const alertFlavors = [...outItems, ...lowItems].map((i) => i.name);

  return (
    <div className="adm-shell">
      <AdminNav activeRoute="/admin/inventory" />

      <div className="adm-main">
        {/* Page header */}
        <header className="adm-page-header">
          <p className="adm-page-header__title">Inventory</p>
          <div className="adm-page-header__actions">
            <a href="/" className="adm-page-header__view-site">
              View website ↗
            </a>
            <Link to="/admin" className="adm-btn adm-btn--outline">
              Owner account
            </Link>
          </div>
        </header>

        <div className="adm-content">
          {/* Hero heading */}
          <div className="adm-hero-row">
            <div className="adm-hero-row__text">
              <h1 className="adm-hero-row__heading">KEEP THE JOY IN STOCK.</h1>
              <p className="adm-hero-row__sub">
                Paletas on hand, promised, and ready to party.
              </p>
            </div>
            <button
              type="button"
              className="adm-btn adm-btn--primary"
              onClick={() => setEditItem({})}
            >
              Add item +
            </button>
          </div>

          {/* Loading / error states */}
          {loadState === "loading" && (
            <p role="status" className="inv-page__loading">
              Loading inventory…
            </p>
          )}
          {loadState === "error" && (
            <div className="inv-page__error" role="alert">
              <p>
                Could not load inventory.{" "}
                <button type="button" onClick={loadInventory}>
                  Try again
                </button>
              </p>
            </div>
          )}

          {loadState === "ready" && (
            <>
              {/* Stat cards */}
              <div
                className="adm-stats-grid adm-stats-grid--4col"
                aria-label="Inventory overview"
              >
                <div className="adm-stat-card adm-stat-card--pink">
                  <p className="adm-stat-card__label">On hand</p>
                  <p className="adm-stat-card__value">
                    {totalOnHand.toLocaleString()}
                  </p>
                </div>
                <div className="adm-stat-card adm-stat-card--pink">
                  <p className="adm-stat-card__label">Reserved</p>
                  <p className="adm-stat-card__value">
                    {totalReserved.toLocaleString()}
                  </p>
                </div>
                <div className="adm-stat-card adm-stat-card--pink">
                  <p className="adm-stat-card__label">Available</p>
                  <p className="adm-stat-card__value">
                    {totalAvail.toLocaleString()}
                  </p>
                </div>
                <div className="adm-stat-card adm-stat-card--yellow">
                  <p className="adm-stat-card__label">Low / out of stock</p>
                  <p className="adm-stat-card__value adm-stat-card__value--dark">
                    {lowItems.length + outItems.length}
                  </p>
                </div>
              </div>

              {/* Alert banner */}
              {hasAlerts && (
                <div className="inv-alert" role="alert">
                  <div className="inv-alert__text">
                    <p className="inv-alert__heading">
                      {lowItems.length + outItems.length} FLAVOR
                      {lowItems.length + outItems.length !== 1 ? "S" : ""} NEED
                      A TOP-UP
                    </p>
                    <p className="inv-alert__body">
                      {alertFlavors.join(", ")}{" "}
                      {alertFlavors.length === 1 ? "is" : "are"} below{" "}
                      {alertFlavors.length === 1 ? "its" : "their"} minimum
                      {alertFlavors.length !== 1 ? "s" : ""}.
                    </p>
                  </div>
                  <button
                    type="button"
                    className="inv-alert__btn"
                    onClick={() => setActiveFilter("low")}
                  >
                    Review low stock ↗
                  </button>
                </div>
              )}

              {/* Search + filter toolbar */}
              <div className="inv-toolbar" role="search">
                <input
                  type="search"
                  className="inv-search"
                  placeholder="Search flavors or SKU…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  aria-label="Search inventory"
                />
                <div
                  className="inv-filters"
                  role="group"
                  aria-label="Filter inventory"
                >
                  <button
                    type="button"
                    className={`inv-filter-btn${activeFilter === "all" ? " inv-filter-btn--active" : ""}`}
                    onClick={() => setActiveFilter("all")}
                    aria-pressed={activeFilter === "all"}
                  >
                    All items · {items.length}
                  </button>
                  {lowItems.length > 0 && (
                    <button
                      type="button"
                      className={`inv-filter-btn inv-filter-btn--yellow${activeFilter === "low" ? " inv-filter-btn--active" : ""}`}
                      onClick={() => setActiveFilter("low")}
                      aria-pressed={activeFilter === "low"}
                    >
                      Low stock · {lowItems.length}
                    </button>
                  )}
                  {outItems.length > 0 && (
                    <button
                      type="button"
                      className={`inv-filter-btn inv-filter-btn--out${activeFilter === "out" ? " inv-filter-btn--active" : ""}`}
                      onClick={() => setActiveFilter("out")}
                      aria-pressed={activeFilter === "out"}
                    >
                      Out of stock · {outItems.length}
                    </button>
                  )}
                </div>
              </div>

              {/* Inventory table */}
              <section
                className="adm-card adm-card--outlined inv-table-card"
                aria-labelledby="inv-table-heading"
              >
                <h2 className="visually-hidden" id="inv-table-heading">
                  Flavor inventory
                </h2>

                {filtered.length === 0 ? (
                  <p className="inv-table__empty">
                    {search
                      ? `No items match "${search}".`
                      : "No items in this category."}
                  </p>
                ) : (
                  <div
                    className="adm-table-wrap"
                    role="region"
                    aria-label="Inventory table"
                    tabIndex={0}
                  >
                    <table className="adm-orders-table inv-table">
                      <thead>
                        <tr>
                          <th scope="col">FLAVOR / SKU</th>
                          <th scope="col">ON HAND</th>
                          <th scope="col">RESERVED</th>
                          <th scope="col">AVAILABLE</th>
                          <th scope="col">MINIMUM</th>
                          <th scope="col">STATUS</th>
                          <th scope="col">ACTION</th>
                        </tr>
                      </thead>
                      <tbody>
                        {filtered.map((item) => {
                          const st = statusOf(item);
                          return (
                            <tr key={item.id} className="inv-table__row">
                              <td>
                                <button
                                  type="button"
                                  className="inv-table__name-btn"
                                  onClick={() => setDetailItem(item)}
                                  aria-label={`View details for ${item.name}`}
                                >
                                  <span className="inv-table__flavor-name">
                                    {item.name}
                                  </span>
                                  <span className="inv-table__flavor-sku">
                                    {item.category} · {item.id}
                                  </span>
                                </button>
                              </td>
                              <td>{item.onHand}</td>
                              <td>{item.reserved}</td>
                              <td
                                className={
                                  st === "low" || st === "out"
                                    ? "inv-table__available--low"
                                    : ""
                                }
                              >
                                {item.available}
                              </td>
                              <td>{item.minimum}</td>
                              <td>
                                <span
                                  className={`inv-badge ${STATUS_CLASS[st]}`}
                                  aria-label={`Status: ${STATUS_LABEL[st]}`}
                                >
                                  {STATUS_LABEL[st]}
                                </span>
                              </td>
                              <td>
                                <button
                                  type="button"
                                  className="inv-table__action"
                                  onClick={() => setAdjItem(item)}
                                  aria-label={`Update stock for ${item.name}`}
                                >
                                  Update ↗
                                </button>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>

              {/* Footer note */}
              <p className="adm-content__footer-note">
                Available = on hand − reserved. Reservations cover{" "}
                {totalReserved.toLocaleString()} paletas across confirmed
                events.
              </p>
            </>
          )}
        </div>
      </div>

      {/* Drawers */}
      {adjItem && (
        <AdjustDrawer
          item={adjItem}
          onClose={() => setAdjItem(null)}
          onSaved={handleAdjustSaved}
        />
      )}
      {editItem !== null && (
        <ItemFormDrawer
          item={Object.keys(editItem).length ? editItem : null}
          onClose={() => setEditItem(null)}
          onSaved={handleItemSaved}
        />
      )}
      {detailItem && (
        <ItemDetailDrawer
          item={detailItem}
          onClose={handleDetailClose}
          onEdit={(it) => {
            setDetailItem(null);
            setEditItem(it);
          }}
          onAdjust={(it) => {
            setDetailItem(null);
            setAdjItem(it);
          }}
        />
      )}

      {/* Toast notification */}
      {toast && (
        <div
          className={`inv-toast inv-toast--${toast.type}`}
          role="status"
          aria-live="polite"
        >
          {toast.message}
        </div>
      )}
    </div>
  );
}
