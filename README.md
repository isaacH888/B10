# Popssibilities desktop frontend

## Open in VS Code
1. Extract the ZIP.
2. Open the `popssibilities-site` folder in VS Code.
3. Open `index.html` in your browser, or use the VS Code Live Server extension.
4. Click **Sign in** to visit the login page; links switch to Create Account and Reset Password.

## Files
- `index.html` — scrolling homepage
- `auth.html` — login, registration, password reset
- `styles.css` — shared styling
- `script.js` — homepage behavior
- `auth.js` — authentication screen behavior
- `assets/` — images

## Backend integration later
- Replace the demo submit handler in `auth.js` with `fetch()` requests to your C# API endpoints.
- Do not store passwords in frontend JavaScript or browser storage.
- Replace the newsletter demo handler in `script.js` with an API request.

## Design note
The provided exports contain a complete 1440px desktop screenshot and a logo, but not a standalone transparent image of the three paletas. `assets/paletas-hero.png` is a crop from the Figma screenshot, so it will look best on the matching pink background. Replace it with your transparent paleta PNG when available for a closer match. The font is approximated using Anton and DM Sans; swap in the exact Figma fonts if different.
