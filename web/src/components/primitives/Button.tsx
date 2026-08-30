import type { ButtonHTMLAttributes, ReactNode } from 'react'

type Variant = 'primary' | 'ghost' | 'danger'

const VARIANT: Record<Variant, string> = {
  primary:
    'bg-coral text-abyss border-coral hover:bg-ink hover:border-ink ' +
    'disabled:bg-hairline/40 disabled:text-dim disabled:border-hairline',
  ghost:
    'bg-transparent text-muted border-hairline hover:text-radar hover:border-radar ' +
    'disabled:text-dim disabled:border-hairline',
  danger:
    'bg-coral/15 text-coral border-coral/50 hover:bg-coral/25 hover:border-coral',
}

export function Button({
  children,
  variant = 'ghost',
  className = '',
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; children: ReactNode }) {
  return (
    <button
      {...rest}
      className={`px-3 py-2 text-xs font-mono font-semibold tracking-[0.08em] uppercase border
                  transition-[background-color,color,border-color] duration-150 disabled:cursor-not-allowed
                  ${VARIANT[variant]} ${className}`}
    >
      {children}
    </button>
  )
}
