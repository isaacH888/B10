import { useLayoutEffect } from "react";
import { useLocation } from "react-router-dom";

export function RouteScroll() {
  const { pathname, hash, key } = useLocation();

  useLayoutEffect(() => {
    const previous = window.history.scrollRestoration;
    window.history.scrollRestoration = "manual";
    return () => {
      window.history.scrollRestoration = previous;
    };
  }, []);

  useLayoutEffect(() => {
    if (hash) {
      try {
        const section = document.getElementById(
          decodeURIComponent(hash.slice(1)),
        );
        if (section) {
          section.scrollIntoView({ behavior: "instant", block: "start" });
          return;
        }
      } catch {
        // A malformed or unknown anchor still opens at the top of the page.
      }
    }
    window.scrollTo({ top: 0, left: 0, behavior: "instant" });
  }, [pathname, hash, key]);

  return null;
}
