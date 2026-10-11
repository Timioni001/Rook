// Render the build-in-public post image (docs/images/post-card.png) at 1600x900.
//
//   node scripts/make-post-image.js
//
// Same technique as the link-preview card: lay it out in HTML with the dashboard's own type and
// colours, screenshot it headlessly. The right-hand panel is a real screenshot of the product,
// embedded from docs/images, so the picture is the thing itself rather than a mockup of it.
const fs = require('fs')
const path = require('path')

const IMAGES = path.join(__dirname, '..', 'docs', 'images')
const OUT = path.join(IMAGES, 'post-card.png')
const SHOT = process.env.ROOK_POST_SHOT || 'run-story.png'
const SITE = process.env.ROOK_SITE || 'rook-keywarden.pages.dev'

const shot = 'data:image/png;base64,' + fs.readFileSync(path.join(IMAGES, SHOT)).toString('base64')

const html = `<!doctype html><html><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>
  :root { --ink:#101010; --paper:#fbfaf7; --lime:#c8f24c; --line:#d9d6cd; --muted:#5c5a54 }
  * { box-sizing: border-box; margin: 0 }
  body { width: 1600px; height: 900px; background: var(--paper); color: var(--ink);
         font-family: "Space Grotesk", system-ui, sans-serif; padding: 56px 60px 48px;
         display: grid; grid-template-rows: auto 1fr auto; gap: 30px }
  header { display: flex; align-items: center; justify-content: space-between }
  .brand { display: flex; align-items: center; gap: 13px; font-size: 31px; font-weight: 700 }
  .brand svg { width: 31px; height: 31px }
  .tag { font-family: "Space Mono", monospace; font-size: 19px; color: var(--muted) }
  main { display: grid; grid-template-columns: 1fr 1.02fr; gap: 54px; align-items: center }
  h1 { font-size: 61px; line-height: 1.04; letter-spacing: -0.025em; font-weight: 700 }
  h1 mark { background: var(--lime); padding: 0 .08em }
  .lead { font-size: 25px; line-height: 1.45; color: #2b2a27; margin-top: 24px }
  /* The panel is taller than the card, so it is cropped on purpose and faded at the cut: the
     first lines stay at a readable size, and the fade says there is more of it. */
  .shot { position: relative; border: 3px solid var(--ink); border-radius: 18px; overflow: hidden;
          background: #fff; box-shadow: 14px 14px 0 var(--lime); height: 470px }
  .shot img { width: 100%; display: block; margin-top: -4px }
  .shot::after { content: ''; position: absolute; left: 0; right: 0; bottom: 0; height: 110px;
                 background: linear-gradient(rgba(255,255,255,0), #fff 72%) }
  .stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px }
  .stat { border: 2.5px solid var(--ink); border-radius: 16px; padding: 16px 20px }
  .stat.fill { background: var(--ink); color: var(--paper) }
  .stat b { display: block; font-size: 38px; line-height: 1.05; letter-spacing: -0.02em }
  .stat span { font-size: 17px; color: var(--muted) }
  .stat.fill span { color: #d7d5cd }
  footer { display: flex; justify-content: space-between; align-items: baseline;
           font-family: "Space Mono", monospace; font-size: 20px; color: var(--muted) }
  footer b { color: var(--ink) }
</style></head><body>
  <header>
    <div class="brand">
      <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 0l2.4 9.6L24 12l-9.6 2.4L12 24l-2.4-9.6L0 12l9.6-2.4z"/></svg>
      Rook
    </div>
    <div class="tag">day 2 &middot; building in public &middot; #neatHacks</div>
  </header>

  <main>
    <div>
      <h1>Most agents stop at a suggestion.<br>Rook <mark>proves the fix.</mark></h1>
      <p class="lead">Staff report a problem. It investigates across every system, waits for a person
        before anything reaches someone outside, then checks the result on the live systems and shows
        the proof. If it cannot finish, it says so.</p>
    </div>
    <div class="shot"><img src="${shot}" alt=""></div>
  </main>

  <div class="stats">
    <div class="stat fill"><b>40</b><span>scenarios, run end to end</span></div>
    <div class="stat"><b>16 / 24</b><span>close with proof / stop and say why</span></div>
    <div class="stat"><b>4</b><span>industries, one engine</span></div>
    <div class="stat"><b>218</b><span>tests, all passing</span></div>
  </div>

  <footer><span><b>${SITE}</b> &middot; live, try it yourself</span><span>Timi &middot; team Keywarden</span></footer>
</body></html>`

;(async () => {
  const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')
  const b = await chromium.launch()
  const p = await (await b.newContext({ viewport: { width: 1600, height: 900 }, deviceScaleFactor: 1 })).newPage()
  await p.setContent(html, { waitUntil: 'networkidle' })
  await p.waitForTimeout(700)                      // let the webfonts land before the shot
  await p.screenshot({ path: OUT })
  await b.close()
  console.log('wrote', OUT)
})()
