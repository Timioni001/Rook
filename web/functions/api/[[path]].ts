// Cloudflare Pages Function: forwards /api/* from the Pages site to the Rook backend.
// Set ROOK_API_ORIGIN (e.g. the Cloudflare Tunnel address from scripts/share.sh) in the Pages project's environment variables.
export async function onRequest(context: any): Promise<Response> {
  const { request, env } = context
  const origin: string | undefined = env.ROOK_API_ORIGIN
  if (!origin) return new Response(JSON.stringify({ detail: 'ROOK_API_ORIGIN is not configured' }), { status: 503 })
  const url = new URL(request.url)
  const target = new URL(url.pathname + url.search, origin)
  const headers = new Headers(request.headers)
  headers.delete('host')
  const hasBody = !['GET', 'HEAD'].includes(request.method)
  return fetch(target.toString(), {
    method: request.method,
    headers,
    body: hasBody ? await request.arrayBuffer() : undefined,
    redirect: 'manual',
  })
}
