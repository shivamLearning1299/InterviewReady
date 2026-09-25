import { useState, type ReactNode } from 'react';

import { cn } from '@/lib/utils';

/** Accessible switch with an inline label and description. */
export function Switch({
  checked,
  onChange,
  label,
  description,
  disabled = false,
  id,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  description?: string;
  disabled?: boolean;
  id?: string;
}) {
  const controlId = id ?? `switch-${label.replace(/\s+/g, '-').toLowerCase()}`;

  return (
    <div className="flex items-start justify-between gap-4">
      <div className="min-w-0">
        <label htmlFor={controlId} className="text-[13px] font-medium">
          {label}
        </label>
        {description ? (
          <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>
        ) : null}
      </div>
      <button
        id={controlId}
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={cn(
          'relative mt-0.5 h-5 w-9 shrink-0 rounded-full border transition-colors disabled:opacity-50',
          checked ? 'border-primary bg-primary' : 'border-border-strong bg-muted',
        )}
      >
        <span
          className={cn(
            'absolute top-0.5 size-3.5 rounded-full bg-white shadow-sm transition-[left]',
            checked ? 'left-[18px]' : 'left-0.5',
          )}
        />
      </button>
    </div>
  );
}

/** Segmented control for two-to-four mutually exclusive options. */
export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  size = 'md',
  className,
  label,
}: {
  options: readonly { value: T; label: ReactNode; title?: string }[];
  value: T;
  onChange: (value: T) => void;
  size?: 'sm' | 'md';
  className?: string;
  label?: string;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className={cn('inline-flex items-center gap-0.5 rounded-[var(--radius-control)] border border-border bg-muted p-0.5', className)}
    >
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={selected}
            title={option.title}
            onClick={() => onChange(option.value)}
            className={cn(
              'rounded-[calc(var(--radius-control)-2px)] font-medium transition-colors',
              size === 'sm' ? 'px-2 py-1 text-[12px]' : 'px-2.5 py-1 text-[13px]',
              selected
                ? 'bg-surface text-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground',
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

/**
 * Confidence picker on the 0–5 scale the API expects. Exposed as a radio group so it is
 * keyboard navigable rather than a row of plain buttons.
 */
export function ConfidencePicker({
  value,
  onChange,
  disabled = false,
  compact = false,
}: {
  value: number | null;
  onChange: (value: number) => void;
  disabled?: boolean;
  compact?: boolean;
}) {
  const [hovered, setHovered] = useState<number | null>(null);
  const active = hovered ?? value ?? 0;

  return (
    <div
      role="radiogroup"
      aria-label="Confidence"
      className="inline-flex items-center gap-1"
      onMouseLeave={() => setHovered(null)}
    >
      {[1, 2, 3, 4, 5].map((score) => (
        <button
          key={score}
          type="button"
          role="radio"
          aria-checked={value === score}
          aria-label={`Confidence ${score} of 5`}
          disabled={disabled}
          onMouseEnter={() => setHovered(score)}
          onClick={() => onChange(score)}
          className={cn(
            'rounded border font-medium tabular transition-colors disabled:opacity-50',
            compact ? 'size-6 text-[11px]' : 'size-7 text-xs',
            active >= score
              ? 'border-primary/30 bg-primary-soft text-primary'
              : 'border-border bg-surface text-subtle-foreground hover:border-border-strong',
          )}
        >
          {score}
        </button>
      ))}
    </div>
  );
}

/** Read-only confidence display for tables and cards. */
export function ConfidenceMeter({ value }: { value: number | null | undefined }) {
  const score = value ?? 0;
  return (
    <span className="inline-flex items-center gap-1" title={score ? `${score} / 5` : 'Not rated'}>
      {[1, 2, 3, 4, 5].map((step) => (
        <span
          key={step}
          aria-hidden
          className={cn(
            'h-3 w-1 rounded-sm',
            step <= score ? 'bg-primary' : 'bg-border',
          )}
        />
      ))}
      <span className="sr-only">{score ? `Confidence ${score} of 5` : 'Not rated'}</span>
    </span>
  );
}
