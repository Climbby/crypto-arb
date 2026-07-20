import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

export type ChartDatum = {
  y: number
  /** Short label for the bottom time axis */
  axisLabel?: string
  /** Kept for callers; unused when showLevels (hover shows price only) */
  label: string
  valueLabel: string
}

type Props = {
  data: ChartDatum[]
  height?: number
  className?: string
  ariaLabel?: string
  /** TradingView-style: side prices + level lines, time axis, price-only hover */
  showLevels?: boolean
  formatLevel?: (value: number) => string
}

function niceTicks(min: number, max: number, count: number): number[] {
  if (!(max > min) || count < 2) return [min, max]
  const span = max - min
  const raw = span / (count - 1)
  const pow = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * pow).find((s) => s >= raw) ?? raw
  const start = Math.ceil(min / step) * step
  const ticks: number[] = []
  for (let v = start; v <= max + step * 1e-9; v += step) ticks.push(v)
  if (ticks.length === 0) return [min, max]
  return ticks
}

/**
 * SVG line chart with nearest-point hover.
 * ViewBox width tracks the container so hover X matches the drawn line.
 */
export function HoverLineChart({
  data,
  height = 140,
  className = '',
  ariaLabel = 'Chart',
  showLevels = false,
  formatLevel = (v) => v.toFixed(2),
}: Props) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(0)
  const [hoverIndex, setHoverIndex] = useState<number | null>(null)

  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const update = () => setWidth(Math.max(1, Math.floor(el.clientWidth)))
    update()
    const ro = new ResizeObserver(update)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const layout = useMemo(() => {
    if (data.length === 0 || width <= 0) return null

    const padL = 8
    const padR = showLevels ? 78 : 10
    const padT = 10
    const padB = showLevels ? 24 : 10
    const plotW = Math.max(1, width - padL - padR)
    const plotH = Math.max(1, height - padT - padB)

    const ys = data.map((d) => d.y)
    const min = Math.min(...ys)
    const max = Math.max(...ys)
    const start = ys[0]
    const span = Math.max(max - min, 1e-9)
    const step = plotW / Math.max(data.length - 1, 1)

    const yAt = (v: number) => padT + plotH - ((v - min) / span) * plotH
    const points = data.map((d, i) => ({
      x: padL + i * step,
      y: yAt(d.y),
      value: d.y,
      axisLabel: d.axisLabel ?? '',
      label: d.label,
      valueLabel: d.valueLabel,
    }))

    // Side levels: high, start, low (TradingView-style tags)
    const levels = [
      { key: 'max', value: max, kind: 'bound' as const },
      { key: 'start', value: start, kind: 'start' as const },
      { key: 'min', value: min, kind: 'bound' as const },
    ]

    // Extra grid ticks between bounds when there's room
    const grid = showLevels
      ? niceTicks(min, max, 5).filter(
          (t) => Math.abs(t - min) / span > 0.04 && Math.abs(t - max) / span > 0.04,
        )
      : []

    const xTickCount = Math.min(6, Math.max(2, Math.floor(plotW / 72)))
    const xTicks: { x: number; label: string }[] = []
    if (showLevels && data.length >= 2) {
      for (let i = 0; i < xTickCount; i++) {
        const idx =
          xTickCount === 1
            ? 0
            : Math.round((i / (xTickCount - 1)) * (data.length - 1))
        const p = points[idx]
        if (!p.axisLabel) continue
        if (xTicks.some((t) => Math.abs(t.x - p.x) < 28)) continue
        xTicks.push({ x: p.x, label: p.axisLabel })
      }
    }

    return {
      padL,
      padR,
      padT,
      padB,
      plotW,
      plotH,
      min,
      max,
      start,
      span,
      yAt,
      levels,
      grid,
      xTicks,
      points,
      polyline: points.map((p) => `${p.x},${p.y}`).join(' '),
    }
  }, [data, width, height, showLevels])

  const onMove = useCallback(
    (ev: React.MouseEvent<HTMLDivElement>) => {
      if (!layout || !wrapRef.current || data.length === 0 || width <= 0) return
      const rect = wrapRef.current.getBoundingClientRect()
      const relX = ((ev.clientX - rect.left) / rect.width) * width
      let best = 0
      let bestDist = Infinity
      for (let i = 0; i < layout.points.length; i++) {
        const dist = Math.abs(layout.points[i].x - relX)
        if (dist < bestDist) {
          bestDist = dist
          best = i
        }
      }
      setHoverIndex(best)
    },
    [layout, data.length, width],
  )

  const active = hoverIndex != null && layout ? layout.points[hoverIndex] : null

  return (
    <div
      ref={wrapRef}
      className={`relative w-full ${className}`}
      onMouseMove={onMove}
      onMouseLeave={() => setHoverIndex(null)}
    >
      {layout && width > 0 ? (
        <svg
          viewBox={`0 0 ${width} ${height}`}
          width="100%"
          height={height}
          className="block w-full cursor-crosshair"
          preserveAspectRatio="none"
          role="img"
          aria-label={ariaLabel}
        >
          {/* Grid / level lines */}
          {showLevels &&
            layout.grid.map((v) => (
              <line
                key={`g-${v}`}
                x1={layout.padL}
                x2={width - layout.padR}
                y1={layout.yAt(v)}
                y2={layout.yAt(v)}
                stroke="var(--border)"
                strokeWidth="1"
                opacity={0.35}
                vectorEffect="non-scaling-stroke"
              />
            ))}
          {showLevels &&
            layout.levels.map((lv) => (
              <line
                key={lv.key}
                x1={layout.padL}
                x2={width - layout.padR}
                y1={layout.yAt(lv.value)}
                y2={layout.yAt(lv.value)}
                stroke={lv.kind === 'start' ? 'var(--accent)' : 'var(--border)'}
                strokeWidth={lv.kind === 'start' ? 1.25 : 1}
                strokeDasharray={lv.kind === 'start' ? '5 4' : undefined}
                opacity={lv.kind === 'start' ? 0.85 : 0.75}
                vectorEffect="non-scaling-stroke"
              />
            ))}

          <polyline
            fill="none"
            stroke="var(--accent)"
            strokeWidth="2"
            vectorEffect="non-scaling-stroke"
            points={layout.polyline}
          />

          {active && (
            <>
              <line
                x1={active.x}
                x2={active.x}
                y1={layout.padT}
                y2={height - layout.padB}
                stroke="var(--muted)"
                strokeWidth="1"
                strokeDasharray="3 3"
                opacity={0.75}
                vectorEffect="non-scaling-stroke"
              />
              {showLevels && (
                <line
                  x1={layout.padL}
                  x2={width - layout.padR}
                  y1={active.y}
                  y2={active.y}
                  stroke="var(--muted)"
                  strokeWidth="1"
                  strokeDasharray="3 3"
                  opacity={0.75}
                  vectorEffect="non-scaling-stroke"
                />
              )}
              <circle
                cx={active.x}
                cy={active.y}
                r={4}
                fill="var(--accent)"
                stroke="var(--bg)"
                strokeWidth="2"
                vectorEffect="non-scaling-stroke"
              />
            </>
          )}
        </svg>
      ) : (
        <div style={{ height }} className="w-full" />
      )}

      {/* Right-side price tags (HTML so text doesn't distort) */}
      {showLevels && layout && width > 0 && (
        <>
          {layout.levels.map((lv) => {
            const topPx = layout.yAt(lv.value)
            // Nudge labels apart if start sits on min/max
            let nudge = 0
            if (lv.key === 'start') {
              const maxY = layout.yAt(layout.max)
              const minY = layout.yAt(layout.min)
              if (Math.abs(topPx - maxY) < 12) nudge = 12
              else if (Math.abs(topPx - minY) < 12) nudge = -12
            }
            const isHoverNear =
              active != null && Math.abs(active.value - lv.value) / layout.span < 0.002
            return (
              <div
                key={lv.key}
                className={`pointer-events-none absolute z-[1] rounded px-1 py-0.5 text-[10px] tabular-nums leading-none ${
                  lv.kind === 'start'
                    ? 'bg-[var(--accent)] text-[#062016]'
                    : 'bg-[var(--bg-panel)] text-[var(--muted)] ring-1 ring-[var(--border)]'
                }`}
                style={{
                  right: 4,
                  top: Math.max(2, Math.min(height - 14, topPx + nudge - 6)),
                  opacity: isHoverNear && active ? 0.35 : 1,
                }}
                title={
                  lv.key === 'max'
                    ? 'High'
                    : lv.key === 'min'
                      ? 'Low'
                      : 'Start of timeframe'
                }
              >
                {formatLevel(lv.value)}
              </div>
            )
          })}

          {/* Bottom time axis */}
          {layout.xTicks.map((t) => (
            <div
              key={`${t.x}-${t.label}`}
              className="pointer-events-none absolute text-[10px] tabular-nums text-[var(--muted)]"
              style={{
                left: t.x,
                bottom: 4,
                transform: 'translateX(-50%)',
              }}
            >
              {t.label}
            </div>
          ))}
        </>
      )}

      {/* Hover: price only (TV-style tag on the right) */}
      {active && showLevels && layout && (
        <div
          className="pointer-events-none absolute z-[2] rounded bg-[var(--accent)] px-1.5 py-0.5 text-[10px] font-medium tabular-nums leading-none text-[#062016]"
          style={{
            right: 4,
            top: Math.max(2, Math.min(height - 16, active.y - 7)),
          }}
        >
          {formatLevel(active.value)}
        </div>
      )}

      {/* Simple tooltip when not in levels mode (edge diary etc.) */}
      {active && !showLevels && (
        <div
          className="pointer-events-none absolute z-10 min-w-[8.5rem] rounded border border-[var(--border)] bg-[var(--bg-panel)] px-2.5 py-1.5 text-xs shadow-md"
          style={{
            left: Math.min(Math.max(8, active.x - 70), Math.max(8, width - 158)),
            top: 8,
          }}
        >
          <p className="m-0 font-medium text-[var(--text)]">{active.valueLabel}</p>
          <p className="m-0 mt-0.5 text-[var(--muted)]">{active.label}</p>
        </div>
      )}
    </div>
  )
}
