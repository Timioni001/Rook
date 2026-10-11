'use client'
import { useState } from 'react'
import { Star } from './components/Mark'

const SECTORS = ['Clinic or practice', 'IT & security', 'Engineering', 'Sport & clubs', 'Something else']
const SIZES = ['1–10', '11–50', '51–200', '201–1000', '1000+']

const STEPS: [string, string][] = [
  ['Someone reports it', 'A doctor is off. A pitch is shut. Someone left and their keys did not. Staff raise it in one place, or a connected system does.'],
  ['Rook investigates', 'It reads every system the problem touches and works out who and what is really affected. Nothing is changed while it looks.'],
  ['A person approves', 'It proposes the fix as ordered steps. Anything that reaches someone outside your organisation waits for a human yes.'],
  ['Rook proves it', 'It checks the result on the systems themselves and shows the evidence. Whatever it could not finish stays open, named, with the reason.'],
]

const INDUSTRIES: [string, string][] = [
  ['Healthcare', 'A doctor off sick with a day of patients booked in. Referrals and results the record calls done that never happened.'],
  ['IT & security', 'Someone left, but their accounts and API keys live on. A scanner finds a live key in a repository.'],
  ['Engineering', 'A production service starts failing right after a change, and auto-deploy keeps putting it back.'],
  ['Sport & clubs', 'A pitch is shut on a Saturday. Three matches, six clubs and three referees, all needing to be told.'],
]

export default function Landing() {
  return (
    <div className="page land">
      <div className="frame">
        <nav className="nav land-nav" aria-label="Main">
          <a className="brand" href="#top"><Star /> Rook</a>
          <a className="btn-dark land-cta" href="/app/">Open the demo</a>
        </nav>

        <header className="land-hero" id="top">
          <p className="mono small land-kicker">An operations agent · neatHacks 2026</p>
          <h1>Start with a problem.<br /><mark>Rook proves the fix.</mark></h1>
          <p className="lead">
            Every organisation runs on work that falls between its systems, and a person ends up doing it by
            hand. Rook does that work: it investigates across everything connected, waits for a human before
            anything reaches someone outside, then checks the result and shows the proof.
          </p>
          <div className="row land-actions">
            <a className="btn-dark" href="/app/">Open the demo</a>
            <a className="btn-outline" href="#waitlist">Join the waitlist</a>
          </div>
          <p className="small muted">No sign-up for the demo. Every system behind it is a sandboxed copy with
            made-up data, so nothing real is touched and no real person is contacted.</p>
        </header>

        <WorkedExample />

        <section className="section">
          <h2 className="h2 land-h">How it works</h2>
          <ol className="how land-how">
            {STEPS.map(([t, x], i) => (
              <li key={t}><span className="mono small">{String(i + 1).padStart(2, '0')}</span><b>{t}</b><span className="small">{x}</span></li>
            ))}
          </ol>
        </section>

        <section className="section">
          <h2 className="h2 land-h">The same engine, wherever the work falls</h2>
          <div className="land-grid">
            {INDUSTRIES.map(([name, text]) => (
              <div key={name} className="card land-card"><b>{name}</b><p className="small">{text}</p></div>
            ))}
          </div>
        </section>

        <section className="section">
          <h2 className="h2 land-h">What makes it different</h2>
          <div className="land-grid land-grid-3">
            <div className="card land-card"><b>It writes the finish line first</b>
              <p className="small">Before changing anything, Rook writes down what would have to be true on the
                live systems before this can be called done. The finish line cannot move later.</p></div>
            <div className="card land-card"><b>A tool saying &ldquo;ok&rdquo; is not evidence</b>
              <p className="small">Every step is read back from the system it ran on: the appointment book, the
                pharmacy&rsquo;s queue, an authentication probe, a synthetic order.</p></div>
            <div className="card land-card"><b>It refuses, out loud</b>
              <p className="small">Of 40 scenarios, 24 end without closing: no slot free, nobody who can be told,
                a key whose revocation would break a live service. Each one is named, with the reason.</p></div>
          </div>
          <div className="stats land-stats">
            <div className="stat"><b>40</b><span className="small">scenarios, run end to end</span></div>
            <div className="stat"><b>16 / 24</b><span className="small">close with proof / stop and say why</span></div>
            <div className="stat"><b>6</b><span className="small">playbooks across 4 industries</span></div>
            <div className="stat"><b>218</b><span className="small">tests, all passing</span></div>
          </div>
        </section>

        <section className="section land-shot">
          <h2 className="h2 land-h">And it shows its working</h2>
          <p className="small muted land-shot-note">Every run ends with a plain account of what happened, and
            the evidence for each line of it underneath: the plan, every check with what was observed on the
            live system, what it refused to do, and a tamper-evident log. This is a real one.</p>
          <img src="/run-story.png" width={1556} height={1340}
            alt="Rook's What just happened panel: what it started with, what it read, the checks it wrote before touching anything, the plan it worked, what it verified, and how it ended" />
        </section>

        <Waitlist />

        <footer className="footer mono small land-foot">
          <span>Rook · built by Keywarden for neatHacks 2026</span>
          <span><a href="https://github.com/Timioni001/Rook">source on GitHub</a> · <a href="/app/">open the demo</a></span>
        </footer>
      </div>
    </div>
  )
}

/**
 * One real morning, in three panels.
 *
 * The numbers are a measured run of the `cover_unreachable` scenario, not a story: twelve booked,
 * eleven moved and told, one left alone on purpose, 23 of 24 checks passing. A judge should be able
 * to read this in ten seconds and know exactly what the thing is for.
 */
function WorkedExample() {
  const panels: [string, string, React.ReactNode][] = [
    ['08:02', 'What comes in', <>
      A doctor calls in sick. <b>Twelve patients</b> are booked in with her today, the first at nine.
      None of them know. Somebody at the front desk is about to lose the morning to the phone.
    </>],
    ['08:03', 'What Rook does', <>
      It reads the appointment book, the patient records and the messaging system. <b>Eleven</b> can be
      moved to a colleague at a similar time, and each person is told by text. The twelfth cannot: the
      only number on file for her is dead.
    </>],
    ['08:05', 'What you are left with', <>
      Eleven moved and confirmed, checked against the systems themselves. The twelfth is <b>not quietly
      moved</b> — her appointment stays where it is, and reception gets her name, her time and the reason.
    </>],
  ]
  return (
    <section className="section">
      <h2 className="h2 land-h">A Monday morning, start to finish</h2>
      <div className="strip3">
        {panels.map(([time, head, body]) => (
          <div key={head} className="card strip3-card">
            <span className="mono small strip3-time">{time}</span>
            <b>{head}</b>
            <p className="small">{body}</p>
          </div>
        ))}
      </div>
      <p className="strip mono strip3-facts" role="note">
        <span>22 steps</span><span>23 of 24 checks passed</span><span>1 refused, with the reason</span>
        <span>nothing marked done that was not</span>
      </p>
      <p className="small muted">The same engine does the same thing for a pitch shut on a Saturday, an API
        key that outlived the person who made it, or a service failing after a deploy.{' '}
        <a href="/app/">Open the demo and run this one yourself</a>.</p>
    </section>
  )
}

/** One email, kept for one purpose. Everything else on the form is optional and bounded. */
function Waitlist() {
  const [form, setForm] = useState<Record<string, string>>({})
  const [state, setState] = useState<'idle' | 'sending' | 'done' | 'error'>('idle')
  const [error, setError] = useState('')
  const set = (k: string, v: string) => setForm((f) => ({ ...f, [k]: f[k] === v && (k === 'sector' || k === 'size') ? '' : v }))

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setState('sending'); setError('')
    try {
      const body: Record<string, string> = {}
      for (const [k, v] of Object.entries(form)) if (v && v.trim()) body[k] = v.trim()
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

  if (state === 'done') {
    return (
      <section className="section" id="waitlist">
        <div className="card land-done">
          <h2 className="h2">You are on the list.</h2>
          <p>One email when Rook is ready for real systems, and nothing else. In the meantime the demo is
            open: <a href="/app/">try it on your own clinic or company</a>.</p>
        </div>
      </section>
    )
  }

  return (
    <section className="section" id="waitlist">
      <div className="card land-form-card">
        <p className="mono small muted">GET NOTIFIED</p>
        <h2 className="h2">Join the waitlist</h2>
        <p className="lead small">One email when we go live. No spam, and we will not pass it on.</p>
        <form className="land-form" onSubmit={submit}>
          <label className="own-text">
            <span className="small">Email</span>
            <input type="email" required maxLength={254} value={form.email || ''} placeholder="you@company.com"
              onChange={(e) => set('email', e.target.value)} />
          </label>
          <div className="land-two">
            <label className="own-text">
              <span className="small">Name <i className="muted">optional</i></span>
              <input type="text" maxLength={60} value={form.name || ''} placeholder="Ada Okafor"
                onChange={(e) => set('name', e.target.value)} />
            </label>
            <label className="own-text">
              <span className="small">Organisation <i className="muted">optional</i></span>
              <input type="text" maxLength={60} value={form.organisation || ''} placeholder="Riverside Family Practice"
                onChange={(e) => set('organisation', e.target.value)} />
            </label>
          </div>

          <fieldset className="land-chips">
            <legend className="small">Where you work</legend>
            {SECTORS.map((s) => (
              <button type="button" key={s} className={`chip ind ${form.sector === s ? 'sel' : ''}`}
                aria-pressed={form.sector === s} onClick={() => set('sector', s)}><b>{s}</b></button>
            ))}
          </fieldset>

          <fieldset className="land-chips">
            <legend className="small">How many people</legend>
            {SIZES.map((s) => (
              <button type="button" key={s} className={`chip ind ${form.size === s ? 'sel' : ''}`}
                aria-pressed={form.size === s} onClick={() => set('size', s)}><b>{s}</b></button>
            ))}
          </fieldset>

          <label className="own-text">
            <span className="small">What would you point it at? <i className="muted">optional</i></span>
            <textarea maxLength={300} rows={2} value={form.use_for || ''}
              placeholder="Cover for absences, chasing referrals, offboarding…"
              onChange={(e) => set('use_for', e.target.value)} />
          </label>

          <button className="btn-dark land-submit" disabled={state === 'sending'}>
            {state === 'sending' ? 'Sending…' : 'Join the waitlist →'}
          </button>
          {error && <p className="small err-text" role="alert">{error}</p>}
          <p className="small muted">We only use your email to tell you when Rook launches.</p>
        </form>
      </div>
    </section>
  )
}
