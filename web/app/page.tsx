'use client'
import { useCallback, useEffect, useRef, useState } from 'react'
import Graph from './components/Graph'
import {
  ACTION_LABEL, ApiError, IDENTITIES, INCIDENT_STATE, PLAYBOOK_COPY, actionState, api, eventText, eventTone,
  reachable, time,
} from './lib'

// What a person can tell Rook about themselves. Typed once, these names come back in the incident
// title, in every step of the plan, in the approval prompts and in the evidence pack, because Rook
// writes those sentences out of them rather than out of anything scripted in advance.
const ABOUT_YOU = [
  { key: 'organisation', label: 'Your clinic or company name', hint: 'Riverside Family Practice', max: 60 },
  { key: 'we_do', label: 'What you do, in one line', hint: 'Two GP surgeries in Leeds, about 9,000 patients', max: 140 },
]
// The person at the centre of this kind of problem, in the words each kind would use.
const PERSON_AWAY: Record<string, { label: string; hint: string }> = {
  cover: { label: 'The doctor who is off today', hint: 'Dr Kofi Mensah' },
  care: { label: 'The doctor whose patients these are', hint: 'Dr Lin Wei' },
  offboarding: { label: 'The person who left', hint: 'Marcus Ngata' },
  fixtures: { label: 'The official who cannot make it', hint: 'Petra Novak' },
}
const COLLEAGUES: Record<string, string[]> = {
  cover: ['A colleague who could take some of the list', 'Another colleague who could'],
}
// The two people in the loop, named by whoever runs the place. These change the labels only:
// who may start an incident and who may approve one is still decided by the sign-in the server
// checks, never by anything typed here.
const IN_THE_LOOP = [
  { key: 'who_reports', label: 'Who raises problems (reception, a nurse, anyone)', hint: 'Grace Boateng', max: 60 },
  { key: 'who_approves', label: 'Who signs off anything that reaches a patient', hint: 'Dr Amina Yusuf', max: 60 },
]

// The demo sign-ins, relabelled with those names where they have been given.
const ROLE_WORD: Record<string, string> = { analyst: 'staff', approver: 'manager (approves)' }
function identityList(setup: Record<string, any>) {
  const typed: Record<string, string> = {
    analyst: String(setup.who_reports || '').trim(), approver: String(setup.who_approves || '').trim(),
  }
  return IDENTITIES.map((i) => (typed[i.key] ? { ...i, label: `${typed[i.key]} \u00b7 ${ROLE_WORD[i.key]}` } : i))
}
const approverName = (setup: Record<string, any>) => String(setup.who_approves || '').trim() || 'Priya'

// Numbers a person can change to describe a situation nobody wrote in advance. Bounds match the API's.
const SETUP_NUMBERS: Record<string, { key: string; label: string; min: number; max: number }[]> = {
  cover: [
    { key: 'people_booked_in', label: 'People booked in with the doctor who is off', min: 1, max: 12 },
    { key: 'cover_slots', label: 'Slots colleagues have free today', min: 0, max: 12 },
    { key: 'people_we_cannot_reach', label: 'People whose number is out of date', min: 0, max: 12 },
  ],
}
const SETUP_TOGGLES: Record<string, { key: string; label: string }[]> = {
  care: [{ key: 'one_result_is_urgent', label: 'Make one result urgent, so a doctor has to decide' }],
}
const ALWAYS_TOGGLE = { key: 'one_step_fails', label: 'Make one step fail once, to watch Rook recover' }

// The same engine, grouped by the kind of place it is working in. A visitor picks the industry
// closest to theirs first, which is a shorter question than "which of five incident types".
const INDUSTRIES: { key: string; label: string; blurb: string; playbooks: string[] }[] = [
  { key: 'health', label: 'Healthcare', blurb: 'Clinics, practices and anywhere people are booked in to be seen.',
    playbooks: ['cover', 'care'] },
  { key: 'it', label: 'IT & security', blurb: 'Accounts, keys and the access that outlives the person who had it.',
    playbooks: ['offboarding', 'leak'] },
  { key: 'engineering', label: 'Engineering', blurb: 'Production services, deployments and the change that broke one.',
    playbooks: ['outage'] },
  { key: 'sport', label: 'Sport & clubs', blurb: 'Fixtures, venues and officials, and the teams waiting to be told.',
    playbooks: ['fixtures'] },
]
const industryOf = (pb: string) => INDUSTRIES.find((i) => i.playbooks.includes(pb))?.key || 'health'

const PLAYBOOK_NAME: Record<string, string> = {
  offboarding: 'Access & offboarding',
  outage: 'Service outage',
  leak: 'Leaked credential',
  care: 'Care follow-up',
  cover: 'Doctor off sick',
  fixtures: 'Fixture cannot go ahead',
}

const Pill = ({ tone, children }: { tone: string; children: React.ReactNode }) =>
  <span className={`pill tone-${tone}`}>{children}</span>

function useIdentity() {
  const [key, setKey] = useState('analyst')
  useEffect(() => {
    try { const k = sessionStorage.getItem('kw-identity'); if (k) setKey(k) } catch { /* storage unavailable */ }
  }, [])
  const choose = (k: string) => { setKey(k); try { sessionStorage.setItem('kw-identity', k) } catch { /* ignore */ } }
  return [IDENTITIES.find((i) => i.key === key) || IDENTITIES[0], choose] as const
}

function liveState(actions: any[], graph: any): Record<string, string> {
  const m: Record<string, string> = {}
  for (const a of actions) {
    const ok = a.status === 'verified', bad = a.status === 'failed'
    if (a.type === 'disable_account') m[`${a.service}:${a.target}`] = ok ? 'disabled' : bad ? 'disable failed' : m[`${a.service}:${a.target}`]
    if (a.type === 'update_dependent') m[a.target] = ok ? 'moved to new key' : bad ? 'update failed' : m[a.target]
    if (a.type === 'issue_replacement' && ok) m[a.target] = 'replacement issued'
    if (a.type === 'revoke_credential') m[a.target] = ok ? 'revoked' : bad ? 'revoke failed' : m[a.target]
    if (a.type === 'revoke_credential' && ok) (graph?.nodes || []).filter((n: any) => n.kind === 'repo').forEach((n: any) => { m[n.id] = 'leaked key is dead' })
    if (a.type === 'scrub_exposed_secret' && ok) m[`repo:${a.target}`] = 'key removed from file'
    if (a.type === 'update_dependent' && a.result?.rolled_back) m[a.target] = 'rolled back · healthy'
    const svc = `cloud:${a.target}`
    if (a.type === 'pause_pipeline' && ok) m[`pipeline:${a.target}`] = 'paused'
    if (a.type === 'rollback_service') {
      if (ok) {
        m[svc] = 'healthy'
        ;(graph?.nodes || []).filter((n: any) => n.kind === 'revision').forEach((n: any) => {
          m[n.id] = n.status === 'known good' ? 'running · known good' : 'rolled off'
        })
        ;(graph?.nodes || []).forEach((n: any) => {
          if (n.kind === 'caller') m[n.id] = 'healthy'
          if (n.kind === 'alert') m[n.id] = 'cleared'
          if (n.kind === 'host') m[n.id] = 'no longer used'
        })
      } else if (bad) m[svc] = 'still failing after rollback'
    }
    if (a.type === 'resume_pipeline' && ok) m[`pipeline:${a.target}`] = 'resumed, rev blocked'
  }
  return Object.fromEntries(Object.entries(m).filter(([, v]) => v))
}

export default function Page() {
  const [who, setWho] = useIdentity()
  const [me, setMe] = useState<any>(null)
  const [scenarios, setScenarios] = useState<any[]>([])
  const [scenario, setScenario] = useState('cover_clean')
  const [playbook, setPlaybook] = useState('cover')
  const [industry, setIndustry] = useState('health')
  const pickIndustry = (k: string) => {
    setIndustry(k)
    const first = (INDUSTRIES.find((i) => i.key === k)?.playbooks || []).find((pb) => PLAYBOOK_COPY[pb])
    if (first) pickPlaybook(first)
  }
  const pickPlaybook = (k: string) => {
    setPlaybook(k)
    setSetup({})                       // the knobs belong to the problem type that is showing
    const first = scenarios.find((s) => s.playbook === k)
    if (first) setScenario(first.name)
  }
  const [setup, setSetup] = useState<Record<string, any>>({})
  const [reported, setReported] = useState('')
  const [list, setList] = useState<any[] | null>(null)
  const [id, setId] = useState<string | null>(null)
  const [d, setD] = useState<any>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [waking, setWaking] = useState(false)
  const wakeChecks = useRef(0)
  const timer = useRef<any>(null)
  const tl = useRef<HTMLOListElement>(null)
  const nEvents = d?.audit?.length || 0
  useEffect(() => { if (tl.current) tl.current.scrollTop = tl.current.scrollHeight }, [nEvents])

  const loadList = useCallback(async () => {
    try {
      const [m, s, l] = await Promise.all([api(who.token, '/me'), api(who.token, '/scenarios'), api(who.token, '/incidents')])
      setMe(m); setScenarios(s); setList(l); setErr(null)
    } catch (e: any) {
      // A sleeping host is unreachable, or the /api proxy reports a gateway error on its
      // behalf. Any other 5xx means the agent is awake and something else is wrong, so
      // only these are worth waiting out.
      const asleep = e instanceof ApiError && [0, 502, 503, 504].includes(e.status)
      if (asleep && wakeChecks.current < 60) setWaking(true)
      setErr(e.message); setList([])
    }
  }, [who.token])

  // On identity switch keep the open incident; if the new identity can't see it, loadIncident clears it.
  useEffect(() => { setD(null); loadList() }, [loadList])

  // Somebody typing out their own clinic should not lose it to a reload or a stray refresh.
  useEffect(() => {
    try {
      const raw = sessionStorage.getItem('rook-own')
      if (!raw) return
      const saved = JSON.parse(raw)
      if (saved.setup) setSetup(saved.setup)
      if (saved.reported) setReported(saved.reported)
      if (saved.playbook) {
        setPlaybook(saved.playbook); setIndustry(industryOf(saved.playbook))
        setScenario(saved.scenario || 'cover_clean')
      }
    } catch { /* storage unavailable or not ours: start blank */ }
  }, [])
  useEffect(() => {
    try { sessionStorage.setItem('rook-own', JSON.stringify({ setup, reported, playbook, scenario })) }
    catch { /* ignore */ }
  }, [setup, reported, playbook, scenario])

  // The demo agent runs on a free host that sleeps when nobody is using it, and takes
  // up to a minute to come back. Wait for it instead of leaving an error on the screen.
  useEffect(() => {
    if (!waking) return
    let stop = false
    const tick = async () => {
      if (stop) return
      // wakeChecks is a ref, so the budget holds across identity switches and cannot loop.
      if (await reachable()) { if (!stop) { setWaking(false); setErr(null); loadList() }; return }
      if (++wakeChecks.current < 60 && !stop) setTimeout(tick, 3000)
      else if (!stop) setWaking(false)
    }
    const h = setTimeout(tick, 1200)
    return () => { stop = true; clearTimeout(h) }
  }, [waking, loadList])

  const loadIncident = useCallback(async (iid: string) => {
    try {
      const x = await api(who.token, `/incidents/${iid}`)
      setD((prev: any) => {
        if (!prev || prev.report.status !== x.report.status || prev.running !== x.running) loadList()
        return x
      })
      setErr(null)
      return x
    } catch (e: any) {
      if (e instanceof ApiError && e.status === 404) { setD(null); setId(null); setNotice('That incident is not visible to this identity.') }
      else setErr(e.message)
      return null
    }
  }, [who.token, loadList])

  // Poll while the backend reports a run in progress; stop once it settles.
  useEffect(() => {
    if (!id) return
    let stop = false
    const tick = async () => {
      const x = await loadIncident(id)
      if (stop) return
      const settled = x && !x.running && ['closed_verified', 'escalated', 'awaiting_approval', 'ready'].includes(x.report.status)
      timer.current = setTimeout(tick, settled ? 4000 : 700)
    }
    tick()
    return () => { stop = true; clearTimeout(timer.current) }
  }, [id, loadIncident])

  async function act(fn: () => Promise<any>, ok?: string) {
    setBusy(true); setNotice(null)
    try { await fn(); if (ok) setNotice(ok); if (id) await loadIncident(id); await loadList() } catch (e: any) { setNotice(e.message) } finally { setBusy(false) }
  }

  async function create() {
    await act(async () => {
      const body: any = { scenario }
      const own = cleanSetup(setup)
      if (Object.keys(own).length) body.setup = own
      if (reported.trim()) body.reported = reported.trim()
      const inc = await api(who.token, '/incidents', body)
      setId(inc.id)
    })
  }

  const R = d?.report
  const state = R ? INCIDENT_STATE[R.status] || INCIDENT_STATE.open : null
  const pending = R?.actions.filter((a: any) => a.status === 'needs_approval') || []

  const isAnalyst = !!me?.roles.includes('analyst')
  const isApprover = !!me?.roles.includes('approver')

  return (
    <div className="page">
      <div className="frame">
        <nav className="nav" aria-label="Main">
          <a className="brand" href="#top"><Star /> Rook</a>
          <div className="nav-links">
            <a href="#incident">Incident</a>
            <a href="#plan">Plan</a>
            <a href="#verify">Verification</a>
            <a href="#refusals">Limits</a>
            <a href="#timeline">Timeline</a>
          </div>
          <label className="who">
            <span className="sr-only">Who you are using the demo as. Real sign-in is coming soon.</span>
            <select id="who" value={who.key} onChange={(e) => setWho(e.target.value)}>
              {identityList(setup).map((i) => <option key={i.key} value={i.key}>{i.label}</option>)}
            </select>
          </label>
        </nav>

        {waking && (
          <div className="card notice waking" role="status">
            <b>Starting the agent…</b> The demo agent is hosted on a free plan that sleeps when
            nobody is using it, so the first visit takes up to a minute. This page keeps checking
            and starts on its own, no reload needed.
          </div>
        )}

        <HowToUse />

        <header className="hero" id="top">
          <div className="hero-copy">
            <h1>Start with a problem. Rook takes it from there.</h1>
            <p className="lead">Every industry runs on work that falls between its systems: a clinic, an
              engineering team, an IT department, a sports club. Pick the one closest to yours, or tell Rook
              about your own organisation.</p>
            <div className="hero-form">
              <span className="mono small">Industry</span>
              <div className="row industries" role="group" aria-label="Industry">
                {INDUSTRIES.filter((i) => i.playbooks.some((pb) => PLAYBOOK_COPY[pb])).map((i) => (
                  <button key={i.key} className={`chip ind ${industry === i.key ? 'sel' : ''}`}
                    aria-pressed={industry === i.key} onClick={() => pickIndustry(i.key)}>
                    <b>{i.label}</b>
                  </button>
                ))}
              </div>
              <p className="small muted ind-blurb">{INDUSTRIES.find((i) => i.key === industry)?.blurb}</p>
              <span className="mono small">What has gone wrong</span>
              <div className="row playbooks" role="group" aria-label="Incident type">
                {(INDUSTRIES.find((i) => i.key === industry)?.playbooks || []).filter((k) => PLAYBOOK_COPY[k]).map((k) => (
                  <button key={k} className={`chip ${playbook === k ? 'sel' : ''}`} aria-pressed={playbook === k} onClick={() => pickPlaybook(k)}>
                    <b>{PLAYBOOK_NAME[k] || k}</b>
                    <span className="small">{PLAYBOOK_COPY[k].pitch}</span>
                  </button>
                ))}
              </div>
              <label htmlFor="scenario" className="mono small">Sandbox scenario</label>
              <div className="row">
                <select id="scenario" value={scenario} onChange={(e) => setScenario(e.target.value)}>
                  {scenarios.filter((s) => s.playbook === playbook).map((s) => <option key={s.name} value={s.name}>{s.name.replace(/_/g, ' ')}</option>)}
                </select>
                <button className="btn-dark" disabled={busy || !isAnalyst} onClick={create}>{PLAYBOOK_COPY[playbook]?.button}</button>
              </div>
              <p className="small muted">
                {Object.keys(cleanSetup(setup)).length
                  ? <><b>Your own situation.</b> {describeSetup(setup)}</>
                  : scenarios.find((s) => s.name === scenario)?.description}
              </p>
              <YourSituation playbook={playbook} setup={setup} onChange={setSetup}
                reported={reported} onReported={setReported} />
              {me && !isAnalyst && <p className="small muted">{who.label} cannot start incidents.</p>}
            </div>
          </div>
          <aside className="hero-side">
            <div className="card explain">
              <p>Rook connects to the software a company already runs. Staff report a problem, Rook works out what
                is really going on across every system it touches, proposes a fix, waits for a person to approve
                anything that reaches someone outside the building, then checks the result and shows the proof.</p>
              <p>It does not replace your appointment book or your accounting software. It does the chasing and
                coordinating between them that otherwise lands on a member of staff.</p>
            </div>
            <HeroArt />
          </aside>
        </header>

        <HowItWorks />

        <Guide R={R} d={d} me={me} busy={busy} who={who} approver={approverName(setup)}
          onRun={() => act(() => api(who.token, `/incidents/${id}/run`, {}), 'Run started.')}
          onApprover={() => setWho('approver')}
          onTry={(pb: string, sc: string) => { setPlaybook(pb); setScenario(sc); setId(null); setD(null); window.scrollTo({ top: 0, behavior: 'smooth' }) }} />

        <p className="strip mono" role="note">
          <span>sandbox</span><span>mock integrations</span><span>org {me?.org || '…'}</span>
          <span>{me ? me.roles.join(' + ') : 'loading'}</span><span>sign-in coming soon</span>
        </p>

        {err && !waking && (
          <div className="card alert" role="alert">
            <b>Something went wrong.</b> {err}{' '}
            <button className="btn-outline" onClick={() => (id ? loadIncident(id) : loadList())}>Retry</button>
          </div>
        )}
        {notice && <div className="card notice" role="status">{notice}</div>}

        <section className="section">
          <SectionTitle label="Incidents" text="Each run is stored with its plan, checkpoints and audit trail." />
          {list === null && <p className="muted">Loading…</p>}
          {list?.length === 0 && !waking && <p className="muted">No incidents yet for this organisation. Start one above.</p>}
          <ul className="chips">
            {list?.map((i) => {
              const st = INCIDENT_STATE[i.status] || INCIDENT_STATE.open
              return (
                <li key={i.id}>
                  <button className={`chip ${i.id === id ? 'sel' : ''}`} aria-pressed={i.id === id}
                    onClick={() => { setNotice(null); setId(i.id) }}>
                    <span className="mono small">{time(i.created_at)}</span>
                    <b>{i.playbook} · {i.scenario.replace(/_/g, ' ')}</b>
                    <Pill tone={st.tone}>{st.label}</Pill>
                  </button>
                </li>
              )
            })}
          </ul>
        </section>

        <div aria-live="polite">
          {id && !R && !err && <p className="muted section">Loading incident…</p>}

          {R && state && (<>
            {/* Overview */}
            <section className="section" id="incident">
              <div className="overview">
                <div>
                  <p className="mono small muted">
                    {R.incident.organisation?.name ? `${R.incident.organisation.name} · ` : ''}
                    {R.playbook?.name} · {R.incident.id} · severity {R.incident.severity} · ticket {R.incident.ticket || 'none'}
                  </p>
                  <h2 className="h2">{R.incident.title}</h2>
                  {R.incident.reported && (
                    <p className="reported">“{R.incident.reported}”
                      <span className="small muted"> — as it was reported</span></p>
                  )}
                  <p className="lead">{R.summary}</p>
                  <div className="row">
                    {isAnalyst && !d.running && ['ready', 'escalated', 'open', 'awaiting_approval'].includes(R.status) && (
                      <button className="btn-dark" disabled={busy} onClick={() => act(() => api(who.token, `/incidents/${id}/run`, {}), 'Run started.')}>
                        {R.status === 'ready' ? 'Run plan' : 'Run again'}
                      </button>
                    )}
                    {isAnalyst && d.running && (
                      <button className="btn-outline" disabled={busy} onClick={() => act(() => api(who.token, `/incidents/${id}/cancel`, {}), 'Cancel requested.')}>Cancel run</button>
                    )}
                  </div>
                </div>
                <div className={`status-card tone-${state.tone}`}>
                  <span className="mono small">status</span>
                  <b>{d.running ? 'Running' : state.label}</b>
                  <span className="small">{d.running ? 'Rook is making and checking changes.' : state.text}</span>
                </div>
              </div>
              <div className="stats">
                <Stat dark={false} label="Steps verified" note="checked against the systems, not Rook's word"
                  value={`${R.actions.filter((a: any) => a.status === 'verified').length}/${R.actions.length}`}
                  of={{ done: R.actions.filter((a: any) => a.status === 'verified').length, total: R.actions.length }} />
                <Stat dark label="Proof it worked" note="every one must pass before anything is called done"
                  value={`${R.conditions.filter((c: any) => c.result === true).length}/${R.conditions.length}`}
                  of={{ done: R.conditions.filter((c: any) => c.result === true).length, total: R.conditions.length }} />
                <Stat dark label="Work it replaced" note={`across ${R.metrics.systems_touched} system${R.metrics.systems_touched === 1 ? '' : 's'}`}
                  value={R.metrics.manual_steps_replaced} />
                <Stat dark={false} label={R.metrics.contain_label}
                  note={R.metrics.declined > 0
                    ? `${R.metrics.declined} step${R.metrics.declined === 1 ? '' : 's'} refused on purpose`
                    : R.metrics.waiting_on_a_person > 0
                      ? `${R.metrics.waiting_on_a_person} waiting on a person`
                      : 'nothing refused'}
                  value={R.metrics.seconds_to_contain != null ? `${R.metrics.seconds_to_contain}s` : '—'} />
              </div>
            </section>

            {/* Approval */}
            {pending.map((a: any) => {
              const ready = a.depends_on.every((x: string) => R.actions.find((y: any) => y.id === x)?.status === 'verified')
              return (
                <section key={a.id} className="section" id="approval">
                  <div className="approval" aria-labelledby={`ap-${a.id}`}>
                    <div>
                      <h2 id={`ap-${a.id}`} className="h3"><mark>{ready ? 'Approval needed now' : 'Approval will be needed'}</mark></h2>
                      <p className="lead">{a.summary}</p>
                      {!ready && <p className="small">Rook pauses here once the earlier steps are verified. An approver can confirm in advance; policy is re-checked just before it runs.</p>}
                      <ul className="facts">
                        <li><b>Why approval:</b> {a.policy.reason}</li>
                        <li><b>Can it be undone?</b> {a.undo}</li>
                        <li><b>Safety check:</b> runs only after steps {a.depends_on.map((x: string) => R.actions.findIndex((y: any) => y.id === x) + 1).join(', ')} are verified.</li>
                      </ul>
                    </div>
                    <div className="approval-actions">
                      {isApprover ? (<>
                        <button className="btn-lime" disabled={busy} onClick={() => act(() => api(who.token, `/incidents/${id}/actions/${a.id}/approve`, {}), 'Approved. Rook is continuing.')}>Approve: {ACTION_LABEL[a.type] || a.type}</button>
                        <button className="btn-ghost" disabled={busy} onClick={() => act(() => api(who.token, `/incidents/${id}/actions/${a.id}/reject`, { note: 'Rejected from dashboard' }), 'Rejected. The incident will be escalated.')}>Reject</button>
                      </>) : <p className="small">Waiting for someone with the approver role. Switch to “{approverName(setup)}” to approve.</p>}
                    </div>
                  </div>
                </section>
              )
            })}

            {R.playbook?.key === 'cover' && <DayStrip R={R} />}

            {/* Graph + findings */}
            <section className="section">
              <SectionTitle label="What is connected" text="Discovered by Rook, with each node updated as actions are verified." />
              <div className="card"><Graph graph={R.incident.graph} live={liveState(R.actions, R.incident.graph)} playbook={R.playbook?.key} /></div>
            </section>

            <section className="section">
              <SectionTitle label="Findings" text="What the evidence shows, before anything is changed." />
              <ul className="findings">
                {R.incident.findings.map((f: any, i: number) => (
                  <li key={i} className="card finding">
                    <Pill tone={f.severity === 'high' ? 'bad' : f.severity === 'medium' ? 'warn' : 'mute'}>{f.severity}</Pill>
                    <span>{f.text}</span>
                  </li>
                ))}
              </ul>
            </section>

            {/* What Rook refused to do */}
            {R.refusals?.length > 0 && (
              <section className="section" id="refusals">
                <SectionTitle label="What Rook refused to do"
                  text="Deliberate limits, not gaps. An agent that acts on what it cannot explain is the dangerous kind." />
                <ul className="findings">
                  {R.refusals.map((r: any, i: number) => (
                    <li key={i} className="card finding">
                      <Pill tone={r.kind === 'blocked' ? 'bad' : r.kind === 'waiting' ? 'warn' : 'mute'}>
                        {r.kind === 'blocked' ? 'blocked' : r.kind === 'waiting' ? 'needs a person' : 'declined'}
                      </Pill>
                      <span><b>{r.what}.</b> {r.why}{r.rule ? <span className="small dim"> · policy {r.rule}</span> : null}</span>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {/* Plan */}
            <section className="section" id="plan">
              <SectionTitle label="Plan" text="Steps run in this order. Each one is checked against live state before the next can start." />
              <PlanFlow actions={R.actions} />
              <ol className="plan">
                {R.actions.map((a: any, i: number) => {
                  const s = actionState(a)
                  const dark = a.risk === 'high'
                  return (
                    <li key={a.id} className={`step ${dark ? 'step-dark' : ''}`}>
                      <div className="step-head">
                        <span className="num mono">{String(i + 1).padStart(2, '0')}</span>
                        <h3 className="h4"><mark>{ACTION_LABEL[a.type] || a.type}</mark></h3>
                        <Pill tone={s.tone}>{s.label}</Pill>
                        {a.risk === 'high' && <Pill tone="bad">irreversible</Pill>}
                        {a.risk === 'medium' && <Pill tone="warn">production change</Pill>}
                      </div>
                      <p className="mono small target">{a.target}</p>
                      <p>{a.summary}</p>
                      <p className="small dim">
                        Policy {a.policy.rule}: {a.policy.reason}
                        {a.depends_on.length > 0 && <> · after step {a.depends_on.map((x: string) => R.actions.findIndex((y: any) => y.id === x) + 1).join(', ')}</>}
                        {a.retries > 0 && <> · {a.retries} failed attempt{a.retries > 1 ? 's' : ''}</>}
                      </p>
                      {a.result?.error && <p className="small err-text">{a.result.error}</p>}
                      {(Object.keys(a.evidence || {}).length > 0) && (
                        <details><summary><Arrow /> Verification evidence</summary><pre>{JSON.stringify(a.evidence, null, 2)}</pre></details>
                      )}
                    </li>
                  )
                })}
              </ol>
            </section>

            <Recovery R={R} audit={d.audit} checkpoints={d.checkpoints} />

            {/* Verification */}
            <section className="section" id="verify">
              <SectionTitle label="Verification" text="Fixed before any change was made, and measured by probing live state, never by trusting a tool’s reply." />
              <div className="card table-card">
                <table>
                  <thead><tr><th scope="col">Check</th><th scope="col">Result</th><th scope="col">Evidence</th></tr></thead>
                  <tbody>
                    {R.conditions.map((c: any) => {
                      const r = c.result === true ? ['ok', 'Pass'] : c.result === false ? ['bad', 'Fail'] : ['warn', c.evaluated_at ? 'Inconclusive' : 'Not checked yet']
                      return (
                        <tr key={c.id}>
                          <td>{c.description}<div className="small muted">{c.expected}</div></td>
                          <td><Pill tone={r[0]}>{r[1]}</Pill></td>
                          <td><code className="small">{Object.entries(c.evidence || {}).map(([k, v]) => `${k}: ${JSON.stringify(v)}`).join(' · ') || '—'}</code></td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </section>

            {/* Timeline */}
            <section className="section" id="timeline">
              <SectionTitle label="Timeline" text={`${d.audit.length} audit events, append-only, straight from the backend.`} />
              <div className="soft">
                <ol className="timeline" ref={tl} tabIndex={0} aria-label="Audit events, oldest first">
                  {d.audit.map((e: any) => (
                    <li key={e.n} className={`ev-${eventTone(e.event)}`}>
                      <time className="mono small">{time(e.ts)}</time><span>{eventText(e)}</span>
                    </li>
                  ))}
                </ol>
              </div>
            </section>

            {/* Report */}
            <section className="section">
              <SectionTitle label="Report" text="What a reviewer needs to sign off, or to pick up an escalation." />
              <div className="report">
                <div>
                  <p className="lead">{R.summary}</p>
                  {R.closure_blocked_reason && <p className="small"><b>Why it is not closed:</b> {R.closure_blocked_reason}</p>}
                  <p className="small">
                    <b>What this replaced:</b> {R.metrics.manual_steps_replaced} steps a person would have carried out
                    or checked by hand across {R.metrics.systems_touched} system{R.metrics.systems_touched === 1 ? '' : 's'},
                    including {R.metrics.independent_checks} independent verification{R.metrics.independent_checks === 1 ? '' : 's'}
                    {R.metrics.human_decisions > 0 && <> · {R.metrics.human_decisions} decision{R.metrics.human_decisions === 1 ? '' : 's'} escalated to a person</>}
                    {R.metrics.refusals > 0 && <> · {R.metrics.refusals} action{R.metrics.refusals === 1 ? '' : 's'} refused</>}
                  </p>
                  {R.approvals.length > 0 && <p className="small">Approvals: {R.approvals.map((a: any) => `${a.decision} by ${a.by} at ${time(a.ts)}`).join('; ')}</p>}
                  {R.follow_ups.length > 0 && (<>
                    <h3 className="h4" style={{ marginTop: 16 }}><mark>Left for a person</mark></h3>
                    <ul className="facts">{R.follow_ups.map((f: string, i: number) => <li key={i}>→ {f}</li>)}</ul>
                  </>)}
                  <div className="row">
                    <button className="btn-dark" disabled={busy} onClick={() => act(async () => {
                      const r = await fetch(`/api/incidents/${id}/evidence`, { headers: { Authorization: `Bearer ${who.token}` } })
                      if (!r.ok) throw new Error('Could not build the evidence pack.')
                      const u = URL.createObjectURL(await r.blob()); const el = document.createElement('a')
                      el.href = u; el.download = `${R.incident.id}-evidence.md`; el.click(); URL.revokeObjectURL(u)
                    })}>Download evidence pack (.md)</button>
                    <button className="btn-outline" onClick={() => {
                      const blob = new Blob([JSON.stringify({ report: R, audit: d.audit }, null, 2)], { type: 'application/json' })
                      const u = URL.createObjectURL(blob); const el = document.createElement('a')
                      el.href = u; el.download = `${R.incident.id}-report.json`; el.click(); URL.revokeObjectURL(u)
                    }}>Raw JSON</button>
                  </div>
                  <p className="small muted">Audit log is hash-chained: {R.invariants.audit_chain_intact ? 'chain verified intact' : 'CHAIN BROKEN'} · {R.metrics.checkpoints} checkpoints.</p>
                </div>
                <ul className="facts invariants">
                  {Object.entries(R.invariants).map(([k, v]) => (
                    <li key={k}><Pill tone={v ? 'ok' : 'bad'}>{v ? 'yes' : 'no'}</Pill> {k.replace(/_/g, ' ')}</li>
                  ))}
                </ul>
              </div>
            </section>
          </>)}

          {!id && !err && (
            <section className="section">
              <div className="soft cta">
                <div>
                  <h2 className="h3">What a company is actually buying</h2>
                  <ul className="facts">
                    <li>One place to see the problems nobody has finished yet.</li>
                    <li>Connections into the software the company already runs.</li>
                    <li>An agent that works out what happened and coordinates the fix across all of them.</li>
                    <li>Approval on anything sensitive, a full audit trail, and proof the work actually landed.</li>
                  </ul>
                  <p className="small muted">Rook does not replace a clinic&rsquo;s appointment book, a club&rsquo;s
                    fixture list or a company&rsquo;s accounting software. It works across them, on the problems that
                    otherwise need a person to chase information and coordinate a fix by hand.</p>
                  <h3 className="h4" style={{ marginTop: 18 }}>Try one</h3>
                  <p><b>A doctor calls in sick:</b> twelve people are booked in and none of them know. Rook finds who
                    is affected, finds colleagues with room, moves each appointment and tells each person. Anyone it
                    cannot reach is left exactly where they are and handed to reception, because moving someone who
                    will not hear about it is worse than leaving it alone.</p>
                  <p><b>Things marked done that never happened:</b> a referral, a test result and a prescription the
                    record calls finished. Rook asks the clinic, the pharmacy and the doctor they were meant to
                    reach. Three of the four never happened. The fourth really did, so Rook says so and leaves it.</p>
                  <p><b>A pitch is shut on a Saturday:</b> three matches, six clubs and three referees. Rook finds
                    which pitches are open, moves each match, puts an available official on the one whose referee is
                    away, and tells both clubs. A club whose group chat is dead keeps its match where it is.</p>
                  <p><b>The same engine on infrastructure:</b> a contractor&rsquo;s API key still running two services,
                    a service failing right after a change, a live key found in a repository. Same investigate,
                    approve, verify, prove.</p>
                </div>
                <Star big />
              </div>
            </section>
          )}
        </div>

        <footer className="footer mono small">Rook · the operations agent that proves the fix · built by Keywarden · every connected system here is a sandboxed mock with synthetic data</footer>
      </div>
    </div>
  )
}

const SETUP_WORDS: Record<string, (v: any) => string> = {
  organisation: (v) => `${v}`,
  we_do: (v) => `${v}`,
  person_away: (v) => `${v} is away`,
  colleagues: (v) => `${v.join(' and ')} can cover`,
  people_booked_in: (v) => `${v} booked in`,
  cover_slots: (v) => `${v} slot${v === 1 ? '' : 's'} free`,
  people_we_cannot_reach: (v) => `${v} we cannot reach`,
  one_result_is_urgent: () => 'one result urgent',
  one_step_fails: () => 'one step will fail once',
}

// What actually goes to the API: trimmed, blanks dropped, so an empty box means "use the example"
// rather than an empty name in somebody's evidence pack.
function cleanSetup(setup: Record<string, any>) {
  const out: Record<string, any> = {}
  for (const [k, v] of Object.entries(setup)) {
    if (Array.isArray(v)) { const list = v.map((x) => String(x).trim()).filter(Boolean); if (list.length) out[k] = list }
    else if (typeof v === 'string') { const t = v.trim(); if (t) out[k] = t }
    else if (v !== '' && v !== false && v !== null && v !== undefined) out[k] = v
  }
  return out
}

function describeSetup(setup: Record<string, any>) {
  const parts = Object.entries(cleanSetup(setup))
    .map(([k, v]) => (SETUP_WORDS[k] ? SETUP_WORDS[k](v) : `${k} ${v}`))
  return parts.join(' \u00b7 ') + '. Rook works the plan and the checks out from that.'
}

function YourSituation({ playbook, setup, onChange, reported, onReported }: {
  playbook: string; setup: Record<string, any>; onChange: (s: Record<string, any>) => void
  reported: string; onReported: (v: string) => void
}) {
  const numbers = SETUP_NUMBERS[playbook] || []
  const toggles = [...(SETUP_TOGGLES[playbook] || []), ALWAYS_TOGGLE]
  const away = PERSON_AWAY[playbook]
  const colleagues = COLLEAGUES[playbook] || []
  const set = (k: string, v: any) => {
    const next = { ...setup }
    if (v === '' || v === false || v === null) delete next[k]
    else next[k] = v
    onChange(next)
  }
  const setColleague = (i: number, v: string) => {
    const list = [...(setup.colleagues || ['', ''])]
    list[i] = v
    set('colleagues', list.some((x) => String(x).trim()) ? list : '')
  }
  const n = Object.keys(cleanSetup(setup)).length + (reported.trim() ? 1 : 0)
  const text = (f: { key: string; label: string; hint: string; max?: number }) => (
    <label key={f.key} className="own-text">
      <span className="small">{f.label}</span>
      <input type="text" value={setup[f.key] ?? ''} placeholder={f.hint} maxLength={f.max || 60}
        onChange={(e) => set(f.key, e.target.value)} />
    </label>
  )
  return (
    <details className="own" open>
      <summary>
        <b>Tell Rook about your own organisation</b>
        {n > 0 && <span className="own-count mono">{n} filled in</span>}
        <span className="howto-chev" aria-hidden="true">+</span>
      </summary>
      <div className="own-body">
        <p className="small muted">Fill in as much or as little as you like. Whatever you type comes back in the
          incident, the plan, the approval requests and the evidence pack. Anything you leave blank uses the
          sandbox&rsquo;s own example instead.</p>

        <span className="own-group mono small">Who you are</span>
        {ABOUT_YOU.map(text)}

        <label className="own-text">
          <span className="small">What are you reporting? In your own words.</span>
          <textarea value={reported} maxLength={300} rows={2} onChange={(e) => onReported(e.target.value)}
            placeholder="Dr Mensah has just called in sick and we have a full list this morning. Nobody has told the patients yet." />
          <span className="own-left mono small">{300 - reported.length} characters left</span>
        </label>

        <span className="own-group mono small">Who is in the loop</span>
        {IN_THE_LOOP.map(text)}
        <p className="small muted">These are names on the sign-in menu, nothing more. Who is allowed to start an
          incident and who is allowed to approve one is still decided by the sign-in itself, which the agent
          checks on every request.</p>

        {(away || colleagues.length > 0) && <span className="own-group mono small">Your people</span>}
        {away && text({ key: 'person_away', ...away })}
        {colleagues.map((label, i) => (
          <label key={label} className="own-text">
            <span className="small">{label}</span>
            <input type="text" value={setup.colleagues?.[i] ?? ''} placeholder={i === 0 ? 'Dr Ruth Adeyemi' : 'Dr Tom Hale'}
              maxLength={60} onChange={(e) => setColleague(i, e.target.value)} />
          </label>
        ))}

        {numbers.length > 0 && <span className="own-group mono small">Your numbers</span>}
        {numbers.map((f) => (
          <label key={f.key} className="own-field">
            <span className="small">{f.label}</span>
            <input type="number" min={f.min} max={f.max} inputMode="numeric"
              value={setup[f.key] ?? ''} placeholder="example"
              onChange={(e) => set(f.key, e.target.value === '' ? '' : Math.max(f.min, Math.min(f.max, Number(e.target.value))))} />
          </label>
        ))}

        <span className="own-group mono small">Make it harder</span>
        {toggles.map((t) => (
          <label key={t.key} className="own-check">
            <input type="checkbox" checked={!!setup[t.key]} onChange={(e) => set(t.key, e.target.checked)} />
            <span className="small">{t.label}</span>
          </label>
        ))}
        {n > 0 && (
          <button className="btn-outline own-clear" onClick={() => { onChange({}); onReported('') }}>
            Clear and use the written example
          </button>
        )}
      </div>
    </details>
  )
}

// The plan as the engine actually holds it: columns are dependency depth, so what can run at the
// same time sits in the same column and nothing is drawn as a queue that is not one.
function PlanFlow({ actions }: { actions: any[] }) {
  if (!actions.length) return null
  const byId: Record<string, any> = Object.fromEntries(actions.map((a) => [a.id, a]))
  const depth: Record<string, number> = {}
  const of = (a: any): number => {
    if (depth[a.id] != null) return depth[a.id]
    depth[a.id] = 0                                    // set first: a cycle cannot hang the page
    const deps = (a.depends_on || []).map((x: string) => byId[x]).filter(Boolean)
    depth[a.id] = deps.length ? 1 + Math.max(...deps.map(of)) : 0
    return depth[a.id]
  }
  actions.forEach(of)
  const cols: any[][] = []
  actions.forEach((a) => { (cols[depth[a.id]] ||= []).push(a) })
  const n = (a: any) => actions.findIndex((x) => x.id === a.id) + 1
  return (
    <div className="flow-wrap">
      <div className="flow" style={{ gridTemplateColumns: `repeat(${cols.length}, minmax(178px, 1fr))` }}>
        {cols.map((col, i) => (
          <div className="flow-col" key={i}>
            <span className="mono small flow-head">{i === 0 ? 'first' : i === 1 ? 'then' : 'after that'}</span>
            {col.map((a) => {
              const st = actionState(a)
              return (
                <div key={a.id} className={`flow-node flow-${st.tone}`} title={a.summary}>
                  <span className="mono small">{String(n(a)).padStart(2, '0')} · {st.label}</span>
                  <b>{ACTION_LABEL[a.type] || a.type}</b>
                  <span className="small dim">{a.target}</span>
                </div>
              )
            })}
          </div>
        ))}
      </div>
    </div>
  )
}

function HowToUse() {
  const steps = [
    ['Pick a problem and press the button', 'Each one is a real situation. Start with “A doctor calls in sick”, scenario “cover clean”.'],
    ['Or put your own organisation in', 'Open “Tell Rook about your own organisation” and type your clinic or company name, who is off, who can cover and what you are reporting. Everything that comes back is written about you.'],
    ['Read what Rook found', 'It has looked across every connected system and changed nothing yet. The Findings say who is affected and why.'],
    ['Press Run plan', 'Watch the Plan and the Timeline. Each step is checked against the system itself before the next one starts.'],
    ['Approve when it stops', 'Rook will not message a patient without a person saying yes. Switch the menu at the top right to the manager and approve.'],
    ['Check the proof, not the promise', 'Verification lists what was confirmed against the live systems. Closed means every one of them passed.'],
    ['See what it refused to do', 'Open “Limits”. Try scenario “cover unreachable” to watch Rook deliberately leave one appointment alone, and say why.'],
    ['Take the evidence away', 'Download the evidence pack at the bottom: every action, approval, check and a tamper-evident audit trail.'],
  ]
  return (
    <details className="howto">
      <summary>
        <span className="howto-badge mono">Start here</span>
        <b>How to use this in two minutes</b>
        <span className="howto-chev" aria-hidden="true">+</span>
      </summary>
      <ol className="howto-steps">
        {steps.map(([t, d], i) => (
          <li key={t}>
            <span className="howto-num mono">{String(i + 1).padStart(2, '0')}</span>
            <div><b>{t}</b><span className="small">{d}</span></div>
          </li>
        ))}
      </ol>
      <p className="small muted howto-foot">Every system Rook touches here is a sandboxed copy with made-up data.
        Nothing real is changed, and no real person is contacted.</p>
    </details>
  )
}

function HowItWorks() {
  const steps = [
    ['A problem comes in', 'A doctor calls in sick, an order is late, someone leaves. Staff raise it, or a connected system does.'],
    ['Rook investigates', 'It reads every system the problem touches and works out who and what is actually affected. Nothing is changed yet.'],
    ['Staff approve', 'Rook proposes the fix as ordered steps. Anything that reaches a person outside the building waits for someone to say yes.'],
    ['Rook proves it', 'It checks the result against the systems themselves. Whatever it could not finish stays open, named, and with the reason.'],
  ]
  return (
    <ol className="how" aria-label="How Rook works">
      {steps.map(([t, x], i) => (
        <li key={t}><span className="mono small">{String(i + 1).padStart(2, '0')}</span><b>{t}</b><span className="small">{x}</span></li>
      ))}
    </ol>
  )
}

/** Plain-language "what now?" for whoever is looking at the screen. */
function Guide({ R, d, me, busy, who, approver, onRun, onApprover, onTry }: any) {
  const isApprover = !!me?.roles.includes('approver'), isAnalyst = !!me?.roles.includes('analyst')
  let step = '', title = '', text = '', action: React.ReactNode = null
  if (!R) {
    step = 'Start'; title = 'Pick a problem above, then press the button.'
    text = 'Five kinds, from a doctor calling in sick to a key found in a repository. Or open “Tell Rook about your own organisation” and put your own clinic or company in. Every system behind them is a sandboxed copy, so nothing real is touched.'
    if (me && !isAnalyst) text = `${who.label} can only watch. Switch to Sam in the top-right menu to start an incident.`
  } else if (d?.running) {
    step = 'Working'; title = 'Rook is fixing the incident now.'
    text = 'Watch the Plan steps turn green and the Timeline fill in. If a step fails, the Failure and recovery panel shows what Rook did about it.'
  } else if (R.status === 'ready') {
    step = 'Step 2 of 4'; title = 'Rook has investigated and made a plan. Nothing has changed yet.'
    text = 'Skim the Findings and the Plan below, then start the fix.'
    if (isAnalyst) action = <button className="btn-dark" disabled={busy} onClick={onRun}>Run plan</button>
  } else if (R.status === 'awaiting_approval') {
    step = 'Step 3 of 4'; title = 'Rook is waiting for a person to approve a step that cannot be undone.'
    text = isApprover ? 'Read the black approval card below, then approve or reject it.'
      : `Only someone with approver rights can sign off, like ${approver}, the manager.`
    if (!isApprover) action = <button className="btn-lime" onClick={onApprover}>Switch to {approver} (approver)</button>
    else action = <button className="btn-lime" onClick={() => document.getElementById('approval')?.scrollIntoView({ behavior: 'smooth' })}>Go to the approval</button>
  } else if (R.status === 'closed_verified') {
    step = 'Done'; title = 'Fixed, and proven fixed: every check passed on the live systems.'
    text = 'Download the evidence pack from the Report at the bottom, or see how Rook handles a fix that does not work.'
    action = R.playbook?.key === 'outage'
      ? <button className="btn-outline" onClick={() => onTry('outage', 'outage_wrong_cause')}>Try: rollback does not help</button>
      : <button className="btn-outline" onClick={() => onTry('offboarding', 'faulty_update')}>Try: a service breaks mid-fix</button>
  } else if (R.status === 'escalated') {
    step = 'Handed to a person'; title = 'Rook stopped safely instead of pretending it worked.'
    text = 'The Report at the bottom says exactly which checks failed and what a person needs to do next ("Left for a person").'
  } else {
    step = 'In progress'; title = R.summary; text = ''
  }
  return (
    <section className="guide" aria-live="polite" aria-label="What to do next">
      <span className="mono small">{step}</span>
      <div><b>{title}</b>{text && <p className="small">{text}</p>}</div>
      {action}
    </section>
  )
}

function SectionTitle({ label, text }: { label: string; text: string }) {
  return (
    <div className="section-title">
      <h2><mark>{label}</mark></h2>
      <p className="small">{text}</p>
    </div>
  )
}

function Stat({ label, value, dark, note, of }: {
  label: string; value: any; dark: boolean; note?: string; of?: { done: number; total: number }
}) {
  // A meter only where there is a whole to be a part of. Everything else is a plain number,
  // which reads faster than a chart would.
  const pct = of && of.total ? Math.round((of.done / of.total) * 100) : null
  return (
    <div className={`stat ${dark ? 'stat-dark' : ''}`}>
      <span className="small"><mark>{label}</mark></span>
      <div className="stat-body">
        <b>{value}</b>
        {pct !== null && (
          <div className="meter" role="img" aria-label={`${of!.done} of ${of!.total}`}>
            <span style={{ width: `${pct}%` }} />
          </div>
        )}
        {note && <span className="stat-note small">{note}</span>}
      </div>
    </div>
  )
}

/* The day, before and after. Times and labels carry the meaning; colour only repeats it. */
function DayStrip({ R }: { R: any }) {
  const rows = (R.incident.relationships || []).filter((r: any) => r.rel === 'booking')
  if (!rows.length) return null
  const byTarget: Record<string, any> = {}
  for (const a of R.actions) if (a.type === 'move_appointment') byTarget[a.target] = a
  const moved = rows.filter((r: any) => byTarget[r.appointment]?.status === 'verified').length
  return (
    <section className="section">
      <SectionTitle label="The day" text={`${rows.length} people were booked in. ${moved} have been moved to a doctor who is in; the rest are still on the absent doctor's list.`} />
      <ul className="day">
        {rows.map((r: any) => {
          const a = byTarget[r.appointment]
          const done = a?.status === 'verified'
          return (
            <li key={r.appointment} className={`day-row ${done ? 'done' : 'open'}`}>
              <span className="mono day-time">{r.time}</span>
              <span className="day-who"><b>{r.patient_name}</b><span className="small">{r.reason}</span></span>
              <span className="day-arrow mono" aria-hidden="true">→</span>
              <span className="mono day-new">{done ? `${r.new_time} · ${r.to_doctor_name}` : '—'}</span>
              <Pill tone={done ? 'ok' : 'warn'}>{done ? 'moved and told' : 'left for reception'}</Pill>
            </li>
          )
        })}
      </ul>
    </section>
  )
}

const Arrow = () => (
  <svg className="arrow" viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
    <circle cx="12" cy="12" r="11" fill="currentColor" />
    <path d="M8 16 L16 8 M10 8 H16 V14" stroke="var(--lime)" strokeWidth="2" fill="none" strokeLinecap="round" />
  </svg>
)

const Star = ({ big }: { big?: boolean }) => (
  <svg viewBox="0 0 24 24" width={big ? 96 : 20} height={big ? 96 : 20} aria-hidden="true" className={big ? 'star-big' : ''}>
    <path d="M12 0 C13 8 16 11 24 12 C16 13 13 16 12 24 C11 16 8 13 0 12 C8 11 11 8 12 0Z" fill={big ? 'var(--lime)' : 'currentColor'} stroke={big ? 'var(--ink)' : 'none'} />
  </svg>
)

function HeroArt() {
  return (
    <svg className="hero-art" viewBox="0 0 320 240" role="img" aria-label="A key inside orbit rings, with check marks">
      <ellipse cx="170" cy="130" rx="130" ry="46" fill="none" stroke="var(--ink)" strokeWidth="1.5" transform="rotate(-12 170 130)" />
      <ellipse cx="170" cy="130" rx="110" ry="34" fill="none" stroke="var(--ink)" strokeWidth="1.5" transform="rotate(14 170 130)" />
      <g transform="translate(110 70) rotate(-30 50 60)">
        <circle cx="40" cy="60" r="34" fill="var(--lime)" stroke="var(--ink)" strokeWidth="3" />
        <circle cx="40" cy="60" r="12" fill="#fff" stroke="var(--ink)" strokeWidth="3" />
        <rect x="72" y="52" width="92" height="16" rx="3" fill="var(--ink)" />
        <rect x="132" y="66" width="12" height="20" fill="var(--ink)" />
        <rect x="152" y="66" width="12" height="14" fill="var(--ink)" />
      </g>
      <g transform="translate(250 40)"><circle r="18" fill="var(--ink)" /><path d="M-7 0 L-2 6 L8 -6" stroke="var(--lime)" strokeWidth="3" fill="none" strokeLinecap="round" /></g>
      <g transform="translate(286 92)"><circle r="14" fill="var(--lime)" stroke="var(--ink)" strokeWidth="2" /><path d="M-5 0 L-1 4 L6 -4" stroke="var(--ink)" strokeWidth="2.5" fill="none" strokeLinecap="round" /></g>
      <g transform="translate(262 196)"><circle r="16" fill="var(--ink)" /><path d="M-6 -6 L6 6 M6 -6 L-6 6" stroke="#fff" strokeWidth="2.5" strokeLinecap="round" /></g>
      <path d="M40 190 C42 202 46 206 58 208 C46 210 42 214 40 226 C38 214 34 210 22 208 C34 206 38 202 40 190Z" fill="var(--ink)" />
      <path d="M70 40 C71 46 73 48 79 49 C73 50 71 52 70 58 C69 52 67 50 61 49 C67 48 69 46 70 40Z" fill="var(--ink)" />
      <circle cx="96" cy="200" r="5" fill="var(--lime)" stroke="var(--ink)" /><circle cx="214" cy="20" r="4" fill="var(--lime)" />
    </svg>
  )
}

function Recovery({ R, audit, checkpoints }: { R: any; audit: any[]; checkpoints: any[] }) {
  const failures = R.tool_calls.filter((c: any) => !['ok', 'rollback_ok', 'rollback_failed'].includes(c.outcome))
  const rollbacks = audit.filter((e) => e.event === 'rolled_back')
  const restored = audit.filter((e) => e.event === 'checkpoint_restored')
  return (
    <section className="section">
      <SectionTitle label="Failure and recovery" text="What went wrong, what Rook checked, and what it did about it." />
      {!failures.length && !restored.length && !rollbacks.length ? (
        <div className="soft"><p className="muted">No failed tool calls so far. {checkpoints.length} checkpoints saved.</p></div>
      ) : (
        <div className="dark-panel">
          {restored.map((e) => <div key={e.n} className="col"><span className="mono small lime">restart</span><p>{eventText(e)}</p></div>)}
          {rollbacks.map((e) => (
            <div key={e.n} className="recovery-row">
              <div className="col"><span className="mono small lime">01 · broken update</span><p>{e.data.target} accepted the new key but failed its independent check.</p></div>
              <div className="col"><span className="mono small lime">02 · rollback</span><p>{eventText(e)}.</p><p className="small dim">{e.data.reason}</p></div>
              <div className="col"><span className="mono small lime">03 · result</span><p className={e.data.healthy_after_rollback ? 'lime' : 'err-text-dark'}>{e.data.healthy_after_rollback ? 'Service healthy again. Revocation held back; escalated to a person.' : 'Still unhealthy after rollback. Escalated.'}</p></div>
            </div>
          ))}
          {failures.map((f: any) => {
            const a = R.actions.find((x: any) => x.id === f.action)
            const after = audit.filter((e) => e.data?.action === f.action && e.ts >= f.ts)
            const reconcile = after.find((e) => e.event.startsWith('reconcile'))
            const cp = checkpoints.find((c) => c.ts >= f.ts && c.data?.action === f.action)
            const next = R.tool_calls.find((c: any) => c.action === f.action && c.attempt === f.attempt + 1)
            const last = f === failures.filter((x: any) => x.action === f.action).slice(-1)[0]
            return (
              <div key={f.n} className="recovery-row">
                <div className="col">
                  <span className="mono small lime">01 · failure</span>
                  <p><b>Attempt {f.attempt}: {ACTION_LABEL[a?.type] || f.action}</b> on {a?.target}</p>
                  <p className="small dim">{f.data.error || f.outcome}</p>
                </div>
                <div className="col">
                  <span className="mono small lime">02 · checkpoint + inspect</span>
                  {cp && <p>Checkpoint #{cp.n} saved, step marked “outcome unclear”.</p>}
                  {reconcile && <p className="small dim">{eventText(reconcile)}.</p>}
                </div>
                <div className="col">
                  <span className="mono small lime">03 · result</span>
                  {next && <p>Attempt {next.attempt}: {next.outcome === 'ok' ? 'succeeded with the same idempotency key.' : next.data.error || next.outcome}</p>}
                  {a && last && a.status === 'verified' && <p className="lime">Independently verified after recovery.</p>}
                  {a && last && a.status === 'failed' && <p className="err-text-dark">Stopped: {a.result.error} Escalated instead of retrying forever.</p>}
                  {!next && a && !['verified', 'failed'].includes(a.status) && <p className="small dim">In progress…</p>}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </section>
  )
}
