// Easter egg interaction — click the pixel border collie to bark.
(function () {
  const btn = document.getElementById('collie');
  if (!btn) return;
  const bark = document.getElementById('collie-bark');
  const svg = btn.querySelector('svg');
  let resetTimer = null;

  btn.addEventListener('click', () => {
    const state = btn.dataset.state || 'idle';
    const copy = {
      idle: '汪!',
      ready: '开工?',
      working: '盯着呢',
      done: '完成!',
      error: '呜...',
    };
    // Reset prior animation state so rapid clicks retrigger cleanly
    if (bark) {
      bark.textContent = copy[state] || copy.idle;
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
