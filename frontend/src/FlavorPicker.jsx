import { DEMO_FLAVORS, flavorMixIssue, flavorMixTotal } from "./flavors.js";
import "./flavors.css";

export function FlavorMixSummary({ allocations }) {
  if (!allocations?.length) return null;
  return (
    <ul className="flavor-mix-summary" aria-label="Flavor quantities">
      {allocations.map((row) => (
        <li key={row.flavor}>
          <span>{row.flavor}</span>
          <strong>{row.quantity}</strong>
        </li>
      ))}
    </ul>
  );
}

export default function FlavorPicker({ quantity, rows, onChange, error }) {
  const total = Number(quantity);
  const validTotal = Number.isInteger(total) && total >= 50 && total <= 100000;
  const assigned = flavorMixTotal(rows);
  const issue = error ? flavorMixIssue(rows, quantity) : null;

  function updateRow(id, field, value) {
    onChange(
      rows.map((row) => (row.id === id ? { ...row, [field]: value } : row)),
    );
  }

  function splitEvenly() {
    const each = Math.floor(total / DEMO_FLAVORS.length);
    const extra = total % DEMO_FLAVORS.length;
    onChange(
      DEMO_FLAVORS.map((flavor, index) => ({
        id: crypto.randomUUID(),
        flavor,
        quantity: String(each + (index < extra ? 1 : 0)),
      })),
    );
  }

  function addFlavor() {
    const flavor = DEMO_FLAVORS.find(
      (name) => !rows.some((row) => row.flavor === name),
    );
    onChange([
      ...rows,
      {
        id: crypto.randomUUID(),
        flavor,
        quantity: assigned < total ? String(total - assigned) : "",
      },
    ]);
  }

  return (
    <section className="flavor-picker" aria-labelledby="cf-flavor-mix-heading">
      <h3 id="cf-flavor-mix-heading">
        Build your flavor mix <small>(optional)</small>
      </h3>
      <p id="cf-flavor-mix-hint" className="field-hint">
        Choose from our sample flavors. We’ll confirm availability for your
        event. Leave the mix empty if you’d like Audrey to choose.
      </p>
      <div className="flavor-picker__actions">
        <button type="button" onClick={splitEvenly} disabled={!validTotal}>
          Split evenly across all 5
        </button>
        {rows.length > 0 && (
          <button type="button" onClick={() => onChange([])}>
            Let Audrey choose
          </button>
        )}
      </div>
      {rows.length > 0 && (
        <p className="flavor-picker__progress" role="status">
          {assigned} of {quantity} paletas assigned
          {validTotal &&
            assigned < total &&
            ` · ${total - assigned} left to choose`}
          {validTotal && assigned > total && ` · ${assigned - total} too many`}
        </p>
      )}
      {rows.map((row, index) => {
        const invalid = issue?.index === index;
        const description = `cf-flavor-mix-hint${error ? " cf-flavor-mix-error" : ""}`;
        return (
          <div className="flavor-picker__row" key={row.id}>
            <div className="form-field">
              <label htmlFor={`cf-flavor-${row.id}`}>Flavor {index + 1}</label>
              <select
                id={`cf-flavor-${row.id}`}
                value={row.flavor}
                aria-describedby={description}
                aria-invalid={
                  invalid && issue.field === "flavor" ? true : undefined
                }
                onChange={(event) =>
                  updateRow(row.id, "flavor", event.target.value)
                }
              >
                {DEMO_FLAVORS.map((flavor) => (
                  <option
                    key={flavor}
                    value={flavor}
                    disabled={rows.some(
                      (other) => other.id !== row.id && other.flavor === flavor,
                    )}
                  >
                    {flavor}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-field">
              <label htmlFor={`cf-flavor-quantity-${row.id}`}>
                Qty {index + 1}
              </label>
              <input
                id={`cf-flavor-quantity-${row.id}`}
                type="number"
                min="1"
                max={validTotal ? total : 100000}
                step="1"
                value={row.quantity}
                aria-describedby={description}
                aria-invalid={
                  invalid && issue.field === "quantity" ? true : undefined
                }
                onChange={(event) =>
                  updateRow(row.id, "quantity", event.target.value)
                }
              />
            </div>
            <button
              className="flavor-picker__remove"
              type="button"
              aria-label={`Remove ${row.flavor}`}
              onClick={() =>
                onChange(rows.filter((other) => other.id !== row.id))
              }
            >
              <span aria-hidden="true">×</span>
            </button>
          </div>
        );
      })}
      {rows.length < DEMO_FLAVORS.length && (
        <button
          className="flavor-picker__add"
          type="button"
          onClick={addFlavor}
          disabled={!validTotal}
        >
          + Add a flavor
        </button>
      )}
      {error && (
        <p id="cf-flavor-mix-error" className="field-error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
