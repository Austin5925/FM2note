// Render the top-nav balance badge and optionally pop the critical-low modal.
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
      badge.classList.add('text-stone-500');
      return;
    }
    const cash = (data.available_cash_amount || 0).toFixed(2);
    const cur = data.currency || 'CNY';
    badge.textContent = `${cur === 'CNY' ? '¥' : cur + ' '}${cash}`;
    badge.classList.remove('hidden');
    if (data.alert_level === 'critical') {
      badge.classList.add('bg-red-100', 'text-red-700', 'border-red-200');
      showCriticalModal(cur, cash);
    } else if (data.alert_level === 'warn') {
      badge.classList.add('bg-amber-100', 'text-amber-700', 'border-amber-200');
    } else {
      badge.classList.add('bg-emerald-50', 'text-emerald-700', 'border-emerald-200');
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
  // Eagerly try to load QR; the img's onerror handler hides it if missing.
  const qr = document.getElementById('balance-qr');
  if (qr) qr.classList.remove('hidden');
  close.addEventListener('click', () => modal.classList.add('hidden'));
  modal.addEventListener('click', (e) => {
    if (e.target === modal) modal.classList.add('hidden');
  });
}
