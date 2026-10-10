'use client'
import { useEffect, useState } from 'react'

const PRESETS: Record<string, any> = {
  'Transient failure (signature scenario)': { failures: { 'app.repair': ['transient'] }, flags: {} },
  'Ambiguous rotation (applied, response lost)': { failures: { 'vault.rotate': ['timeout_applied'] }, flags: {} },
  'Faulty patch': { failures: {}, flags: { faulty_patch: true } },
  'Invalid replacement credential': { failures: {}, flags: { bad_replacement: true } },
  'Permanent cloud permission failure': { failures: { 'disable:cloud': ['permanent'] }, flags: {} },
}

const api = (p: string, body?: any) =>
  fetch('/api' + p, body === undefined ? undefined : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  }).then((r) => r.json())

const Badge = ({ s }: { s: string }) => <span className={`badge ${s}`}>{s.replace('_', ' ')}</span>

function Graph({ rel, subject }: { rel: any[]; subject: string }) {
  const accts = rel.filter((r) => r.rel === 'has_account')
  const creds = rel.filter((r) => r.rel === 'owns_credential')
  const apps = Array.from(new Set(creds.flatMap((c) => c.used_by))) as string[]
  const repos = Array.from(new Set(creds.flatMap((c) => c.exposed_in))) as string[]
  const mid = [
    ...accts.map((a) => ({ k: a.service + ':' + a.user, s: a.status, t: 'account' })),
    ...creds.map((c) => ({ k: c.cred, s: c.status, t: 'credential', c })),
  ]
  const right = [...apps.map((k) => ({ k, t: 'app' })), ...repos.map((k) => ({ k, t: 'repo' }))]
  const y = (i: number) => 28 + i * 40
  const h = Math.max(mid.length, right.length, 1) * 40 + 20
  const color = (s?: string) => (s === 'active' ? 'var(--warn)' : s === 'disabled' ? 'var(--ok)' : 'var(--mute)')
  return (
    <svg viewBox={`0 0 760 ${h}`} width="100%" role="img" aria-label="Identity and credential relationship graph">
      <circle cx="70" cy={h / 2} r="6" fill="var(--info)" />
      <text x="82" y={h / 2 + 4}>{subject}</text>
      {mid.map((m: any, i) => (
        <g key={m.k}>
          <line x1="76" y1={h / 2} x2="290" y2={y(i)} stroke="var(--line)" />
          <circle cx="296" cy={y(i)} r="5" fill={color(m.s)} />
          <text x="308" y={y(i) + 4}>{m.k} · {m.t} · {m.s}</text>
          {m.c && right.map((r: any, j) =>
            (m.c.used_by.includes(r.k) || m.c.exposed_in.includes(r.k)) &&
            <line key={j} x1="302" y1={y(i)} x2="560" y2={y(mid.length > 0 ? j : 0)} stroke="var(--line)" />)}
        </g>
      ))}
      {right.map((r: any, j) => (
        <g key={r.k}>
          <circle cx="566" cy={y(j)} r="5" fill="var(--mute)" />
          <text x="578" y={y(j) + 4}>{r.k} · {r.t}</text>
        </g>
      ))}
    </svg>
  )
}

export default function Page() {
  const [preset, setPreset] = useState(Object.keys(PRESETS)[0])
  const [id, setId] = useState<string | null>(null)
  const [d, setD] = useState<any>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    if (!id) return
    const t = setInterval(() => api('/incidents/' + id).then(setD).catch((e) => setErr(String(e))), 1000)
    return () => clearInterval(t)
  }, [id])

  async function start() {
    setErr(null); setD(null)
    try {
      await api('/reset', PRESETS[preset])
      const inc = await api('/incidents', {})
      setId(inc.id)
      await api(`/incidents/${inc.id}/run`, {})
    } catch (e) { setErr('Backend unreachable: ' + String(e)) }
  }

  const R = d?.report
  return (
    <main>
      <h1>Keywarden</h1>
      <p className="tag">Rook · Investigate. Contain. Verify.</p>

      <div className="row">
        <label htmlFor="p" className="tag" style={{ margin: 0 }}>Sandbox scenario</label>
        <select id="p" value={preset} onChange={(e) => setPreset(e.target.value)}>
          {Object.keys(PRESETS).map((k) => <option key={k}>{k}</option>)}
        </select>
        <button className="primary" onClick={start}>Start incident</button>
        {id && <button onClick={() => api(`/incidents/${id}/cancel`, {})}>Cancel run</button>}
      </div>
      {err && <p className="failed" role="alert">{err}</p>}
      {id && !R && <p className="tag">Loading incident…</p>}

      {R && (<>
        <h2>Verdict</h2>
        <div className="panel">
          <div className="banner"><Badge s={R.status} />{' '}
            {R.status === 'closed_verified'
              ? `All ${R.conditions.length} closure conditions independently verified`
              : 'Incident open: closure refused'}</div>
          {R.closure_blocked_reason && <p className="tag">{R.closure_blocked_reason}</p>}
        </div>

        <h2>What happened (evidence-backed)</h2>
        <div className="panel">{R.exposure}</div>

        <h2>Access graph (as observed at discovery)</h2>
        <div className="panel"><Graph rel={R.incident.relationships} subject={R.incident.subject} /></div>

        <h2>Remediation actions</h2>
        <div className="panel"><table>
          <thead><tr><th>Action</th><th>Proposed → Executed → Verified</th><th>Status</th><th>Policy</th></tr></thead>
          <tbody>{R.actions.map((a: any) => (
            <tr key={a.id}>
              <td><b>{a.type}</b><br />{a.target}{a.retries > 0 && <> · retries {a.retries}</>}</td>
              <td className="steps">
                <span className="on">proposed</span>
                <span className={['executed', 'verified'].includes(a.status) ? 'on' : ''}>executed</span>
                <span className={a.status === 'verified' ? 'on' : ''}>verified</span>
              </td>
              <td><Badge s={a.status} />
                {a.status === 'needs_approval' &&
                  <><br /><button onClick={() => api(`/incidents/${id}/actions/${a.id}/approve`, {})}>Approve</button></>}
              </td>
              <td>{a.policy?.reason}
                <details><summary>technical</summary><pre>{JSON.stringify({ result: a.result, evidence: a.evidence }, null, 2)}</pre></details>
              </td>
            </tr>))}</tbody></table></div>

        <h2>Verified Closure conditions</h2>
        <div className="panel"><table>
          <thead><tr><th>Condition</th><th>Expected</th><th>Result</th></tr></thead>
          <tbody>{R.conditions.map((c: any) => {
            const s = c.result === true ? 'pass' : c.result === false ? 'fail' : 'inconclusive'
            return (<tr key={c.id}><td>{c.description}</td><td>{c.expected}</td>
              <td><Badge s={s} />
                <details><summary>evidence</summary><pre>{JSON.stringify(c.evidence, null, 2)}</pre></details></td></tr>)
          })}</tbody></table></div>

        <h2>Execution timeline ({d.checkpoints} checkpoints)</h2>
        <div className="panel tl">{d.audit.map((e: any) => {
          const cls = /fail|permanent|unmet|inconclusive|escalated/.test(e.event) ? 'bad'
            : /retry|timeout|reconcil|approval|blocked/.test(e.event) ? 'hot'
            : /verified|granted|closed/.test(e.event) ? 'good' : ''
          return (<div key={e.n} className={cls}><b>{e.event}</b>{' '}
            <details style={{ display: 'inline' }}><summary>details</summary><pre>{JSON.stringify(e.data, null, 2)}</pre></details></div>)
        })}</div>

        <h2>Final report</h2>
        <div className="panel">
          <details><summary>Invariants and metrics (JSON)</summary>
            <pre>{JSON.stringify({ invariants: R.invariants, unresolved: R.unresolved, metrics: R.metrics }, null, 2)}</pre></details>
        </div>
      </>)}
    </main>
  )
}
