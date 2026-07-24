(() => {
  "use strict";

  const root = document.documentElement;
  const key = "mead-tracker-theme";
  const allowed = new Set(["system", "light", "dark"]);
  let choice = "system";

  try {
    const stored = window.localStorage.getItem(key);
    if (allowed.has(stored)) choice = stored;
  } catch (_error) {
    // Storage can be unavailable in private or hardened browsing modes.
  }

  const systemIsDark = window.matchMedia
    && window.matchMedia("(prefers-color-scheme: dark)").matches;
  const effective = choice === "system"
    ? (systemIsDark ? "dark" : "light")
    : choice;

  root.dataset.themeChoice = choice;
  root.dataset.theme = effective;
})();
