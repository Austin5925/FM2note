// History page — list state.db episodes + pending summaries.
(async function () {
  const loading = document.getElementById('history-loading');
  const list = document.getElementById('history-list');
  const empty = document.getElementById('history-empty');
  const pendingHeading = document.getElementById('pending-heading');
  const pendingList = document.getElementById('pending-list');
  const retryAllBtn = document.getElementById('retry-all-btn');

  async function reload() {
    try {
      const resp = await fetch('/api/history?limit=50');
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      const data = await resp.json();
      renderEpisodes(data.episodes || []);
      renderPending(data.pending_summaries || []);
    } catch (e) {
      loading.textContent = '加载失败：' + e.message;
    }
  }

  function renderEpisodes(items) {
    loading.classList.add('hidden');
    if (items.length === 0) {
      empty.classList.remove('hidden');
      list.classList.add('hidden');
      return;
    }
    empty.classList.add('hidden');
    list.classList.remove('hidden');
    list.innerHTML = items.map(renderEpisodeRow).join('');
  }

  function renderEpisodeRow(ep) {
    const statusInfo = statusBadge(ep.status);
    const time = ep.updated_at ? new Date(ep.updated_at).toLocaleString('zh-CN') : '';
    const openBtn = ep.note_path
      ? `<a href="#" data-action="open" data-note-path="${escapeHtml(ep.note_path)}"
            class="text-xs px-2 py-1 rounded-md bg-stone-900 text-white hover:bg-stone-700">看笔记</a>`
      : '';
    const errorRow = ep.error_msg
      ? `<div class="text-xs text-red-600 mt-1">${escapeHtml(ep.error_msg)}</div>`
      : '';
    return `
      <li class="p-4 border border-stone-200 rounded-lg bg-white">
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0 flex-1">
            <div class="text-xs text-stone-500">${escapeHtml(ep.podcast_name || '—')}</div>
            <div class="text-sm font-medium truncate">${escapeHtml(ep.title)}</div>
            <div class="text-xs text-stone-400 mt-1">${time}</div>
            ${errorRow}
          </div>
          <div class="flex items-center gap-2 shrink-0">
            ${statusInfo}
            ${openBtn}
          </div>
        </div>
      </li>
    `;
  }

  function renderPending(items) {
    if (items.length === 0) {
      pendingHeading.classList.add('hidden');
      pendingList.classList.add('hidden');
      retryAllBtn.classList.add('hidden');
      return;
    }
    pendingHeading.classList.remove('hidden');
    pendingList.classList.remove('hidden');
    retryAllBtn.classList.remove('hidden');
    pendingList.innerHTML = items.map(renderPendingRow).join('');
  }

  function renderPendingRow(item) {
    return `
      <li class="p-4 border border-amber-200 rounded-lg bg-amber-50">
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0 flex-1">
            <div class="text-xs text-amber-700">${escapeHtml(item.podcast_name || '—')}</div>
            <div class="text-sm font-medium truncate">${escapeHtml(item.title)}</div>
          </div>
          <button data-action="retry" data-id="${escapeHtml(item.id)}"
                  class="text-xs px-2 py-1 rounded-md bg-amber-600 text-white hover:bg-amber-500">
            重试摘要
          </button>
        </div>
      </li>
    `;
  }

  function statusBadge(status) {
    const cls = {
      done: 'bg-emerald-100 text-emerald-700',
      failed: 'bg-red-100 text-red-700',
      transcribing: 'bg-stone-100 text-stone-700',
      writing: 'bg-stone-100 text-stone-700',
      pending: 'bg-stone-100 text-stone-700',
      downloading: 'bg-stone-100 text-stone-700',
    }[status] || 'bg-stone-100 text-stone-700';
    return `<span class="text-xs px-2 py-0.5 rounded-md ${cls}">${escapeHtml(status || '?')}</span>`;
  }

  function escapeHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  // -- Event delegation --
  document.body.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-action]');
    if (!btn) return;
    const action = btn.dataset.action;
    if (action === 'open') {
      e.preventDefault();
      const notePath = btn.dataset.notePath;
      const url = await buildObsidianUrl(notePath);
      if (url) window.location.href = url;
    } else if (action === 'retry') {
      btn.disabled = true;
      btn.textContent = '重试中…';
      const resp = await fetch('/api/history/retry-summary', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: btn.dataset.id }),
      });
      const data = await resp.json().catch(() => ({}));
      if (data.ok) {
        await reload();
      } else {
        btn.disabled = false;
        btn.textContent = '失败（点击重试）';
      }
    }
  });

  retryAllBtn.addEventListener('click', async () => {
    retryAllBtn.disabled = true;
    retryAllBtn.textContent = '处理中…';
    try {
      const resp = await fetch('/api/history/retry-all', { method: 'POST' });
      const data = await resp.json();
      retryAllBtn.textContent = `完成 ${data.success}/${data.total}（失败 ${data.failed}）`;
      await reload();
    } finally {
      setTimeout(() => {
        retryAllBtn.disabled = false;
        retryAllBtn.textContent = '重试所有失败摘要';
      }, 3000);
    }
  });

  async function buildObsidianUrl(notePath) {
    // The note path is absolute; ask the server to compute the deep link
    try {
      const resp = await fetch('/api/settings');
      if (!resp.ok) return null;
      const s = await resp.json();
      const vaultPath = s.vault_path;
      if (!vaultPath || !notePath.startsWith(vaultPath)) return null;
      const rel = notePath.slice(vaultPath.length).replace(/^\//, '').replace(/\.md$/, '');
      const vaultName = vaultPath.split('/').filter(Boolean).pop();
      return `obsidian://open?vault=${encodeURIComponent(vaultName)}&file=${encodeURIComponent(rel)}`;
    } catch (_) {
      return null;
    }
  }

  reload();
})();
