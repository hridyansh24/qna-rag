import { cn } from '../../lib/utils';

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'default' | 'outline' | 'ghost' | 'destructive';
  size?: 'sm' | 'md' | 'lg';
}

export function Button({ className, variant = 'default', size = 'md', ...props }: ButtonProps) {
  return (
    <button
      className={cn(
        'inline-flex items-center justify-center whitespace-nowrap rounded-lg font-semibold transition-colors',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-canvas',
        'disabled:opacity-50 disabled:pointer-events-none',
        variant === 'default' && 'bg-accent text-on-accent shadow-sm hover:bg-accent-hover',
        variant === 'outline' && 'border border-border-strong bg-surface text-fg-secondary hover:bg-surface-hover hover:text-fg',
        variant === 'ghost' && 'text-fg-secondary hover:bg-surface-hover hover:text-fg',
        variant === 'destructive' && 'bg-danger-solid text-on-accent hover:bg-danger-solid/90',
        size === 'sm' && 'px-3 py-1.5 text-sm',
        size === 'md' && 'px-4 py-2 text-base',
        size === 'lg' && 'px-6 py-3 text-lg',
        className
      )}
      {...props}
    />
  );
}
