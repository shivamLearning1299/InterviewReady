import type { ReactNode } from 'react';
import { cva, type VariantProps } from 'class-variance-authority';

import { cn } from '@/lib/utils';

/**
 * Badges carry status through a subtle tinted background plus a matching border. Colour is
 * never the only signal — the label always states the status in words.
 */
const badgeVariants = cva(
  'inline-flex items-center gap-1.5 rounded-md border font-medium whitespace-nowrap',
  {
    variants: {
      tone: {
        neutral: 'bg-neutral-soft text-muted-foreground border-border',
        primary: 'bg-primary-soft text-primary border-primary/25',
        success: 'bg-success-soft text-success border-success/25',
        warning: 'bg-warning-soft text-warning border-warning/25',
        danger: 'bg-danger-soft text-danger border-danger/25',
        info: 'bg-info-soft text-info border-info/25',
        easy: 'bg-easy-soft text-easy border-easy/25',
        medium: 'bg-medium-soft text-medium border-medium/25',
        hard: 'bg-hard-soft text-hard border-hard/25',
        outline: 'border-border-strong text-muted-foreground',
      },
      size: {
        sm: 'px-1.5 py-0.5 text-[11px] leading-4',
        md: 'px-2 py-0.5 text-xs leading-5',
        lg: 'px-2.5 py-1 text-[13px] leading-5',
      },
      shape: {
        rounded: '',
        pill: 'rounded-full',
      },
    },
    defaultVariants: { tone: 'neutral', size: 'md', shape: 'rounded' },
  },
);

export interface BadgeProps extends VariantProps<typeof badgeVariants> {
  children: ReactNode;
  className?: string;
  /** Optional leading dot — useful when the badge sits next to other coloured elements. */
  dot?: boolean;
  title?: string;
}

export function Badge({ children, className, tone, size, shape, dot, title }: BadgeProps) {
  return (
    <span className={cn(badgeVariants({ tone, size, shape }), className)} title={title}>
      {dot ? <span aria-hidden className="size-1.5 rounded-full bg-current opacity-70" /> : null}
      {children}
    </span>
  );
}

export { badgeVariants };
