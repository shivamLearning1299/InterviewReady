import { forwardRef, type HTMLAttributes } from 'react';
import { cva, type VariantProps } from 'class-variance-authority';

import { cn } from '@/lib/utils';

/**
 * The base surface used for every panel, table wrapper and sidebar section. A single
 * definition keeps borders and radii consistent across the app.
 */
const cardVariants = cva('rounded-[var(--radius-card)] border border-border bg-surface', {
  variants: {
    padding: {
      none: 'p-0',
      sm: 'p-3',
      md: 'p-4',
      lg: 'p-5',
      xl: 'p-6',
    },
    tone: {
      default: '',
      muted: 'bg-muted',
      transparent: 'bg-transparent',
    },
  },
  defaultVariants: { padding: 'md', tone: 'default' },
});

export interface CardProps
  extends HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof cardVariants> {}

export const Card = forwardRef<HTMLDivElement, CardProps>(function Card(
  { className, padding, tone, ...props },
  ref,
) {
  return <div ref={ref} className={cn(cardVariants({ padding, tone }), className)} {...props} />;
});

/** Card header: title on the left, actions on the right. Compact by design. */
export function CardHeader({
  title,
  description,
  actions,
  className,
  titleClassName,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
  titleClassName?: string;
}) {
  return (
    <div className={cn('flex items-start justify-between gap-4', className)}>
      <div className="min-w-0">
        <h2 className={cn('text-sm font-semibold tracking-tight', titleClassName)}>{title}</h2>
        {description ? (
          <p className="mt-0.5 text-[13px] text-muted-foreground">{description}</p>
        ) : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </div>
  );
}

export function CardDivider({ className }: { className?: string }) {
  return <div className={cn('-mx-4 my-4 h-px bg-border', className)} />;
}
