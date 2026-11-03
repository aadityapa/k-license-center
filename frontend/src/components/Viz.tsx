/**
 * Small hand-built SVG visualisations: sparkline, donut, radial gauge.
 * Written by hand rather than pulled from a chart library because each is a few
 * lines of geometry, needs no axes/tooltips, and must inherit theme tokens.
 */

interface SparklineProps {
  /** Oldest → newest. An all-zero or too-short series renders nothing. */
  data: number[];
  color?: string;
  width?: number;
  height?: number;
}

export function Sparkline({ data, color = 'currentColor', width = 96, height = 28 }: SparklineProps) {
  if (data.length < 2 || data.every((v) => v === 0)) return null;

  const max = Math.max(...data);
  const min = Math.min(...data);
  const span = max - min || 1;
  const stepX = width / (data.length - 1);
  const pad = 2;
  const usable = height - pad * 2;

  const points = data.map((v, i) => {
    const x = i * stepX;
    const y = pad + usable - ((v - min) / span) * usable;
    return [x, y] as const;
  });

  const line = points.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
  const area = `${line} L${width},${height} L0,${height} Z`;
  const gradientId = `spark-${Math.round(max * 1000 + data.length)}-${Math.round(min * 7)}`;

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden focusable="false">
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.32" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#${gradientId})`} />
      <path d={line} fill="none" stroke={color} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export interface DonutSlice {
  label: string;
  value: number;
  color: string;
}

interface DonutProps {
  slices: DonutSlice[];
  size?: number;
  thickness?: number;
  centerValue: number | string;
  centerLabel: string;
}

/** Two concentric arcs: outer ring is the split, inner is a dimmed track. */
export function Donut({ slices, size = 190, thickness = 20, centerValue, centerLabel }: DonutProps) {
  const total = slices.reduce((sum, s) => sum + s.value, 0);
  const radius = (size - thickness) / 2;
  const circumference = 2 * Math.PI * radius;
  const center = size / 2;
  const gap = total > 1 ? 2 : 0; // hairline separator between slices

  let offset = 0;

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={centerLabel}>
      <circle
        cx={center}
        cy={center}
        r={radius}
        fill="none"
        stroke="var(--border)"
        strokeWidth={thickness}
        opacity={0.5}
      />
      {total > 0 &&
        slices.map((s) => {
          const length = (s.value / total) * circumference;
          const dash = Math.max(length - gap, 0.5);
          const el = (
            <circle
              key={s.label}
              cx={center}
              cy={center}
              r={radius}
              fill="none"
              stroke={s.color}
              strokeWidth={thickness}
              strokeDasharray={`${dash} ${circumference - dash}`}
              strokeDashoffset={-offset}
              strokeLinecap="butt"
              transform={`rotate(-90 ${center} ${center})`}
              style={{ filter: `drop-shadow(0 0 6px ${s.color}55)` }}
            />
          );
          offset += length;
          return el;
        })}
      <text
        x={center}
        y={center - 6}
        textAnchor="middle"
        style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', fill: 'var(--text-muted)' }}
      >
        {centerLabel.toUpperCase()}
      </text>
      <text
        x={center}
        y={center + 18}
        textAnchor="middle"
        style={{ fontSize: 26, fontWeight: 700, fill: 'var(--text)' }}
      >
        {centerValue}
      </text>
    </svg>
  );
}

/**
 * Initials avatar. Customers have no logo field, so this is an identicon-style
 * stand-in — a deterministic hue from the name keeps each company recognisable
 * across pages without pretending to be a real uploaded logo.
 */
export function Avatar({ name, size = 28 }: { name: string; size?: number }) {
  const trimmed = name.trim();
  const parts = trimmed.split(/\s+/).filter(Boolean);
  const initials = parts.length === 0
    ? '?'
    : parts.length === 1
      ? parts[0]!.slice(0, 2).toUpperCase()
      : (parts[0]![0]! + parts[1]![0]!).toUpperCase();

  let hash = 0;
  for (let i = 0; i < trimmed.length; i++) hash = (hash * 31 + trimmed.charCodeAt(i)) % 360;

  return (
    <span
      className="avatar-chip"
      style={{
        width: size,
        height: size,
        fontSize: Math.round(size * 0.38),
        background: `linear-gradient(140deg, hsl(${hash} 70% 42% / 0.35), hsl(${(hash + 40) % 360} 70% 30% / 0.5))`,
        borderColor: `hsl(${hash} 70% 55% / 0.45)`,
        color: `hsl(${hash} 85% 78%)`,
      }}
      aria-hidden
    >
      {initials}
    </span>
  );
}

interface UsageBarProps {
  used: number;
  max: number;
}

/** "n of m" plus a fill bar — turns amber when a licence is nearly exhausted. */
export function UsageBar({ used, max }: UsageBarProps) {
  const ratio = max > 0 ? Math.min(used / max, 1) : 0;
  const tone = ratio >= 1 ? 'var(--danger)' : ratio >= 0.75 ? 'var(--warning)' : 'var(--primary)';
  return (
    <div className="usage">
      <span className="usage-text">
        {used} of {max}
      </span>
      <span className="usage-track">
        <span className="usage-fill" style={{ width: `${ratio * 100}%`, background: tone }} />
      </span>
    </div>
  );
}

interface ArcGaugeProps {
  /** 0-100. */
  score: number;
  color: string;
  size?: number;
}

/** Half-circle score gauge used by the security-posture panel. */
export function ArcGauge({ score, color, size = 150 }: ArcGaugeProps) {
  const stroke = 12;
  const radius = (size - stroke) / 2;
  const cx = size / 2;
  const cy = size / 2;
  // Semicircle: left edge → right edge over the top.
  const track = `M ${cx - radius} ${cy} A ${radius} ${radius} 0 0 1 ${cx + radius} ${cy}`;
  const length = Math.PI * radius;
  const filled = (Math.min(Math.max(score, 0), 100) / 100) * length;

  return (
    <svg width={size} height={size / 2 + 8} viewBox={`0 0 ${size} ${size / 2 + 8}`} role="img"
      aria-label={`Posture score ${score} out of 100`}>
      <path d={track} fill="none" stroke="var(--border)" strokeWidth={stroke} strokeLinecap="round" />
      <path
        d={track}
        fill="none"
        stroke={color}
        strokeWidth={stroke}
        strokeLinecap="round"
        strokeDasharray={`${filled} ${length}`}
        style={{ filter: `drop-shadow(0 0 8px ${color}77)` }}
      />
      <text x={cx} y={cy - 12} textAnchor="middle"
        style={{ fontSize: 30, fontWeight: 700, fill: 'var(--text)' }}>
        {score}
      </text>
      <text x={cx} y={cy + 4} textAnchor="middle"
        style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.12em', fill: 'var(--text-muted)' }}>
        / 100
      </text>
    </svg>
  );
}

interface MiniBarsProps {
  bars: Array<{ label: string; value: number; color: string }>;
  height?: number;
}

/** Compact labelled bar chart for the product cards. */
export function MiniBars({ bars, height = 44 }: MiniBarsProps) {
  const max = Math.max(...bars.map((b) => b.value), 1);
  return (
    <div className="flex items-end gap-1.5" style={{ height }}>
      {bars.map((b) => (
        <div key={b.label} className="flex h-full flex-1 flex-col items-center gap-1" title={`${b.label}: ${b.value}`}>
          <div className="flex w-full flex-1 items-end">
            <div
              className="min-h-[2px] w-full rounded-t-[3px]"
              style={{
                height: `${Math.max((b.value / max) * 100, b.value > 0 ? 8 : 2)}%`,
                background: b.color,
                boxShadow: b.value > 0 ? `0 0 8px ${b.color}88` : 'none',
              }}
            />
          </div>
          <div className="text-[9px] font-bold uppercase tracking-[0.06em] text-muted">{b.label}</div>
        </div>
      ))}
    </div>
  );
}

interface GaugeProps {
  value: number;
  /** Denominator for the arc. When 0 the ring shows empty rather than full. */
  max: number;
  color: string;
  label: string;
  size?: number;
}

/** Small ring + number, used for per-product stats. */
export function Gauge({ value, max, color, label, size = 46 }: GaugeProps) {
  const stroke = 4;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const ratio = max > 0 ? Math.min(value / max, 1) : 0;
  const center = size / 2;

  return (
    <div className="flex items-center gap-2">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden focusable="false">
        <circle cx={center} cy={center} r={radius} fill="none" stroke="var(--border)" strokeWidth={stroke} />
        {ratio > 0 && (
          <circle
            cx={center}
            cy={center}
            r={radius}
            fill="none"
            stroke={color}
            strokeWidth={stroke}
            strokeDasharray={`${circumference * ratio} ${circumference}`}
            strokeLinecap="round"
            transform={`rotate(-90 ${center} ${center})`}
            style={{ filter: `drop-shadow(0 0 5px ${color}66)` }}
          />
        )}
      </svg>
      <div className="min-w-0">
        <div className="text-2xs font-bold uppercase tracking-[0.08em] text-muted">{label}</div>
        <div className="text-lg font-bold leading-[1.2]" style={{ color }}>{value}</div>
      </div>
    </div>
  );
}
