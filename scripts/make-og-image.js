// Render the link-preview card (web/public/og.png) from HTML, with the dashboard's own type and
// colours, so a shared link looks like the product rather than a bare URL.
//
//   node scripts/make-og-image.js        # needs playwright; the PNG it writes is committed,
//                                        # so nobody has to run this to build or deploy the site
//
// Why HTML and a headless browser rather than an image editor: the card is then the same two
// typefaces and the same lime as the page, and changing the words is a one-line edit.
const path = require('path')
const fs = require('fs')

const OUT = path.join(__dirname, '..', 'web', 'public', 'og.png')
const SITE = process.env.ROOK_SITE || 'rook-keywarden.pages.dev'

const html = `<!doctype html><html><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;600;700&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>
  :root { --ink:#101010; --paper:#fbfaf7; --lime:#c8f24c; --line:#d9d6cd }
  * { box-sizing: border-box; margin: 0 }
  body { width: 1200px; height: 630px; background: var(--paper); color: var(--ink);
         font-family: "Space Grotesk", system-ui, sans-serif; padding: 64px 72px;
         display: flex; flex-direction: column; justify-content: space-between; gap: 18px }
  .brand { display: flex; align-items: center; gap: 14px; font-size: 34px; font-weight: 700 }
  .star { width: 34px; height: 34px }
  h1 { font-size: 76px; line-height: 1.02; letter-spacing: -0.025em; font-weight: 700; max-width: 17ch }
  p { font-size: 27px; line-height: 1.45; max-width: 46ch; opacity: .78; margin-top: 22px }
  .sectors { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 30px }
  .sectors span { border: 2px solid var(--ink); border-radius: 999px; padding: 7px 18px; font-size: 21px }
  .sectors span.on { background: var(--lime) }
  footer { display: flex; justify-content: space-between; align-items: center;
           font-family: "Space Mono", monospace; font-size: 21px; border-top: 2px solid var(--line);
           padding-top: 22px }
  mark { background: var(--lime); padding: 0 .1em }
</style></head><body>
  <div class="brand">
    <svg class="star" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0l2.4 9.6L24 12l-9.6 2.4L12 24l-2.4-9.6L0 12l9.6-2.4z"/></svg>
    Rook
  </div>
  <div>
    <h1>Start with a problem. <mark>Rook proves the fix.</mark></h1>
    <p>Staff report it. Rook investigates across every system it touches, waits for a person
      before anything reaches someone outside, then checks the result and shows the evidence.</p>
    <div class="sectors">
      <span class="on">Healthcare</span><span>IT &amp; security</span><span>Engineering</span><span>Sport &amp; clubs</span>
    </div>
  </div>
  <footer><span>${SITE}</span><span>built by Keywarden &middot; neatHack 2026</span></footer>
</body></html>`

;(async () => {
  const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')
  const b = await chromium.launch()
  const p = await (await b.newContext({ viewport: { width: 1200, height: 630 }, deviceScaleFactor: 1 })).newPage()
  await p.setContent(html, { waitUntil: 'networkidle' })
  await p.waitForTimeout(600)                       // let the webfonts land before the shot
  fs.mkdirSync(path.dirname(OUT), { recursive: true })
  await p.screenshot({ path: OUT })
  await b.close()
  console.log('wrote', OUT)
})()
