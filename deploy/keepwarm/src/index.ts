// Keeps the Rook agent awake, and reports what it last saw when visited directly.
//
// ROOK_API_ORIGIN is passed at deploy time by scripts/deploy-keepwarm.sh.
interface Env {
  ROOK_API_ORIGIN?: string
}

async function ping(env: Env): Promise<{ ok: boolean; origin: string; status?: number; error?: string; ms: number }> {
  const origin = (env.ROOK_API_ORIGIN || '').trim().replace(/\/+$/, '')
  const started = Date.now()
  if (!origin) return { ok: false, origin: '', error: 'ROOK_API_ORIGIN is not set', ms: 0 }
  try {
    const r = await fetch(new URL('/api/health', origin).toString(), {
      headers: { 'user-agent': 'rook-keepwarm' },
      cache: 'no-store',
    })
    return { ok: r.ok, origin, status: r.status, ms: Date.now() - started }
  } catch (e: any) {
    return { ok: false, origin, error: e?.message || 'unreachable', ms: Date.now() - started }
  }
}

export default {
  async scheduled(_event: unknown, env: Env): Promise<void> {
    const r = await ping(env)
    // Shows up in `wrangler tail` and in the worker's Cloudflare logs.
    console.log(JSON.stringify({ at: new Date().toISOString(), ...r }))
  },

  async fetch(_request: Request, env: Env): Promise<Response> {
    const r = await ping(env)
    return new Response(JSON.stringify({ keepwarm: 'rook', every: '5 minutes', ...r }, null, 2), {
      status: r.ok ? 200 : 503,
      headers: { 'content-type': 'application/json', 'cache-control': 'no-store' },
    })
  },
}
