import { StrictMode, useEffect } from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import "./shell.css";

function StartupReady() {
  useEffect(() => {
    const fallback = document.getElementById("startup-fallback");
    if (fallback) fallback.hidden = true;
    window.dispatchEvent(new Event("popssibilities:app-ready"));
  }, []);
  return null;
}

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <App />
    <StartupReady />
  </StrictMode>,
);
