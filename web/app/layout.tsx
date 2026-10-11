import './globals.css'

const TITLE = 'Rook · the operations agent that proves the fix'
const DESC = 'Staff report a problem. Rook investigates across every system it touches, waits for a person '
  + 'before anything reaches someone outside, then checks the result and shows the evidence.'

export const metadata = {
  metadataBase: new URL('https://rook-keywarden.pages.dev'),
  title: TITLE,
  description: DESC,
  openGraph: { title: TITLE, description: DESC, type: 'website', images: ['/og.png'] },
  twitter: { card: 'summary_large_image', title: TITLE, description: DESC, images: ['/og.png'] },
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet" />
      </head>
      <body>{children}</body>
    </html>
  )
}
