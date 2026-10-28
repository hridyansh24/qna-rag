import { Moon, Sun } from 'lucide-react';
import { useTheme } from '../lib/theme';
import { cn } from '../lib/utils';

/** Light/dark switch (T8). Shows the theme it switches to. */
export function ThemeToggle({ className }: { className?: string }) {
  const { theme, toggle } = useTheme();
  const next = theme === 'dark' ? 'light' : 'dark';

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={`Switch to ${next} theme`}
      title={`Switch to ${next} theme`}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-sm',
        'text-fg-secondary hover:bg-surface-hover hover:text-fg transition-colors',
        className
      )}
    >
      {next === 'light' ? <Sun size={16} aria-hidden /> : <Moon size={16} aria-hidden />}
      <span>{next === 'light' ? 'Light' : 'Dark'}</span>
    </button>
  );
}
