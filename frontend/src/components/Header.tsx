import { useState } from 'react'
import type { AutoPaperStatus } from '../hooks/useOpportunities'
import type { Theme } from '../hooks/useTheme'

type Props = {
  connected: boolean
  scansLastMinute: number
  autoPaper: AutoPaperStatus | null
  theme: Theme
  onToggleTheme: () => void
}

/** When paper realism tightened (transfer delays, fees, fill slippage). */
const REALISM_SINCE_MS = Date.parse('2026-07-20T19:00:18.000Z')

export function Header({
  connected,
  scansLastMinute,
  autoPaper,
  theme,
  onToggleTheme,
}: Props) {
  const [changelogOpen, setChangelogOpen] = useState(false)
  const autoLabel = autoPaper?.enabled ? 'Auto paper ON' : 'Auto paper: off'
  const liveTip = connected
    ? `${scansLastMinute} scan${scansLastMinute === 1 ? '' : 's'} last minute`
    : 'Disconnected — reconnecting'
  const realismSinceLabel = new Date(REALISM_SINCE_MS).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })

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
        <div className="relative">
          <button
            type="button"
            onClick={() => setChangelogOpen((o) => !o)}
            className="inline-flex h-8 w-8 items-center justify-center rounded border border-[var(--border)] bg-[var(--bg-panel)] text-[var(--text)] hover:border-[var(--warn)]/50 hover:text-[var(--warn)]"
            title="Changelog"
            aria-label="Changelog"
            aria-expanded={changelogOpen}
          >
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
              <path d="M14 2H7a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
              <path d="M14 2v6h6" />
              <path d="M9 13h6M9 17h6M9 9h1" />
            </svg>
          </button>
          {changelogOpen ? (
            <div
              className="absolute right-0 top-full z-30 mt-1.5 w-[min(22rem,calc(100vw-2.5rem))] rounded border border-[var(--border)] bg-[var(--bg-panel)] p-3 pt-2 text-[11px] leading-snug text-[var(--text)] shadow-lg"
              role="dialog"
              aria-label="Changelog"
            >
              <div className="mb-1.5 flex items-start justify-between gap-2">
                <p className="m-0 pr-2 font-medium text-[var(--warn)]">
                  Stricter paper realism · {realismSinceLabel}
                </p>
                <button
                  type="button"
                  onClick={() => setChangelogOpen(false)}
                  className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded text-[var(--muted)] hover:bg-[var(--bg)] hover:text-[var(--text)]"
                  title="Close"
                  aria-label="Close changelog"
                >
                  <svg
                    aria-hidden
                    viewBox="0 0 24 24"
                    className="h-3.5 w-3.5"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                  >
                    <path d="M6 6l12 12M18 6L6 18" />
                  </svg>
                </button>
              </div>
              <p className="m-0 text-[var(--muted)]">
                Before that, transfers were instant and fills ignored slippage — earlier PnL is
                optimistic. After: withdraw delays (USDT~3m → BTC~30m), burn fees in transit, and
                fill slippage. Still paper (no depth/latency). Lifetime totals mix both regimes.
                Chart marker shows the cutover.
              </p>
            </div>
          ) : null}
        </div>
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
