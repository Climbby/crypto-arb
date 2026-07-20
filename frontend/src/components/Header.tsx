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
          className="inline-flex h-8 w-8 items-center justify-center rounded border border-[var(--border)] bg-[var(--bg-panel)] text-[var(--text)] hover:border-[var(--accent)]/50 hover:text-[var(--accent)]"
          title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
          aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
        >
          {theme === 'dark' ? (
            <svg
              aria-hidden
              viewBox="0 0 24 24"
              className="h-4 w-4"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.75"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <circle cx="12" cy="12" r="4" />
              <path d="M12 2v2.5M12 19.5V22M4.93 4.93l1.77 1.77M17.3 17.3l1.77 1.77M2 12h2.5M19.5 12H22M4.93 19.07l1.77-1.77M17.3 6.7l1.77-1.77" />
            </svg>
          ) : (
            <svg
              aria-hidden
              viewBox="0 0 24 24"
              className="h-4 w-4"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.75"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M21 14.5A8.5 8.5 0 0 1 9.5 3 7 7 0 1 0 21 14.5Z" />
            </svg>
          )}
        </button>
      </div>
    </header>
  )
}
