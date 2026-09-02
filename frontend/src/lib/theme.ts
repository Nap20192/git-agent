/** Theme toggle: dark (default) / light. Persisted to localStorage and applied
 *  as data-theme on <html>, where tokens.css scopes the palette. */
import { useEffect, useState } from "react";

export type Theme = "dark" | "light";
const KEY = "git-agent:theme";

function stored(): Theme {
  const t = typeof localStorage !== "undefined" ? localStorage.getItem(KEY) : null;
  return t === "light" ? "light" : "dark";
}

export function useTheme(): { theme: Theme; toggle: () => void } {
  const [theme, setTheme] = useState<Theme>(stored);
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    try {
      localStorage.setItem(KEY, theme);
    } catch {
      /* ignore */
    }
  }, [theme]);
  return { theme, toggle: () => setTheme((t) => (t === "dark" ? "light" : "dark")) };
}
