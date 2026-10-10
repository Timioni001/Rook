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

  return (
    <div className="shell">
      <header className="top">
        <div>
          <h1>Keywarden <span className="muted">· Rook</span></h1>
          <p className="muted small">Investigate. Contain. Verify.</p>
        </div>
        <div className="who">
          <label htmlFor="who" className="small muted">Signed in as (demo identity)</label>
          <select id="who" value={who.key} onChange={(e) => setWho(e.target.value)}>
            {IDENTITIES.map((i) => <option key={i.key} value={i.key}>{i.label}</option>)}
          </select>
          {me && <span className="small muted">org {me.org} · {me.roles.join(', ')}</span>}
        </div>
      </header>
      <p className="sandbox-note" role="note">
        Sandbox: every system here is a mock integration with synthetic keys. Nothing real is touched.
      </p>

      {err && (
        <div className="panel error" role="alert">
          <b>Something went wrong.</b> {err}{' '}
          <button onClick={() => (id ? loadIncident(id) : loadList())}>Retry</button>
        </div>
      )}

      <div className="layout">
        <aside>
          <section className="panel">
            <h2>New incident</h2>
            <label htmlFor="scenario" className="small muted">Sandbox scenario</label>
            <select id="scenario" value={scenario} onChange={(e) => setScenario(e.target.value)}>
              {scenarios.map((s) => <option key={s.name} value={s.name}>{s.name.replace(/_/g, ' ')}</option>)}
            </select>
            <p className="small muted">{scenarios.find((s) => s.name === scenario)?.description}</p>
            <button className="primary" disabled={busy || !me?.roles.includes('analyst')} onClick={create}>
              Investigate offboarded contractor
            </button>
            {me && !me.roles.includes('analyst') && <p className="small muted">This identity cannot start incidents.</p>}
          </section>
          <section className="panel">
            <h2>Incidents</h2>
            {list === null && <p className="muted small">Loading…</p>}
            {list?.length === 0 && <p className="muted small">No incidents yet for this organisation.</p>}
            <ul className="inc-list">
              {list?.map((i) => (
                <li key={i.id}>
                  <button className={`inc ${i.id === id ? 'sel' : ''}`} onClick={() => { setNotice(null); setId(i.id) }}>
                    <span>{i.scenario.replace(/_/g, ' ')}</span>
                    <Pill tone={(INCIDENT_STATE[i.status] || INCIDENT_STATE.open).tone}>{(INCIDENT_STATE[i.status] || INCIDENT_STATE.open).label}</Pill>
                    <span className="small muted">{i.id} · {time(i.created_at)}</span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        </aside>

        <main aria-live="polite">
          {notice && <div className="panel notice" role="status">{notice}</div>}
          {!id && <div className="panel empty"><h2>No incident selected</h2>
            <p className="muted">Start one on the left. Rook will investigate, propose a plan, and wait for approval before anything irreversible.</p></div>}
          {id && !R && !err && <div className="panel"><p className="muted">Loading incident…</p></div>}

          {R && state && (<>
            {/* 1. Overview */}
            <section className="panel overview">
              <div className="ov-head">
                <div>
                  <p className="small muted">{R.incident.id} · severity {R.incident.severity} · ticket {R.incident.ticket || 'none'}</p>
                  <h2 className="title">{R.incident.title}</h2>
                </div>
                <Pill tone={state.tone}>{d.running ? 'Running' : state.label}</Pill>
              </div>
              <p className="lead">{R.summary}</p>
              <div className="stats">
                <div><b>{R.actions.filter((a: any) => a.status === 'verified').length}/{R.actions.length}</b><span>actions verified</span></div>
                <div><b>{R.conditions.filter((c: any) => c.result === true).length}/{R.conditions.length}</b><span>closure checks passing</span></div>
                <div><b>{R.metrics.failed_tool_calls}</b><span>failed tool calls</span></div>
                <div><b>{R.metrics.checkpoints}</b><span>checkpoints saved</span></div>
              </div>
              <div className="row">
                {me?.roles.includes('analyst') && !d.running && ['ready', 'escalated', 'open', 'awaiting_approval'].includes(R.status) && (
                  <button className="primary" disabled={busy} onClick={() => act(() => api(who.token, `/incidents/${id}/run`, {}), 'Run started.')}>
                    {R.status === 'ready' ? 'Run plan' : 'Run again'}
                  </button>
                )}
                {me?.roles.includes('analyst') && d.running && (
                  <button disabled={busy} onClick={() => act(() => api(who.token, `/incidents/${id}/cancel`, {}), 'Cancel requested.')}>Cancel run</button>
                )}
              </div>
            </section>

            {/* 4. Approval */}
            {pending.map((a: any) => {
              const ready = a.depends_on.every((x: string) => R.actions.find((y: any) => y.id === x)?.status === 'verified')
              return (
              <section key={a.id} className="panel approval" aria-labelledby={`ap-${a.id}`}>
                <h2 id={`ap-${a.id}`}>{ready ? 'Approval needed now' : 'Approval will be needed'}: {ACTION_LABEL[a.type] || a.type}</h2>
                {!ready && <p className="small">Rook pauses here once the earlier steps are verified. An approver can confirm in advance; policy is still re-checked before it runs.</p>}
                <p className="lead">{a.summary}</p>
                <ul className="facts">
                  <li><b>Why approval:</b> {a.policy.reason}</li>
                  <li><b>Can it be undone?</b> No. The old key stops working everywhere, permanently.</li>
                  <li><b>Safety check:</b> it runs only after {a.depends_on.length} earlier steps are verified, and policy is checked again just before it runs.</li>
                </ul>
                {me?.roles.includes('approver') ? (
                  <div className="row">
                    <button className="danger" disabled={busy} onClick={() => act(() => api(who.token, `/incidents/${id}/actions/${a.id}/approve`, {}), 'Approved. Rook is continuing.')}>Approve revocation</button>
                    <button disabled={busy} onClick={() => act(() => api(who.token, `/incidents/${id}/actions/${a.id}/reject`, { note: 'Rejected from dashboard' }), 'Rejected. The incident will be escalated.')}>Reject</button>
                  </div>
                ) : <p className="small muted">Waiting for someone with the approver role. Switch to “Priya” to approve.</p>}
              </section>
            )})}

            {/* 2. Graph */}
            <section className="panel">
              <h2>Who and what is connected</h2>
              <Graph graph={R.incident.graph} live={liveState(R.actions, R.incident.graph)} />
            </section>

            {/* 3. Findings + plan */}
            <section className="panel">
              <h2>What Rook found</h2>
              <ul className="findings">
                {R.incident.findings.map((f: any, i: number) => (
                  <li key={i}><Pill tone={f.severity === 'high' ? 'bad' : f.severity === 'medium' ? 'warn' : 'mute'}>{f.severity}</Pill> {f.text}</li>
                ))}
              </ul>
            </section>

            <section className="panel">
              <h2>Plan, in safe order</h2>
              <ol className="plan">
                {R.actions.map((a: any, i: number) => {
                  const s = actionState(a)
                  return (
                    <li key={a.id} className={`step tone-border-${s.tone}`}>
                      <div className="step-head">
                        <span className="num">{i + 1}</span>
                        <b>{ACTION_LABEL[a.type] || a.type}</b>
                        <span className="muted">{a.target}</span>
                        {a.risk === 'high' && <Pill tone="bad">irreversible</Pill>}
                        <Pill tone={s.tone}>{s.label}</Pill>
                      </div>
                      <p>{a.summary}</p>
                      <p className="small muted">
                        Policy {a.policy.rule}: {a.policy.reason}
                        {a.depends_on.length > 0 && <> · after step {a.depends_on.map((x: string) => R.actions.findIndex((y: any) => y.id === x) + 1).join(', ')}</>}
                        {a.retries > 0 && <> · {a.retries} failed attempt{a.retries > 1 ? 's' : ''}</>}
                      </p>
                      {a.result?.error && <p className="small tone-text-bad">{a.result.error}</p>}
                      {(Object.keys(a.evidence || {}).length > 0) && (
                        <details><summary>Verification evidence</summary><pre>{JSON.stringify(a.evidence, null, 2)}</pre></details>
                      )}
                    </li>
                  )
                })}
              </ol>
            </section>

            {/* 6. Failure + recovery */}
            <Recovery R={R} audit={d.audit} checkpoints={d.checkpoints} />

            {/* 7. Verification */}
            <section className="panel">
              <h2>Independent verification</h2>
              <p className="small muted">These checks were fixed before any change was made. They are measured by probing live state, never by trusting a tool’s reply.</p>
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
            </section>

            {/* 5. Timeline */}
            <section className="panel">
              <h2>Live timeline <span className="muted small">({d.audit.length} audit events, append-only)</span></h2>
              <ol className="timeline" ref={tl} tabIndex={0} aria-label="Audit events, oldest first">
                {d.audit.map((e: any) => (
                  <li key={e.n} className={`tone-text-${eventTone(e.event)}`}>
                    <time className="small muted">{time(e.ts)}</time> {eventText(e)}
                  </li>
                ))}
              </ol>
            </section>

            {/* 8. Report */}
            <section className="panel">
              <h2>Incident report</h2>
              <p className="lead">{R.summary}</p>
              {R.closure_blocked_reason && <p><b>Why it is not closed:</b> {R.closure_blocked_reason}</p>}
              <ul className="facts">
                {Object.entries(R.invariants).map(([k, v]) => (
                  <li key={k}><Pill tone={v ? 'ok' : 'bad'}>{v ? 'yes' : 'no'}</Pill> {k.replace(/_/g, ' ')}</li>
                ))}
              </ul>
              {R.approvals.length > 0 && (
                <p className="small">Approvals: {R.approvals.map((a: any) => `${a.decision} by ${a.by} at ${time(a.ts)}`).join('; ')}</p>
              )}
              <button onClick={() => {
                const blob = new Blob([JSON.stringify({ report: R, audit: d.audit }, null, 2)], { type: 'application/json' })
                const u = URL.createObjectURL(blob); const el = document.createElement('a')
                el.href = u; el.download = `${R.incident.id}-report.json`; el.click(); URL.revokeObjectURL(u)
              }}>Download report and audit trail (JSON)</button>
            </section>
          </>)}
        </main>
      </div>
    </div>
  )
}

function Recovery({ R, audit, checkpoints }: { R: any; audit: any[]; checkpoints: any[] }) {
  const failures = R.tool_calls.filter((c: any) => c.outcome !== 'ok')
  const restored = audit.filter((e) => e.event === 'checkpoint_restored')
  if (!failures.length && !restored.length) {
    return (
      <section className="panel">
        <h2>Failures and recovery</h2>
        <p className="muted">No failed tool calls so far. {checkpoints.length} checkpoints saved.</p>
      </section>
    )
  }
  return (
    <section className="panel recovery">
      <h2>Failures and recovery</h2>
      {restored.map((e) => <p key={e.n}><Pill tone="warn">restart</Pill> {eventText(e)}</p>)}
      {failures.map((f: any) => {
        const a = R.actions.find((x: any) => x.id === f.action)
        const after = audit.filter((e) => e.n > 0 && e.data?.action === f.action && e.ts >= f.ts)
        const reconcile = after.find((e) => e.event.startsWith('reconcile'))
        const cp = checkpoints.find((c) => c.ts >= f.ts && c.data?.action === f.action)
        const next = R.tool_calls.find((c: any) => c.action === f.action && c.attempt === f.attempt + 1)
        return (
          <ol key={f.n} className="chain">
            <li className="tone-text-bad"><b>Attempt {f.attempt} of “{ACTION_LABEL[a?.type] || f.action}” on {a?.target}:</b> {f.data.error || f.outcome}</li>
            {cp && <li>Checkpoint #{cp.n} saved with the step marked “outcome unclear”.</li>}
            {reconcile && <li className="tone-text-warn">{eventText(reconcile)}.</li>}
            {next && <li className={next.outcome === 'ok' ? 'tone-text-ok' : 'tone-text-bad'}>Attempt {next.attempt}: {next.outcome === 'ok' ? 'succeeded (same idempotency key)' : next.data.error || next.outcome}</li>}
            {a && a.status === 'verified' && f === failures.filter((x: any) => x.action === f.action).slice(-1)[0] && <li className="tone-text-ok">Independently verified after recovery.</li>}
            {a && a.status === 'failed' && f === failures.filter((x: any) => x.action === f.action).slice(-1)[0] && <li className="tone-text-bad">Stopped: {a.result.error} Escalated instead of retrying forever.</li>}
          </ol>
        )
      })}
    </section>
  )
}
