import { Link } from 'react-router-dom';
import { Compass } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { routes } from '@/lib/query-keys';

/** Not found. Offers the routes people actually mistype rather than a dead end. */
export function NotFoundPage() {
  return (
    <div className="flex min-h-[70vh] items-center justify-center px-4">
      <div className="max-w-md text-center">
        <div
          aria-hidden
          className="mx-auto flex size-10 items-center justify-center rounded-full border border-border bg-muted text-subtle-foreground"
        >
          <Compass className="size-5" />
        </div>

        <h1 className="mt-4 text-lg font-semibold tracking-tight">Nothing here</h1>
        <p className="mt-1.5 text-[13px] leading-relaxed text-muted-foreground">
          That page does not exist. It may have been renamed, or the link may be stale.
        </p>

        <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
          <Button asChild variant="primary" size="sm">
            <Link to={routes.today}>Go to Today</Link>
          </Button>
          <Button asChild variant="secondary" size="sm">
            <Link to={routes.dsa}>Browse DSA</Link>
          </Button>
          <Button asChild variant="ghost" size="sm">
            <Link to={routes.revisions}>Revisions</Link>
          </Button>
        </div>
      </div>
    </div>
  );
}
