import { Link } from 'react-router-dom'
import { EmptyState } from '@/components/primitives/States'

export function NotFound() {
  return (
    <div className="flex-1 flex items-center justify-center">
      <EmptyState
        icon="⌀"
        title="No such page"
        body="That address does not correspond to a screen in this console."
        action={
          <Link to="/" className="px-3 py-1.5 text-xs font-mono tracking-wider border border-radar/50
                                  text-radar hover:bg-radar/15 rounded-sm transition-colors">
            BACK TO THE OPS BOARD
          </Link>
        }
      />
    </div>
  )
}
