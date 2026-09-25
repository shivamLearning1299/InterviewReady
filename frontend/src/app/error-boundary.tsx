import { Component, type ErrorInfo, type ReactNode } from 'react';
import { AlertTriangle, RotateCcw } from 'lucide-react';

import { Button } from '@/components/ui/button';

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * Route-level error boundary.
 *
 * Scoped to the content area so a rendering failure in one screen never takes out the
 * shell — the sidebar and header stay usable and the user can navigate away.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Kept as a console error: there is no client-side error reporting service configured.
    console.error('Unhandled error in route', error, info.componentStack);
  }

  private reset = () => this.setState({ error: null });

  render() {
    const { error } = this.state;

    if (!error) return this.props.children;

    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4 px-6 text-center">
        <div
          aria-hidden
          className="flex size-11 items-center justify-center rounded-full border border-danger/25 bg-danger-soft text-danger"
        >
          <AlertTriangle className="size-5" />
        </div>
        <div className="max-w-md space-y-1.5">
          <h1 className="text-base font-semibold">This screen failed to render</h1>
          <p className="text-[13px] leading-relaxed text-muted-foreground">
            The rest of the app is still working — use the sidebar to move somewhere else, or
            retry this screen.
          </p>
          <pre className="mt-2 overflow-x-auto rounded-md border border-border bg-muted p-2.5 text-left text-[11px] leading-relaxed text-muted-foreground">
            {error.message}
          </pre>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="secondary" size="sm" onClick={this.reset}>
            <RotateCcw />
            Retry
          </Button>
          <Button variant="ghost" size="sm" onClick={() => window.location.reload()}>
            Reload the app
          </Button>
        </div>
      </div>
    );
  }
}
