import { strings } from "../strings.js";

export default function ThemeToggle({ theme, setTheme }) {
  const dark = theme === "dark";
  return (
    <button
      type="button"
      className="textButton"
      aria-pressed={dark}
      onClick={() => setTheme(dark ? "light" : "dark")}
    >
      <span>{strings.themeName}</span>
      <span className="toggleState">{dark ? strings.themeDark : strings.themeLight}</span>
    </button>
  );
}
