// Settings page — read + write config.yaml + .env.
(function () {
  const KEY_DEFS = [
    { id: 'dashscope_api_key', label: 'DashScope（阿里语音引擎）', placeholder: 'sk-xxx' },
    { id: 'deepseek_api_key', label: 'DeepSeek API Key（V4.1 Flash）', placeholder: 'sk-xxx' },
    { id: 'openai_api_key', label: 'OpenAI', placeholder: '' },
    { id: 'tingwu_app_id', label: 'TingWu App ID', placeholder: '仅 asr_engine=tingwu 时需要' },
  ];

  const ALIYUN_DEFS = [
    { id: 'aliyun_access_key_id', label: 'Aliyun Access Key ID', placeholder: 'LTAI5t...' },
    { id: 'aliyun_access_key_secret', label: 'Aliyun Access Key Secret', placeholder: '' },
  ];

  const DEFAULT_DEEPSEEK_MODEL = 'deepseek-flash';
  const SUMMARY_MODELS = [DEFAULT_DEEPSEEK_MODEL, 'gpt-4o-mini'];

  const DEFAULT_FUNASR_MODEL = 'fun-asr';
  const FUNASR_MODELS = [
    DEFAULT_FUNASR_MODEL,
    'fun-asr-2025-11-07',
    'fun-asr-2025-08-25',
    'fun-asr-mtl',
    'fun-asr-mtl-2025-08-25',
  ];

  const DEFAULT_BAILIAN_MODEL = 'qwen-audio-3.1-asr-flash-filetrans';
  const BAILIAN_MODELS = [
    DEFAULT_BAILIAN_MODEL,
    'qwen3-asr-flash-filetrans',
    'qwen-audio-3.0-asr-flash-filetrans',
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

  function normalizedSummaryModel(value) {
    return value === '(provider default)' ? '' : String(value || '').trim();
  }

  function fillDatalist(id, values) {
    const list = document.getElementById(id);
    if (list) list.innerHTML = values.map((id) => `<option value="${escapeHtml(id)}"></option>`).join('');
  }

  function renderSummaryModelControl(provider, modelValue, baseUrl) {
    const group = document.getElementById('summary_model_group');
    const label = document.getElementById('summary_model_label');
    const input = document.getElementById('summary_model');
    const hint = document.getElementById('summary_model_hint');
    const urlGroup = document.getElementById('summary_base_url_group');
    const urlInput = document.getElementById('summary_base_url');
    if (!group || !label || !input || !hint || !urlGroup || !urlInput) return;

    const model = normalizedSummaryModel(modelValue);
    const visible = provider === 'deepseek' || provider === 'openai';
    group.classList.toggle('hidden', !visible);
    urlGroup.classList.toggle('hidden', provider !== 'openai');
    input.value = model || (provider === 'deepseek' ? DEFAULT_DEEPSEEK_MODEL : '');
    urlInput.value = baseUrl || '';
    fillDatalist('summary_models', SUMMARY_MODELS);
    if (provider === 'deepseek') {
      label.textContent = 'DeepSeek 摘要模型';
      hint.textContent = '默认 deepseek-flash（DeepSeek V4.1 Flash）；也可手动填写兼容模型 ID。';
    } else if (provider === 'openai') {
      label.textContent = 'OpenAI-compatible 摘要模型';
      hint.textContent = '可填写 CometAPI、DeepInfra 或其他 OpenAI-compatible 服务提供的模型 ID。';
    } else {
      hint.textContent = '';
    }
  }

  function selectedSummaryModel() {
    const provider = document.getElementById('summary_provider').value;
    if (provider === 'deepseek' && !document.getElementById('summary_model').value.trim()) {
      return DEFAULT_DEEPSEEK_MODEL;
    }
    return provider === 'deepseek' || provider === 'openai'
      ? document.getElementById('summary_model').value.trim()
      : '';
  }

  function renderAsrModelControls(engine, funasrValue, bailianValue) {
    const funasrGroup = document.getElementById('funasr_model_group');
    const funasrInput = document.getElementById('funasr_model');
    const bailianGroup = document.getElementById('bailian_model_group');
    const bailianInput = document.getElementById('bailian_model');
    if (!funasrGroup || !funasrInput || !bailianGroup || !bailianInput) return;

    funasrGroup.classList.toggle('hidden', engine !== 'funasr');
    bailianGroup.classList.toggle('hidden', engine !== 'bailian');
    fillDatalist('funasr_models', FUNASR_MODELS);
    fillDatalist('bailian_models', BAILIAN_MODELS);
    funasrInput.value = funasrValue || DEFAULT_FUNASR_MODEL;
    bailianInput.value = bailianValue || DEFAULT_BAILIAN_MODEL;
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
      const asrEngineEl = document.getElementById('asr_engine');
      asrEngineEl.value = s.asr_engine || 'bailian';
      renderAsrModelControls(asrEngineEl.value, s.funasr_model, s.bailian_model);
      const providerEl = document.getElementById('summary_provider');
      providerEl.value = s.summary_provider || 'auto';
      renderSummaryModelControl(providerEl.value, s.summary_model, s.summary_base_url);
      document.getElementById('key-fields').innerHTML =
        makeField(KEY_DEFS[0], s.keys.dashscope) +
        makeField(KEY_DEFS[1], s.keys.deepseek) +
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
      funasr_model: document.getElementById('funasr_model').value,
      bailian_model: document.getElementById('bailian_model').value,
      summary_provider: document.getElementById('summary_provider').value,
      summary_model: selectedSummaryModel(),
      summary_base_url: document.getElementById('summary_base_url').value.trim() || null,
      dashscope_api_key: document.getElementById('dashscope_api_key').value,
      deepseek_api_key: document.getElementById('deepseek_api_key').value,
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
      if (window.refreshBalanceBadge) await window.refreshBalanceBadge();
    } catch (e) {
      statusEl.textContent = '✕ ' + e.message;
      statusEl.className = 'text-xs text-red-700';
    } finally {
      saveBtn.disabled = false;
    }
  });

  const summaryProviderEl = document.getElementById('summary_provider');
  if (summaryProviderEl) {
    summaryProviderEl.addEventListener('change', () => {
      renderSummaryModelControl(summaryProviderEl.value, selectedSummaryModel(), document.getElementById('summary_base_url').value);
    });
  }

  const asrEngineEl = document.getElementById('asr_engine');
  if (asrEngineEl) {
    asrEngineEl.addEventListener('change', () => {
      renderAsrModelControls(
        asrEngineEl.value,
        document.getElementById('funasr_model').value,
        document.getElementById('bailian_model').value,
      );
    });
  }

  // -------- "使用默认路径" button --------
  const fillDefaultBtn = document.getElementById('vault_path_fill_default');
  if (fillDefaultBtn) {
    fillDefaultBtn.addEventListener('click', () => {
      const v = fillDefaultBtn.dataset.default;
      if (v) document.getElementById('vault_path').value = v;
    });
  }

  // -------- Software update check --------
  async function loadUpdate() {
    const el = document.getElementById('update-status');
    if (!el) return;
    try {
      const resp = await fetch('/api/updates');
      const data = await resp.json();
      if (!resp.ok || !data.ok) {
        el.textContent = data.detail || '暂时无法检查更新';
        return;
      }
      const link = data.release_url
        ? ` <a class="text-blue-700 hover:underline" target="_blank" rel="noreferrer" href="${escapeHtml(data.release_url)}">打开 Releases</a>`
        : '';
      el.innerHTML = data.update_available
        ? `当前 ${escapeHtml(data.current_version)}，发现新版本 ${escapeHtml(data.latest_version)}。${link}`
        : `当前 ${escapeHtml(data.current_version)}，已经是最新版本。${link}`;
    } catch (e) {
      el.textContent = '检查失败：' + e.message;
    }
  }
  const updateBtn = document.getElementById('update-check-btn');
  if (updateBtn) {
    updateBtn.addEventListener('click', async () => {
      updateBtn.disabled = true;
      updateBtn.textContent = '检查中…';
      await loadUpdate();
      updateBtn.disabled = false;
      updateBtn.textContent = '检查更新';
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
        ? '当前桌面窗口已经在运行；开启后台后，关掉窗口也会继续定时抓取。'
        : '开启后 FM2note 会立即启动后台进程，并在 macOS 登录后自动检查新剧集。';
      if (!data.installed) {
        const offCopy = data.auto_start_disabled
          ? '后台已手动关闭；再次开启后会立即启动，并恢复随 App/登录自动检查。'
          : desktopHint;
        el.innerHTML = `
          <div class="flex items-center justify-between gap-3">
            <div>
              <div class="text-stone-600">后台自动检查未开启</div>
              <div class="text-xs text-stone-400 mt-1">
                ${escapeHtml(offCopy)}
              </div>
            </div>
            <button id="svc-install-btn"
                    type="button"
                    class="px-3 py-1.5 rounded-md bg-stone-900 text-white text-xs hover:bg-stone-700 whitespace-nowrap">
              开启后台
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
              关闭后台
            </button>
          </div>
        `;
      } else {
        const stoppedHint = data.desktop_app
          ? '桌面 App 不受影响；可以直接启动后台，或关闭后台自动检查。'
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
            <div class="flex items-center gap-2 shrink-0">
              <button id="svc-start-btn"
                      type="button"
                      class="px-3 py-1.5 rounded-md bg-stone-900 text-white text-xs hover:bg-stone-700 whitespace-nowrap">
                启动后台
              </button>
              <button id="svc-uninstall-btn"
                      type="button"
                      class="px-3 py-1.5 rounded-md border border-stone-300 text-xs hover:bg-stone-50 whitespace-nowrap">
                关闭后台
              </button>
            </div>
          </div>
        `;
      }
      const startBtn = document.getElementById('svc-start-btn');
      if (startBtn) startBtn.addEventListener('click', (event) => toggleService('start', startBtn, event));
      const offBtn = document.getElementById('svc-uninstall-btn');
      if (offBtn) offBtn.addEventListener('click', (event) => toggleService('uninstall', offBtn, event));
    } catch (e) {
      el.innerHTML = `<span class="text-red-600">检测失败：${escapeHtml(e.message)}</span>`;
    }
  }

  async function toggleService(action, btn, event) {
    if (event) event.preventDefault();
    const verb = action === 'install' ? '安装中…' : '卸载中…';
    const pending = action === 'start' ? '启动中…' : verb;
    btn.disabled = true;
    btn.textContent = pending;
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
  loadUpdate();
})();
