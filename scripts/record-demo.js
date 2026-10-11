// Record the demo as a video, the same way every time.
//
//   ROOK_DEMO_URL=http://localhost:8000 node scripts/record-demo.js            # the short one
//   ROOK_DEMO_URL=https://rook-keywarden.pages.dev node scripts/record-demo.js --technical
//
// Why a script and not a hand-recorded screen capture: a demo you can re-run is a demo you can fix.
// Change a word, run it again, get the same clip with the same pacing. It drives the real site in
// a real browser, draws a cursor (Playwright's video does not capture the system one) and burns in
// a caption per beat, so the clip is followable with the sound off before any voice-over exists.
//
// Output: docs/video/<name>.webm, at 1280x720.
const fs = require('fs')
const path = require('path')

const URL = (process.env.ROOK_DEMO_URL || 'http://localhost:8000').replace(/\/+$/, '')
const TECHNICAL = process.argv.includes('--technical')
const OUT = path.join(__dirname, '..', 'docs', 'video')
const PACE = Number(process.env.ROOK_DEMO_PACE || 1)      // 1.5 slows everything down by half

const wait = (ms) => new Promise((r) => setTimeout(r, ms * PACE))

/** A cursor the recording can see, and a caption anyone can read. */
const CHROME = `
  #rk-cursor { position: fixed; z-index: 2147483647; width: 22px; height: 22px; margin: -4px 0 0 -4px;
    pointer-events: none; transition: transform .45s cubic-bezier(.4,0,.2,1); will-change: transform }
  #rk-cursor svg { filter: drop-shadow(0 2px 3px rgba(0,0,0,.45)) }
  #rk-ring { position: fixed; z-index: 2147483646; width: 46px; height: 46px; margin: -23px 0 0 -23px;
    border-radius: 50%; border: 3px solid #c8f24c; opacity: 0; pointer-events: none }
  #rk-ring.go { animation: rk-pop .5s ease-out }
  @keyframes rk-pop { from { opacity: 1; transform: scale(.3) } to { opacity: 0; transform: scale(1.3) } }
  #rk-cap { position: fixed; left: 0; right: 0; bottom: 0; z-index: 2147483645; padding: 18px 34px 22px;
    background: linear-gradient(transparent, rgba(16,16,16,.92) 38%); color: #fbfaf7;
    font-family: "Space Grotesk", system-ui, sans-serif; font-size: 25px; line-height: 1.3;
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

async function say(page, html, hold = 2600) {
  await page.evaluate((t) => {
    const cap = document.getElementById('rk-cap')
    if (cap) { cap.innerHTML = t; cap.classList.add('on') }
  }, html)
  await wait(hold)
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
    viewport: { width: 1280, height: 720 }, deviceScaleFactor: 1,
    recordVideo: { dir: OUT, size: { width: 1280, height: 720 } },
  })
  const page = await ctx.newPage()

  // ---------------------------------------------------------------- the front page
  await page.goto(URL + '/', { waitUntil: 'networkidle' })
  await chrome(page)
  await wait(900)
  await say(page, 'A clinic. A doctor calls in sick at eight in the morning.', 3000)
  await say(page, '<b>Twelve patients</b> are booked in with her today. None of them know.', 3200)
  await clear(page)
  await glide(page, page.locator('.strip3').first(), 3)
  await say(page, 'Normally someone loses the morning to the phone. This is what Rook does instead.', 3400)
  await clear(page)

  // ---------------------------------------------------------------- into the demo
  await tap(page, page.locator('.land-nav a.btn-dark'))
  await page.waitForSelector('.sheet', { timeout: 30000 })
  await chrome(page)
  await wait(700)
  await say(page, 'First question: who are you? What you may do here depends on the answer.', 3400)
  await tap(page, page.locator('.who-card:has-text("Priya")'))
  await chrome(page)
  await say(page, 'Priya is the manager. She can approve things that reach a patient.', 3000)
  await clear(page)

  // ---------------------------------------------------------------- start it
  await tap(page, page.locator('.hero-form button.btn-dark'))
  await page.waitForSelector('.overview h2', { timeout: 40000 })
  await chrome(page)
  await wait(800)
  await say(page, 'Rook has read the appointment book, the records and the messaging system.', 3400)
  await say(page, 'It has changed <b>nothing</b> yet. It writes down what must be true first.', 3400)
  await clear(page)
  await glide(page, page.locator('.findings').first(), 2)
  await say(page, 'Who is affected, who has room, and who it cannot reach.', 3200)
  await clear(page)

  // ---------------------------------------------------------------- run it
  await page.locator('.overview button.btn-dark').scrollIntoViewIfNeeded()
  await tap(page, page.locator('.overview button.btn-dark'))
  await chrome(page)
  await say(page, 'Now it works the plan, one step at a time.', 2600)
  await clear(page)

  let approvals = 0
  for (let i = 0; i < 40; i++) {
    await wait(1400)
    const btn = page.locator('.approval-actions button.btn-lime').first()
    if (await btn.count()) {
      if (approvals === 0) {
        await chrome(page)
        await say(page, 'It stops. Texting a patient reaches a real person, so it waits for Priya.', 3600)
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
  await say(page, 'Done. And this is the part that matters:', 2600)
  await clear(page)
  const story = page.locator('#story')
  if (await story.count()) {
    await story.scrollIntoViewIfNeeded()
    await wait(700)
    await say(page, 'The whole run in six lines, in plain English.', 3200)
    await clear(page)
    await glide(page, null, 2)
  }
  const verify = page.locator('#verify')
  if (await verify.count()) {
    await verify.scrollIntoViewIfNeeded()
    await wait(700)
    await say(page, 'Every check read back <b>from the systems themselves</b>, not from a tool saying "ok".', 3800)
    await clear(page)
  }
  const limits = page.locator('#refusals')
  if (await limits.count()) {
    await limits.scrollIntoViewIfNeeded()
    await wait(700)
    await say(page, 'And what it refused to do, with the reason, handed to a person by name.', 3600)
    await clear(page)
  }
  await say(page, 'Nothing is called done unless it was checked. <b>rook-keywarden.pages.dev</b>', 3800)

  await ctx.close()
  await browser.close()
  const made = fs.readdirSync(OUT).filter((f) => f.endsWith('.webm')).sort()
  const latest = made[made.length - 1]
  const name = (TECHNICAL ? 'rook-technical' : 'rook-demo') + '.webm'
  fs.renameSync(path.join(OUT, latest), path.join(OUT, name))
  const kb = Math.round(fs.statSync(path.join(OUT, name)).size / 1024)
  console.log(`wrote ${path.join(OUT, name)} (${kb} KB)`)
})()
