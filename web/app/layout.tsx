import './globals.css'

export const metadata = { title: 'Keywarden · Rook', description: 'Investigate. Contain. Verify.' }

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}
