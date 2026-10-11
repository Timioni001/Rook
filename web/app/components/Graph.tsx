'use client'

type Node = { id: string; kind: string; label: string; status: string; detail?: string }
type Edge = { from: string; to: string; rel: string }

const COLS: Record<string, number> = {
  identity: 0, account: 1, credential: 1, dependent: 2, repo: 2,
  alert: 0, caller: 0, service: 1, pipeline: 1, revision: 2, host: 2,
}
const KIND_LABEL: Record<string, string> = {
  identity: 'Person', account: 'Account', credential: 'API key', dependent: 'Service', repo: 'Code',
  alert: 'Alert', caller: 'Caller', service: 'Service', pipeline: 'Pipeline', revision: 'Deploy', host: 'Database',
}
// The three columns mean different things in different places, so the words follow the playbook
// rather than the shape: the same box is a patient's appointment in a clinic and a match at a club.
const KIND_BY_PLAYBOOK: Record<string, Record<string, string>> = {
  cover: { identity: 'Doctor', credential: 'Appointment', dependent: 'Covering' },
  care: { identity: 'Patient', credential: 'Handoff', dependent: 'Who it had to reach' },
  fixtures: { identity: 'Pitch', credential: 'Match', dependent: 'Moved to' },
}

// Ordered, because "can be moved" and "moved" mean opposite things and a substring test gets that
// wrong. First match wins, so the finished states are listed before the found-this-way ones.
const TONES: [RegExp, string][] = [
  // the thing that is wrong, or the one Rook deliberately left alone
  [/(broken|failed|failing|decommissioned|firing|suspect|stuck|unreachable|cannot|closed today|off sick|shut)/, 'bad'],
  // not done yet: these all describe the plan, not the result
  [/^(can be|could be|waiting|to be|still|not )|(uses old key|exposed|auto-deploy|paused|no longer used)/, 'warn'],
  // finished and checked
  [/(disabled|revoked|moved|told|replied|rebooked|sent|healthy|dead|issued|known good|resumed|cleared|done)/, 'ok'],
]

function tone(n: Node, live: Record<string, string>) {
  const s = (live[n.id] || n.status || '').toLowerCase()
  for (const [re, t] of TONES) if (re.test(s)) return t
  return 'mute'
}

const fit = (t: string, max = 34) => (t.length > max ? t.slice(0, max - 1) + '…' : t)

/** Two short lines rather than one truncated one: a name cut off mid-word helps nobody. */
function wrap(label: string, max = 28, maxLines = 3): string[] {
  if (label.length <= max) return [label]
  const words = label.split(' ')
  const lines: string[] = ['']
  for (const w of words) {
    const line = lines[lines.length - 1]
    if (!line) lines[lines.length - 1] = w
    else if ((line + ' ' + w).length <= max) lines[lines.length - 1] = line + ' ' + w
    else lines.push(w)
  }
  if (lines.length > maxLines) {
    const kept = lines.slice(0, maxLines - 1)
    const rest = lines.slice(maxLines - 1).join(' ')
    return [...kept, rest.length > max ? rest.slice(0, max - 1) + '…' : rest]
  }
  return lines
}

/**
 * What Rook found, and what changed on it.
 *
 * The layout is three columns: what the incident is about, what it affects, and where each of
 * those had to get to. Colour and wording come from verified actions, so after a run the map is
 * the current state rather than the one Rook walked into.
 */
export default function Graph({ graph, live, playbook, ran }: {
  graph: { nodes: Node[]; edges: Edge[] }; live: Record<string, string>; playbook?: string; ran?: boolean
}) {
  const kind = (k: string) => (playbook && KIND_BY_PLAYBOOK[playbook]?.[k]) || KIND_LABEL[k] || k
  const nodes = graph?.nodes || []
  if (!nodes.length) return <p className="muted">No relationships discovered.</p>
  const cols: Node[][] = [[], [], []]
  nodes.forEach((n) => cols[COLS[n.kind] ?? 1].push(n))
  // A day with twelve appointments draws a map taller than the screen and tells you nothing the
  // seventh box did not. Past six, the rest collapse into one box that says how they ended.
  const foldedInto: Record<string, string> = {}
  const folded = cols.map((col) => {
    if (col.length <= 7) return col
    const rest = col.slice(6)
    rest.forEach((n) => { foldedInto[n.id] = '__more__' })
    const tones = rest.map((n) => tone(n, live))
    const bad = tones.filter((t) => t === 'bad').length
    const ok = tones.filter((t) => t === 'ok').length
    const status = bad ? `${bad} left alone` : ok === rest.length ? 'same as above' : 'not finished yet'
    return [...col.slice(0, 6), {
      id: '__more__', kind: col[0].kind, label: `and ${rest.length} more`, status,
      detail: rest.map((n) => n.label).join(', '),
    } as Node]
  })
  const BW = 252, BH = 70, GAP = 18, W = 3 * BW + 2 * 92 + 24
  const x = [12, BW + 104, 2 * BW + 196]
  const rows = Math.max(...folded.map((c) => c.length))
  const H = rows * (BH + GAP) + 12
  const pos: Record<string, { x: number; y: number }> = {}
  folded.forEach((c, i) => {
    const off = (H - c.length * (BH + GAP)) / 2
    c.forEach((n, j) => { pos[n.id] = { x: x[i], y: off + j * (BH + GAP) + GAP / 2 } })
  })
  const drawn = folded.flat()
  // Edges to a folded node are redrawn to the box that now stands for it, and de-duplicated, so
  // the summary box is connected like the ones it replaced rather than floating on its own.
  const edges = Object.values(Object.fromEntries((graph.edges || []).map((e) => {
    const from = foldedInto[e.from] || e.from, to = foldedInto[e.to] || e.to
    return [`${from}>${to}>${e.rel}`, { ...e, from, to }]
  })))
  const changed = Object.keys(live).length
  return (
    <>
      <div className="graph-key">
        <span><i className="dot dot-ok" />{ran ? 'changed, and checked' : 'ready to change'}</span>
        <span><i className="dot dot-warn" />as Rook found it</span>
        <span><i className="dot dot-bad" />a problem, or left alone on purpose</span>
        <span className="graph-hint">scroll the map sideways for the rest</span>
      </div>
      <div className="graph-wrap">
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-labelledby="graph-title graph-desc" style={{ minWidth: 700 }}>
          <title id="graph-title">What is connected, and what changed</title>
          <desc id="graph-desc">
            {nodes.map((n) => `${kind(n.kind)} ${n.label} is ${live[n.id] || n.status}`).join('. ')}
            {'. '}
            {graph.edges.map((e) => `${e.from} ${e.rel} ${e.to}`).join('. ')}
          </desc>
          <defs>
            <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M0,0 L10,5 L0,10 z" fill="var(--ink)" />
            </marker>
          </defs>
          {edges.map((e, i) => {
            const a = pos[e.from], b = pos[e.to]
            if (!a || !b) return null
            const [l, r] = a.x < b.x ? [a, b] : [b, a]
            const x1 = l.x + BW, y1 = l.y + BH / 2, x2 = r.x, y2 = r.y + BH / 2
            const mx = (x1 + x2) / 2
            return (
              <g key={i}>
                <path d={`M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2 - 2},${y2}`} fill="none"
                  stroke="var(--ink)" strokeWidth="1.2" markerEnd="url(#arrow)" />
                {e.rel !== 'has account' && (
                  <text x={mx} y={(y1 + y2) / 2 - 5} textAnchor="middle" className="edge-label">{e.rel}</text>
                )}
              </g>
            )
          })}
          {drawn.map((n) => {
            const p = pos[n.id]
            const t = tone(n, live)
            const status = live[n.id] || n.status
            const lines = wrap(n.label)
            return (
              <g key={n.id} transform={`translate(${p.x},${p.y})`}>
                <rect width={BW} height={BH} rx="8" className={`node node-${t}`} />
                <text x="12" y="18" className="node-kind">{fit(`${kind(n.kind)} · ${status}`)}</text>
                {lines.map((line, i) => (
                  <text key={i} x="12" y={36 + i * 14} className="node-label">{line}</text>
                ))}
              </g>
            )
          })}
        </svg>
      </div>
      {ran && (
        <p className="small muted graph-foot">
          {changed > 0
            ? `${changed} of these changed during the run, and each change was read back from the system it is on.`
            : 'Nothing on this map needed changing.'}
        </p>
      )}
    </>
  )
}
