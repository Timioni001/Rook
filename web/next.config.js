// Dev: the browser talks to Next.js, which proxies /api/* to the Rook backend.
// STATIC_EXPORT=1 builds plain files (web/out) that the backend serves itself, for single-container deploys.
module.exports = process.env.STATIC_EXPORT === '1'
  ? { output: 'export' }
  : {
      async rewrites() {
        return [{ source: '/api/:path*', destination: (process.env.ROOK_API || 'http://127.0.0.1:8000') + '/api/:path*' }]
      },
    }
