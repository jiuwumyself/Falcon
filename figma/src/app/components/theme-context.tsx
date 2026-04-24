import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from "react";

type Theme = "dark" | "light";

interface ThemeCtx {
  theme: Theme;
  toggleTheme: (e: React.MouseEvent) => void;
  ripple: { x: number; y: number; active: boolean };
}

const ThemeContext = createContext<ThemeCtx>({
  theme: "dark",
  toggleTheme: () => {},
  ripple: { x: 0, y: 0, active: false },
});

export const useTheme = () => useContext(ThemeContext);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>("dark");
  const [ripple, setRipple] = useState({ x: 0, y: 0, active: false });

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
  }, [theme]);

  const toggleTheme = useCallback((e: React.MouseEvent) => {
    setRipple({ x: e.clientX, y: e.clientY, active: true });
    setTimeout(() => {
      setTheme((t) => (t === "dark" ? "light" : "dark"));
      setTimeout(() => setRipple((r) => ({ ...r, active: false })), 600);
    }, 50);
  }, []);

  return (
    <ThemeContext.Provider value={{ theme, toggleTheme, ripple }}>
      {children}
    </ThemeContext.Provider>
  );
}
