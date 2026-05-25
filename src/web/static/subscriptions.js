// Subscriptions page — list/add/edit/delete podcast RSS feeds.
(function () {
  const listEl = document.getElementById('subs-list');
  const emptyEl = document.getElementById('subs-empty');
  const loadingEl = document.getElementById('subs-loading');
  const addBtn = document.getElementById('add-sub-btn');
  const modal = document.getElementById('sub-modal');
  const modalTitle = document.getElementById('sub-modal-title');
  const indexInput = document.getElementById('sub-index');
  const pasteInput = document.getElementById('sub-paste');
  const rsshubBaseInput = document.getElementById('sub-rsshub-base');
  const nameInput = document.getElementById('sub-name');
  const rssInput = document.getElementById('sub-rss');
  const tagsInput = document.getElementById('sub-tags');
  const testResult = document.getElementById('sub-test-result');
  const resolveBtn = document.getElementById('sub-resolve-btn');
  const testBtn = document.getElementById('sub-test-btn');
  const cancelBtn = document.getElementById('sub-cancel-btn');
  const saveBtn = document.getElementById('sub-save-btn');

  let defaultRsshubBase = 'https://macroclaw.app/rsshub';
  let resolveTimer = null;

  function escapeHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  async function reload() {
    await loadDefaults();
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

  async function loadDefaults() {
    try {
      const resp = await fetch('/api/subscriptions/defaults');
      if (!resp.ok) return;
      const data = await resp.json();
      if (data.rsshub_base) defaultRsshubBase = data.rsshub_base;
      if (rsshubBaseInput && !rsshubBaseInput.value.trim()) {
        rsshubBaseInput.value = defaultRsshubBase;
      }
    } catch (_) {
      // The local fallback is enough for the UI to stay usable.
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
    pasteInput.value = '';
    rsshubBaseInput.value = defaultRsshubBase;
    nameInput.value = name;
    rssInput.value = rss_url;
    tagsInput.value = tags.join(', ');
    testResult.textContent = '';
    modal.classList.remove('hidden');
    pasteInput.focus();
  }

  function closeModal() {
    modal.classList.add('hidden');
  }

  addBtn.addEventListener('click', () => openModal());
  cancelBtn.addEventListener('click', closeModal);
  modal.addEventListener('click', (e) => {
    if (e.target === modal) closeModal();
  });

  pasteInput.addEventListener('input', () => {
    if (resolveTimer) clearTimeout(resolveTimer);
    const pasted = pasteInput.value.trim();
    if (!pasted) return;
    testResult.textContent = '准备识别…';
    testResult.className = 'text-xs text-stone-500';
    resolveTimer = setTimeout(resolvePastedInput, 500);
  });

  resolveBtn.addEventListener('click', resolvePastedInput);

  async function resolvePastedInput() {
    const input = pasteInput.value.trim();
    if (!input) {
      testResult.textContent = '先把小宇宙播客链接粘贴到上面';
      testResult.className = 'text-xs text-amber-700';
      return false;
    }
    resolveBtn.disabled = true;
    testResult.textContent = '自动识别中…';
    testResult.className = 'text-xs text-stone-500';
    try {
      const resp = await fetch('/api/subscriptions/resolve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          input,
          rsshub_base: rsshubBaseInput.value.trim() || defaultRsshubBase,
        }),
      });
      const data = await resp.json();
      if (!resp.ok || !data.ok) {
        testResult.textContent = '✕ ' + (data.error || data.detail || '识别失败');
        testResult.className = 'text-xs text-red-700';
        return false;
      }
      if (data.rsshub_base) {
        defaultRsshubBase = data.rsshub_base;
        rsshubBaseInput.value = data.rsshub_base;
      }
      nameInput.value = data.name || nameInput.value;
      rssInput.value = data.rss_url || rssInput.value;
      if (!tagsInput.value.trim() && data.kind === 'xiaoyuzhou') tagsInput.value = 'podcast';
      testResult.textContent = '✓ ' + (data.message || '已识别') + '：' + (data.name || data.rss_url);
      testResult.className = 'text-xs text-emerald-700';
      return true;
    } catch (e) {
      testResult.textContent = '✕ 请求失败：' + e.message;
      testResult.className = 'text-xs text-red-700';
      return false;
    } finally {
      resolveBtn.disabled = false;
    }
  }

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
    if ((!nameInput.value.trim() || !rssInput.value.trim()) && pasteInput.value.trim()) {
      const resolved = await resolvePastedInput();
      if (!resolved) return;
    }
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
    // Edit path is unchanged — backfill strategy is a one-shot thing applied
    // at create time only.
    if (isEdit) {
      saveBtn.disabled = true;
      try {
        const resp = await fetch(`/api/subscriptions/${index}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name, rss_url, tags }),
        });
        if (!resp.ok) {
          const err = await resp.json().catch(() => ({}));
          testResult.textContent = '✕ 保存失败：' + (err.detail || resp.status);
          testResult.className = 'text-xs text-red-700';
          return;
        }
        closeModal();
        await reload();
      } finally {
        saveBtn.disabled = false;
      }
      return;
    }
    // Add path — preview first, then open backfill strategy modal.
    await beginAddWithBackfill({ name, rss_url, tags });
  });

  // -------- v1.4.15: preview + backfill strategy flow --------

  let pendingAdd = null;  // { name, rss_url, tags, preview }

  async function beginAddWithBackfill(item) {
    testResult.textContent = '正在统计该 feed 的剧集数 + 预估额度…';
    testResult.className = 'text-xs text-stone-500';
    saveBtn.disabled = true;
    try {
      const resp = await fetch('/api/subscriptions/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rss_url: item.rss_url }),
      });
      const data = await resp.json();
      if (!data.ok) {
        testResult.textContent = '✕ 预览失败：' + (data.error || resp.status);
        testResult.className = 'text-xs text-red-700';
        return;
      }
      pendingAdd = { ...item, preview: data };
      openBackfillModal(data);
    } catch (e) {
      testResult.textContent = '✕ 预览请求失败：' + e.message;
      testResult.className = 'text-xs text-red-700';
    } finally {
      saveBtn.disabled = false;
    }
  }

  function openBackfillModal(preview) {
    const summaryEl = document.getElementById('backfill-summary');
    const allHintEl = document.getElementById('backfill-all-cost-hint');
    const totalMin = Math.round((preview.total_duration_sec || 0) / 60);
    // Code Review C2 (v1.4.15): preview.asr_engine ultimately comes from
    // user-editable config.yaml, so escapeHtml it before going into innerHTML.
    // Numbers are safe (toFixed coerces to a numeric string), the engine
    // name is the only string field interpolated here.
    const safeEngine = escapeHtml(preview.asr_engine || 'funasr');
    const costText = preview.estimated_cost_cny > 0
      ? `约 ¥${preview.estimated_cost_cny.toFixed(2)}（${totalMin} 分钟，${safeEngine}）`
      : '（feed 未提供 duration，无法估算成本）';
    summaryEl.innerHTML = `Feed 当前有 <b>${preview.episode_count}</b> 集，其中 <b>${preview.unprocessed_count}</b> 集未在本机处理。<br/>全部转录预计 ${costText}`;
    allHintEl.textContent = preview.estimated_cost_cny > 0
      ? `预计消耗约 ¥${preview.estimated_cost_cny.toFixed(2)}（${preview.unprocessed_count} 集）`
      : '— 这会一次性消耗大量 DashScope / Poe 额度';
    // Reset radio + secondary inputs
    document.querySelectorAll('#backfill-form input[name="backfill"]').forEach((el) => {
      el.checked = el.value === 'new_only';
    });
    document.getElementById('backfill-recent-n').disabled = true;
    document.getElementById('backfill-since-date').disabled = true;
    document.getElementById('backfill-modal').classList.remove('hidden');
  }

  function closeBackfillModal() {
    document.getElementById('backfill-modal').classList.add('hidden');
    pendingAdd = null;
  }

  // Enable the secondary input next to the selected radio
  document.querySelectorAll('#backfill-form input[name="backfill"]').forEach((radio) => {
    radio.addEventListener('change', () => {
      document.getElementById('backfill-recent-n').disabled = radio.value !== 'recent_n' || !radio.checked;
      document.getElementById('backfill-since-date').disabled = radio.value !== 'since_date' || !radio.checked;
      if (radio.checked && radio.value === 'recent_n') document.getElementById('backfill-recent-n').focus();
      if (radio.checked && radio.value === 'since_date') document.getElementById('backfill-since-date').focus();
    });
  });

  document.getElementById('backfill-cancel-btn').addEventListener('click', closeBackfillModal);
  document.getElementById('backfill-modal').addEventListener('click', (e) => {
    if (e.target.id === 'backfill-modal') closeBackfillModal();
  });

  document.getElementById('backfill-confirm-btn').addEventListener('click', async () => {
    if (!pendingAdd) return closeBackfillModal();
    const chosen = document.querySelector('#backfill-form input[name="backfill"]:checked');
    if (!chosen) return;
    const strategy = chosen.value;
    const body = { ...pendingAdd, backfill_strategy: strategy };
    delete body.preview;
    if (strategy === 'recent_n') {
      const n = parseInt(document.getElementById('backfill-recent-n').value, 10);
      if (!Number.isInteger(n) || n < 1) { alert('请输入有效的 N (≥1)'); return; }
      body.recent_n = n;
    }
    if (strategy === 'since_date') {
      const d = document.getElementById('backfill-since-date').value;
      if (!d) { alert('请选择起始日期'); return; }
      body.since_date = d;
    }
    const btn = document.getElementById('backfill-confirm-btn');
    btn.disabled = true;
    try {
      const resp = await fetch('/api/subscriptions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await resp.json();
      if (!resp.ok) {
        testResult.textContent = '✕ 添加失败：' + (data.detail || resp.status);
        testResult.className = 'text-xs text-red-700';
        return;
      }
      // Success — close both modals and reload
      closeBackfillModal();
      closeModal();
      await reload();
    } finally {
      btn.disabled = false;
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
