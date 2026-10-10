// Cloudflare Pages Function: forwards /api/* from the Pages site to the Rook agent.
//
// Where the agent lives, in order of precedence:
//   1. the ROOK_API_ORIGIN environment variable on the Pages project
//      (dashboard -> Settings -> Environment variables, or `wrangler pages secret put`)
//   2. DEFAULT_API_ORIGIN below -- set it once, commit it, and the site needs no
//      dashboard configuration at all. It is a public address, not a secret.
const DEFAULT_API_ORIGIN = ''

// The free Render instance sleeps when idle and takes up to a minute to wake, which
// surfaces as a gateway error rather than a slow response. Retry those a couple of
// times so a judge arriving cold sees the dashboard, not a 502.
//
// Reads are retried on any gateway error. Writes are retried only on statuses that
// mean the agent was never reached, because 502 and 504 can also follow a request the
// agent did process, and replaying those would create a second incident.
const RETRY_READ = new Set([502, 503, 504, 521, 522, 523, 524])
const RETRY_WRITE = new Set([503, 521, 522, 523])
const ATTEMPTS = 3
const BACKOFF_MS = 2000

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

export async function onRequest(context: any): Promise<Response> {
  const { request, env } = context
  const origin: string = (env.ROOK_API_ORIGIN || DEFAULT_API_ORIGIN || '').trim().replace(/\/+$/, '')
  if (!origin) {
    return json(503, {
      detail: 'This dashboard has no agent behind it yet. Set ROOK_API_ORIGIN on the ' +
        'Cloudflare Pages project (or DEFAULT_API_ORIGIN in web/functions/api) to the ' +
        'address of the Rook agent, for example https://rook.onrender.com.',
    })
  }

  const url = new URL(request.url)
  let target: string
  try {
    target = new URL(url.pathname + url.search, origin).toString()
  } catch {
    return json(503, { detail: 'ROOK_API_ORIGIN is not a valid absolute URL.' })
  }

  const headers = new Headers(request.headers)
  headers.delete('host')
  // Let the runtime negotiate compression with the agent. If the client's own
  // accept-encoding is forwarded, the body and the content-encoding header can
  // disagree by the time they reach the browser, and the page arrives as noise.
  headers.delete('accept-encoding')
  const method = request.method
  const safe = method === 'GET' || method === 'HEAD'
  const body = safe ? undefined : await request.arrayBuffer()
  const retryable = safe ? RETRY_READ : RETRY_WRITE

  let last = ''
  for (let attempt = 1; attempt <= ATTEMPTS; attempt++) {
    try {
      const resp = await fetch(target, { method, headers, body, redirect: 'manual' })
      if (!retryable.has(resp.status) || attempt === ATTEMPTS) return passthrough(resp)
      last = `the agent answered ${resp.status}`
    } catch (e: any) {
      // A dropped connection on a write may still have been processed, so never replay it.
      last = e?.message || 'the agent could not be reached'
      if (!safe || attempt === ATTEMPTS) break
    }

    await sleep(BACKOFF_MS * attempt)
  }
  return json(504, { detail: `Could not reach the Rook agent (${last}). It may still be starting up.` })
}

// The runtime hands back a decoded body, so the agent's framing headers no longer
// describe it. Drop them and let the edge re-encode for the client.
const DROP = ['content-encoding', 'content-length', 'transfer-encoding', 'connection']

function passthrough(resp: Response): Response {
  const headers = new Headers(resp.headers)
  for (const h of DROP) headers.delete(h)
  return new Response(resp.body, { status: resp.status, statusText: resp.statusText, headers })
}

function json(status: number, data: unknown): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'content-type': 'application/json', 'cache-control': 'no-store' },
  })
}
