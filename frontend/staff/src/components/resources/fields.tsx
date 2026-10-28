import { cloneElement, isValidElement, useId, type ReactElement, type ReactNode } from 'react';
import { cn } from '../../lib/utils';

/** Matches components/ui/input.tsx, for native <select>s. */
export const selectClass =
  'w-full rounded-lg border border-border-strong bg-surface-sunken px-3 py-2 text-fg ' +
  'focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent';

/**
 * A labelled form control with an optional hint underneath. The hint sits
 * outside the <label>, so it isn't part of the control's accessible name,
 * and is linked to the control with aria-describedby instead.
 */
export function Field({
  label,
  hint,
  className,
  children,
}: {
  label: string;
  hint?: ReactNode;
  className?: string;
  children: ReactElement;
}) {
  const hintId = useId();
  const control =
    hint && isValidElement<{ 'aria-describedby'?: string }>(children)
      ? cloneElement(children, { 'aria-describedby': hintId })
      : children;
  return (
    <div className={cn('space-y-1.5', className)}>
      <label className="block space-y-1.5">
        <span className="block text-sm font-medium text-fg-secondary">{label}</span>
        {control}
      </label>
      {hint && (
        <span id={hintId} className="block text-xs text-fg-muted">
          {hint}
        </span>
      )}
    </div>
  );
}

/** A titled block on the Resources page. */
export function Section({
  title,
  description,
  action,
  children,
}: {
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="space-y-3">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h3 className="text-lg font-semibold text-fg">{title}</h3>
          {description && <p className="text-sm text-fg-muted mt-0.5">{description}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

/** Short relative time, e.g. "3 min ago". */
export function timeAgo(iso: string | null): string {
  if (!iso) return '';
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return 'just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
  return new Date(iso).toLocaleDateString();
}
