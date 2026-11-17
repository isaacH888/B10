export function squareDestination(value, environment) {
  const destination = new URL(value);
  const hosts =
    environment === "sandbox"
      ? ["sandbox.square.link", "connect.squareupsandbox.com"]
      : environment === "production"
        ? ["square.link", "checkout.square.site"]
        : [];
  if (
    destination.protocol !== "https:" ||
    destination.username ||
    destination.password ||
    !hosts.includes(destination.hostname) ||
    (destination.port && destination.port !== "443")
  )
    throw new Error("invalid_destination");
  return destination.href;
}
