// v1.5.3 — header daemon health chip. Polls /api/service/status and
// renders a tiny "● 运行中 · 上次 5 min ago" indicator that doubles as a
// link to the settings page. Hidden on platforms that don't support a
// service (Linux without systemd, Windows) — matches existing balance
// badge UX.
(async function () {
  const el = document.getElementById('daemon-chip');
  if (!el) return;

  function fmtAgo(iso) {
    if (!iso) return '从未运行';
    const ms = Date.now() - new Date(iso).getTime();
    if (isNaN(ms) || ms < 0) return iso;
    const min = Math.round(ms / 60000);
    if (min < 1) return '刚刚';
    if (min < 60) return `${min} 分钟前`;
    const hr = Math.round(min / 60);
    if (hr < 48) return `${hr} 小时前`;
    return `${Math.round(hr / 24)} 天前`;
  }

  async function refresh() {
    try {
      const resp = await fetch('/api/service/status');
      if (!resp.ok) return;
      const d = await resp.json();
      if (d.platform === 'darwin' && d.desktop_app && !d.running) {
        const suffix = d.installed ? '后台未运行' : '后台未启';
        el.innerHTML = `<span class="text-emerald-600">●</span> 桌面 App 运行中 · ${suffix}`;
        el.title = '桌面窗口正在运行；后台服务只负责关掉窗口后的定时自动检查';
        el.classList.remove('hidden');
      } else if (d.platform === 'darwin' && d.installed) {
        const dot = d.running
          ? '<span class="text-emerald-600">●</span>'
          : '<span class="text-amber-600">●</span>';
        const word = d.running ? '运行中' : '已停';
        const ago = fmtAgo(d.last_run_at);
        el.innerHTML = `${dot} 后台 ${word} · 上次 ${ago}`;
        el.title = '点击查看后台自动检查详情';
        el.classList.remove('hidden');
      } else if (d.platform === 'darwin') {
        // Installed=false on macOS — gently nudge the user to enable autostart
        el.innerHTML = '<span class="text-stone-400">● 后台未启</span>';
        el.title = '点击开启后台自动检查';
        el.classList.remove('hidden');
      } else {
        // Non-Darwin: hide chip entirely, like balance badge does
        el.classList.add('hidden');
      }
    } catch (_) {
      // Silent — chip is non-critical
    }
  }
  refresh();
  // Refresh every 60s — chip is informational, not real-time
  setInterval(refresh, 60_000);
})();
