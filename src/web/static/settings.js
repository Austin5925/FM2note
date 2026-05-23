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
      document.getElementById('vault_path').value = s.vault_path || '';
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

  saveBtn.addEventListener('click', async () => {
    const payload = {
      vault_path: document.getElementById('vault_path').value.trim(),
      podcast_dir: document.getElementById('podcast_dir').value.trim(),
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
      if (!data.installed) {
        el.innerHTML = `
          <div class="text-stone-600">未安装后台服务</div>
          <div class="text-xs text-stone-400 mt-1">
            在终端运行 <code class="bg-stone-100 px-1">fm2note install-service</code>
            即可让 FM2note 在开机时自动启动并定时抓取新剧集
          </div>
        `;
        return;
      }
      if (data.running) {
        el.innerHTML = `
          <div><span class="text-emerald-600">●</span>
          <span class="text-stone-700">服务运行中</span>
          <span class="text-xs text-stone-400 ml-2 font-mono">PID ${data.pid}</span></div>
          <div class="text-xs text-stone-400 mt-1">${escapeHtml(data.plist_path || '')}</div>
        `;
      } else {
        el.innerHTML = `
          <div><span class="text-amber-600">●</span>
          <span class="text-stone-700">已安装但未运行</span></div>
          <div class="text-xs text-stone-400 mt-1">
            终端运行 <code class="bg-stone-100 px-1">launchctl load ${escapeHtml(data.plist_path || '')}</code> 启动
          </div>
        `;
      }
    } catch (e) {
      el.innerHTML = `<span class="text-red-600">检测失败：${escapeHtml(e.message)}</span>`;
    }
  }

  loadSettings();
  loadHealth();
  loadService();
})();
