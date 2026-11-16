import { Link, NavLink, useLocation } from "react-router-dom";
import { useLayoutEffect, useRef } from "react";
import { useAuth } from "./auth/AuthContext.jsx";
import SocialLinks from "./SocialLinks.jsx";
import logo from "./assets/logo.png";
import { version } from "../package.json";
import "./public-chrome.css";

const siteCommit = typeof __SITE_COMMIT__ === "string" ? __SITE_COMMIT__ : null;

function SectionLink({ to, hash, children }) {
  const { pathname } = useLocation();
  function handleClick(e) {
    if (pathname === "/") {
      const section = document.getElementById(hash);
      if (section) {
        e.preventDefault();
        if (window.location.hash !== `#${hash}`) {
          window.history.pushState(null, "", `/#${hash}`);
        }
        const prefersReducedMotion =
          typeof window !== "undefined" &&
          window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        section.scrollIntoView({
          behavior: prefersReducedMotion ? "instant" : "smooth",
          block: "start",
        });
      }
    }
  }

  return (
    <Link to={to} onClick={handleClick}>
      {children}
    </Link>
  );
}

function SectionLinks() {
  return (
    <>
      <SectionLink to="/#paleta-life" hash="paleta-life">
        The Paleta Life
      </SectionLink>
      <SectionLink to="/#flavors" hash="flavors">
        Flavors
      </SectionLink>
      <SectionLink to="/#our-story" hash="our-story">
        Our Story
      </SectionLink>
      <NavLink to="/order" end aria-label="Catering order">
        Catering
      </NavLink>
    </>
  );
}

export function PublicHeader() {
  const { sessions } = useAuth();
  const { pathname } = useLocation();
  const header = useRef(null);

  function handleBrandClick(e) {
    if (pathname === "/") {
      e.preventDefault();
      if (window.location.hash) {
        window.history.pushState(null, "", "/");
      }
      const prefersReducedMotion =
        typeof window !== "undefined" &&
        window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      window.scrollTo({
        top: 0,
        left: 0,
        behavior: prefersReducedMotion ? "instant" : "smooth",
      });
    }
  }

  useLayoutEffect(() => {
    const element = header.current;
    const site = element?.closest(".public-site");
    if (!site) return;
    const resize = () =>
      site.style.setProperty(
        "--site-header-height",
        `${element.getBoundingClientRect().height}px`,
      );
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const signedIn = sessions.customer.status === "authenticated";
  return (
    <div className="public-chrome site-topbar" ref={header}>
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <div className="announcement" aria-label="Site announcement">
        MEXICAN PALETAS. ENDLESS POPSSIBILITIES.
      </div>
      <header className="site-header">
        <Link
          className="site-brand"
          to="/"
          aria-label="Popssibilities home"
          onClick={handleBrandClick}
        >
          <img src={logo} alt="Popssibilities" width="88" height="88" />
        </Link>
        <nav className="site-nav" aria-label="Main navigation">
          <SectionLinks />
        </nav>
        <Link className="site-signin" to={signedIn ? "/account" : "/login"}>
          {signedIn ? "My Account" : "Sign In"}
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="12" cy="8" r="4" />
            <path d="M4 22v-3a8 8 0 0 1 16 0v3" />
          </svg>
        </Link>
      </header>
    </div>
  );
}

export function PublicFooter() {
  return (
    <footer className="public-chrome site-footer">
      <div className="site-footer__inner">
        <div className="site-footer__brand">
          <img src={logo} alt="" width="48" height="48" />
          <span>POPSSIBILITIES</span>
        </div>
        <p className="site-footer__tagline">
          Mexican paletas. Endless Popssibilities.
        </p>
        <div className="site-footer__contact">
          <span>Houston, TX · Serving the Houston area</span>
          <a href="mailto:info@popssibilities.com">info@popssibilities.com</a>
          <a href="tel:+12812487514">281-248-7514</a>
        </div>
        <nav className="site-footer__links" aria-label="Footer navigation">
          <SectionLinks />
          <Link to="/admin/login">Owner Sign-In</Link>
        </nav>
        <SocialLinks />
        <p className="site-footer__copy">
          © {new Date().getFullYear()} Popssibilities. All rights reserved.
          <br />
          Version {version} ·{" "}
          <a href="https://github.com/isaacH888/B10/tree/main">main</a>
          {siteCommit && (
            <>
              {" · "}
              <a href={`https://github.com/isaacH888/B10/commit/${siteCommit}`}>
                {siteCommit.slice(0, 7)}
              </a>
            </>
          )}
        </p>
      </div>
    </footer>
  );
}
