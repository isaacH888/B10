import { Link } from "react-router-dom";
import { DEMO_FLAVORS } from "./flavors.js";
import paletas from "./assets/paletas-flavor-preview.png";
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
          src={paletas}
          alt="Three colorful Popssibilities paletas"
          loading="lazy"
          width="429"
          height="581"
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
