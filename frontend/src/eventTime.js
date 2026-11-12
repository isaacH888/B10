export const EVENT_TIME_ZONE = "America/Chicago";

const partsFormatter = new Intl.DateTimeFormat("en-US", {
  timeZone: EVENT_TIME_ZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});

function wallTime(timestamp) {
  const parts = Object.fromEntries(
    partsFormatter
      .formatToParts(new Date(timestamp))
      .filter((part) => part.type !== "literal")
      .map((part) => [part.type, Number(part.value)]),
  );
  return Date.UTC(
    parts.year,
    parts.month - 1,
    parts.day,
    parts.hour,
    parts.minute,
    parts.second,
  );
}

// Interpret the entered clock time in Houston, regardless of the browser's zone.
// Match both offsets around a clock change rather than guessing at a DST gap or fold.
export function centralTimeToIso(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/.exec(
    value,
  );
  if (!match) throw new Error("Enter a complete date and time.");
  const [, year, month, day, hour, minute, second = "00"] = match;
  const local = `${year}-${month}-${day}T${hour}:${minute}:${second}`;
  const target = Date.parse(`${local}Z`);
  if (
    !Number.isFinite(target) ||
    new Date(target).toISOString().slice(0, 19) !== local
  ) {
    throw new Error("Enter a valid date and time.");
  }
  const dayMs = 86400000;
  const offsets = new Set(
    [-dayMs, 0, dayMs].map((delta) => {
      const sample = target + delta;
      return wallTime(sample) - sample;
    }),
  );
  const matches = [...offsets].filter(
    (offset) => wallTime(target - offset) === target,
  );
  if (!matches.length) {
    throw new Error(
      "This Central time is skipped when daylight saving time begins. Choose a different time.",
    );
  }
  if (matches.length > 1) {
    throw new Error(
      "This Central time occurs twice when daylight saving time ends. Choose an unambiguous time or contact us for help.",
    );
  }
  const offsetMinutes = matches[0] / 60000;
  const absolute = Math.abs(offsetMinutes);
  const hours = String(Math.floor(absolute / 60)).padStart(2, "0");
  const minutes = String(absolute % 60).padStart(2, "0");
  return `${local}${offsetMinutes < 0 ? "-" : "+"}${hours}:${minutes}`;
}

export function formatEventTime(value, timeZone = EVENT_TIME_ZONE) {
  if (!value) return "Not provided";
  try {
    return new Intl.DateTimeFormat("en-US", {
      timeZone,
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
      timeZoneName: "short",
    }).format(new Date(value));
  } catch {
    return "Not provided";
  }
}
