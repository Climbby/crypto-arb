import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

export type ChartDatum = {
  y: number
  label: string
  valueLabel: string
}

type Props = {
  data: ChartDatum[]
  height?: number
  className?: string
  ariaLabel?: string
}

/**
 * SVG line chart with nearest-point hover.
 * ViewBox width tracks the container so hover X matches the drawn line
 * (avoids letterboxing mismatch from a fixed viewBox + w-full).
 */
export function HoverLineChart({
  data,
  height = 140,
  className = '',
  ariaLabel = 'Chart',
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
      points,
      polyline: points.map((p) => `${p.x},${p.y}`).join(' '),
    }
  }, [data, width, height])

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
  const tipLeft = active
    ? Math.min(Math.max(8, active.x - 70), Math.max(8, width - 158))
    : 0

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
                y1={layout.pad}
                y2={height - layout.pad}
                stroke="var(--muted)"
                strokeWidth="1"
                strokeDasharray="3 3"
                opacity={0.7}
                vectorEffect="non-scaling-stroke"
              />
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
      {active && (
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
