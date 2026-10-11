import React from "react";

export function getInitialTheme() {
  try {
    const saved = window.localStorage.getItem("mm-theme");
    if (saved === "light" || saved === "dark") return saved;
  } catch {
    /* storage unavailable */
  }

  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function useTheme() {
  const [theme, setTheme] = React.useState(getInitialTheme);

  React.useEffect(() => {
    const root = document.documentElement;
    const previousTheme = root.getAttribute("data-theme");
    const previousScheme = root.style.colorScheme;

    root.dataset.theme = theme;
    root.style.colorScheme = theme;
    try {
      window.localStorage.setItem("mm-theme", theme);
    } catch {
      /* storage unavailable */
    }

    return () => {
      if (previousTheme) root.setAttribute("data-theme", previousTheme);
      else root.removeAttribute("data-theme");
      root.style.colorScheme = previousScheme;
    };
  }, [theme]);

  return [theme, setTheme];
}
