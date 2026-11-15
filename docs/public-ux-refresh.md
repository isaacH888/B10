# Public UI refresh and startup intro

This pass refines the existing homepage and catering page. It retains the current
palette, typography, navigation, section order, sharper responsive paleta images,
and the quote/authentication/order flows. Existing event photographs now fill the
three homepage feature cards and the closing catering quote area. Small, authored
SVG illustrations provide fruit, paleta and catering-cart accents.

The final review used the project's Impeccable skill at
`.github/skills/impeccable/SKILL.md`, including its context, polish, motion and craft
guidance. `.impeccable/config.local.json` is hook consent/configuration, rather than
the design instructions themselves. Existing code and the approved user plan were
the design authority; this pass did not create a new brand or product brief.

## Opening animation

- On the first full entry to `/` or `/order` in a tab, an illustrated strawberry
  popsicle loses five cumulative bites at 320-millisecond intervals. Only the
  wooden stick remains at 1.6 seconds, followed by a 200-millisecond hold and
  200-millisecond fade.
- `frontend/index.html` contains the small inline SVG, critical styles and startup
  controller so it can render before React. `frontend/src/main.jsx` signals React
  readiness. The app initializes behind the intro; backend/authentication responses
  and all-image completion are not prerequisites for dismissing it.
- Skip and Escape work immediately, including before the bundle finishes loading.
  Keyboard focus stays within the introductory dialog until dismissal; scrolling
  and the page's interactive state are restored afterward.
- Session storage key `popssibilities:intro:v1` records `seen`. Reloads and internal
  navigation do not replay the intro. Hash links, account, confirmation and sign-in
  pages bypass it. Blocked storage does not prevent the page from working.
- Reduced motion uses a static illustration and no minimum delay. Once reduced
  motion is requested during an intro, it remains reduced for that intro.
- A four-second startup watchdog survives Skip and previously seen sessions on
  eligible routes. If React has not mounted, it unlocks the page and exposes a
  reload action. A late React mount hides that fallback. With JavaScript disabled,
  the page supplies a short explanation and the existing contact phone number.

To replay the intro during local review, use a fresh tab with no copied session
storage, or remove this key in the browser console and reload:

```js
sessionStorage.removeItem("popssibilities:intro:v1");
location.reload();
```

## Verification

The browser tests in `frontend/tests/startup-intro.spec.js` cover all bite stages,
bare-stick completion, Skip/Escape, focus cleanup, once-per-tab behavior, excluded
routes, unavailable storage, reduced motion, slow bundle delivery, and recovery
after skipping a failed startup. Existing public-site and catering tests cover the
unchanged navigation and quote flow. Manual render checks cover 320, 375, 768,
1024 and 1440 pixels, loaded imagery, photo crops and readable text. Small red
text uses a darker brand shade to meet normal-text contrast on pink and cream.

No runtime dependencies, backend/API changes, database migrations or AWS changes
are needed. Source changes remain uncommitted and undeployed for review.
