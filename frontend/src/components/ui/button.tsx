import { forwardRef, type ButtonHTMLAttributes } from 'react';
import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';

import { cn } from '@/lib/utils';

const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-[var(--radius-control)] font-medium transition-colors disabled:pointer-events-none disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring [&_svg]:shrink-0',
  {
    variants: {
      variant: {
        primary: 'bg-primary text-primary-foreground hover:bg-primary-hover',
        secondary: 'bg-accent text-accent-foreground hover:bg-surface-hover border border-border',
        outline: 'border border-border-strong bg-transparent hover:bg-surface-hover',
        ghost: 'bg-transparent hover:bg-accent text-foreground',
        subtle: 'bg-transparent text-muted-foreground hover:bg-accent hover:text-foreground',
        danger: 'bg-danger text-white hover:opacity-90',
        link: 'bg-transparent text-primary underline-offset-4 hover:underline h-auto px-0',
      },
      size: {
        sm: 'h-8 px-2.5 text-[13px] [&_svg]:size-3.5',
        md: 'h-9 px-3.5 text-sm [&_svg]:size-4',
        lg: 'h-10 px-5 text-sm [&_svg]:size-4',
        icon: 'size-9 [&_svg]:size-4',
        'icon-sm': 'size-7 [&_svg]:size-3.5',
      },
    },
    defaultVariants: { variant: 'secondary', size: 'md' },
  },
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  /** Renders a busy label state without changing width. */
  loading?: boolean;
  /**
   * Render as the child element (typically an `<a>` from `Link`) while keeping the button
   * styles. Used by every navigation action so links stay real links.
   */
  asChild?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant, size, loading = false, disabled, asChild = false, children, ...props },
  ref,
) {
  const Component = asChild ? Slot : 'button';

  // `Slot` forwards to a single child, so the spinner cannot be injected alongside it.
  if (asChild) {
    return (
      <Component
        ref={ref}
        className={cn(buttonVariants({ variant, size }), className)}
        aria-disabled={disabled || undefined}
        {...props}
      >
        {children}
      </Component>
    );
  }

  return (
    <Component
      ref={ref}
      className={cn(buttonVariants({ variant, size }), className)}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...props}
    >
      {loading ? (
        <span
          aria-hidden
          className="size-3.5 animate-spin rounded-full border-2 border-current border-t-transparent"
        />
      ) : null}
      {children}
    </Component>
  );
});

export { buttonVariants };
