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
  cover: { identity: 'Doctor', credential: 'Appointment', dependent: 'Covering doctor' },
  fixtures: { identity: 'Pitch', credential: 'Match', dependent: 'Moved to' },
}

function tone(n: Node, live: Record<string, string>) {
  const s = live[n.id] || n.status
  if (/broken|failed|failing|decommissioned|firing|suspect/.test(s)) return 'bad'
  if (/disabled|revoked|moved|healthy|dead|issued|known good|resumed|cleared/.test(s)) return 'ok'
  if (/active|uses old key|exposed|auto-deploy|paused|no longer used/.test(s)) return n.kind === 'identity' ? 'mute' : 'warn'
  return 'mute'
}

/** Relationship graph as discovered, with current state layered on from verified actions. */
export default function Graph({ graph, live, playbook }: {
  graph: { nodes: Node[]; edges: Edge[] }; live: Record<string, string>; playbook?: string
}) {
  const kind = (k: string) => (playbook && KIND_BY_PLAYBOOK[playbook]?.[k]) || KIND_LABEL[k] || k
  const nodes = graph?.nodes || []
  if (!nodes.length) return <p className="muted">No relationships discovered.</p>
  const cols: Node[][] = [[], [], []]
  nodes.forEach((n) => cols[COLS[n.kind] ?? 1].push(n))
  const W = 760, BW = 210, BH = 46, GAP = 16
  const x = [12, 275, 538]
  const rows = Math.max(...cols.map((c) => c.length))
  const H = rows * (BH + GAP) + 10
  const pos: Record<string, { x: number; y: number }> = {}
  cols.forEach((c, i) => {
    const off = (H - c.length * (BH + GAP)) / 2
    c.forEach((n, j) => { pos[n.id] = { x: x[i], y: off + j * (BH + GAP) + GAP / 2 } })
  })
  return (
    <>
    <p className="graph-hint small muted">Scroll the map sideways to see the rest of it.</p>
    <div className="graph-wrap">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-labelledby="graph-title graph-desc" style={{ minWidth: 620 }}>
        <title id="graph-title">Relationship graph</title>
        <desc id="graph-desc">
          {graph.edges.map((e) => `${e.from} ${e.rel} ${e.to}`).join('. ')}
        </desc>
        <defs>
          <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" fill="var(--ink)" />
          </marker>
        </defs>
        {graph.edges.map((e, i) => {
          const a = pos[e.from], b = pos[e.to]
          if (!a || !b) return null
          const [l, r] = a.x < b.x ? [a, b] : [b, a]
          const x1 = l.x + BW, y1 = l.y + BH / 2, x2 = r.x, y2 = r.y + BH / 2
          const mx = (x1 + x2) / 2
          return (
            <g key={i}>
              <path d={`M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2 - 2},${y2}`} fill="none"
                stroke="var(--ink)" strokeWidth="1.2" markerEnd="url(#arrow)" />
              {e.rel !== 'has account' && <text x={mx} y={(y1 + y2) / 2 - 4} textAnchor="middle" className="edge-label">{e.rel}</text>}
            </g>
          )
        })}
        {nodes.map((n) => {
          const p = pos[n.id]
          const t = tone(n, live)
          const status = live[n.id] || n.status
          return (
            <g key={n.id} transform={`translate(${p.x},${p.y})`}>
              <rect width={BW} height={BH} rx="8" className={`node node-${t}`} />
              <text x="10" y="18" className="node-kind">{kind(n.kind)} · {status}</text>
              <text x="10" y="35" className="node-label">{n.label.length > 30 ? n.label.slice(0, 29) + '…' : n.label}</text>
            </g>
          )
        })}
      </svg>
    </div>
    </>
  )
}
