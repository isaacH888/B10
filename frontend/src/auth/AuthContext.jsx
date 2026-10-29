import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { ApiError, apiRequest, navigateToProvider } from "./api.js";

const AuthContext = createContext(null);
const signedOut = () => ({ status: "signed-out", data: null, error: null });
const loading = () => ({ status: "loading", data: null, error: null });
const identityKey = { customer: "customer", admin: "administrator" };

export function sessionDeadline(data) {
  return Math.min(
    Date.parse(data?.expires_at),
    Date.parse(data?.idle_expires_at),
  );
}

function validSession(area, data) {
  const identity = data?.[identityKey[area]];
  return (
    identity &&
    typeof identity.id === "string" &&
    identity.id.length > 0 &&
    typeof identity.email === "string" &&
    (identity.name == null || typeof identity.name === "string") &&
    typeof data.csrf_token === "string" &&
    data.csrf_token.length > 0 &&
    Number.isFinite(sessionDeadline(data)) &&
    (area !== "admin" ||
      (["owner", "staff"].includes(identity.role) &&
        Array.isArray(identity.permissions) &&
        identity.permissions.every(
          (permission) => typeof permission === "string",
        )))
  );
}

export function AuthProvider({ children }) {
  const [sessions, setSessions] = useState({
    customer: loading(),
    admin: loading(),
  });
  const versions = useRef({ customer: 0, admin: 0 });
  const pending = useRef({});
  const logoutTokens = useRef({});

  const refresh = useCallback((area, { force = false } = {}) => {
    if (force) {
      versions.current[area] += 1;
      delete pending.current[area];
    }
    if (pending.current[area]) return pending.current[area];
    const version = versions.current[area];
    const request = (async () => {
      let next;
      try {
        const data = await apiRequest(`/${area}/session`);
        if (!validSession(area, data))
          throw new ApiError(502, "invalid_response");
        next =
          sessionDeadline(data) <= Date.now()
            ? { ...signedOut(), expired: true }
            : { status: "authenticated", data, error: null };
      } catch (error) {
        next =
          error.status === 401
            ? { ...signedOut(), expired: error.code === "session_expired" }
            : { status: "error", data: null, error };
      }
      if (version === versions.current[area]) {
        if (next.status === "authenticated")
          logoutTokens.current[area] = next.data.csrf_token;
        else if (next.status === "signed-out")
          delete logoutTokens.current[area];
        else if (next.status === "error")
          next.canLogout = Boolean(logoutTokens.current[area]);
        setSessions((current) => ({ ...current, [area]: next }));
      }
      return next;
    })();
    pending.current[area] = request;
    request.finally(() => {
      if (pending.current[area] === request) delete pending.current[area];
    });
    return request;
  }, []);

  const expire = useCallback((area) => {
    versions.current[area] += 1;
    delete logoutTokens.current[area];
    setSessions((current) => ({
      ...current,
      [area]: { ...signedOut(), expired: true },
    }));
  }, []);

  const login = useCallback(async (area, provider = "password") => {
    const data = await apiRequest(`/${area}/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider }),
    });
    navigateToProvider(data.authorization_url);
  }, []);

  const logout = useCallback(async (area, csrfToken) => {
    const token = csrfToken || logoutTokens.current[area];
    logoutTokens.current[area] = token;
    versions.current[area] += 1;
    setSessions((current) => ({ ...current, [area]: signedOut() }));
    try {
      const data = await apiRequest(`/${area}/session`, {
        method: "DELETE",
        headers: { "X-CSRF-Token": token },
      });
      navigateToProvider(data.logout_url);
      delete logoutTokens.current[area];
    } catch (error) {
      // A 401 confirms there is no longer an application session.
      if (error.status === 401) delete logoutTokens.current[area];
      else
        setSessions((current) => ({
          ...current,
          [area]: { ...signedOut(), logoutPending: true, error },
        }));
    }
  }, []);

  useEffect(() => {
    refresh("customer");
    refresh("admin");
  }, [refresh]);
  const value = useMemo(
    () => ({ sessions, refresh, expire, login, logout }),
    [sessions, refresh, expire, login, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth requires AuthProvider");
  return value;
}
