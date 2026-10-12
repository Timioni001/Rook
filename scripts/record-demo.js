// Record the submission video, the same way every time.
//
//   ROOK_DEMO_URL=https://rook-keywarden.pages.dev node scripts/record-demo.js
//   ROOK_DEMO_PACE=1.3 node scripts/record-demo.js        # slower, if you are talking over it
//
// One video, in the order neatHack asked for it: the problem, the agent solving it on the live
// site, then the incident neatlogs raised against our own traces and how it was fixed, then cfo.ai
// and Entire. The first two parts are the real deployed product driven in a real browser; the last
// two are cards in scripts/video/story.html, which uses the product's own type and colours so the
// cut does not jolt.
//
// Why a script and not a hand-recorded screen capture: a demo you can re-run is a demo you can fix.
// Change a word, run it again, get the same clip with the same pacing. It draws a cursor
// (Playwright's video does not capture the system one) and burns in a caption per beat, so the clip
// is followable with the sound off before any voice-over exists.
//
// Output: docs/video/rook-demo.webm, at 1600x900.
const fs = require('fs')
const path = require('path')

const URL = (process.env.ROOK_DEMO_URL || 'http://localhost:8000').replace(/\/+$/, '')
const STORY = 'file://' + path.join(__dirname, 'video', 'story.html')
const OUT = path.join(__dirname, '..', 'docs', 'video')
const PACE = Number(process.env.ROOK_DEMO_PACE || 1)      // 1.5 slows everything down by half

const wait = (ms) => new Promise((r) => setTimeout(r, ms * PACE))
const round = (n) => Math.round(n * 100) / 100

// The spoken lines, with how long each one takes. Made by scripts/make-voice.py; without it the
// captions still play, at a reading speed.
const VO = path.join(OUT, 'vo')
const LINES = JSON.parse(fs.readFileSync(path.join(__dirname, 'video', 'narration.json'), 'utf8')).lines
try {
  const spoken = JSON.parse(fs.readFileSync(path.join(VO, 'lines.json'), 'utf8'))
  for (const [k, v] of Object.entries(spoken)) Object.assign(LINES[k], v)
} catch { console.log('no voice track yet: holding each caption for as long as it takes to read') }
const cues = []
let t0 = Date.now()

/** A cursor the recording can see, and a caption anyone can read. */
const CHROME = `
  #rk-cursor { position: fixed; z-index: 2147483647; width: 22px; height: 22px; margin: -4px 0 0 -4px;
    pointer-events: none; transition: transform .45s cubic-bezier(.4,0,.2,1); will-change: transform }
  #rk-cursor svg { filter: drop-shadow(0 2px 3px rgba(0,0,0,.45)) }
  #rk-ring { position: fixed; z-index: 2147483646; width: 46px; height: 46px; margin: -23px 0 0 -23px;
    border-radius: 50%; border: 3px solid #c8f24c; opacity: 0; pointer-events: none }
  #rk-ring.go { animation: rk-pop .5s ease-out }
  @keyframes rk-pop { from { opacity: 1; transform: scale(.3) } to { opacity: 0; transform: scale(1.3) } }
  #rk-cap { position: fixed; left: 0; right: 0; bottom: 0; z-index: 2147483645; padding: 22px 44px 26px;
    background: linear-gradient(transparent, rgba(16,16,16,.92) 38%); color: #fbfaf7;
    font-family: "Space Grotesk", system-ui, sans-serif; font-size: 29px; line-height: 1.3;
    opacity: 0; transition: opacity .3s; text-align: center; pointer-events: none }
  #rk-cap.on { opacity: 1 }
  #rk-cap b { color: #c8f24c }
`

async function chrome(page) {
  await page.addStyleTag({ content: CHROME })
  await page.evaluate(() => {
    for (const id of ['rk-cursor', 'rk-ring', 'rk-cap']) document.getElementById(id)?.remove()
    const c = document.createElement('div')
    c.id = 'rk-cursor'
    c.innerHTML = '<svg viewBox="0 0 24 24" width="22" height="22"><path d="M5 2l14 10-6.5.9L15 20l-2.6 1-2.6-7L5 18z" fill="#101010" stroke="#fff" stroke-width="1.4"/></svg>'
    const r = document.createElement('div'); r.id = 'rk-ring'
    const cap = document.createElement('div'); cap.id = 'rk-cap'
    document.body.append(c, r, cap)
    const move = (x, y) => {
      for (const el of [c, r]) el.style.transform = `translate(${x}px, ${y}px)`
    }
    move(window.innerWidth / 2, window.innerHeight * 0.7)
  })
}

/**
 * One beat: show its caption, hold it for as long as the spoken line takes, log when it happened.
 *
 * The holds are not hand-tuned numbers. They come from the voice track, so a line that gets longer
 * makes its own shot longer and picture and voice cannot drift apart. With no voice track, the
 * fallback is a reading speed.
 */
async function say(page, id, fallback) {
  const line = LINES[id]
  if (!line) throw new Error(`no narration line "${id}"`)
  const html = line.caption
  const hold = line.hold || fallback || Math.max(2.4, html.replace(/<[^>]+>/g, '').length / 13)
  cues.push({ id, at: round((Date.now() - t0) / 1000) })
  await page.evaluate((t) => {
    const cap = document.getElementById('rk-cap')
    if (cap) { cap.innerHTML = t; cap.classList.add('on') }
  }, html)
  await wait(hold * 1000)
}

async function clear(page) {
  await page.evaluate(() => document.getElementById('rk-cap')?.classList.remove('on'))
  await wait(250)
}

async function point(page, locator) {
  await locator.scrollIntoViewIfNeeded()
  await wait(250)
  const box = await locator.boundingBox()
  if (!box) return
  const x = Math.round(box.x + box.width / 2), y = Math.round(box.y + box.height / 2)
  await page.evaluate(({ x, y }) => {
    for (const id of ['rk-cursor', 'rk-ring']) {
      const el = document.getElementById(id)
      if (el) el.style.transform = `translate(${x}px, ${y}px)`
    }
  }, { x, y })
  await wait(600)
}

async function tap(page, locator) {
  await point(page, locator)
  await page.evaluate(() => {
    const r = document.getElementById('rk-ring')
    if (r) { r.classList.remove('go'); void r.offsetWidth; r.classList.add('go') }
  })
  await wait(260)
  await locator.click()
  await wait(500)
}

/** Show one card from story.html and hold it. The page animates nothing on its own. */
async function slide(page, n) {
  await page.evaluate((i) => window.go(i), n)
  await wait(500)
  await say(page, 's' + n)
  await clear(page)
}

/** Scroll in steps rather than jumping, so the eye can follow it. */
async function glide(page, locator, steps = 3) {
  for (let i = 0; i < steps; i++) {
    await page.mouse.wheel(0, 320)
    await wait(260)
  }
  if (locator) await locator.scrollIntoViewIfNeeded()
  await wait(400)
}

;(async () => {
  const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')
  fs.mkdirSync(OUT, { recursive: true })
  const browser = await chromium.launch()
  const ctx = await browser.newContext({
    viewport: { width: 1600, height: 900 }, deviceScaleFactor: 1,
    recordVideo: { dir: OUT, size: { width: 1600, height: 900 } },
  })
  const page = await ctx.newPage()
  t0 = Date.now()          // the recording starts with the page; cue times are measured from here

  // ---------------------------------------------------------------- the front page
  await page.goto(URL + '/', { waitUntil: 'networkidle' })
  await chrome(page)
  await wait(900)
  await say(page, 'between')
  await say(page, 'sick')
  await say(page, 'phone')
  await clear(page)
  await glide(page, page.locator('.strip3').first(), 3)
  await say(page, 'same-engine')
  await clear(page)

  // ---------------------------------------------------------------- into the demo
  await tap(page, page.locator('.land-nav a.btn-dark'))
  await page.waitForSelector('.sheet', { timeout: 30000 })
  await chrome(page)
  await wait(700)
  await say(page, 'who')
  await tap(page, page.locator('.who-card:has-text("Priya")'))
  await chrome(page)
  await say(page, 'priya')
  await clear(page)

  // ---------------------------------------------------------------- start it
  await tap(page, page.locator('.hero-form button.btn-dark'))
  await page.waitForSelector('.overview h2', { timeout: 40000 })
  await chrome(page)
  await wait(800)
  await say(page, 'read')
  await say(page, 'nothing-yet')
  await clear(page)
  await glide(page, page.locator('.findings').first(), 2)
  await say(page, 'findings')
  await clear(page)

  // ---------------------------------------------------------------- run it
  await page.locator('.overview button.btn-dark').scrollIntoViewIfNeeded()
  await tap(page, page.locator('.overview button.btn-dark'))
  await chrome(page)
  await say(page, 'works')
  await clear(page)

  let approvals = 0
  for (let i = 0; i < 40; i++) {
    await wait(1400)
    const btn = page.locator('.approval-actions button.btn-lime').first()
    if (await btn.count()) {
      if (approvals === 0) {
        await chrome(page)
        await say(page, 'approval')
        await clear(page)
      }
      await tap(page, btn)
      approvals++
      continue
    }
    const status = (await page.locator('.status-card b').innerText().catch(() => '')).trim()
    if (/Closed|Escalated/i.test(status)) break
  }

  // ---------------------------------------------------------------- the proof
  await chrome(page)
  await wait(800)
  await say(page, 'done')
  await clear(page)
  const story = page.locator('#story')
  if (await story.count()) {
    await story.scrollIntoViewIfNeeded()
    await wait(700)
    await say(page, 'six-lines')
    await clear(page)
    await glide(page, null, 2)
  }
  const verify = page.locator('#verify')
  if (await verify.count()) {
    await verify.scrollIntoViewIfNeeded()
    await wait(700)
    await say(page, 'evidence')
    await clear(page)
  }
  const limits = page.locator('#refusals')
  if (await limits.count()) {
    await limits.scrollIntoViewIfNeeded()
    await wait(700)
    await say(page, 'refused')
    await clear(page)
  }

  // ---------------------------------------------------------------- neatlogs, cfo.ai, Entire
  await page.goto(STORY, { waitUntil: 'networkidle' })
  await chrome(page)
  await wait(700)
  await slide(page, 1)
  await slide(page, 2)
  await slide(page, 3)
  await slide(page, 4)
  await slide(page, 5)
  await slide(page, 6)
  await slide(page, 7)
  await slide(page, 8)
  await slide(page, 9)

  await ctx.close()
  await browser.close()
  const name = 'rook-demo.webm'
  // Playwright names the file by hash. Take the one just written, by mtime: sorting by name picks
  // up a previous rook-demo.webm instead, and you encode yesterday's clip without noticing.
  const latest = fs.readdirSync(OUT).filter((f) => f.endsWith('.webm') && f !== name)
    .map((f) => [f, fs.statSync(path.join(OUT, f)).mtimeMs]).sort((a, b) => b[1] - a[1])[0][0]
  fs.rmSync(path.join(OUT, name), { force: true })
  fs.renameSync(path.join(OUT, latest), path.join(OUT, name))
  fs.mkdirSync(VO, { recursive: true })
  fs.writeFileSync(path.join(VO, 'cues.json'), JSON.stringify(cues, null, 2) + '\n')
  const kb = Math.round(fs.statSync(path.join(OUT, name)).size / 1024)
  console.log(`wrote ${path.join(OUT, name)} (${kb} KB)`)
})()
