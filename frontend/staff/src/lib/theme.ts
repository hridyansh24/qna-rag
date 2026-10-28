import { useEffect, useState } from 'react';

export type Theme = 'light' | 'dark';

/** Same key and logic as the pre-paint script in index.html. */
const STORAGE_KEY = 'qna-theme';
const media = window.matchMedia('(prefers-color-scheme: dark)');

function storedTheme(): Theme | null {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    return value === 'light' || value === 'dark' ? value : null;
  } catch {
    return null;
  }
}

function systemTheme(): Theme {
  return media.matches ? 'dark' : 'light';
}

function apply(theme: Theme) {
  document.documentElement.dataset.theme = theme;
}

/**
 * The current theme and a toggle. The first visit follows the OS preference
 * (and keeps following it while no choice is stored); toggling saves the
 * choice, so it persists across reloads.
 */
export function useTheme() {
  const [theme, setTheme] = useState<Theme>(() => storedTheme() ?? systemTheme());

  useEffect(() => apply(theme), [theme]);

  useEffect(() => {
    function onSystemChange() {
      if (!storedTheme()) setTheme(systemTheme());
    }
    media.addEventListener('change', onSystemChange);
    return () => media.removeEventListener('change', onSystemChange);
  }, []);

  function toggle() {
    const next: Theme = theme === 'dark' ? 'light' : 'dark';
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Storage blocked: the toggle still works for this page view.
    }
    setTheme(next);
  }

  return { theme, toggle };
}
