'use client'
import { useRef, useState } from 'react'
import { Star } from './components/Mark'

const GITHUB = 'https://github.com/Timioni001/Rook'
const CFO = 'https://cfo.ai/s/D9MnZeXwqy0WpZeV'

/**
 * One real run per sector. Every number here is a measured run of the named scenario through the
 * engine that serves the demo, and the picture is that run's own map, captured from the demo. A
 * visitor can open the demo and get the same result.
 */
const SECTORS = [
  {
    key: 'health', tab: 'Healthcare', scenario: 'cover_unreachable', when: '08:02, Monday',
    problem: 'A doctor calls in sick. Twelve patients are booked in today, the first at nine, and none of them know.',
    did: [
      'Reads the appointment book, the patient records and the messaging system. Changes nothing yet.',
      'Moves eleven patients to a colleague at a similar time and texts each one. A person approves the texts first.',
      'One number on file is dead, so that appointment is left where it is and reception gets the name, the time and the reason.',
    ],
    facts: ['11 of 12 moved and told', '23 of 24 checks passed', '1 refused, with the reason'],
    img: '/shots/cover_unreachable-graph.webp', w: 1400, h: 1020,
    alt: 'Map of the run: the doctor who is off, eleven appointments moved and confirmed in green, one left alone in red, and the two colleagues covering',
  },
  {
    key: 'it', tab: 'IT & security', scenario: 'clean', when: '16:40, last day',
    problem: 'Jordan has left. Their accounts are still open, and an API key they created is still running billing and payments.',
    did: [
      'Finds every account they had and every service that authenticates with their key.',
      'Closes the accounts, issues a new key and moves each service onto it, checking each one is healthy.',
      'Only then switches the old key off, and removes the copy that was committed to a repository.',
    ],
    facts: ['7 steps, all verified', '13 of 13 checks passed', 'no service went down'],
    img: '/shots/clean-graph.webp', w: 1400, h: 656,
    alt: 'Map of the run: the person who left, three accounts disabled, the old key revoked, and two services moved to the new key',
  },
  {
    key: 'eng', tab: 'Engineering', scenario: 'outage_clean', when: '14:12, release day',
    problem: 'Checkout starts failing right after a deploy. Customers cannot pay, and auto-deploy is about to push the same change again.',
    did: [
      'Ties the alert to the deploy, the pipeline, the database and the services that call checkout.',
      'Pauses auto-deploy first, so a rollback cannot be overwritten, then rolls back to the last good version.',
      'Turns the pipeline back on with the bad version blocked, and puts a test order through.',
    ],
    facts: ['3 steps, all verified', '7 of 7 checks passed', 'test order went through'],
    img: '/shots/outage_clean-graph.webp', w: 1400, h: 535,
    alt: 'Map of the run: the alert cleared, checkout healthy on the known-good revision, the bad revision rolled off and the pipeline resumed',
  },
  {
    key: 'sport', tab: 'Sport & clubs', scenario: 'fixtures_clean', when: '07:30, match day',
    problem: 'The main pitch is waterlogged with three matches on it this morning. Six clubs and three referees are about to set off.',
    did: [
      'Finds the pitches that are open, the slots that are free and the referees who are available.',
      'Moves each match, puts a referee on every game, and swaps in a spare where one cannot make it.',
      'Tells both clubs in every match, and only closes once all six have answered.',
    ],
    facts: ['3 matches moved', '6 clubs told and replied', '11 of 11 checks passed'],
    img: '/shots/fixtures_clean-graph.webp', w: 1400, h: 535,
    alt: 'Map of the run: the closed pitch, three matches moved and confirmed, and the two venues they moved to',
  },
]

const STEPS: [string, string][] = [
  ['Someone reports it', 'A doctor is off. A pitch is shut. Someone left and their keys did not. Staff say it in one sentence, or a connected system raises it.'],
  ['Rook investigates', 'It reads every system the problem touches and works out who and what is really affected. Nothing is changed while it looks.'],
  ['A person approves', 'It proposes the fix as ordered steps. Anything that reaches someone outside your organisation waits for a human yes.'],
  ['Rook proves it', 'It reads the result back from the systems themselves. Whatever it could not finish stays open, named, with the reason.'],
]

export default function Landing() {
  return (
    <div className="lp">
      <nav className="lp-nav" aria-label="Main">
        <div className="lp-wrap lp-nav-in">
          <a className="brand" href="#top"><Star /> Rook</a>
          <div className="lp-links">
            <a href="#industries">Industries</a>
            <a href="#how">How it works</a>
            <a href="#proof">Built in the open</a>
          </div>
          <a className="lp-btn lp-btn-ghost lp-hide-sm" href="#waitlist">Join the waitlist</a>
          <a className="lp-btn lp-btn-lime" href="/app/">Open the demo</a>
        </div>
      </nav>

      <header className="lp-hero" id="top">
        <div className="lp-wrap">
          <p className="lp-kicker mono">Operations agent · open source · neatHack 2026</p>
          <h1>Rook fixes the work that falls between your systems. <mark>Then it proves it.</mark></h1>
          <p className="lp-sub">
            A doctor off sick, a key that outlived its owner, a deploy that broke checkout, a pitch shut on
            match day. Rook investigates every connected system, waits for a person before anything reaches
            the outside world, and only calls the job done once the systems themselves confirm it.
          </p>
          <div className="lp-actions">
            <a className="lp-btn lp-btn-lime lp-btn-lg" href="/app/">Open the live demo &rarr;</a>
            <a className="lp-btn lp-btn-ghost lp-btn-lg" href="#waitlist">Join the waitlist</a>
          </div>
          <p className="lp-note">No sign-up. Every system behind the demo is a sandboxed copy with made-up data.</p>

          <figure className="lp-window">
            <div className="lp-window-bar" aria-hidden="true"><i /><i /><i /><span className="mono">rook · a doctor is off sick</span></div>
            <img src="/shots/cover_clean-incident.webp" width={1400} height={613}
              alt="A finished Rook run: Dr Ada Okafor is off sick, 12 appointments moved. Closed and verified, 24 of 24 steps checked, 26 of 26 checks passed" />
          </figure>
        </div>
      </header>

      <div className="lp-tools">
        <div className="lp-wrap lp-tools-in mono">
          <span>Traced with <b>neatlogs</b></span>
          <span>Business modelled on <b>cfo.ai</b></span>
          <span>Every build session checkpointed with <b>Entire</b></span>
          <span><a href={GITHUB}>Open source on GitHub &rarr;</a></span>
        </div>
      </div>

      <Industries />

      <section className="lp-sec lp-alt" id="how">
        <div className="lp-wrap">
          <p className="lp-eyebrow mono">How it works</p>
          <h2 className="lp-h2">Four steps, and the last one is the point.</h2>
          <ol className="lp-steps">
            {STEPS.map(([t, x], i) => (
              <li key={t}>
                <span className="lp-step-n mono">{String(i + 1).padStart(2, '0')}</span>
                <b>{t}</b>
                <p>{x}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className="lp-sec">
        <div className="lp-wrap">
          <p className="lp-eyebrow mono">What makes it different</p>
          <h2 className="lp-h2">An agent you can leave alone with a real system.</h2>
          <div className="lp-cards">
            <div className="lp-card"><b>It writes the finish line first</b>
              <p>Before changing anything, Rook writes down what would have to be true on the live systems
                for this to be done. The finish line cannot move later.</p></div>
            <div className="lp-card"><b>&ldquo;OK&rdquo; from a tool is not evidence</b>
              <p>Every step is read back from the system it ran on: the appointment book, the pharmacy&rsquo;s
                queue, a login attempt with the old key, a test order through checkout.</p></div>
            <div className="lp-card"><b>It stops, out loud</b>
              <p>No free slot, nobody who can be told, a key that would break a live service if switched off.
                Rook hands it to a person by name, with the reason, instead of guessing.</p></div>
          </div>
          <dl className="lp-stats">
            <div><dt>40</dt><dd>scenarios, each run end to end</dd></div>
            <div><dt>16 / 24</dt><dd>close with proof / stop and say why</dd></div>
            <div><dt>$0</dt><dd>model cost per incident: the planner is deterministic code</dd></div>
            <div><dt>265</dt><dd>tests, all passing</dd></div>
          </dl>
        </div>
      </section>

      <section className="lp-sec lp-alt">
        <div className="lp-wrap lp-split">
          <div>
            <p className="lp-eyebrow mono">It shows its working</p>
            <h2 className="lp-h2">Every run ends in plain English, with the evidence underneath.</h2>
            <p className="lp-p">What it started with, what it read, the checks it wrote before touching
              anything, the plan, what it verified, and how it ended. Under that: every check with what was
              observed on the live system, what it refused to do, and a tamper-evident log you can download.</p>
            <a className="lp-btn lp-btn-dark" href="/app/">See one for yourself &rarr;</a>
          </div>
          <img className="lp-shot" src="/run-story.png" width={1556} height={1340} loading="lazy"
            alt="Rook's What just happened panel: what it started with, what it read, the checks it wrote, the plan, what it verified, and how it ended" />
        </div>
      </section>

      <section className="lp-sec" id="proof">
        <div className="lp-wrap">
          <p className="lp-eyebrow mono">Built in the open</p>
          <h2 className="lp-h2">We held ourselves to the same standard.</h2>
          <div className="lp-cards">
            <a className="lp-card lp-card-link" href={`${GITHUB}/blob/main/evidence/neatlogs-traces.md`}>
              <span className="lp-tag mono">neatlogs</span>
              <b>It caught a silent failure in our own agent</b>
              <p>Neatlogs flagged runs we had called fine: tool steps reporting nothing, and failures the
                agent survived closing green. Now a handled failure marks itself, and a test fails if any
                step comes back empty.</p>
              <span className="lp-more mono">Read the incident &rarr;</span>
            </a>
            <a className="lp-card lp-card-link" href={CFO}>
              <span className="lp-tag mono">cfo.ai</span>
              <b>The business, modelled from sourced numbers</b>
              <p>Every input is labelled measured, benchmark or assumption. It found the assumption that
                breaks the plan: paid acquisition instead of founder time needs about $15,000 more in year one.</p>
              <span className="lp-more mono">Open the plan &rarr;</span>
            </a>
            <a className="lp-card lp-card-link" href={`${GITHUB}/blob/main/evidence/entire-workflow.md`}>
              <span className="lp-tag mono">Entire</span>
              <b>Every session that built it, on the record</b>
              <p>Each agent session is checkpointed, and the checkpoint id sits in the commit it produced,
                so where the code came from travels with the repository.</p>
              <span className="lp-more mono">See the checkpoints &rarr;</span>
            </a>
          </div>
        </div>
      </section>

      <Waitlist />

      <footer className="lp-foot">
        <div className="lp-wrap lp-foot-in mono">
          <span><Star /> Rook · built by Keywarden for neatHack 2026</span>
          <span><a href="/app/">Demo</a><a href={GITHUB}>GitHub</a><a href={CFO}>Business plan</a></span>
        </div>
      </footer>
    </div>
  )
}

/** The same engine in four places, one real run each. Arrow keys move between tabs. */
function Industries() {
  const [at, setAt] = useState(0)
  const tabs = useRef<(HTMLButtonElement | null)[]>([])
  const s = SECTORS[at]
  const go = (i: number) => { const n = (i + SECTORS.length) % SECTORS.length; setAt(n); tabs.current[n]?.focus() }
  return (
    <section className="lp-sec" id="industries">
      <div className="lp-wrap">
        <p className="lp-eyebrow mono">One engine, four industries</p>
        <h2 className="lp-h2">Same morning. Different building.</h2>
        <div className="lp-tabs" role="tablist" aria-label="Industry">
          {SECTORS.map((x, i) => (
            <button key={x.key} role="tab" id={`tab-${x.key}`} aria-controls={`panel-${x.key}`}
              aria-selected={i === at} tabIndex={i === at ? 0 : -1} ref={(el) => { tabs.current[i] = el }}
              className={i === at ? 'on' : ''} onClick={() => setAt(i)}
              onKeyDown={(e) => {
                if (e.key === 'ArrowRight') { e.preventDefault(); go(at + 1) }
                if (e.key === 'ArrowLeft') { e.preventDefault(); go(at - 1) }
              }}>
              {x.tab}
            </button>
          ))}
        </div>
        <div className="lp-panel" role="tabpanel" id={`panel-${s.key}`} aria-labelledby={`tab-${s.key}`}>
          <div className="lp-panel-copy">
            <span className="lp-when mono">{s.when}</span>
            <p className="lp-problem">{s.problem}</p>
            <p className="lp-label mono">What Rook does</p>
            <ol className="lp-did">{s.did.map((d) => <li key={d}>{d}</li>)}</ol>
            <ul className="lp-facts mono">{s.facts.map((f) => <li key={f}>{f}</li>)}</ul>
            <a className="lp-btn lp-btn-dark" href={`/app/?scenario=${s.scenario}`}>Run this one yourself &rarr;</a>
          </div>
          <figure className="lp-panel-shot">
            <img key={s.img} src={s.img} width={s.w} height={s.h} alt={s.alt} />
            <figcaption className="mono">The map from that run. Green was changed and checked; red is the problem, or left alone on purpose.</figcaption>
          </figure>
        </div>
      </div>
    </section>
  )
}

const SECTOR_CHOICES = ['Clinic or practice', 'IT & security', 'Engineering', 'Sport & clubs', 'Something else']

/** One email, kept for one purpose. The sector is optional and tells us who to build for first. */
function Waitlist() {
  const [email, setEmail] = useState('')
  const [sector, setSector] = useState('')
  const [state, setState] = useState<'idle' | 'sending' | 'done' | 'error'>('idle')
  const [error, setError] = useState('')

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setState('sending'); setError('')
    try {
      const body: Record<string, string> = { email: email.trim() }
      if (sector) body.sector = sector
      const r = await fetch('/api/waitlist', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      })
      if (!r.ok) {
        const d = await r.json().catch(() => ({}))
        throw new Error(r.status === 429 ? 'That is a lot of sign-ups from one place. Try again in a minute.'
          : typeof d.detail === 'string' ? d.detail : 'Something went wrong. Try again?')
      }
      setState('done')
    } catch (err: any) {
      setError(err.message || 'Something went wrong.'); setState('error')
    }
  }

  return (
    <section className="lp-sec lp-cta" id="waitlist">
      <div className="lp-wrap lp-cta-in">
        {state === 'done' ? (
          <div>
            <h2 className="lp-h2">You are on the list.</h2>
            <p className="lp-p">One email when Rook is ready for real systems, and nothing else. The demo is
              open in the meantime: <a href="/app/">try it on your own clinic or company</a>.</p>
          </div>
        ) : (<>
          <div>
            <p className="lp-eyebrow mono">Get notified</p>
            <h2 className="lp-h2">Point Rook at your own systems.</h2>
            <p className="lp-p">One email when it can connect to real software. No spam, and we will not pass
              your address on.</p>
          </div>
          <form className="lp-form" onSubmit={submit}>
            <label className="sr-only" htmlFor="wl-email">Email</label>
            <div className="lp-form-row">
              <input id="wl-email" type="email" required maxLength={254} value={email}
                placeholder="you@company.com" onChange={(e) => setEmail(e.target.value)} />
              <button className="lp-btn lp-btn-lime" disabled={state === 'sending'}>
                {state === 'sending' ? 'Sending…' : 'Join the waitlist'}
              </button>
            </div>
            <fieldset className="lp-chips">
              <legend className="mono">Where you work <i>optional</i></legend>
              {SECTOR_CHOICES.map((c) => (
                <button type="button" key={c} aria-pressed={sector === c} className={sector === c ? 'on' : ''}
                  onClick={() => setSector(sector === c ? '' : c)}>{c}</button>
              ))}
            </fieldset>
            {error && <p className="lp-err" role="alert">{error}</p>}
          </form>
        </>)}
      </div>
    </section>
  )
}
