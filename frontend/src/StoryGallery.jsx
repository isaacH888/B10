import { useEffect, useRef, useState } from "react";
import outdoorCart from "./assets/story/audrey-outdoor-cart.jpg";
import eventCart from "./assets/story/audrey-event-cart.jpg";
import sharingPaletas from "./assets/story/audrey-sharing-paletas.jpg";
import servingPaletas from "./assets/story/audrey-serving-paletas.jpg";

const photos = [
  {
    src: outdoorCart,
    alt: "Audrey smiling behind the Popssibilities cart at an outdoor event",
  },
  {
    src: sharingPaletas,
    alt: "Audrey handing a guest a fruit paleta from her cart",
  },
  {
    src: eventCart,
    alt: "Audrey with her Popssibilities cart and colorful popsicle shirt",
  },
  {
    src: servingPaletas,
    alt: "Audrey opening her paleta cart to serve a guest",
  },
];

export default function StoryGallery() {
  const galleryRef = useRef(null);
  const [activePhoto, setActivePhoto] = useState(0);
  const [paused, setPaused] = useState(
    () => window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
  const [hovered, setHovered] = useState(false);
  const [inView, setInView] = useState(false);
  const [pageVisible, setPageVisible] = useState(!document.hidden);

  useEffect(() => {
    const observer = new IntersectionObserver(
      ([entry]) => setInView(entry.intersectionRatio >= 0.25),
      { threshold: 0.25 },
    );
    observer.observe(galleryRef.current);

    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const handleMotionChange = () => {
      if (motion.matches) setPaused(true);
    };
    const handleVisibility = () => setPageVisible(!document.hidden);
    motion.addEventListener("change", handleMotionChange);
    document.addEventListener("visibilitychange", handleVisibility);

    return () => {
      observer.disconnect();
      motion.removeEventListener("change", handleMotionChange);
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, []);

  useEffect(() => {
    if (paused || hovered || !inView || !pageVisible) return;
    const timer = window.setTimeout(
      () => setActivePhoto((current) => (current + 1) % photos.length),
      5500,
    );
    return () => window.clearTimeout(timer);
  }, [activePhoto, paused, hovered, inView, pageVisible]);

  function showPhoto(index) {
    setPaused(true);
    setActivePhoto((index + photos.length) % photos.length);
  }

  return (
    <div
      className="story-gallery"
      ref={galleryRef}
      role="region"
      aria-roledescription="carousel"
      aria-label="Moments with Audrey"
      onPointerEnter={(event) => {
        if (event.pointerType === "mouse") setHovered(true);
      }}
      onPointerLeave={(event) => {
        if (event.pointerType === "mouse") setHovered(false);
      }}
      onFocusCapture={(event) => {
        if (!event.target.closest("[data-rotation-control]")) setPaused(true);
      }}
    >
      <div
        className="story-gallery-photos"
        aria-live={paused ? "polite" : "off"}
      >
        {photos.map((photo, index) => (
          <div
            key={photo.src}
            className={`story-gallery-slide${index === activePhoto ? " is-active" : ""}`}
            role="group"
            aria-roledescription="slide"
            aria-label={`Photo ${index + 1} of ${photos.length}`}
            aria-hidden={index !== activePhoto}
          >
            <img
              src={photo.src}
              alt={photo.alt}
              loading="lazy"
              decoding="async"
            />
          </div>
        ))}
      </div>
      <div className="story-gallery-caption">
        <div>
          <div className="eyebrow">A LITTLE COLOR. A LOT OF HEART.</div>
          <p>Moments with Audrey</p>
        </div>
        <button
          type="button"
          className="story-gallery-button"
          data-rotation-control
          aria-label={paused ? "Play slideshow" : "Pause slideshow"}
          title={paused ? "Play slideshow" : "Pause slideshow"}
          onClick={() => setPaused((current) => !current)}
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            {paused ? (
              <path d="m9 5 10 7-10 7Z" />
            ) : (
              <path d="M7 5h3v14H7zm7 0h3v14h-3z" />
            )}
          </svg>
        </button>
      </div>
      <div className="story-gallery-controls">
        <button
          type="button"
          className="story-gallery-button"
          aria-label="Previous photo"
          onClick={() => showPhoto(activePhoto - 1)}
        >
          <span aria-hidden="true">←</span>
        </button>
        <div
          className="story-gallery-dots"
          role="group"
          aria-label="Choose a photo"
        >
          {photos.map((photo, index) => (
            <button
              key={photo.src}
              type="button"
              aria-label={`Show photo ${index + 1}`}
              aria-current={index === activePhoto ? "true" : undefined}
              onClick={() => showPhoto(index)}
            >
              <span />
            </button>
          ))}
        </div>
        <button
          type="button"
          className="story-gallery-button"
          aria-label="Next photo"
          onClick={() => showPhoto(activePhoto + 1)}
        >
          <span aria-hidden="true">→</span>
        </button>
      </div>
    </div>
  );
}
