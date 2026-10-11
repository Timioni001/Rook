'use client'

/** The Rook mark. Shared by the landing page and the demo so they are visibly one product. */
export const Star = ({ big }: { big?: boolean }) => (
  <svg viewBox="0 0 24 24" width={big ? 96 : 20} height={big ? 96 : 20} aria-hidden="true" className={big ? 'star-big' : ''}>
    <path d="M12 0 C13 8 16 11 24 12 C16 13 13 16 12 24 C11 16 8 13 0 12 C8 11 11 8 12 0Z"
      fill={big ? 'var(--lime)' : 'currentColor'} stroke={big ? 'var(--ink)' : 'none'} />
  </svg>
)
