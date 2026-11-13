import { useEffect, useRef, useState } from "react";
import { apiRequest } from "./auth/api.js";

export const ADDRESS_FIELDS = [
  "location_line1",
  "location_city",
  "location_region",
  "location_postal_code",
];

export function locationFromForm(form) {
  return {
    line1: form.location_line1.trim(),
    city: form.location_city.trim(),
    region: form.location_region.trim().toUpperCase(),
    postal_code: form.location_postal_code.trim(),
    country_code: "US",
  };
}

export function locationKey(location) {
  return JSON.stringify(
    ["line1", "city", "region", "postal_code", "country_code"].map((key) =>
      (location[key] || "").trim().toLowerCase(),
    ),
  );
}

export function serviceAreaKey(location) {
  const code = (location.postal_code || "").trim();
  const normalized = /^\d{5}(?:-\d{4})?$/.test(code) ? code.slice(0, 5) : code;
  return JSON.stringify([
    normalized,
    (location.country_code || "US").toUpperCase(),
  ]);
}

function safeAttributions(items) {
  return Array.isArray(items)
    ? items.filter((item) => {
        if (typeof item?.name !== "string" || typeof item?.url !== "string")
          return false;
        try {
          const url = new URL(item.url);
          return url.protocol === "https:" && !url.username && !url.password;
        } catch {
          return false;
        }
      })
    : [];
}

export function AddressAttribution({ sources = [] }) {
  const extraSources = safeAttributions(sources).filter(
    (item, index, all) =>
      ![
        "https://www.geoapify.com/",
        "https://www.openstreetmap.org/copyright",
      ].includes(item.url) &&
      all.findIndex((source) => source.url === item.url) === index,
  );
  return (
    <small className="address-attribution" translate="no">
      Powered by{" "}
      <a
        href="https://www.geoapify.com/"
        target="_blank"
        rel="noopener noreferrer"
      >
        Geoapify
      </a>
      {" · "}
      <a
        href="https://www.openstreetmap.org/copyright"
        target="_blank"
        rel="noopener noreferrer"
      >
        © OpenStreetMap contributors
      </a>
      {extraSources.map((item) => (
        <span key={item.url}>
          {" · "}
          <a href={item.url} target="_blank" rel="noopener noreferrer">
            {item.name}
          </a>
        </span>
      ))}
    </small>
  );
}

export function ServiceAreaNotice({ config, result, checking }) {
  const radius = config.radius_miles;
  const within = !checking && result?.status === "within_area";
  const outside = !checking && result?.status === "outside_area";
  return (
    <div
      className={`service-area-notice${within ? " service-area-notice--within" : outside ? " service-area-notice--outside" : ""}`}
    >
      <strong>
        {within && (
          <svg
            className="service-area-check"
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <path
              d="M5 12l4 4L19 6"
              fill="none"
              stroke="currentColor"
              strokeWidth="3"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        )}
        {within
          ? "Within our service area"
          : outside
            ? "Owner review needed"
            : `Standard service area: ${radius} miles`}
      </strong>
      <p role="status">
        {checking
          ? "Checking service area…"
          : within
            ? "This ZIP code is within our standard catering area."
            : outside
              ? `This ZIP code is outside our usual ${radius}-mile area. You can continue to a quote estimate; the owner will confirm availability and any travel fees.`
              : result?.message ||
                (config.enabled
                  ? "Enter the event ZIP code to check the service area."
                  : "Enter your event ZIP code to check the service area. You can enter the rest of the address manually.")}
      </p>
      <p className="field-hint">
        Based on ZIP-area centers within {radius} miles of Stafford, TX{" "}
        {config.origin_postal_code || "77477"}.
      </p>
      {outside && (
        <p>
          <a href="mailto:info@popssibilities.com">Ask about a custom event</a>{" "}
          or <a href="tel:+12812487514">call 281-248-7514</a>.
        </p>
      )}
    </div>
  );
}

export function AddressField({
  value,
  onChange,
  onResolved,
  onBusyChange,
  addressKey,
  enabled,
  ...inputProps
}) {
  const [focused, setFocused] = useState(false);
  const [items, setItems] = useState([]);
  const [active, setActive] = useState(-1);
  const [message, setMessage] = useState("");
  const [searching, setSearching] = useState(false);
  const [attributions, setAttributions] = useState([]);
  const token = useRef(null);
  const latestKey = useRef(addressKey);
  const selection = useRef(null);
  const resultsRef = useRef(null);
  const generation = useRef(0);
  latestKey.current = addressKey;

  useEffect(
    () => () => {
      generation.current++;
      selection.current?.abort();
      onBusyChange(false);
    },
    [onBusyChange],
  );

  useEffect(() => {
    setItems([]);
    setActive(-1);
    setSearching(false);
    if (!enabled || !focused || value.trim().length < 4) return;
    let current = true;
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      setSearching(true);
      token.current ||= crypto.randomUUID();
      try {
        const data = await apiRequest("/catering/address/suggestions", {
          method: "POST",
          signal: controller.signal,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            input: value.trim(),
            session_token: token.current,
          }),
        });
        if (!current) return;
        const suggestions = Array.isArray(data.suggestions)
          ? data.suggestions
              .filter(
                (item) =>
                  typeof item?.place_id === "string" &&
                  typeof item?.label === "string",
              )
              .slice(0, 5)
          : [];
        setItems(suggestions);
        setAttributions(
          suggestions.flatMap((item) => safeAttributions(item.attributions)),
        );
        setMessage(
          suggestions.length
            ? ""
            : "No matching addresses. Try adding the city, state or ZIP, or enter the address manually.",
        );
      } catch {
        if (current)
          setMessage(
            "Address suggestions are unavailable. You can enter the address manually.",
          );
      } finally {
        if (current) setSearching(false);
      }
    }, 350);
    return () => {
      current = false;
      clearTimeout(timer);
      controller.abort();
    };
  }, [enabled, focused, value]);

  async function choose(item) {
    const requestKey = latestKey.current;
    const current = ++generation.current;
    selection.current?.abort();
    const controller = new AbortController();
    selection.current = controller;
    setFocused(false);
    setItems([]);
    setMessage("Filling in address details…");
    onBusyChange(true);
    try {
      const data = await apiRequest("/catering/address/resolve", {
        method: "POST",
        signal: controller.signal,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          place_id: item.place_id,
          session_token: token.current,
          check_service_area: false,
        }),
      });
      if (current !== generation.current || requestKey !== latestKey.current)
        return;
      if (
        !data.location ||
        !["line1", "city", "region", "postal_code", "country_code"].every(
          (key) => typeof data.location[key] === "string",
        )
      )
        throw new Error("invalid address");
      onResolved(data);
      setAttributions(safeAttributions(data.attributions));
      setMessage("Address filled in. Please check the details below.");
    } catch {
      if (current === generation.current && requestKey === latestKey.current)
        setMessage(
          "We could not fill that address. Enter the details manually and try checking the service area.",
        );
    } finally {
      if (current === generation.current) {
        token.current = null;
        selection.current = null;
        onBusyChange(false);
      }
    }
  }

  const open = focused && items.length > 0;
  useEffect(() => {
    if (open && active < 0) {
      resultsRef.current?.scrollIntoView({ block: "nearest" });
    } else if (open && active >= 0) {
      document
        .getElementById(`cf-address-option-${active}`)
        ?.scrollIntoView({ block: "nearest" });
    }
  }, [open, active]);
  return (
    <div className="address-search">
      <input
        {...inputProps}
        value={value}
        role={enabled ? "combobox" : undefined}
        aria-autocomplete={enabled ? "list" : undefined}
        aria-busy={searching || undefined}
        aria-expanded={enabled ? open : undefined}
        aria-controls={open ? "cf-address-options" : undefined}
        aria-activedescendant={
          open && active >= 0 ? `cf-address-option-${active}` : undefined
        }
        autoComplete={enabled ? "off" : "street-address"}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        onChange={(event) => {
          setFocused(true);
          setMessage("");
          setAttributions([]);
          generation.current++;
          if (selection.current) {
            selection.current.abort();
            selection.current = null;
            token.current = null;
          }
          onBusyChange(false);
          onChange(event.target.value);
        }}
        onKeyDown={(event) => {
          if (!open) return;
          if (["ArrowDown", "ArrowUp"].includes(event.key)) {
            event.preventDefault();
            setActive((index) =>
              index < 0
                ? event.key === "ArrowDown"
                  ? 0
                  : items.length - 1
                : (index +
                    (event.key === "ArrowDown" ? 1 : -1) +
                    items.length) %
                  items.length,
            );
          } else if (event.key === "Enter" && active >= 0) {
            event.preventDefault();
            choose(items[active]);
          } else if (event.key === "Escape") {
            event.preventDefault();
            event.stopPropagation();
            setFocused(false);
          }
        }}
      />
      {open && (
        <div className="address-search__results" ref={resultsRef}>
          <ul
            id="cf-address-options"
            role="listbox"
            aria-label="Address suggestions"
          >
            {items.map((item, index) => (
              <li
                key={item.place_id}
                id={`cf-address-option-${index}`}
                role="option"
                aria-selected={index === active}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => choose(item)}
              >
                {item.label}
              </li>
            ))}
          </ul>
          <AddressAttribution sources={attributions} />
        </div>
      )}
      {(searching || message) && (
        <p className="field-hint" role="status">
          {searching ? "Searching addresses…" : message}
        </p>
      )}
      {!open && attributions.length > 0 && (
        <div className="address-search__attributions">
          <AddressAttribution sources={attributions} />
        </div>
      )}
    </div>
  );
}
