module.exports = {
  async rewrites() {
    return [{ source: '/api/:path*', destination: (process.env.ROOK_API || 'http://127.0.0.1:8000') + '/:path*' }]
  },
}
