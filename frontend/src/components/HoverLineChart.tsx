import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

export type ChartDatum = {
  y: number
  /** Epoch ms for time-scaled X axis (preferred when timeDomain is set) */
  t?: number
  /** Short label for the bottom time axis (fallback when not using timeDomain) */
  axisLabel?: string
  /** Kept for callers; unused when showLevels (hover shows price only) */
  label: string
  valueLabel: string
}

type LevelKind = 'high' | 'low' | 'start' | 'current'

type Props = {
  data: ChartDatum[]
  height?: number
  className?: string
  ariaLabel?: string
  /** TradingView-style: side prices + level lines, time axis, price-only hover */
  showLevels?: boolean
  formatLevel?: (value: number) => string
  /** Optional live current (overrides last point for the Current tag) */
  currentValue?: number | null
  /**
   * Fixed time window for the X axis (TradingView-style).
   * Points are placed by timestamp; axis ticks span this domain even if data is shorter.
   */
  timeDomain?: { startMs: number; endMs: number } | null
  formatTimeAxis?: (ms: number) => string
  /** Vertical event markers on the time axis (e.g. realism regime change) */
  markers?: { t: number; label: string }[] | null
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

const TIME_STEPS_MS = [
  60_000, // 1m
  5 * 60_000,
  15 * 60_000,
  30 * 60_000,
  60 * 60_000, // 1h
  2 * 60 * 60_000,
  3 * 60 * 60_000,
  4 * 60 * 60_000,
  6 * 60 * 60_000,
  12 * 60 * 60_000,
  24 * 60 * 60_000,
] as const

/** Floor a timestamp to a local-time boundary for the given step. */
function floorTimeToStep(ms: number, stepMs: number): number {
  const d = new Date(ms)
  if (stepMs >= 24 * 60 * 60_000) {
    return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
  }
  if (stepMs >= 60 * 60_000) {
    const hours = stepMs / (60 * 60_000)
    const h = Math.floor(d.getHours() / hours) * hours
    return new Date(d.getFullYear(), d.getMonth(), d.getDate(), h, 0, 0, 0).getTime()
  }
  const mins = stepMs / 60_000
  const m = Math.floor(d.getMinutes() / mins) * mins
  return new Date(d.getFullYear(), d.getMonth(), d.getDate(), d.getHours(), m, 0, 0).getTime()
}

function addTimeStep(ms: number, stepMs: number): number {
  const d = new Date(ms)
  if (stepMs >= 24 * 60 * 60_000) {
    d.setDate(d.getDate() + Math.round(stepMs / (24 * 60 * 60_000)))
    return d.getTime()
  }
  if (stepMs >= 60 * 60_000) {
    d.setHours(d.getHours() + Math.round(stepMs / (60 * 60_000)))
    return d.getTime()
  }
  d.setMinutes(d.getMinutes() + Math.round(stepMs / 60_000))
  return d.getTime()
}

/**
 * Even clock-aligned time ticks (e.g. 14:00, 16:00) instead of raw span/n
 * offsets like every 2h24m.
 */
function niceTimeTicks(t0: number, t1: number, maxCount: number): number[] {
  if (!(t1 > t0)) return [t0]
  const span = t1 - t0
  const ideal = span / Math.max(maxCount - 1, 1)
  let step = TIME_STEPS_MS.find((s) => s >= ideal) ?? TIME_STEPS_MS[TIME_STEPS_MS.length - 1]
  // If that still yields too many labels, bump to the next coarser step
  let idx = TIME_STEPS_MS.indexOf(step as (typeof TIME_STEPS_MS)[number])
  while (idx < TIME_STEPS_MS.length - 1 && span / step > maxCount) {
    idx += 1
    step = TIME_STEPS_MS[idx]
  }

  let t = floorTimeToStep(t0, step)
  if (t < t0) t = addTimeStep(t, step)

  const ticks: number[] = []
  for (let guard = 0; t <= t1 + 1 && guard < 64; guard++) {
    if (t >= t0) ticks.push(t)
    t = addTimeStep(t, step)
  }
  return ticks.length > 0 ? ticks : [t0, t1]
}

const LEVEL_META: Record<
  LevelKind,
  { title: string; line: 'solid' | 'dash'; emphasis: boolean }
> = {
  high: { title: 'High', line: 'solid', emphasis: false },
  low: { title: 'Low', line: 'solid', emphasis: false },
  start: { title: 'Start', line: 'dash', emphasis: false },
  current: { title: 'Current', line: 'dash', emphasis: true },
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
  currentValue = null,
  timeDomain = null,
  formatTimeAxis = (ms) =>
    new Date(ms).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }),
  markers = null,
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
    const padR = showLevels ? 118 : 10
    const padT = 10
    const padB = showLevels ? 24 : 10
    const plotW = Math.max(1, width - padL - padR)
    const plotH = Math.max(1, height - padT - padB)

    const ys = data.map((d) => d.y)
    const min = Math.min(...ys)
    const max = Math.max(...ys)
    const start = ys[0]
    const end = ys[ys.length - 1]
    const current = currentValue != null && Number.isFinite(currentValue) ? currentValue : end
    const plotMin = Math.min(min, current)
    const plotMax = Math.max(max, current)
    const span = Math.max(plotMax - plotMin, 1e-9)

    const useTime =
      Boolean(timeDomain) &&
      data.every((d) => typeof d.t === 'number' && Number.isFinite(d.t))
    const t0 = useTime ? timeDomain!.startMs : 0
    const t1 = useTime ? Math.max(timeDomain!.endMs, t0 + 1) : 1
    const tSpan = t1 - t0

    const yAt = (v: number) => padT + plotH - ((v - plotMin) / span) * plotH
    const xAtIndex = (i: number) => padL + (i / Math.max(data.length - 1, 1)) * plotW
    const xAtTime = (t: number) => padL + ((t - t0) / tSpan) * plotW

    const points = data.map((d, i) => ({
      x: useTime
        ? Math.min(padL + plotW, Math.max(padL, xAtTime(d.t as number)))
        : xAtIndex(i),
      y: yAt(d.y),
      value: d.y,
      axisLabel: d.axisLabel ?? '',
      label: d.label,
      valueLabel: d.valueLabel,
    }))

    const levels: { key: LevelKind; value: number }[] = [
      { key: 'high', value: max },
      { key: 'current', value: current },
      { key: 'start', value: start },
      { key: 'low', value: min },
    ]

    const kept: typeof levels = levels.filter((lv) => {
      if (lv.key !== 'start') return true
      return !['high', 'low', 'current'].some(
        (k) =>
          Math.abs(levels.find((l) => l.key === k)!.value - lv.value) / span < 0.012,
      )
    })

    const grid = showLevels
      ? niceTicks(plotMin, plotMax, 5).filter(
          (t) =>
            Math.abs(t - plotMin) / span > 0.04 && Math.abs(t - plotMax) / span > 0.04,
        )
      : []

    const xTickCount = Math.min(6, Math.max(2, Math.floor(plotW / 80)))
    const xTicks: { x: number; label: string }[] = []
    if (showLevels && data.length >= 2) {
      if (useTime) {
        for (const ms of niceTimeTicks(t0, t1, xTickCount)) {
          const x = xAtTime(ms)
          if (x < padL - 1 || x > padL + plotW + 1) continue
          if (xTicks.some((tick) => Math.abs(tick.x - x) < 36)) continue
          xTicks.push({ x, label: formatTimeAxis(ms) })
        }
      } else {
        for (let i = 0; i < xTickCount; i++) {
          const idx =
            xTickCount === 1
              ? 0
              : Math.round((i / (xTickCount - 1)) * (data.length - 1))
          const p = points[idx]
          if (!p.axisLabel) continue
          if (xTicks.some((tick) => Math.abs(tick.x - p.x) < 36)) continue
          xTicks.push({ x: p.x, label: p.axisLabel })
        }
      }
    }

    const markerLines: { x: number; label: string }[] = []
    if (useTime && markers?.length) {
      for (const m of markers) {
        if (m.t < t0 || m.t > t1) continue
        markerLines.push({ x: xAtTime(m.t), label: m.label })
      }
    }

    return {
      padL,
      padR,
      padT,
      padB,
      plotMin,
      plotMax,
      span,
      yAt,
      levels: kept,
      grid,
      xTicks,
      markerLines,
      points,
      polyline: points.map((p) => `${p.x},${p.y}`).join(' '),
    }
  }, [data, width, height, showLevels, currentValue, timeDomain, formatTimeAxis, markers])

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

  // Stable vertical slots so overlapping tags don't stack on the same pixel
  const levelTops = useMemo(() => {
    if (!layout) return {} as Record<string, number>
    const ordered = [...layout.levels].sort(
      (a, b) => layout.yAt(a.value) - layout.yAt(b.value),
    )
    const tops: Record<string, number> = {}
    let lastBottom = -Infinity
    const tagH = 16
    for (const lv of ordered) {
      let top = layout.yAt(lv.value) - tagH / 2
      if (top < lastBottom + 2) top = lastBottom + 2
      top = Math.max(2, Math.min(height - tagH - 2, top))
      tops[lv.key] = top
      lastBottom = top + tagH
    }
    return tops
  }, [layout, height])

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
            layout.levels.map((lv) => {
              const meta = LEVEL_META[lv.key]
              return (
                <line
                  key={lv.key}
                  x1={layout.padL}
                  x2={width - layout.padR}
                  y1={layout.yAt(lv.value)}
                  y2={layout.yAt(lv.value)}
                  stroke={meta.emphasis ? 'var(--accent)' : 'var(--border)'}
                  strokeWidth={meta.emphasis ? 1.25 : 1}
                  strokeDasharray={meta.line === 'dash' ? '5 4' : undefined}
                  opacity={meta.emphasis ? 0.9 : 0.7}
                  vectorEffect="non-scaling-stroke"
                />
              )
            })}

          {showLevels &&
            layout.markerLines.map((m) => (
              <line
                key={`m-${m.x}-${m.label}`}
                x1={m.x}
                x2={m.x}
                y1={layout.padT}
                y2={height - layout.padB}
                stroke="var(--warn)"
                strokeWidth="1.25"
                strokeDasharray="4 3"
                opacity={0.85}
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

      {showLevels && layout && width > 0 && (
        <>
          {layout.levels.map((lv) => {
            const meta = LEVEL_META[lv.key]
            const isHoverNear =
              active != null && Math.abs(active.value - lv.value) / layout.span < 0.002
            return (
              <div
                key={lv.key}
                className={`pointer-events-none absolute z-[1] max-w-[112px] truncate rounded px-1 py-0.5 text-[10px] tabular-nums leading-none ${
                  meta.emphasis
                    ? 'bg-[var(--accent)] font-medium text-[var(--on-accent)]'
                    : 'bg-[var(--bg-panel)] text-[var(--muted)] ring-1 ring-[var(--border)]'
                }`}
                style={{
                  right: 4,
                  top: levelTops[lv.key] ?? 2,
                  opacity: isHoverNear && active ? 0.35 : 1,
                }}
                title={`${meta.title}: ${formatLevel(lv.value)}`}
              >
                <span className="opacity-80">{meta.title}</span>{' '}
                {formatLevel(lv.value)}
              </div>
            )
          })}

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

          {layout.markerLines.map((m) => (
            <div
              key={`ml-${m.x}-${m.label}`}
              className="pointer-events-none absolute z-[1] max-w-[7rem] truncate rounded bg-[var(--bg-panel)] px-1 py-0.5 text-[9px] font-medium leading-none text-[var(--warn)] ring-1 ring-[var(--warn)]/40"
              style={{
                left: Math.min(Math.max(40, m.x), Math.max(40, width - 40)),
                top: 4,
                transform: 'translateX(-50%)',
              }}
              title={m.label}
            >
              {m.label}
            </div>
          ))}
        </>
      )}

      {active && showLevels && layout && (
        <>
          <div
            className="pointer-events-none absolute z-[2] rounded bg-[var(--accent)] px-1.5 py-0.5 text-[10px] font-medium tabular-nums leading-none text-[var(--on-accent)]"
            style={{
              right: 4,
              top: Math.max(2, Math.min(height - 16, active.y - 7)),
            }}
          >
            {formatLevel(active.value)}
          </div>
          <div
            className="pointer-events-none absolute z-[2] whitespace-nowrap rounded border border-[var(--border)] bg-[var(--bg-panel)] px-1.5 py-0.5 text-[10px] tabular-nums leading-none text-[var(--text)] shadow-sm"
            style={{
              left: Math.min(Math.max(48, active.x), Math.max(48, width - 48)),
              top: 6,
              transform: 'translateX(-50%)',
            }}
          >
            <span className="font-medium">{formatLevel(active.value)}</span>
            <span className="text-[var(--muted)]"> · {active.label || active.axisLabel}</span>
          </div>
          <div
            className="pointer-events-none absolute z-[2] whitespace-nowrap rounded bg-[var(--bg-panel)] px-1 py-0.5 text-[10px] font-medium tabular-nums leading-none text-[var(--accent)] ring-1 ring-[var(--accent)]/40"
            style={{
              left: Math.min(Math.max(36, active.x), Math.max(36, width - 36)),
              bottom: 2,
              transform: 'translateX(-50%)',
            }}
          >
            {active.axisLabel || active.label}
          </div>
        </>
      )}

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
