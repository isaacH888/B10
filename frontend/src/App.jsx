import { useState } from "react";

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "");

// This temporary shell verifies connectivity; feature owners replace its content.
export default function App() {
  const [result, setResult] = useState("Not checked");
  const [checking, setChecking] = useState(false);

  async function checkConnection() {
    if (!apiBaseUrl) {
      setResult("Set VITE_API_BASE_URL in the frontend environment.");
      return;
    }
    setChecking(true);
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 10000);
    try {
      const options = { credentials: "include", signal: controller.signal };
      const live = await fetch(`${apiBaseUrl}/live`, options);
      if (!live.ok) throw new Error("Backend liveness check failed.");
      const readiness = await fetch(`${apiBaseUrl}/health`, options);
      const body = await readiness.json();
      if (readiness.status === 503 && body.data?.database === "unavailable") {
        setResult("Backend reachable. Database is unavailable or not configured.");
      } else if (readiness.ok && body.data?.database === "ok") {
        setResult("Backend reachable. Database connectivity verified.");
      } else {
        throw new Error("Backend readiness response did not match the contract.");
      }
    } catch (error) {
      setResult(error.name === "AbortError" ? "Connectivity check timed out." : error.message);
    } finally {
      clearTimeout(timer);
      setChecking(false);
    }
  }

  return (
    <main>
      <h1>Popssibilities - Development Shell</h1>
      <p>Shared scaffold for the development team. Customer and administrator features are pending.</p>
      <button type="button" onClick={checkConnection} disabled={checking}>
        {checking ? "Checking connection..." : "Check backend connection"}
      </button>
      <p role="status" aria-live="polite">{result}</p>
    </main>
  );
}
