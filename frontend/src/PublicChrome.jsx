import { Link, NavLink } from "react-router-dom";
import { useAuth } from "./auth/AuthContext.jsx";
import SocialLinks from "./SocialLinks.jsx";
import logo from "./assets/logo.png";
import "./public-chrome.css";

function SectionLinks() {
  return (
    <>
      <Link to="/#paleta-life">The Paleta Life</Link>
      <Link to="/#flavors">Flavors</Link>
      <Link to="/#our-story">Our Story</Link>
      <NavLink to="/order" end aria-label="Catering order">
        Catering
      </NavLink>
    </>
  );
}

export function PublicHeader() {
  const { sessions } = useAuth();
  const signedIn = sessions.customer.status === "authenticated";
  return (
    <div className="public-chrome site-topbar">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <div className="announcement" aria-label="Site announcement">
        MEXICAN PALETAS. ENDLESS POPSSIBILITIES.
      </div>
      <header className="site-header">
        <Link className="site-brand" to="/" aria-label="Popssibilities home">
          <img src={logo} alt="Popssibilities" width="64" height="64" />
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
          <span>Stafford, TX · Serving the Houston area</span>
          <a href="mailto:info@popssibilities.com">info@popssibilities.com</a>
          <a href="tel:+12812487514">281-248-7514</a>
        </div>
        <nav className="site-footer__links" aria-label="Footer navigation">
          <SectionLinks />
          <Link to="/admin/login">Team Sign-In</Link>
        </nav>
        <SocialLinks />
        <p className="site-footer__copy">
          © {new Date().getFullYear()} Popssibilities. All rights reserved.
        </p>
      </div>
    </footer>
  );
}
