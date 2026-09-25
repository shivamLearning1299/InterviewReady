import { cn } from '@/lib/utils';

export type ProgressTone = 'primary' | 'success' | 'warning' | 'danger' | 'info' | 'easy' | 'medium' | 'hard' | 'neutral';

const TONE_CLASS: Record<ProgressTone, string> = {
  primary: 'bg-primary',
  success: 'bg-success',
  warning: 'bg-warning',
  danger: 'bg-danger',
  info: 'bg-info',
  easy: 'bg-easy',
  medium: 'bg-medium',
  hard: 'bg-hard',
  neutral: 'bg-subtle-foreground',
};

export interface ProgressBarProps {
  value: number;
  max?: number;
  tone?: ProgressTone;
  size?: 'xs' | 'sm' | 'md';
  className?: string;
  /** Accessible label; the numbers are also exposed as text when `showValue` is set. */
  label?: string;
  showValue?: boolean;
}

/**
 * Thin determinate progress bar. Values are clamped, so a backend that overshoots its
 * total (or a stale cache) cannot render a bar that escapes its track.
 */
export function ProgressBar({
  value,
  max = 100,
  tone = 'primary',
  size = 'sm',
  className,
  label,
  showValue = false,
}: ProgressBarProps) {
  const safeMax = max > 0 ? max : 100;
  const ratio = Math.min(Math.max(value / safeMax, 0), 1);
  const percentage = Math.round(ratio * 100);

  const height = size === 'xs' ? 'h-1' : size === 'sm' ? 'h-1.5' : 'h-2';

  return (
    <div className={cn('space-y-1', className)}>
      <div
        role="progressbar"
        aria-valuenow={Math.round(value)}
        aria-valuemin={0}
        aria-valuemax={safeMax}
        aria-label={label}
        className={cn('w-full overflow-hidden rounded-full bg-muted', height)}
      >
        <div
          className={cn('h-full rounded-full transition-[width] duration-300 ease-out', TONE_CLASS[tone])}
          style={{ width: `${percentage}%` }}
        />
      </div>
      {showValue ? (
        <p className="tabular text-xs text-muted-foreground">
          {Math.round(value)} / {safeMax}
        </p>
      ) : null}
    </div>
  );
}

/**
 * Progress expressed as "127 / 400" with the percentage beside it — the recurring
 * numerator/denominator pattern used on Today and Statistics.
 */
export function ProgressStat({
  label,
  value,
  total,
  tone = 'primary',
  className,
  compact = false,
  hint,
}: {
  label: string;
  value: number;
  total: number;
  tone?: ProgressTone;
  className?: string;
  compact?: boolean;
  hint?: string;
}) {
  return (
    <div className={cn('space-y-1.5', className)}>
      <div className="flex items-baseline justify-between gap-3">
        <span className={cn('font-medium text-foreground', compact ? 'text-[13px]' : 'text-sm')}>
          {label}
        </span>
        <span className="tabular text-[13px] text-muted-foreground">
          <span className="font-semibold text-foreground">{value}</span>
          <span className="mx-0.5">/</span>
          {total}
        </span>
      </div>
      <ProgressBar value={value} max={total} tone={tone} size={compact ? 'xs' : 'sm'} label={label} />
      {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

/** Segmented bar for a status breakdown (e.g. mastered / solved / remaining). */
export function StackedBar({
  segments,
  className,
  size = 'sm',
}: {
  segments: { value: number; tone: ProgressTone; label: string }[];
  className?: string;
  size?: 'xs' | 'sm' | 'md';
}) {
  const total = segments.reduce((sum, segment) => sum + segment.value, 0);
  const height = size === 'xs' ? 'h-1' : size === 'sm' ? 'h-1.5' : 'h-2';

  if (total <= 0) {
    return <div className={cn('w-full rounded-full bg-muted', height, className)} />;
  }

  return (
    <div className={cn('flex w-full overflow-hidden rounded-full bg-muted', height, className)}>
      {segments.map((segment) => (
        <div
          key={segment.label}
          title={`${segment.label}: ${segment.value}`}
          className={cn('h-full transition-[width] duration-300 ease-out', TONE_CLASS[segment.tone])}
          style={{ width: `${(segment.value / total) * 100}%` }}
        />
      ))}
    </div>
  );
}

/** Small inline ring, used for compact topic-completion figures. */
export function ProgressRing({
  value,
  max = 100,
  size = 40,
  strokeWidth = 3,
  tone = 'primary',
  className,
  children,
}: {
  value: number;
  max?: number;
  size?: number;
  strokeWidth?: number;
  tone?: ProgressTone;
  className?: string;
  children?: React.ReactNode;
}) {
  const safeMax = max > 0 ? max : 100;
  const ratio = Math.min(Math.max(value / safeMax, 0), 1);
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;

  const strokeColour: Record<ProgressTone, string> = {
    primary: 'stroke-primary',
    success: 'stroke-success',
    warning: 'stroke-warning',
    danger: 'stroke-danger',
    easy: 'stroke-easy',
    info: 'stroke-info',
    medium: 'stroke-medium',
    hard: 'stroke-hard',
    neutral: 'stroke-subtle-foreground',
  };

  return (
    <div className={cn('relative inline-flex items-center justify-center', className)} style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90" aria-hidden>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={strokeWidth}
          className="stroke-muted"
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - ratio)}
          className={cn('transition-[stroke-dashoffset] duration-300', strokeColour[tone])}
        />
      </svg>
      <span className="absolute inset-0 flex items-center justify-center">{children}</span>
    </div>
  );
}
