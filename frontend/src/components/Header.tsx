import type { AutoPaperStatus } from '../hooks/useOpportunities'
import type { Theme } from '../hooks/useTheme'

type Props = {
  connected: boolean
  scansLastMinute: number
  autoPaper: AutoPaperStatus | null
  theme: Theme
  onToggleTheme: () => void
}

export function Header({
  connected,
  scansLastMinute,
  autoPaper,
  theme,
  onToggleTheme,
}: Props) {
  const autoLabel = autoPaper?.enabled ? 'Auto paper ON' : 'Auto paper: off'
  const liveTip = connected
    ? `${scansLastMinute} scan${scansLastMinute === 1 ? '' : 's'} last minute`
    : 'Disconnected — reconnecting'

  return (
    <header className="flex flex-wrap items-end justify-between gap-4 border-b border-[var(--border)] pb-5">
      <div>
        <p className="m-0 text-xs tracking-[0.22em] uppercase text-[var(--muted)]">
          Cross-exchange · theoretical edges
        </p>
        <h1 className="m-0 mt-1 text-3xl font-semibold tracking-tight text-[var(--text)] sm:text-4xl">
          Arb<span className="text-[var(--accent)]">Watch</span>
        </h1>
      </div>
      <div className="flex flex-wrap items-center gap-3 text-sm text-[var(--muted)] sm:gap-4">
        <span
          className="inline-flex cursor-default items-center gap-2"
          title={liveTip}
        >
          <span
            className={`h-2 w-2 rounded-full ${connected ? 'bg-[var(--accent)]' : 'bg-[var(--danger)]'}`}
          />
          {connected ? 'Live' : 'Reconnecting'}
        </span>
        <span className={autoPaper?.enabled ? 'text-[var(--accent)]' : ''}>{autoLabel}</span>
        <button
          type="button"
          onClick={onToggleTheme}
          className="rounded border border-[var(--border)] bg-[var(--bg-panel)] px-2.5 py-1 text-xs text-[var(--text)] hover:border-[var(--accent)]/50"
          title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
          aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
        >
          {theme === 'dark' ? 'Light' : 'Dark'}
        </button>
      </div>
    </header>
  )
}
