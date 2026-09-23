# Fonts

`space-mono-latin-400-normal.woff2` / `-700-normal.woff2` — Space Mono,
SIL Open Font License, Latin subset. Extracted from the `@fontsource/space-mono@5.3.0`
npm package (itself built from Google Fonts) rather than imported at
runtime, so the app self-hosts real files at a stable path instead of a
build-hashed one — see `src/styles.css` for the `@font-face` rules and
`index.html` for the matching `<link rel="preload">`.

**Aeonik is not here.** It's a commercial face (CoType) and this repo has
no licensed files — see `docs/implementation-plan.md` Appendix F's own
"Licensing is an action, not an assumption." `styles.css` defines the
`@font-face` blocks ready to receive real Aeonik Regular/Medium woff2
files under this same directory (`aeonik-400.woff2`, `aeonik-500.woff2`)
once a license is confirmed; until then the app renders the spec's own
fallback stack (Arial, sans-serif).
