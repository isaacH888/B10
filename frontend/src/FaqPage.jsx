import { Link } from "react-router-dom";
import paletaIllustration from "./assets/illustrations/paleta.svg";
import "./faq.css";

const questions = [
  {
    question: "What is the minimum order for catering?",
    answer:
      "Our minimum catering order is 50 popsicles. Orders of 50 or more popsicles qualify for catering services.",
  },
  {
    question: "How far in advance should I place my order?",
    answer:
      "We recommend placing custom catering orders at least two weeks in advance to ensure availability and allow time for preparation.",
  },
  {
    question: "Can I request custom flavors?",
    answer:
      "Yes! Customers can request custom flavors. We’ll work with you to come up with flavor ideas, too.",
  },
  {
    question:
      "What happens if I place an order less than two weeks before my event?",
    answer:
      "Orders placed within two weeks of the event may be fulfilled using available flavors and inventory rather than custom-made selections.",
  },
  {
    question: "Do you offer delivery?",
    answer:
      "Yes! Delivery is available throughout the Houston area. Delivery fees typically range from $25–$75, depending on location.",
  },
  {
    question: "What is included with full service catering?",
    answer:
      "Full service catering includes event setup, up to two hours of serving, and post-event breakdown. A labor fee applies for full service events.",
  },
  {
    question: "Do you serve events outside of Houston?",
    answer: (
      <>
        Yes! Events outside the immediate Houston area may be accommodated.
        Reach out to us via <a href="mailto:info@popssibilities.com">email</a>{" "}
        and we’ll work with you!
      </>
    ),
  },
];

export function FaqPage() {
  return (
    <div className="faq-page">
      <Link className="faq-page__back" to="/order">
        <span aria-hidden="true">←</span> Back to catering
      </Link>
      <header className="faq-page__intro">
        <p className="faq-page__eyebrow">THE SCOOP BEFORE YOUR EVENT</p>
        <h1>CATERING FAQs.</h1>
        <p className="faq-page__description">
          Planning a little joy? Here’s what to know about orders, flavors,
          delivery, and full service.
        </p>
        <img
          className="faq-page__art"
          src={paletaIllustration}
          alt=""
          width="148"
          height="148"
          aria-hidden="true"
        />
      </header>
      <div className="faq-page__layout">
        <section
          className="faq-list"
          aria-label="Catering questions and answers"
        >
          {questions.map(({ question, answer }, index) => (
            <details key={question} className="faq-item" open={index === 0}>
              <summary>
                <span className="faq-item__number" aria-hidden="true">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <span className="faq-item__question">{question}</span>
                <span className="faq-item__toggle" aria-hidden="true" />
              </summary>
              <div className="faq-item__answer">
                <p>{answer}</p>
              </div>
            </details>
          ))}
        </section>
        <aside className="faq-contact" aria-labelledby="faq-contact-heading">
          <p className="faq-page__eyebrow">STILL HAVE A QUESTION?</p>
          <h2 id="faq-contact-heading">LET’S TALK POPS.</h2>
          <p>
            Every event is a little different. Tell us what you have in mind and
            we’ll help with the details.
          </p>
          <a
            className="faq-contact__email"
            href="mailto:info@popssibilities.com"
          >
            info@popssibilities.com
          </a>
          <Link
            className="faq-contact__cta"
            to="/order"
            state={{ openQuote: true }}
          >
            Request a quote <span aria-hidden="true">↗</span>
          </Link>
        </aside>
      </div>
    </div>
  );
}
