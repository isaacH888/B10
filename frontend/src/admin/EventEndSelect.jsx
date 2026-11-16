import { useId, useRef, useState } from "react";
import {
  centralInputValue,
  centralTimeToIso,
  EVENT_TIME_ZONE,
  formatEventTime,
} from "../eventTime.js";
import "./event-end-select.css";

const minute = 60000;
const clock = new Intl.DateTimeFormat("en-US", {
  timeZone: EVENT_TIME_ZONE,
  hour: "numeric",
  minute: "2-digit",
  timeZoneName: "short",
});

function optionLabel(timestamp, start) {
  const minutes = Math.round((timestamp - start) / minute);
  const hours = Math.floor(minutes / 60);
  const duration = [
    hours ? `${hours} ${hours === 1 ? "hour" : "hours"}` : "",
    minutes % 60 ? `${minutes % 60} min` : "",
  ]
    .filter(Boolean)
    .join(" ");
  const sameDay =
    centralInputValue(timestamp).slice(0, 10) ===
    centralInputValue(start).slice(0, 10);
  const end = sameDay ? clock.format(timestamp) : formatEventTime(timestamp);
  return `${end} (${duration})`;
}

export function EventEndSelect({
  start,
  value: controlledValue,
  defaultValue = "",
  onChange,
  name,
  required = false,
  label = "Event end (Houston/Central time)",
}) {
  const id = useId();
  const [localValue, setLocalValue] = useState(defaultValue);
  const value = controlledValue ?? localValue;
  const initialValue = useRef(value);
  const [custom, setCustom] = useState(false);
  const [customValue, setCustomValue] = useState("");
  const [error, setError] = useState("");
  const startMs = Date.parse(start);
  const hasStart = Number.isFinite(startMs);
  const endMs = Date.parse(value);
  const selected = Number.isFinite(endMs) ? new Date(endMs).toISOString() : "";
  const choices = new Set();
  if (hasStart) {
    for (let minutes = 30; minutes <= 720; minutes += 30)
      choices.add(startMs + minutes * minute);
    for (const end of [initialValue.current, value]) {
      const timestamp = Date.parse(end);
      if (Number.isFinite(timestamp) && timestamp > startMs)
        choices.add(timestamp);
    }
  }

  function update(next) {
    setLocalValue(next);
    onChange?.(next);
  }

  function select(event) {
    setError("");
    if (event.target.value === "custom") {
      setCustom(true);
      setCustomValue(selected ? centralInputValue(selected) : "");
    } else {
      setCustom(false);
      update(event.target.value);
    }
  }

  function changeCustom(event) {
    const entered = event.target.value;
    setCustomValue(entered);
    setError("");
    try {
      const end = entered ? centralTimeToIso(entered) : "";
      if (end && hasStart && Date.parse(end) <= startMs)
        throw new Error("Event end must be after the event start.");
      update(end);
    } catch (failure) {
      update("");
      setError(failure.message);
    }
  }

  return (
    <div className="event-end-select">
      {hasStart && (
        <p className="event-end-select__start">
          Starts {formatEventTime(start)}
        </p>
      )}
      <label htmlFor={id}>{label}</label>
      <select
        id={id}
        value={custom || !hasStart ? "custom" : selected}
        onChange={select}
        required={required}
        aria-describedby={`${id}-hint`}
      >
        <option value="">Choose an end time</option>
        {[...choices]
          .sort((a, b) => a - b)
          .map((timestamp) => (
            <option key={timestamp} value={new Date(timestamp).toISOString()}>
              {optionLabel(timestamp, startMs)}
            </option>
          ))}
        <option value="custom">Custom date and time…</option>
      </select>
      <p id={`${id}-hint`} className="event-end-select__hint">
        End times follow the customer's event start. All times are
        Houston/Central.
      </p>
      {(custom || !hasStart) && (
        <label>
          Custom event end (Houston/Central time)
          <input
            type="datetime-local"
            value={customValue}
            onChange={changeCustom}
            required={required}
            aria-invalid={Boolean(error)}
            aria-describedby={error ? `${id}-error` : undefined}
          />
        </label>
      )}
      {name && <input type="hidden" name={name} value={value} />}
      {error && (
        <p role="alert" id={`${id}-error`}>
          {error}
        </p>
      )}
    </div>
  );
}
