import { Outlet } from "react-router";
import { ThemeProvider } from "./theme-context";

export function Layout() {
  return (
    <ThemeProvider>
      <Outlet />
    </ThemeProvider>
  );
}
