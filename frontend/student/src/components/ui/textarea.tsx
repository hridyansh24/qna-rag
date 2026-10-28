import { cn } from '../../lib/utils';

type TextareaProps = React.TextareaHTMLAttributes<HTMLTextAreaElement>;

export function Textarea({ className, ...props }: TextareaProps) {
  return (
    <textarea
      className={cn(
        'w-full rounded-lg border border-border-strong bg-surface-sunken px-3 py-2',
        'text-fg placeholder:text-fg-muted',
        'focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent',
        className
      )}
      {...props}
    />
  );
}
