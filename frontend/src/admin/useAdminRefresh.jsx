import { useCallback, useEffect, useRef, useState } from "react";
import "./admin-refresh.css";

// Reads only. Callers keep their drafts/selection during background refreshes
// and return false on failed loads so stale data is never marked as fresh.
export function useAdminRefresh(
  load,
  { intervalMs = 60000, debounceMs = 0 } = {},
) {
  const [refreshing, setRefreshing] = useState(false);
  const [updatedAt, setUpdatedAt] = useState(null);
  const [refreshFailed, setRefreshFailed] = useState(false);
  const runner = useRef(null);

  useEffect(() => {
    let active = true;
    let pending = false;
    let lastCompleted = 0;
    let initial;
    async function run({ background = false } = {}) {
      if (!active || pending) return;
      clearTimeout(initial);
      pending = true;
      setRefreshing(true);
      try {
        const result = await load({ background });
        if (active) {
          setRefreshFailed(result === false);
          if (result !== false) setUpdatedAt(new Date());
        }
      } catch {
        if (active) setRefreshFailed(true);
      } finally {
        pending = false;
        lastCompleted = Date.now();
        if (active) setRefreshing(false);
      }
    }
    runner.current = run;
    initial = setTimeout(() => run(), debounceMs);
    const visibleRefresh = () => {
      if (
        document.visibilityState === "visible" &&
        Date.now() - lastCompleted > 1000
      ) {
        run({ background: true });
      }
    };
    const timer = setInterval(visibleRefresh, intervalMs);
    document.addEventListener("visibilitychange", visibleRefresh);
    window.addEventListener("focus", visibleRefresh);
    return () => {
      active = false;
      clearTimeout(initial);
      clearInterval(timer);
      document.removeEventListener("visibilitychange", visibleRefresh);
      window.removeEventListener("focus", visibleRefresh);
      if (runner.current === run) runner.current = null;
    };
  }, [load, intervalMs, debounceMs]);

  const refresh = useCallback(() => runner.current?.(), []);
  return { refresh, refreshing, updatedAt, refreshFailed };
}

export function AdminRefreshStatus({
  refresh,
  refreshing,
  updatedAt,
  refreshFailed = false,
}) {
  return (
    <div className="adm-refresh">
      <p role="status" className="adm-refresh__status">
        {refreshFailed ? (
          <>
            Refresh failed.{" "}
            {updatedAt ? (
              <>
                Last successful update{" "}
                <time dateTime={updatedAt.toISOString()}>
                  {updatedAt.toLocaleTimeString("en-US", {
                    timeZone: "America/Chicago",
                    hour: "numeric",
                    minute: "2-digit",
                  })}
                </time>{" "}
                Central.
              </>
            ) : (
              "Try again."
            )}
          </>
        ) : updatedAt ? (
          <>
            Updated{" "}
            <time dateTime={updatedAt.toISOString()}>
              {updatedAt.toLocaleTimeString("en-US", {
                timeZone: "America/Chicago",
                hour: "numeric",
                minute: "2-digit",
              })}
            </time>{" "}
            Central
          </>
        ) : (
          "Loading latest data…"
        )}
      </p>
      <button
        type="button"
        className="adm-btn adm-btn--outline"
        onClick={refresh}
        disabled={refreshing}
      >
        {refreshing ? "Refreshing…" : "Refresh data"}
      </button>
    </div>
  );
}
