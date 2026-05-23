// FM2note transcribe page — vanilla JS + EventSource
(function () {
  const urlInput = document.getElementById('url-input');
  const submitBtn = document.getElementById('submit-btn');
  const previewBox = document.getElementById('preview');
  const previewPodcast = document.getElementById('preview-podcast');
  const previewTitle = document.getElementById('preview-title');
  const previewSource = document.getElementById('preview-source');
  const progressSection = document.getElementById('progress-section');
  const completeCard = document.getElementById('complete-card');
  const errorCard = document.getElementById('error-card');
  const errorMessage = document.getElementById('error-message');
  const completeTitle = document.getElementById('complete-title');
  const completeMeta = document.getElementById('complete-meta');
  const completeSummaryWarning = document.getElementById('complete-summary-warning');
  const openObsidianLink = document.getElementById('open-obsidian');
  const resetBtn = document.getElementById('reset-btn');
  const errorResetBtn = document.getElementById('error-reset-btn');

  let previewTimer = null;
  let activeStream = null;

  // -------- Init step icons --------
  document.querySelectorAll('.step-icon').forEach((el) => {
    el.setAttribute('data-state', 'pending');
  });

  // -------- URL → enable button + preview --------
  function isLikelyUrl(s) {
    return /^https?:\/\/\S+/i.test(s.trim());
  }

  urlInput.addEventListener('input', () => {
    const value = urlInput.value.trim();
    submitBtn.disabled = !isLikelyUrl(value);
    if (previewTimer) clearTimeout(previewTimer);
    if (!isLikelyUrl(value)) {
      previewBox.classList.add('hidden');
      return;
    }
    previewTimer = setTimeout(() => fetchPreview(value), 500);
  });

  async function fetchPreview(url) {
    try {
      const resp = await fetch('/api/episode/preview?url=' + encodeURIComponent(url));
      if (!resp.ok) return;
      const data = await resp.json();
      if (data.error) {
        previewBox.classList.add('hidden');
        return;
      }
      previewPodcast.textContent = data.podcast_name || '—';
      previewTitle.textContent = data.title || data.audio_url || url;
      previewSource.textContent = data.source === 'xiaoyuzhou' ? '来源：小宇宙' : '来源：直链';
      previewBox.classList.remove('hidden');
    } catch (e) {
      // silent; preview is optional
    }
  }

  // -------- Submit --------
  submitBtn.addEventListener('click', () => startTranscribe(urlInput.value.trim()));
  urlInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !submitBtn.disabled) startTranscribe(urlInput.value.trim());
  });

  async function startTranscribe(url) {
    resetUI(/*hideForm*/ true);
    progressSection.classList.remove('hidden');
    submitBtn.disabled = true;

    let taskId;
    try {
      const resp = await fetch('/api/transcribe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url }),
      });
      if (!resp.ok) throw new Error('提交失败 HTTP ' + resp.status);
      const data = await resp.json();
      taskId = data.task_id;
    } catch (e) {
      showError(e.message);
      return;
    }

    const es = new EventSource(`/api/transcribe/${taskId}/stream`);
    activeStream = es;
    es.addEventListener('progress', (ev) => {
      try {
        const e = JSON.parse(ev.data);
        applyEvent(e);
      } catch (_) {}
    });
    es.addEventListener('end', () => {
      es.close();
      activeStream = null;
    });
    es.onerror = () => {
      // The stream will close on its own end event; only surface errors if no complete card yet
      if (!completeCard.classList.contains('hidden') || !errorCard.classList.contains('hidden')) return;
      // Wait a tick to allow a possible end event to land
      setTimeout(() => {
        if (completeCard.classList.contains('hidden') && errorCard.classList.contains('hidden')) {
          showError('连接中断');
        }
        es.close();
        activeStream = null;
      }, 500);
    };
  }

  // -------- Event handling --------
  function setStepState(stage, state, message) {
    const li = document.querySelector(`li[data-stage="${stage}"]`);
    if (!li) return;
    const icon = li.querySelector('.step-icon');
    const msg = li.querySelector('.step-message');
    icon.setAttribute('data-state', state);
    if (message) msg.textContent = message;
  }

  function applyEvent(e) {
    const { stage, status, message, extra } = e;
    if (status === 'start') setStepState(stage, 'in_progress', message || '');
    else if (status === 'done') {
      setStepState(stage, 'done', message || '');
      if (stage === 'write' && extra && extra.note_path) {
        showComplete(extra);
      }
    } else if (status === 'skipped') setStepState(stage, 'skipped', message || '');
    else if (status === 'error') {
      setStepState(stage, 'error', message || '');
      showError(message || '转录失败');
    }
  }

  function showComplete(extra) {
    completeTitle.textContent = extra.title || '';
    const secs = Math.round((extra.elapsed_ms || 0) / 1000);
    completeMeta.textContent = `${extra.podcast_name || ''} · ${extra.char_count} 字 · ${extra.paragraph_count} 段 · 用时 ${secs} 秒`;
    if (extra.summary_failed) completeSummaryWarning.classList.remove('hidden');
    if (extra.obsidian_url) {
      openObsidianLink.href = extra.obsidian_url;
      openObsidianLink.classList.remove('pointer-events-none', 'opacity-50');
    } else {
      openObsidianLink.classList.add('pointer-events-none', 'opacity-50');
    }
    completeCard.classList.remove('hidden');
  }

  function showError(msg) {
    errorMessage.textContent = msg;
    errorCard.classList.remove('hidden');
    if (activeStream) {
      activeStream.close();
      activeStream = null;
    }
  }

  // -------- Reset --------
  function resetUI(hideForm) {
    completeCard.classList.add('hidden');
    completeSummaryWarning.classList.add('hidden');
    errorCard.classList.add('hidden');
    document.querySelectorAll('.step-icon').forEach((el) => el.setAttribute('data-state', 'pending'));
    document.querySelectorAll('.step-message').forEach((el) => (el.textContent = ''));
    progressSection.classList.add('hidden');
    if (activeStream) {
      activeStream.close();
      activeStream = null;
    }
  }

  resetBtn.addEventListener('click', () => {
    resetUI(false);
    urlInput.value = '';
    submitBtn.disabled = true;
    previewBox.classList.add('hidden');
    urlInput.focus();
  });

  errorResetBtn.addEventListener('click', () => {
    errorCard.classList.add('hidden');
    submitBtn.disabled = !isLikelyUrl(urlInput.value);
    urlInput.focus();
  });
})();
