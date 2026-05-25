// Cloud-browse page — list cached episodes from the shared sidecar,
// grouped by podcast_name into folder cards; clicking a folder reveals
// the episode list with multi-select download.
(function () {
  const loadingEl = document.getElementById('cloud-loading');
  const errorEl = document.getElementById('cloud-error');
  const errorMsgEl = document.getElementById('cloud-error-msg');
  const emptyEl = document.getElementById('cloud-empty');
  const foldersEl = document.getElementById('cloud-folders');
  const folderSummaryEl = document.getElementById('cloud-folder-summary');
  const folderListEl = document.getElementById('cloud-folder-list');
  const episodesEl = document.getElementById('cloud-episodes');
  const episodeListEl = document.getElementById('cloud-episode-list');
  const episodesTitleEl = document.getElementById('cloud-episodes-title');
  const episodesCountEl = document.getElementById('cloud-episodes-count');
  const backBtn = document.getElementById('cloud-back-btn');
  const refreshBtn = document.getElementById('cloud-refresh-btn');
  const selectAllBtn = document.getElementById('cloud-select-all');
  const downloadBtn = document.getElementById('cloud-download-btn');
  const overwriteEl = document.getElementById('cloud-overwrite');
  const resultEl = document.getElementById('cloud-result');
  const resultSummaryEl = document.getElementById('cloud-result-summary');
  const resultListEl = document.getElementById('cloud-result-list');

  // All items returned from the last /api/cloud/list. We group by
  // podcast_name client-side rather than hitting the server twice.
  let items = [];
  let currentFolder = null;

  const PLACEHOLDER_FOLDER = '（旧数据 · 未提供节目名）';

  function escapeHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function fmtBytes(n) {
    if (!n || n < 1024) return `${n || 0} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
    return `${(n / 1024 / 1024).toFixed(2)} MB`;
  }

  function fmtDate(epoch) {
    if (!epoch) return '';
    const d = new Date(epoch * 1000);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  }

  function groupByFolder(items) {
    const map = new Map();
    for (const it of items) {
      const key = it.podcast_name || PLACEHOLDER_FOLDER;
      if (!map.has(key)) map.set(key, []);
      map.get(key).push(it);
    }
    // newest episode first inside each folder
    for (const arr of map.values()) {
      arr.sort((a, b) => (b.updated_at || 0) - (a.updated_at || 0));
    }
    // folders sorted by member count desc, then name
    return [...map.entries()].sort((a, b) => {
      if (b[1].length !== a[1].length) return b[1].length - a[1].length;
      return a[0].localeCompare(b[0]);
    });
  }

  function renderFolders() {
    const groups = groupByFolder(items);
    folderListEl.innerHTML = groups.map(([name, eps]) => `
      <li>
        <button data-folder="${escapeHtml(name)}"
                class="folder-btn w-full text-left p-4 rounded-lg border border-stone-200 hover:bg-stone-50 flex items-center justify-between">
          <span class="font-medium">📁 ${escapeHtml(name)}</span>
          <span class="text-xs text-stone-500">${eps.length} 集</span>
        </button>
      </li>
    `).join('');
    folderSummaryEl.textContent = `共 ${groups.length} 个节目 · ${items.length} 集`;
    folderListEl.querySelectorAll('.folder-btn').forEach((btn) => {
      btn.addEventListener('click', () => openFolder(btn.dataset.folder));
    });
  }

  function openFolder(name) {
    currentFolder = name;
    const groups = new Map(groupByFolder(items));
    const eps = groups.get(name) || [];
    episodesTitleEl.textContent = name;
    episodesCountEl.textContent = `${eps.length} 集`;
    episodeListEl.innerHTML = eps.map((ep) => `
      <li class="p-3 rounded-lg border border-stone-200 flex items-center gap-3">
        <input type="checkbox" class="ep-check accent-stone-900"
               data-guid="${escapeHtml(ep.guid)}" />
        <div class="flex-1 min-w-0">
          <div class="font-medium truncate">${escapeHtml(ep.title || '(无标题)')}</div>
          <div class="text-xs text-stone-500">
            ${escapeHtml(fmtDate(ep.updated_at))} · ${escapeHtml(fmtBytes(ep.size))} ·
            <span class="font-mono">${escapeHtml((ep.guid || '').slice(0, 24))}…</span>
          </div>
        </div>
      </li>
    `).join('');
    foldersEl.classList.add('hidden');
    episodesEl.classList.remove('hidden');
    resultEl.classList.add('hidden');
    updateDownloadBtn();
    episodeListEl.querySelectorAll('.ep-check').forEach((cb) => {
      cb.addEventListener('change', updateDownloadBtn);
    });
  }

  function updateDownloadBtn() {
    const n = episodeListEl.querySelectorAll('.ep-check:checked').length;
    downloadBtn.disabled = n === 0;
    downloadBtn.textContent = n > 0 ? `下载选中 (${n})` : '下载选中';
  }

  async function reload() {
    loadingEl.classList.remove('hidden');
    errorEl.classList.add('hidden');
    emptyEl.classList.add('hidden');
    foldersEl.classList.add('hidden');
    episodesEl.classList.add('hidden');
    resultEl.classList.add('hidden');
    try {
      const resp = await fetch('/api/cloud/list?limit=500');
      const data = await resp.json();
      if (!data.ok) {
        errorMsgEl.textContent = data.detail || '未配置或暂不可用';
        errorEl.classList.remove('hidden');
        return;
      }
      items = data.items || [];
      if (items.length === 0) {
        emptyEl.classList.remove('hidden');
        return;
      }
      foldersEl.classList.remove('hidden');
      renderFolders();
    } catch (e) {
      errorMsgEl.textContent = '加载失败：' + (e.message || e);
      errorEl.classList.remove('hidden');
    } finally {
      loadingEl.classList.add('hidden');
    }
  }

  backBtn.addEventListener('click', () => {
    currentFolder = null;
    episodesEl.classList.add('hidden');
    foldersEl.classList.remove('hidden');
    resultEl.classList.add('hidden');
  });

  refreshBtn.addEventListener('click', reload);

  selectAllBtn.addEventListener('click', () => {
    const cbs = episodeListEl.querySelectorAll('.ep-check');
    const someUnchecked = [...cbs].some((cb) => !cb.checked);
    cbs.forEach((cb) => { cb.checked = someUnchecked; });
    updateDownloadBtn();
  });

  downloadBtn.addEventListener('click', async () => {
    const checked = [...episodeListEl.querySelectorAll('.ep-check:checked')];
    const guids = checked.map((cb) => cb.dataset.guid);
    if (guids.length === 0) return;
    downloadBtn.disabled = true;
    downloadBtn.textContent = '下载中…';
    try {
      const resp = await fetch('/api/cloud/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ guids, overwrite: overwriteEl.checked }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        alert('下载失败：' + (data.detail || resp.status));
        return;
      }
      resultEl.classList.remove('hidden');
      resultSummaryEl.textContent = `✓ 成功下载 ${data.downloaded} / ${data.items.length} 集`;
      resultListEl.innerHTML = data.items.map((it) => {
        if (it.ok) {
          return `<li>✓ <span class="font-mono">${escapeHtml(it.guid.slice(0, 24))}…</span> → <span class="text-stone-700">${escapeHtml(it.path)}</span></li>`;
        }
        const reasonText = {
          already_exists: '已存在（勾选"覆盖已存在"重试）',
          already_exists_by_source: '已存在同一来源（不会重复下载）',
          cache_miss: '缓存里找不到',
          write_failed: '写入失败',
          invalid_guid: 'guid 无效',
          path_escapes_vault: '路径越界，已拒绝写入',
          path_resolve_failed: '路径解析失败',
        }[it.reason] || it.reason || '失败';
        return `<li>✕ <span class="font-mono">${escapeHtml(it.guid.slice(0, 24))}…</span> · ${escapeHtml(reasonText)}</li>`;
      }).join('');
    } catch (e) {
      alert('下载请求失败：' + (e.message || e));
    } finally {
      updateDownloadBtn();
    }
  });

  reload();
})();
