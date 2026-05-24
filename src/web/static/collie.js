// Easter egg interaction — click the pixel border collie to bark.
(function () {
  const btn = document.getElementById('collie');
  if (!btn) return;
  const bark = document.getElementById('collie-bark');
  const svg = btn.querySelector('svg');
  let resetTimer = null;

  btn.addEventListener('click', () => {
    // Reset prior animation state so rapid clicks retrigger cleanly
    if (bark) {
      bark.classList.remove('collie-bark-visible');
      // Force reflow so the animation restarts when we re-add the class
      void bark.offsetWidth;
      bark.classList.add('collie-bark-visible');
    }
    if (svg) {
      svg.classList.remove('collie-shake');
      void svg.offsetWidth;
      svg.classList.add('collie-shake');
    }

    clearTimeout(resetTimer);
    resetTimer = setTimeout(() => {
      if (bark) bark.classList.remove('collie-bark-visible');
      if (svg) svg.classList.remove('collie-shake');
    }, 800);
  });
})();
