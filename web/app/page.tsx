'use client'
import { useCallback, useEffect, useRef, useState } from 'react'
import Graph from './components/Graph'
import {
  ACTION_LABEL, ApiError, IDENTITIES, INCIDENT_STATE, actionState, api, eventText, eventTone, time,
} from './lib'

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
  }
  return Object.fromEntries(Object.entries(m).filter(([, v]) => v))
}

export default function Page() {
  const [who, setWho] = useIdentity()
  const [me, setMe] = useState<any>(null)
  const [scenarios, setScenarios] = useState<any[]>([])
  const [scenario, setScenario] = useState('signature')
  const [list, setList] = useState<any[] | null>(null)
  const [id, setId] = useState<string | null>(null)
  const [d, setD] = useState<any>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const timer = useRef<any>(null)
  const tl = useRef<HTMLOListElement>(null)
  const nEvents = d?.audit?.length || 0
  useEffect(() => { if (tl.current) tl.current.scrollTop = tl.current.scrollHeight }, [nEvents])

  const loadList = useCallback(async () => {
    try {
      const [m, s, l] = await Promise.all([api(who.token, '/me'), api(who.token, '/scenarios'), api(who.token, '/incidents')])
      setMe(m); setScenarios(s); setList(l); setErr(null)
    } catch (e: any) { setErr(e.message); setList([]) }
  }, [who.token])

  useEffect(() => { setD(null); setId(null); loadList() }, [loadList])

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
      const inc = await api(who.token, '/incidents', { scenario })
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
            <a href="#timeline">Timeline</a>
          </div>
          <label className="who">
            <span className="sr-only">Signed in as (demo identity)</span>
            <select id="who" value={who.key} onChange={(e) => setWho(e.target.value)}>
              {IDENTITIES.map((i) => <option key={i.key} value={i.key}>{i.label}</option>)}
            </select>
          </label>
        </nav>

        <header className="hero" id="top">
          <div className="hero-copy">
            <h1>Close credential incidents only when they are actually closed.</h1>
            <p>Rook investigates a leaked key, fixes it in a safe order, recovers when a step fails and closes the incident only after independent checks pass.</p>
            <div className="hero-form">
              <label htmlFor="scenario" className="mono small">Sandbox scenario</label>
              <div className="row">
                <select id="scenario" value={scenario} onChange={(e) => setScenario(e.target.value)}>
                  {scenarios.map((s) => <option key={s.name} value={s.name}>{s.name.replace(/_/g, ' ')}</option>)}
                </select>
                <button className="btn-dark" disabled={busy || !isAnalyst} onClick={create}>Investigate offboarded contractor</button>
              </div>
              <p className="small muted">{scenarios.find((s) => s.name === scenario)?.description}</p>
              {me && !isAnalyst && <p className="small muted">{who.label} cannot start incidents.</p>}
            </div>
          </div>
          <HeroArt />
        </header>

        <p className="strip mono" role="note">
          <span>sandbox</span><span>synthetic keys</span><span>org {me?.org || '…'}</span><span>{me ? me.roles.join(' + ') : 'loading'}</span>
        </p>

        {err && (
          <div className="card alert" role="alert">
            <b>Something went wrong.</b> {err}{' '}
            <button className="btn-outline" onClick={() => (id ? loadIncident(id) : loadList())}>Retry</button>
          </div>
        )}
        {notice && <div className="card notice" role="status">{notice}</div>}

        <section className="section">
          <SectionTitle label="Incidents" text="Each run is stored with its plan, checkpoints and audit trail." />
          {list === null && <p className="muted">Loading…</p>}
          {list?.length === 0 && <p className="muted">No incidents yet for this organisation. Start one above.</p>}
          <ul className="chips">
            {list?.map((i) => {
              const st = INCIDENT_STATE[i.status] || INCIDENT_STATE.open
              return (
                <li key={i.id}>
                  <button className={`chip ${i.id === id ? 'sel' : ''}`} aria-pressed={i.id === id}
                    onClick={() => { setNotice(null); setId(i.id) }}>
                    <span className="mono small">{time(i.created_at)}</span>
                    <b>{i.scenario.replace(/_/g, ' ')}</b>
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
                  <p className="mono small muted">{R.incident.id} · severity {R.incident.severity} · ticket {R.incident.ticket || 'none'}</p>
                  <h2 className="h2">{R.incident.title}</h2>
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
                <Stat dark={false} label="Actions verified" value={`${R.actions.filter((a: any) => a.status === 'verified').length}/${R.actions.length}`} />
                <Stat dark label="Closure checks passing" value={`${R.conditions.filter((c: any) => c.result === true).length}/${R.conditions.length}`} />
                <Stat dark label="Failed tool calls" value={R.metrics.failed_tool_calls} />
                <Stat dark={false} label="Checkpoints saved" value={R.metrics.checkpoints} />
              </div>
            </section>

            {/* Approval */}
            {pending.map((a: any) => {
              const ready = a.depends_on.every((x: string) => R.actions.find((y: any) => y.id === x)?.status === 'verified')
              return (
                <section key={a.id} className="section">
                  <div className="approval" aria-labelledby={`ap-${a.id}`}>
                    <div>
                      <h2 id={`ap-${a.id}`} className="h3"><mark>{ready ? 'Approval needed now' : 'Approval will be needed'}</mark></h2>
                      <p className="lead">{a.summary}</p>
                      {!ready && <p className="small">Rook pauses here once the earlier steps are verified. An approver can confirm in advance; policy is re-checked just before it runs.</p>}
                      <ul className="facts">
                        <li><b>Why approval:</b> {a.policy.reason}</li>
                        <li><b>Can it be undone?</b> No. The old key stops working everywhere, permanently.</li>
                        <li><b>Safety check:</b> runs only after steps {a.depends_on.map((x: string) => R.actions.findIndex((y: any) => y.id === x) + 1).join(', ')} are verified.</li>
                      </ul>
                    </div>
                    <div className="approval-actions">
                      {isApprover ? (<>
                        <button className="btn-lime" disabled={busy} onClick={() => act(() => api(who.token, `/incidents/${id}/actions/${a.id}/approve`, {}), 'Approved. Rook is continuing.')}>Approve revocation</button>
                        <button className="btn-ghost" disabled={busy} onClick={() => act(() => api(who.token, `/incidents/${id}/actions/${a.id}/reject`, { note: 'Rejected from dashboard' }), 'Rejected. The incident will be escalated.')}>Reject</button>
                      </>) : <p className="small">Waiting for someone with the approver role. Switch to “Priya” to approve.</p>}
                    </div>
                  </div>
                </section>
              )
            })}

            {/* Graph + findings */}
            <section className="section">
              <SectionTitle label="Who and what is connected" text="Discovered by Rook, with each node updated as actions are verified." />
              <div className="card"><Graph graph={R.incident.graph} live={liveState(R.actions, R.incident.graph)} /></div>
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

            {/* Plan */}
            <section className="section" id="plan">
              <SectionTitle label="Plan" text="Steps run in this order. Each one is checked against live state before the next can start." />
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
                  {R.approvals.length > 0 && <p className="small">Approvals: {R.approvals.map((a: any) => `${a.decision} by ${a.by} at ${time(a.ts)}`).join('; ')}</p>}
                  <button className="btn-dark" onClick={() => {
                    const blob = new Blob([JSON.stringify({ report: R, audit: d.audit }, null, 2)], { type: 'application/json' })
                    const u = URL.createObjectURL(blob); const el = document.createElement('a')
                    el.href = u; el.download = `${R.incident.id}-report.json`; el.click(); URL.revokeObjectURL(u)
                  }}>Download report + audit trail</button>
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
                  <h2 className="h3">Try the signature scenario</h2>
                  <p>billing-app’s config API fails once mid-fix. Watch Rook save a checkpoint, inspect what really happened, retry safely and still close with evidence.</p>
                </div>
                <Star big />
              </div>
            </section>
          )}
        </div>

        <footer className="footer mono small">Rook · built by Keywarden · sandboxed mock integrations, synthetic credentials only</footer>
      </div>
    </div>
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

function Stat({ label, value, dark }: { label: string; value: any; dark: boolean }) {
  return (
    <div className={`stat ${dark ? 'stat-dark' : ''}`}>
      <span className="small"><mark>{label}</mark></span>
      <b>{value}</b>
    </div>
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
  const failures = R.tool_calls.filter((c: any) => c.outcome !== 'ok')
  const restored = audit.filter((e) => e.event === 'checkpoint_restored')
  return (
    <section className="section">
      <SectionTitle label="Failure and recovery" text="What went wrong, what Rook checked, and what it did about it." />
      {!failures.length && !restored.length ? (
        <div className="soft"><p className="muted">No failed tool calls so far. {checkpoints.length} checkpoints saved.</p></div>
      ) : (
        <div className="dark-panel">
          {restored.map((e) => <div key={e.n} className="col"><span className="mono small lime">restart</span><p>{eventText(e)}</p></div>)}
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
