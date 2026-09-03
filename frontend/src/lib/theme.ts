/** Theme toggle: light (default) / dark. Persisted to localStorage 'ga-hub-theme'
 *  and applied as data-theme on <html>, where vk-colors.css scopes the palette. */
import { useEffect, useState } from "react";

export type Theme = "dark" | "light";
const KEY = "ga-hub-theme";

function stored(): Theme {
  try {
    return localStorage.getItem(KEY) === "dark" ? "dark" : "light";
  } catch {
    return "light";
  }
}

export function useTheme(): { theme: Theme; label: string; toggle: () => void } {
  const [theme, setTheme] = useState<Theme>(stored);
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    try {
      localStorage.setItem(KEY, theme);
    } catch {
      /* ignore */
    }
  }, [theme]);
  return {
    theme,
    label: `theme → ${theme === "dark" ? "light" : "dark"}`,
    toggle: () => setTheme((t) => (t === "dark" ? "light" : "dark")),
  };
}
