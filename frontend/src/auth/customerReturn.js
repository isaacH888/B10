const key = "popssibilities.customer-return";
export const quoteReturn = "/order?quote=1";

export function rememberCustomerReturn(destination) {
  try {
    if (destination === quoteReturn) sessionStorage.setItem(key, destination);
    else sessionStorage.removeItem(key);
  } catch {
    // Sign-in remains available when browser storage is blocked.
  }
}

export function readCustomerReturn() {
  try {
    const destination = sessionStorage.getItem(key);
    return destination === quoteReturn ? destination : null;
  } catch {
    return null;
  }
}
