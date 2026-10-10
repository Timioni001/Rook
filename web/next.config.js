// The browser only talks to this Next.js server; /api/* is proxied to the Keywarden backend.
module.exports = {
  async rewrites() {
    return [{ source: '/api/:path*', destination: (process.env.ROOK_API || 'http://127.0.0.1:8000') + '/api/:path*' }]
  },
}
