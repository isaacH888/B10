import { Link, useLocation } from "react-router-dom";
import { useAuth } from "./auth/AuthContext.jsx";
import StoryGallery from "./StoryGallery.jsx";
import SocialLinks from "./SocialLinks.jsx";
import FlavorMenu from "./FlavorMenu.jsx";
import logo from "./assets/aneena-logo.png";
import paletas from "./assets/aneena-paletas-hero.png";
import "./public-site.css";

const burstPoints = Array.from({ length: 24 }, (_, index) => {
  const angle = (index * Math.PI) / 12;
  const radius = index % 2 === 0 ? 48 : 27;
  return `${50 + radius * Math.sin(angle)},${50 - radius * Math.cos(angle)}`;
}).join(" ");

function Sunburst() {
  return (
    <svg width="1em" height="1em" viewBox="0 0 100 100" aria-hidden="true">
      <polygon points={burstPoints} fill="currentColor" />
    </svg>
  );
}

function PublicHeader() {
  const { sessions } = useAuth();
  const signedIn = sessions.customer.status === "authenticated";
  return (
    <div className="public-chrome">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <div className="announcement">
        MEXICAN PALETAS. ENDLESS POPSSIBILITIES.
      </div>
      <header className="site-header">
        <Link to="/" aria-label="Popssibilities home">
          <img className="nav-logo" src={logo} alt="Popssibilities logo" />
        </Link>
        <nav aria-label="Main navigation">
          <a href="/#paleta-life">The paleta life</a>
          <a href="/#flavors">Flavors</a>
          <a href="/#our-story">Our story</a>
          <Link className="pill red" to="/order">
            Catering order <span aria-hidden="true">↗</span>
          </Link>
        </nav>
        <Link className="signin" to={signedIn ? "/account" : "/login"}>
          {signedIn ? "My account" : "Sign in"}
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="12" cy="8" r="4" />
            <path d="M4 22v-3a8 8 0 0 1 16 0v3" />
          </svg>
        </Link>
      </header>
    </div>
  );
}

function PublicFooter() {
  return (
    <div className="public-chrome">
      <footer>
        <div className="footer-top">
          <span>MEXICAN PALETAS · STAFFORD, TX</span>
          <nav aria-label="Footer navigation">
            <a href="/#paleta-life">The paleta life</a>
            <a href="/#flavors">Flavors</a>
            <a href="/#our-story">Our story</a>
            <Link to="/order">Catering</Link>
            <Link to="/admin/login">Team sign-in</Link>
          </nav>
        </div>
        <div className="footer-brand">POPSSIBILITIES</div>
        <SocialLinks />
        <div className="footer-bottom">
          <span>© {new Date().getFullYear()} Popssibilities.</span>
          <span>Endless Popssibilities.</span>
        </div>
      </footer>
    </div>
  );
}

export function PublicLayout({ children }) {
  const { pathname } = useLocation();
  const contentClass =
    pathname === "/"
      ? "public-home"
      : pathname === "/order"
        ? "public-order"
        : "public-content";
  return (
    <div className="public-site">
      <PublicHeader />
      <main id="main-content" className={contentClass}>
        {children}
      </main>
      <PublicFooter />
    </div>
  );
}

export function PublicHome() {
  return (
    <>
      <section className="hero" aria-labelledby="home-heading">
        <div className="hero-copy">
          <div className="eyebrow">A LITTLE COLD. A WHOLE LOT OF HAPPY.</div>
          <h1 id="home-heading">
            BIG JOY.
            <br />
            ON A STICK.
          </h1>
          <p>
            Meet your next happy little moment.
            <br />
            Mexican paletas. Endless Popssibilities.
          </p>
          <div className="hero-actions">
            <Link className="pill red" to="/order">
              Bring pops to your event <span aria-hidden="true">↗</span>
            </Link>
            <a className="text-link" href="#paleta-life">
              Discover the paleta life <span aria-hidden="true">↓</span>
            </a>
          </div>
          <small>A little taste of Stafford, Texas.</small>
        </div>
        <div className="hero-art">
          <img
            src={paletas}
            alt="Three colorful paletas"
            fetchPriority="high"
          />
        </div>
      </section>
      <div className="ticker" aria-hidden="true">
        <span>MEXICAN PALETAS</span>
        <b>
          <Sunburst />
        </b>
        <span>MEXICAN PALETAS</span>
        <b>
          <Sunburst />
        </b>
        <span>MEXICAN PALETAS</span>
        <b>
          <Sunburst />
        </b>
        <span>ENDLESS JOY</span>
      </div>
      <section
        id="paleta-life"
        className="life cream"
        aria-labelledby="life-heading"
      >
        <div className="section-heading">
          <div>
            <div className="eyebrow red-text">THE PALETA LIFE</div>
            <h2 id="life-heading">
              LITTLE MOMENTS.
              <br />
              BIG POP ENERGY.
            </h2>
          </div>
          <p>
            For the sunshine, the catch-ups,
            <br />
            and the just-because days.
          </p>
        </div>
        <div className="features">
          <article className="feature yellow">
            <span className="burst" aria-hidden="true">
              <Sunburst />
            </span>
            <h3>
              SUN OUT.
              <br />
              POPS OUT.
            </h3>
            <small>A little cool for those big Texas days.</small>
          </article>
          <article className="feature pink">
            <span className="burst" aria-hidden="true">
              <Sunburst />
            </span>
            <h3>
              GOOD COMPANY.
              <br />
              GREAT POPS.
            </h3>
            <small>The sweetest part? Sharing the moment.</small>
          </article>
          <article className="feature blue">
            <span className="burst" aria-hidden="true">
              <Sunburst />
            </span>
            <h3>
              JUST BECAUSE
              <br />
              IS A REASON.
            </h3>
            <small>Make an ordinary day a little more colorful.</small>
          </article>
        </div>
        <FlavorMenu />
        <section
          id="our-story"
          className="story"
          aria-labelledby="story-heading"
        >
          <StoryGallery />
          <div className="story-copy">
            <div className="eyebrow red-text">HELLO FROM STAFFORD, TEXAS</div>
            <h2 id="story-heading">
              MEXICAN SOUL.
              <br />
              TEXAS HEART.
            </h2>
            <p>
              <strong>Hi, I’m Audrey, the owner of Popssibilities!</strong>
            </p>
            <p>
              After years of working in the corporate world, I wanted a space to
              be creative and make something of my own. I didn’t know exactly
              what that would look like until a trip to Bolivia, where I tried
              traditional Latin American paletas. Something as simple as a
              frozen treat inspired me to explore a whole new direction.
            </p>
            <p>
              That curiosity took me to Los Angeles, where I had the opportunity
              to learn the art of paleta-making from a renowned paleta master.
              Little by little, an idea became something I could actually bring
              to life. In 2020, I took the leap and started Popssibilities,
              creating delicious popsicles made with all-natural ingredients and
              fresh fruit. These are a healthier, more refreshing alternative to
              traditional frozen treats.
            </p>
            <p>
              Paleta means “popsicle” in Spanish, but at Popssibilities, it
              represents so much more. Inspired by traditional Latin American
              flavors and tastes from around the world, we love exploring unique
              flavor combinations and bringing them to life. Every paleta is an
              opportunity to experience something new, one delicious bite at a
              time!
            </p>
            <Link className="pill outline" to="/order">
              Plan a little joy <span aria-hidden="true">↗</span>
            </Link>
          </div>
        </section>
      </section>
    </>
  );
}

export function CustomerSignInLayout({ children }) {
  return (
    <div className="customer-signin">
      <main id="main-content" className="auth-body">
        <div className="auth-shell">
          <div className="auth-stripe" />
          <div className="auth-columns">
            <div className="auth-visual">
              <Link to="/" className="back-home">
                ← Back to homepage
              </Link>
              <div className="auth-image">
                <img src={paletas} alt="Popssibilities paletas" />
              </div>
            </div>
            <div className="auth-panel">
              <div className="welcome">BIENVENIDO!</div>
              <div className="sun" aria-hidden="true">
                <Sunburst />
              </div>
              <div className="auth-card">{children}</div>
              <Link className="team-signin" to="/admin/login">
                Team sign-in
              </Link>
            </div>
          </div>
          <div className="auth-stripe" />
        </div>
      </main>
    </div>
  );
}
