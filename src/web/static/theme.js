// Theme toggle — single icon, click flips to the opposite of the current
// rendered theme. Initial state follows the OS preference (no localStorage
// entry); the first click persists an explicit 'light' or 'dark' choice.
//
// The icon shows what you *will get* if you click:
//   - light mode showing → moon icon (click → dark)
//   - dark  mode showing → sun  icon (click → light)
//
// The initial `dark` class on <html> is applied by base.html's inline <head>
// script (pre-paint) — this file only wires the toggle and keeps "system"
// mode in sync with OS preference changes mid-session.
(function () {
  const KEY = 'fm2note-theme';
  const btn = document.getElementById('theme-toggle');
  if (!btn) return;
  const sun = document.getElementById('theme-icon-sun');
  const moon = document.getElementById('theme-icon-moon');
  if (!sun || !moon) return;

  function readStored() {
    try { return localStorage.getItem(KEY) || 'system'; } catch (_) { return 'system'; }
  }
  function writeStored(value) {
    try { localStorage.setItem(KEY, value); } catch (_) {}
  }

  function effectiveIsDark() {
    return document.documentElement.classList.contains('dark');
  }

  function paintIcon() {
    const dark = effectiveIsDark();
    // Show the icon for the destination, not the current state
    sun.classList.toggle('hidden', !dark);
    moon.classList.toggle('hidden', dark);
  }

  // First paint of the icon — the `dark` class is already correct from the
  // inline head script, so we just mirror it.
  paintIcon();

  btn.addEventListener('click', () => {
    const becomingDark = !effectiveIsDark();
    document.documentElement.classList.toggle('dark', becomingDark);
    writeStored(becomingDark ? 'dark' : 'light');
    paintIcon();
  });

  // Keep "system" mode in sync if the OS preference flips mid-session.
  if (window.matchMedia) {
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const handler = (e) => {
      if (readStored() === 'system') {
        document.documentElement.classList.toggle('dark', e.matches);
        paintIcon();
      }
    };
    if (mq.addEventListener) mq.addEventListener('change', handler);
    else if (mq.addListener) mq.addListener(handler);
  }
})();
