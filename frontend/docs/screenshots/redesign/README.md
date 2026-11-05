# Redesign screenshots (2026-11-04)

`before/` is the UI as found, `after/` the redesign. Both sets come from `bun tools/capture-screens.ts` against
`vite preview` of a production build, with `/v1` on a disposable backend instance (empty database, placeholder AI
key). Each set has the same 44 file names: `<viewport>-<theme>-<language>-<page>.png` for desktop 1440 px and mobile
390 px, dark zh-TW and light English, every page, locked and unlocked.

The before set was taken with Playwright's full-page capture, which stops the fixed sidebar at 900 px. The after set
grows the viewport to the page height instead, because the full-page capture drew the price chart past its panel in
the image while the page itself measured correctly.

The four `admin` shots in `after/` were taken again after the settings editor replaced the settings form, with one
save made. The editor's height follows the viewport, so a grown viewport grows the editor with it. These four use the
full-page capture at 1440 × 900 and 390 × 844, as `tools/capture-screens.ts` now does for a page that never fits a
grown viewport. On the phone, the bottom bar stays where the screen ended.
