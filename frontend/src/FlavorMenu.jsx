import { Link } from "react-router-dom";
import { DEMO_FLAVORS } from "./flavors.js";
import paletas from "./assets/paletas-flavors.webp";
import paletasSmall from "./assets/paletas-flavors-640.webp";
import paletaIllustration from "./assets/illustrations/paleta.svg";
import "./flavors.css";

export default function FlavorMenu() {
  return (
    <section
      id="flavors"
      className="flavor-menu"
      aria-labelledby="flavor-menu-heading"
    >
      <div className="flavor-menu__photo">
        <img
          className="flavor-menu__paletas"
          src={paletas}
          srcSet={`${paletasSmall} 640w, ${paletas} 1086w`}
          sizes="(max-width: 800px) 360px, (min-width: 1280px) 520px, 40vw"
          alt="Three colorful Popssibilities paletas"
          loading="lazy"
          width="1086"
          height="1448"
        />
        <img
          className="flavor-menu__accent"
          src={paletaIllustration}
          alt=""
          aria-hidden="true"
          loading="lazy"
          width="128"
          height="128"
        />
      </div>
      <div className="flavor-menu__copy">
        <div className="eyebrow red-text">A TASTE OF THE POPSSIBILITIES</div>
        <h2 id="flavor-menu-heading">
          MEET A FEW
          <br />
          FAVORITES.
        </h2>
        <p>
          Fresh fruit, playful combinations, and a little something for
          everyone.
        </p>
        <ul className="flavor-menu__list" aria-label="Sample flavors">
          {DEMO_FLAVORS.map((flavor, index) => (
            <li key={flavor}>
              <span aria-hidden="true">0{index + 1}</span>
              {flavor}
            </li>
          ))}
        </ul>
        <p className="flavor-menu__availability">
          A few sample flavors to inspire your mix. Flavors vary by batch;
          Audrey will confirm availability for your event.
        </p>
        <Link className="pill red" to="/order">
          Build your catering mix <span aria-hidden="true">↗</span>
        </Link>
      </div>
    </section>
  );
}
