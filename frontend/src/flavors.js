export const DEMO_FLAVORS = [
  "Mango Lime",
  "Strawberry Lime",
  "Mango Dragonfruit",
  "Strawberries and Cream",
  "Watermelon Strawberry and Kiwi",
];

export function flavorMixTotal(rows) {
  return rows.reduce((sum, row) => sum + (Number(row.quantity) || 0), 0);
}

export function flavorMixIssue(rows, quantity) {
  const selected = new Set();
  for (const [index, row] of rows.entries()) {
    if (!DEMO_FLAVORS.includes(row.flavor))
      return {
        index,
        field: "flavor",
        message: "Choose a flavor for each row.",
      };
    if (selected.has(row.flavor))
      return {
        index,
        field: "flavor",
        message: "Choose each flavor only once.",
      };
    selected.add(row.flavor);
    if (
      String(row.quantity).trim() === "" ||
      !Number.isInteger(Number(row.quantity)) ||
      Number(row.quantity) < 1 ||
      Number(row.quantity) > 100000
    )
      return {
        index,
        field: "quantity",
        message: "Enter a whole number of at least 1 for each selected flavor.",
      };
  }
  const total = flavorMixTotal(rows);
  if (rows.length && total !== Number(quantity))
    return {
      index: 0,
      field: "quantity",
      message: `Your flavor quantities must total ${quantity} paletas. You have ${total} selected.`,
    };
  return null;
}

export function validFlavorDraft(rows) {
  return (
    Array.isArray(rows) &&
    rows.length <= DEMO_FLAVORS.length &&
    new Set(rows.map((row) => row?.id)).size === rows.length &&
    rows.every(
      (row) =>
        row &&
        typeof row.id === "string" &&
        row.id.length > 0 &&
        row.id.length <= 64 &&
        DEMO_FLAVORS.includes(row.flavor) &&
        ["string", "number"].includes(typeof row.quantity) &&
        String(row.quantity).length <= 20,
    )
  );
}

export function formatFlavorRequests(catering) {
  return [
    ...(catering.flavor_allocations || []).map(
      (row) => `${row.flavor}: ${row.quantity}`,
    ),
    catering.flavor_requests,
  ]
    .filter(Boolean)
    .join(" · ");
}
