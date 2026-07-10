// Render the top-nav balance badge and optionally pop the critical-low modal.
// "Dismiss" persists in sessionStorage so navigating between tabs in the same
// window doesn't re-trigger the popup — it comes back only after the window is
// closed and reopened (or a new browser tab is started).
const DISMISS_KEY = 'fm2note-balance-modal-dismissed';

(async function () {
  const badge = document.getElementById('balance-badge');
  if (!badge) return;
  try {
    const resp = await fetch('/api/balance');
    if (!resp.ok) return;
    const data = await resp.json();
    if (!data.configured) return;
    if (data.error) {
      badge.textContent = '余额查询失败';
      badge.classList.remove('hidden');
      badge.classList.add('text-stone-500', 'dark:text-stone-400');
      return;
    }
    const cash = (data.available_cash_amount || 0).toFixed(2);
    const cur = data.currency || 'CNY';
    badge.textContent = `${cur === 'CNY' ? '¥' : cur + ' '}${cash}`;
    badge.classList.remove('hidden');
    if (data.alert_level === 'critical') {
      badge.classList.add(
        'bg-red-100', 'text-red-700', 'border-red-200',
        'dark:bg-red-950', 'dark:text-red-300', 'dark:border-red-800'
      );
      if (sessionStorage.getItem(DISMISS_KEY) !== '1') {
        showCriticalModal(cur, cash);
      }
    } else if (data.alert_level === 'warn') {
      badge.classList.add(
        'bg-amber-100', 'text-amber-700', 'border-amber-200',
        'dark:bg-amber-950', 'dark:text-amber-300', 'dark:border-amber-800'
      );
    } else {
      badge.classList.add(
        'bg-emerald-50', 'text-emerald-700', 'border-emerald-200',
        'dark:bg-emerald-950', 'dark:text-emerald-300', 'dark:border-emerald-800'
      );
    }
  } catch (_) {
    // silent
  }
})();

function showCriticalModal(currency, cash) {
  const modal = document.getElementById('balance-modal');
  const amount = document.getElementById('balance-modal-amount');
  const close = document.getElementById('balance-modal-close');
  if (!modal || !amount || !close) return;
  amount.textContent = `当前可用现金余额：${currency === 'CNY' ? '¥' : currency + ' '}${cash}`;
  modal.classList.remove('hidden');

  // Any of these dismissal paths persists the "don't pop again this window"
  // flag — sessionStorage scope is the browser tab/window, so closing &
  // reopening fm2note app starts fresh.
  const dismiss = () => {
    modal.classList.add('hidden');
    try { sessionStorage.setItem(DISMISS_KEY, '1'); } catch (_) {}
  };
  close.addEventListener('click', dismiss);
  modal.addEventListener('click', (e) => {
    if (e.target === modal) dismiss();
  });
}
