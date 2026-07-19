import { useCallback, useMemo, useRef, useState } from 'react'

export type ChartDatum = {
  y: number
  label: string
  valueLabel: string
}

type Props = {
  data: ChartDatum[]
  width?: number
  height?: number
  className?: string
  ariaLabel?: string
}

type HoverState = {
  index: number
  clientX: number
  clientY: number
}

/**
 * Simple SVG line chart with nearest-point hover tooltip.
 * Coordinates are computed in viewBox space; hover maps from client X.
 */
export function HoverLineChart({
  data,
  width = 640,
  height = 140,
  className = '',
  ariaLabel = 'Chart',
}: Props) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const [hover, setHover] = useState<HoverState | null>(null)

  const layout = useMemo(() => {
    if (data.length === 0) return null
    const pad = 10
    const ys = data.map((d) => d.y)
    const min = Math.min(...ys)
    const max = Math.max(...ys)
    const span = Math.max(max - min, 1e-9)
    const step = (width - pad * 2) / Math.max(data.length - 1, 1)
    const points = data.map((d, i) => {
      const x = pad + i * step
      const py = height - pad - ((d.y - min) / span) * (height - pad * 2)
      return { x, y: py, label: d.label, valueLabel: d.valueLabel }
    })
    return {
      pad,
      step,
      min,
      max,
      points,
      polyline: points.map((p) => `${p.x},${p.y}`).join(' '),
    }
  }, [data, width, height])

  const onMove = useCallback(
    (ev: React.MouseEvent<HTMLDivElement>) => {
      if (!layout || !wrapRef.current || data.length === 0) return
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
      setHover({ index: best, clientX: ev.clientX, clientY: ev.clientY })
    },
    [layout, data.length, width],
  )

  if (!layout) return null

  const active = hover ? layout.points[hover.index] : null
  const tipLeft = hover
    ? Math.min(
        Math.max(8, hover.clientX - (wrapRef.current?.getBoundingClientRect().left ?? 0) - 70),
        (wrapRef.current?.clientWidth ?? 200) - 150,
      )
    : 0

  return (
    <div
      ref={wrapRef}
      className={`relative ${className}`}
      onMouseMove={onMove}
      onMouseLeave={() => setHover(null)}
    >
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="h-36 w-full cursor-crosshair"
        role="img"
        aria-label={ariaLabel}
      >
        <polyline
          fill="none"
          stroke="var(--accent)"
          strokeWidth="2"
          points={layout.polyline}
        />
        {active && (
          <>
            <line
              x1={active.x}
              x2={active.x}
              y1={layout.pad}
              y2={height - layout.pad}
              stroke="var(--muted)"
              strokeWidth="1"
              strokeDasharray="3 3"
              opacity={0.7}
            />
            <circle
              cx={active.x}
              cy={active.y}
              r={4}
              fill="var(--accent)"
              stroke="var(--bg)"
              strokeWidth="2"
            />
          </>
        )}
      </svg>
      {active && hover && (
        <div
          className="pointer-events-none absolute z-10 min-w-[8.5rem] rounded border border-[var(--border)] bg-[var(--bg-panel)] px-2.5 py-1.5 text-xs shadow-md"
          style={{ left: tipLeft, top: 8 }}
        >
          <p className="m-0 font-medium text-[var(--text)]">{active.valueLabel}</p>
          <p className="m-0 mt-0.5 text-[var(--muted)]">{active.label}</p>
        </div>
      )}
    </div>
  )
}
