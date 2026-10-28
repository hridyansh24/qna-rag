import { cn } from '../../lib/utils';

type InputProps = React.InputHTMLAttributes<HTMLInputElement>;

export function Input({ className, ...props }: InputProps) {
  return (
    <input
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
