import "./social-links.css";

export default function SocialLinks() {
  return (
    <div className="social-links">
      <p className="social-links__label">Follow Our Socials!</p>
      <nav className="social-links__icons" aria-label="Social media">
        <a
          className="social-links__link"
          href="https://www.instagram.com/popssibilities_llc/"
          target="_blank"
          rel="noopener noreferrer"
          aria-label="Popssibilities on Instagram (opens in a new tab)"
          title="Instagram"
        >
          <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <rect x="3" y="3" width="18" height="18" rx="5" />
            <circle cx="12" cy="12" r="4" />
            <circle
              className="social-links__instagram-dot"
              cx="17.5"
              cy="6.5"
              r="1"
            />
          </svg>
        </a>
        <a
          className="social-links__link"
          href="https://www.facebook.com/popssibilitiesllc/"
          target="_blank"
          rel="noopener noreferrer"
          aria-label="Popssibilities on Facebook (opens in a new tab)"
          title="Facebook"
        >
          <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <path d="M14 22v-9h3l.5-4H14V6.5c0-1.2.4-2 2-2h2V1.2C17.7 1.1 16.6 1 15.3 1 12.6 1 11 2.6 11 5.6V9H8v4h3v9z" />
          </svg>
        </a>
      </nav>
    </div>
  );
}
