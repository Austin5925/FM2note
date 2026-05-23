// Subscriptions page — list/add/edit/delete podcast RSS feeds.
(function () {
  const listEl = document.getElementById('subs-list');
  const emptyEl = document.getElementById('subs-empty');
  const loadingEl = document.getElementById('subs-loading');
  const addBtn = document.getElementById('add-sub-btn');
  const modal = document.getElementById('sub-modal');
  const modalTitle = document.getElementById('sub-modal-title');
  const indexInput = document.getElementById('sub-index');
  const nameInput = document.getElementById('sub-name');
  const rssInput = document.getElementById('sub-rss');
  const tagsInput = document.getElementById('sub-tags');
  const testResult = document.getElementById('sub-test-result');
  const testBtn = document.getElementById('sub-test-btn');
  const cancelBtn = document.getElementById('sub-cancel-btn');
  const saveBtn = document.getElementById('sub-save-btn');

  function escapeHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  async function reload() {
    loadingEl.classList.remove('hidden');
    listEl.classList.add('hidden');
    emptyEl.classList.add('hidden');
    try {
      const resp = await fetch('/api/subscriptions');
      const data = await resp.json();
      const subs = data.subscriptions || [];
      loadingEl.classList.add('hidden');
      if (subs.length === 0) {
        emptyEl.classList.remove('hidden');
        return;
      }
      listEl.classList.remove('hidden');
      listEl.innerHTML = subs.map(renderRow).join('');
    } catch (e) {
      loadingEl.textContent = '加载失败：' + e.message;
    }
  }

  function renderRow(s) {
    const tagsHtml = (s.tags || []).map(t => `<span class="text-xs px-1.5 py-0.5 rounded bg-stone-100 text-stone-600 mr-1">${escapeHtml(t)}</span>`).join('');
    return `
      <li class="p-4 border border-stone-200 rounded-lg bg-white">
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0 flex-1">
            <div class="text-sm font-medium truncate">${escapeHtml(s.name)}</div>
            <div class="text-xs text-stone-500 truncate font-mono">${escapeHtml(s.rss_url)}</div>
            <div class="mt-1">${tagsHtml}</div>
          </div>
          <div class="flex items-center gap-2 shrink-0">
            <button data-action="edit" data-index="${s.index}"
                    class="text-xs px-2 py-1 rounded-md border border-stone-300 hover:bg-stone-50">编辑</button>
            <button data-action="delete" data-index="${s.index}" data-name="${escapeHtml(s.name)}"
                    class="text-xs px-2 py-1 rounded-md border border-red-200 text-red-700 hover:bg-red-50">删除</button>
          </div>
        </div>
      </li>
    `;
  }

  function openModal({ index = '', name = '', rss_url = '', tags = [] } = {}) {
    modalTitle.textContent = index === '' ? '添加播客' : '编辑播客';
    indexInput.value = index;
    nameInput.value = name;
    rssInput.value = rss_url;
    tagsInput.value = tags.join(', ');
    testResult.textContent = '';
    modal.classList.remove('hidden');
    nameInput.focus();
  }

  function closeModal() {
    modal.classList.add('hidden');
  }

  addBtn.addEventListener('click', () => openModal());
  cancelBtn.addEventListener('click', closeModal);
  modal.addEventListener('click', (e) => {
    if (e.target === modal) closeModal();
  });

  testBtn.addEventListener('click', async () => {
    const url = rssInput.value.trim();
    if (!url) {
      testResult.textContent = '请先填 RSS URL';
      testResult.className = 'text-xs text-amber-700';
      return;
    }
    testResult.textContent = '测试中…';
    testResult.className = 'text-xs text-stone-500';
    try {
      const resp = await fetch('/api/subscriptions/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rss_url: url }),
      });
      const data = await resp.json();
      if (data.ok) {
        testResult.textContent = `✓ ${data.feed_title || '(无标题)'} · ${data.episode_count} 集 · 最新：${data.latest_title || '—'}`;
        testResult.className = 'text-xs text-emerald-700';
      } else {
        testResult.textContent = `✕ ${data.error || '失败'}`;
        testResult.className = 'text-xs text-red-700';
      }
    } catch (e) {
      testResult.textContent = '✕ 请求失败：' + e.message;
      testResult.className = 'text-xs text-red-700';
    }
  });

  saveBtn.addEventListener('click', async () => {
    const name = nameInput.value.trim();
    const rss_url = rssInput.value.trim();
    const tags = tagsInput.value.split(',').map(s => s.trim()).filter(Boolean);
    if (!name || !rss_url) {
      testResult.textContent = '名称和 RSS URL 都不能为空';
      testResult.className = 'text-xs text-amber-700';
      return;
    }
    const index = indexInput.value;
    const isEdit = index !== '';
    const url = isEdit ? `/api/subscriptions/${index}` : '/api/subscriptions';
    saveBtn.disabled = true;
    try {
      const resp = await fetch(url, {
        method: isEdit ? 'PUT' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, rss_url, tags }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        testResult.textContent = '✕ 保存失败：' + (err.detail || resp.status);
        testResult.className = 'text-xs text-red-700';
        saveBtn.disabled = false;
        return;
      }
      closeModal();
      await reload();
    } finally {
      saveBtn.disabled = false;
    }
  });

  document.body.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-action]');
    if (!btn) return;
    const action = btn.dataset.action;
    const index = btn.dataset.index;
    if (action === 'edit') {
      const resp = await fetch('/api/subscriptions');
      const data = await resp.json();
      const sub = (data.subscriptions || []).find(s => String(s.index) === String(index));
      if (sub) openModal(sub);
    } else if (action === 'delete') {
      if (!confirm(`删除订阅 "${btn.dataset.name}"？`)) return;
      const resp = await fetch(`/api/subscriptions/${index}`, { method: 'DELETE' });
      if (resp.ok) await reload();
    }
  });

  reload();
})();
