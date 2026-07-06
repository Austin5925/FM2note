// Settings page — read + write config.yaml + .env.
(function () {
  const KEY_DEFS = [
    { id: 'dashscope_api_key', label: 'DashScope（语音转文字 · 必需）', placeholder: 'sk-xxx' },
    { id: 'poe_api_key', label: 'Poe（AI 摘要）', placeholder: '' },
    { id: 'openai_api_key', label: 'OpenAI', placeholder: '' },
    { id: 'tingwu_app_id', label: 'TingWu App ID', placeholder: '仅 asr_engine=tingwu 时需要' },
  ];

  const ALIYUN_DEFS = [
    { id: 'aliyun_access_key_id', label: 'Aliyun Access Key ID', placeholder: 'LTAI5t...' },
    { id: 'aliyun_access_key_secret', label: 'Aliyun Access Key Secret', placeholder: '' },
  ];

  const statusEl = document.getElementById('save-status');
  const saveBtn = document.getElementById('save-btn');

  function makeField(def, info) {
    const status = info && info.configured
      ? `<span class="text-xs text-emerald-700 ml-2 font-mono">${escapeHtml(info.preview)} 已配置</span>`
      : `<span class="text-xs text-stone-400 ml-2">未配置</span>`;
    return `
      <div>
        <label class="block text-xs text-stone-600">${escapeHtml(def.label)}${status}</label>
        <input id="${def.id}" type="password" autocomplete="new-password"
               placeholder="${escapeHtml(def.placeholder || '（留空不修改）')}"
               class="w-full px-3 py-2 mt-1 rounded-md border border-stone-300 text-sm font-mono" />
      </div>
    `;
  }

  function escapeHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  async function loadSettings() {
    try {
      const resp = await fetch('/api/settings');
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      const s = await resp.json();
      const vaultEl = document.getElementById('vault_path');
      vaultEl.value = s.vault_path || '';
      if (s.vault_path_default) {
        vaultEl.placeholder = s.vault_path_default;
        // Wire up the "使用默认路径" button to fill the default when the field is blank or wrong
        const fillBtn = document.getElementById('vault_path_fill_default');
        if (fillBtn) {
          fillBtn.dataset.default = s.vault_path_default;
          fillBtn.classList.remove('hidden');
        }
      }
      document.getElementById('podcast_dir').value = s.podcast_dir || '';
      document.getElementById('asr_engine').value = s.asr_engine || 'funasr';
      document.getElementById('summary_provider').value = s.summary_provider || 'auto';
      document.getElementById('summary_model').value =
        s.summary_model === '(provider default)' ? '' : s.summary_model || '';
      document.getElementById('key-fields').innerHTML =
        makeField(KEY_DEFS[0], s.keys.dashscope) +
        makeField(KEY_DEFS[1], s.keys.poe) +
        makeField(KEY_DEFS[2], s.keys.openai) +
        makeField(KEY_DEFS[3], s.keys.tingwu_app_id);
      document.getElementById('aliyun-fields').innerHTML =
        makeField(ALIYUN_DEFS[0], s.keys.aliyun_access_key_id) +
        makeField(ALIYUN_DEFS[1], s.keys.aliyun_access_key_secret);
    } catch (e) {
      statusEl.textContent = '加载失败：' + e.message;
    }
  }

  // Strip whitespace + any matched wrapping ' or " quotes (sometimes nested
  // from a double-paste like "'/path'"). Caps the loop so pathological input
  // can't hang the page.
  function cleanPath(v) {
    let s = String(v == null ? '' : v).trim();
    for (let i = 0; i < 4; i++) {
      if (s.length >= 2 && s[0] === s[s.length - 1] && (s[0] === "'" || s[0] === '"')) {
        s = s.slice(1, -1).trim();
      } else {
        break;
      }
    }
    return s;
  }

  saveBtn.addEventListener('click', async () => {
    // Reflect the cleaned value back into the input so the user sees what's being saved
    const vaultEl = document.getElementById('vault_path');
    const podcastEl = document.getElementById('podcast_dir');
    vaultEl.value = cleanPath(vaultEl.value);
    podcastEl.value = cleanPath(podcastEl.value);

    const payload = {
      vault_path: vaultEl.value,
      podcast_dir: podcastEl.value,
      asr_engine: document.getElementById('asr_engine').value,
      summary_provider: document.getElementById('summary_provider').value,
      summary_model: document.getElementById('summary_model').value.trim(),
      dashscope_api_key: document.getElementById('dashscope_api_key').value,
      poe_api_key: document.getElementById('poe_api_key').value,
      openai_api_key: document.getElementById('openai_api_key').value,
      tingwu_app_id: document.getElementById('tingwu_app_id').value,
      aliyun_access_key_id: document.getElementById('aliyun_access_key_id').value,
      aliyun_access_key_secret: document.getElementById('aliyun_access_key_secret').value,
    };

    saveBtn.disabled = true;
    statusEl.textContent = '保存中…';
    statusEl.className = 'text-xs text-stone-500';
    try {
      const resp = await fetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        statusEl.textContent = '✕ ' + (err.detail || ('HTTP ' + resp.status));
        statusEl.className = 'text-xs text-red-700';
        return;
      }
      const data = await resp.json();
      statusEl.textContent = data.restart_required
        ? '✓ 已保存（部分配置需重启 fm2note web 才能完全生效）'
        : '✓ 已保存';
      statusEl.className = 'text-xs text-emerald-700';
      await loadSettings();
    } catch (e) {
      statusEl.textContent = '✕ ' + e.message;
      statusEl.className = 'text-xs text-red-700';
    } finally {
      saveBtn.disabled = false;
    }
  });

  // -------- "使用默认路径" button --------
  const fillDefaultBtn = document.getElementById('vault_path_fill_default');
  if (fillDefaultBtn) {
    fillDefaultBtn.addEventListener('click', () => {
      const v = fillDefaultBtn.dataset.default;
      if (v) document.getElementById('vault_path').value = v;
    });
  }

  // -------- Health check --------
  async function loadHealth() {
    const ul = document.getElementById('health-items');
    if (!ul) return;
    ul.innerHTML = '<li class="text-stone-400">检测中…</li>';
    try {
      const resp = await fetch('/api/health-check');
      const data = await resp.json();
      if (!data.items || data.items.length === 0) {
        ul.innerHTML = '<li class="text-stone-400">无可检测项</li>';
        return;
      }
      ul.innerHTML = data.items.map((it) => {
        const icon = it.ok
          ? '<span class="text-emerald-600">✓</span>'
          : '<span class="text-red-600">✕</span>';
        const hintCls = it.ok ? 'text-stone-400' : 'text-red-600';
        return `<li class="flex items-baseline gap-2">
          ${icon}
          <span class="text-stone-700">${escapeHtml(it.label)}</span>
          ${it.hint ? `<span class="text-xs ${hintCls}">— ${escapeHtml(it.hint)}</span>` : ''}
        </li>`;
      }).join('');
    } catch (e) {
      ul.innerHTML = `<li class="text-red-600">检测失败：${escapeHtml(e.message)}</li>`;
    }
  }
  const refreshBtn = document.getElementById('health-refresh-btn');
  if (refreshBtn) refreshBtn.addEventListener('click', loadHealth);

  // -------- Service status --------
  async function loadService() {
    const el = document.getElementById('service-status');
    if (!el) return;
    try {
      const resp = await fetch('/api/service/status');
      const data = await resp.json();
      if (data.platform !== 'darwin') {
        el.innerHTML = `<span class="text-stone-500">当前平台暂不支持检测（${escapeHtml(data.platform)}）</span>`;
        return;
      }
      const desktopHint = data.desktop_app
        ? '当前桌面窗口已经在运行；后台自动检查只负责关掉窗口后的定时抓取。'
        : '开启后 FM2note 会在 macOS 开机时自动启动，定时抓取新剧集。';
      if (!data.installed) {
        el.innerHTML = `
          <div class="flex items-center justify-between gap-3">
            <div>
              <div class="text-stone-600">未开启后台自动检查</div>
              <div class="text-xs text-stone-400 mt-1">
                ${escapeHtml(desktopHint)}
              </div>
            </div>
            <button id="svc-install-btn"
                    type="button"
                    class="px-3 py-1.5 rounded-md bg-stone-900 text-white text-xs hover:bg-stone-700 whitespace-nowrap">
              开机自启
            </button>
          </div>
        `;
        const btn = document.getElementById('svc-install-btn');
        if (btn) btn.addEventListener('click', (event) => toggleService('install', btn, event));
        return;
      }
      if (data.running) {
        el.innerHTML = `
          <div class="flex items-center justify-between gap-3">
            <div>
              <div><span class="text-emerald-600">●</span>
              <span class="text-stone-700">后台自动检查运行中</span>
              <span class="text-xs text-stone-400 ml-2 font-mono">PID ${data.pid}</span></div>
              <div class="text-xs text-stone-400 mt-1">${escapeHtml(data.plist_path || '')}</div>
            </div>
            <button id="svc-uninstall-btn"
                    type="button"
                    class="px-3 py-1.5 rounded-md border border-stone-300 text-xs hover:bg-stone-50 whitespace-nowrap">
              关闭自启
            </button>
          </div>
        `;
      } else {
        const stoppedHint = data.desktop_app
          ? '桌面 App 不受影响；后台自动检查会在下次登录时尝试启动，也可以关闭后重新开启。'
          : `终端运行 launchctl load ${data.plist_path || ''} 启动`;
        el.innerHTML = `
          <div class="flex items-center justify-between gap-3">
            <div>
              <div><span class="text-amber-600">●</span>
              <span class="text-stone-700">后台自动检查已安装但未运行</span></div>
              <div class="text-xs text-stone-400 mt-1">
                ${escapeHtml(stoppedHint)}
              </div>
            </div>
            <button id="svc-uninstall-btn"
                    type="button"
                    class="px-3 py-1.5 rounded-md border border-stone-300 text-xs hover:bg-stone-50 whitespace-nowrap">
              关闭自启
            </button>
          </div>
        `;
      }
      const offBtn = document.getElementById('svc-uninstall-btn');
      if (offBtn) offBtn.addEventListener('click', (event) => toggleService('uninstall', offBtn, event));
    } catch (e) {
      el.innerHTML = `<span class="text-red-600">检测失败：${escapeHtml(e.message)}</span>`;
    }
  }

  async function toggleService(action, btn, event) {
    if (event) event.preventDefault();
    const verb = action === 'install' ? '安装中…' : '卸载中…';
    btn.disabled = true;
    btn.textContent = verb;
    try {
      const resp = await fetch(`/api/service/${action}`, { method: 'POST' });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        alert(`✕ ${err.detail || resp.status}`);
        return;
      }
      // Re-render the panel with the new state
      await loadService();
    } catch (e) {
      alert('✕ ' + e.message);
    } finally {
      btn.disabled = false;
    }
  }

  // -------- v1.5.3: poll-now button --------
  const pollBtn = document.getElementById('poll-now-btn');
  const pollStatusEl = document.getElementById('poll-now-status');
  if (pollBtn) {
    pollBtn.addEventListener('click', async (event) => {
      event.preventDefault();
      pollBtn.disabled = true;
      if (pollStatusEl) {
        pollStatusEl.textContent = '触发中…';
        pollStatusEl.className = 'text-xs text-stone-500 mt-2';
      }
      try {
        const resp = await fetch('/api/service/poll-now', { method: 'POST' });
        const data = await resp.json();
        if (resp.ok) {
          if (pollStatusEl) {
            pollStatusEl.textContent = '✓ ' + (data.message || '已触发');
            pollStatusEl.className = 'text-xs text-emerald-700 mt-2';
          }
        } else if (pollStatusEl) {
          pollStatusEl.textContent = '✕ ' + (data.detail || resp.status);
          pollStatusEl.className = 'text-xs text-red-700 mt-2';
        }
      } catch (e) {
        if (pollStatusEl) {
          pollStatusEl.textContent = '✕ ' + e.message;
          pollStatusEl.className = 'text-xs text-red-700 mt-2';
        }
      } finally {
        pollBtn.disabled = false;
      }
    });
  }

  // -------- v1.5.3: log panel --------
  const logsOutput = document.getElementById('logs-output');
  const logsAutoEl = document.getElementById('logs-auto');
  const logsRefreshBtn = document.getElementById('logs-refresh-btn');
  let lastSeq = 0;
  const levelColor = {
    DEBUG: 'text-stone-400',
    INFO: 'text-stone-700',
    WARNING: 'text-amber-700',
    ERROR: 'text-red-700',
    CRITICAL: 'text-red-700 font-bold',
  };

  function renderLogs(records, append) {
    if (!logsOutput) return;
    // v1.5.3 Code Review I2 fix: only scroll-to-bottom if the user was
    // already at (or very near) the bottom. Otherwise the auto-refresh
    // tick would yank them away from whatever they're reading. Snapshot
    // the position BEFORE we mutate innerHTML.
    const wasAtBottom = (
      logsOutput.scrollHeight - logsOutput.scrollTop - logsOutput.clientHeight < 40
    );
    const html = records.map((r) => {
      const cls = levelColor[r.level] || 'text-stone-700';
      const t = new Date(r.time).toLocaleTimeString('zh-CN', { hour12: false });
      return `<div class="${cls}">[${escapeHtml(t)}] ${escapeHtml(r.level.padEnd(8))} ${escapeHtml(r.module)}:${r.line} - ${escapeHtml(r.message)}</div>`;
    }).join('');
    if (append) {
      // If "加载中…" was the only thing there, replace it
      if (logsOutput.textContent.trim() === '加载中…') {
        logsOutput.innerHTML = html;
      } else {
        logsOutput.insertAdjacentHTML('beforeend', html);
      }
    } else {
      logsOutput.innerHTML = html || '<div class="text-stone-400">暂无日志</div>';
    }
    // Manual refresh (!append) always snaps to bottom for "fresh view" UX.
    // Auto-refresh appends — preserve scroll position if user has scrolled up.
    if (!append || wasAtBottom) {
      logsOutput.scrollTop = logsOutput.scrollHeight;
    }
  }

  async function fetchLogs(reset) {
    try {
      const after = reset ? 0 : lastSeq;
      const resp = await fetch(`/api/logs?after_seq=${after}`);
      if (!resp.ok) return;
      const data = await resp.json();
      if (reset) {
        lastSeq = 0;
        renderLogs(data.records || [], false);
      } else if (data.records && data.records.length) {
        renderLogs(data.records, true);
      }
      if (data.next_after_seq) lastSeq = data.next_after_seq;
    } catch (_) {
      // silent
    }
  }

  if (logsRefreshBtn) logsRefreshBtn.addEventListener('click', () => fetchLogs(true));
  fetchLogs(true);
  // Poll every 3s when "auto" is checked
  setInterval(() => {
    if (logsAutoEl && logsAutoEl.checked) fetchLogs(false);
  }, 3000);

  loadSettings();
  loadHealth();
  loadService();
})();
