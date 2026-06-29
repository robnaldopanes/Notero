const form = document.getElementById('form');
const submitBtn = document.getElementById('submit');
const spinner = document.getElementById('spinner');
const output = document.getElementById('output');
const errorCard = document.getElementById('error');
const metaEl = document.getElementById('meta');
const alertsEl = document.getElementById('alerts');
const qualityEl = document.getElementById('quality');
const sectionListEl = document.getElementById('section-list');
const copyAllBtn = document.getElementById('copy-all');
const copyHtmlBtn = document.getElementById('copy-html');
const copyStatus = document.getElementById('copy-status');
const errorMsg = document.getElementById('error-msg');
const statusBtn = document.getElementById('status-btn');
const noKeysNotice = document.getElementById('no-keys-notice');
const errorExtra = document.getElementById('error-extra');
const copyErrorBtn = document.getElementById('copy-error');
const panelUrl = document.getElementById('panel-url');
const panelText = document.getElementById('panel-text');
const sourceUrlInput = document.getElementById('source_url');
const sourceTextInput = document.getElementById('source_text');
const refineBtn = document.getElementById('refine-btn');
const refineInput = document.getElementById('refine-input');
const refineSpinner = document.getElementById('refine-spinner');
const refineStatus = document.getElementById('refine-status');
const chatLogEl = document.getElementById('chat-log');

document.getElementById('version-badge').textContent = 'v11';
console.log('[nexaa] v11 cargado');

let currentMode = 'url';
let currentFormat = 'nexaa_social_v1';
let lastSections = {};
let lastProvider = null;
let lastSourcePayload = null;
let FORMATS_CACHE = [];

async function loadFormats() {
  try {
    const r = await fetch('/api/formats');
    FORMATS_CACHE = await r.json();
    const sel = document.getElementById('format');
    sel.innerHTML = '';
    for (const f of FORMATS_CACHE) {
      const opt = document.createElement('option');
      opt.value = f.name;
      opt.textContent = f.label;
      sel.appendChild(opt);
    }
    const preferred = FORMATS_CACHE.find(f => f.name === 'nexaa_social_v1') ? 'nexaa_social_v1' : FORMATS_CACHE[0].name;
    sel.value = preferred;
    currentFormat = preferred;
  } catch (e) {
    FORMATS_CACHE = [{ name: 'nexaa_social_v1', label: 'Nexaa social (con Facebook)' }, { name: 'nexaa_v1', label: 'Nexaa clásico (7 secciones)' }];
  }
}
loadFormats();

document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => {
      t.classList.remove('tab-active');
      t.setAttribute('aria-selected', 'false');
    });
    tab.classList.add('tab-active');
    tab.setAttribute('aria-selected', 'true');
    currentMode = tab.dataset.mode;
    panelUrl.hidden = currentMode !== 'url';
    panelText.hidden = currentMode !== 'text';
  });
});

// ── Loader overlay animado ────────────────────────────────────
const loaderOverlay = document.getElementById('loader-overlay');
const loaderIcon    = document.getElementById('loader-icon');
const loaderTitle   = document.getElementById('loader-title');
const loaderPhase   = document.getElementById('loader-phase');
const loaderBar     = document.getElementById('loader-bar');

const LOADER_PHASES = [
  { pct: 8,  icon: '🔗', title: 'Generando noticia…',    phase: 'Conectando con el sitio…' },
  { pct: 22, icon: '📰', title: 'Leyendo el artículo…',   phase: 'Extrayendo contenido original…' },
  { pct: 38, icon: '🔍', title: 'Buscando fuentes…',     phase: 'Consultando otros medios sobre el tema…' },
  { pct: 55, icon: '📚', title: 'Leyendo las fuentes…',  phase: 'Descargando texto completo de fuentes adicionales…' },
  { pct: 70, icon: '🧠', title: 'La IA está redactando…', phase: 'El modelo sintetiza y redacta la noticia Nexaa…' },
  { pct: 85, icon: '✏️',  title: 'Puliendo la noticia…', phase: 'Verificando calidad y extensión…' },
  { pct: 95, icon: '✨',  title: 'Casi lista…',          phase: 'Finalizando y formateando secciones…' },
];

let _loaderInterval = null;
let _loaderPhaseIdx = 0;

function loaderStart() {
  _loaderPhaseIdx = 0;
  loaderOverlay.classList.add('active');
  _applyLoaderPhase(LOADER_PHASES[0]);
  _loaderInterval = setInterval(() => {
    _loaderPhaseIdx = Math.min(_loaderPhaseIdx + 1, LOADER_PHASES.length - 1);
    _applyLoaderPhase(LOADER_PHASES[_loaderPhaseIdx]);
  }, 2200);
}

function loaderStop() {
  clearInterval(_loaderInterval);
  _loaderInterval = null;
  // Flash de éxito antes de ocultar
  loaderIcon.textContent = '🌟';
  loaderTitle.textContent = '¡Lista!';
  loaderPhase.textContent = 'Tu noticia está lista para copiar.';
  loaderBar.style.width = '100%';
  setTimeout(() => loaderOverlay.classList.remove('active'), 600);
}

function loaderError() {
  clearInterval(_loaderInterval);
  _loaderInterval = null;
  loaderOverlay.classList.remove('active');
}

function _applyLoaderPhase(p) {
  loaderIcon.textContent  = p.icon;
  loaderTitle.textContent = p.title;
  loaderPhase.textContent = p.phase;
  loaderBar.style.width   = p.pct + '%';
}
// ─────────────────────────────────────────────────────────────────────────

function setLoading(loading) {
  submitBtn.disabled = loading;
  spinner.hidden = true;  // siempre oculto, usamos el overlay
  if (loading) {
    output.hidden = true;
    errorCard.hidden = true;
    loaderStart();
  }
}

function sectionEmoji(name) {
  const meta = FORMATS_CACHE.find(f => f.name === currentFormat);
  const spec = (meta && meta.sections) ? meta.sections.find(s => s.name === name) : null;
  return spec ? spec.emoji : '';
}

function renderMeta(data) {
  metaEl.innerHTML = '';
  const items = [];
  if (data.provider) items.push({ text: `IA: ${data.provider}`, cls: '' });
  if (data.source_site) items.push({ text: `fuente: ${data.source_site}`, cls: 'review' });
  if (data.is_draft) items.push({ text: 'BORRADOR', cls: 'draft' });
  if (data.quality_ok && (data.warnings || []).length === 0 && (data.issues || []).length === 0) {
    items.push({ text: 'OK', cls: 'ok' });
  } else if ((data.issues || []).length > 0) {
    items.push({ text: `${data.issues.length} issues`, cls: 'issue' });
  } else {
    items.push({ text: `${(data.warnings || []).length} warnings`, cls: 'review' });
  }
  if (data.elapsed_ms) items.push({ text: `${Math.round(data.elapsed_ms)} ms`, cls: '' });
  for (const it of items) {
    const span = document.createElement('span');
    span.className = 'tag ' + (it.cls || '');
    span.textContent = it.text;
    metaEl.appendChild(span);
  }
}

function renderAlerts(data) {
  alertsEl.innerHTML = '';
  for (const w of data.warnings || []) {
    const d = document.createElement('div');
    d.className = 'alert warn';
    d.textContent = '⚠ ' + w;
    alertsEl.appendChild(d);
  }
  for (const i of data.issues || []) {
    const d = document.createElement('div');
    d.className = 'alert err';
    d.textContent = '✕ ' + i;
    alertsEl.appendChild(d);
  }
}

function renderSections(sections) {
  sectionListEl.innerHTML = '';
  const order = (() => {
    const meta = FORMATS_CACHE.find(f => f.name === currentFormat);
    return (meta && meta.sections) ? meta.sections.map(s => s.name) : [];
  })();
  const seen = new Set();
  const names = [...order, ...Object.keys(sections || {}).filter(n => !order.includes(n))];
  for (const name of names) {
    if (seen.has(name)) continue;
    seen.add(name);
    const value = (sections || {})[name];
    if (value == null) continue;
    const emoji = sectionEmoji(name);
    const card = document.createElement('div');
    card.className = 'section-card';
    card.dataset.sectionName = name;
    card.dataset.sectionValue = value;
    const header = document.createElement('div');
    header.className = 'section-header';
    const title = document.createElement('span');
    title.className = 'section-title';
    title.textContent = `${emoji} ${name}`.trim();
    header.appendChild(title);
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'copy-btn ghost';
    btn.textContent = 'Copiar';
    btn.addEventListener('click', () => copyValue(value, btn, name));
    header.appendChild(btn);
    card.appendChild(header);
    const body = document.createElement('div');
    body.className = 'section-body';
    body.textContent = value;
    card.appendChild(body);
    sectionListEl.appendChild(card);
  }
}

function renderQuality(data) {
  const wc = data.word_counts || {};
  const lines = [];
  lines.push(`Issues: ${(data.issues || []).length}`);
  lines.push(`Warnings: ${(data.warnings || []).length}`);
  lines.push(`Marcadores de incertidumbre: ${(data.text || '').split('[DATO NO CONFIRMADO').length - 1}`);
  lines.push(`Palabras por sección: ${JSON.stringify(wc)}`);
  if (data.source_url) lines.push(`Fuente: ${data.source_site} — ${data.source_url}`);
  qualityEl.innerHTML = '<pre class="output-text">' + lines.join('\n') + '</pre>';
}

function renderNoKeysNotice(data) {
  if (data.provider !== 'local_template' && !data.is_draft) {
    noKeysNotice.hidden = true;
    return;
  }
  fetch('/api/status').then(r => r.json()).then(status => {
    const provs = status.available_providers || [];
    const breaker = status.circuit_breaker || {};
    const groqState = (breaker.groq || {}).state || 'unknown';
    const reason = provs.length === 0
      ? 'No hay API keys configuradas en <code>.env</code>.'
      : (groqState === 'open'
          ? `Groq está en cooldown (rate limit). Circuit breaker abierto: ${(breaker.groq || {}).open_until_in || 0}s restantes. Esperá unos segundos.`
          : 'Todos los proveedores externos fallaron. Revisa los logs del servidor.');
    noKeysNotice.hidden = false;
    noKeysNotice.className = 'notice warn-notice';
    noKeysNotice.innerHTML =
      '⚠ Estás viendo un <b>BORRADOR local</b> (estructura vacía, no escrito por una IA). ' +
      `<b>Motivo:</b> ${reason}<br>` +
      `<small>Proveedores con key: <b>${provs.join(', ') || '(ninguno)'}</b></small>`;
  });
}

async function copyValue(text, btn, label) {
  const ok = await copyToClipboard(text);
  if (ok) {
    const orig = btn.textContent;
    btn.textContent = `✓ copiado`;
    btn.classList.add('copied');
    setTimeout(() => {
      btn.textContent = orig;
      btn.classList.remove('copied');
    }, 1800);
  } else {
    btn.textContent = 'falló';
  }
}

function updateImagePreview(imageUrl) {
  const outImgContainer = document.getElementById('output-image-container');
  const outImg = document.getElementById('output-image');
  const imgLinkCard = document.getElementById('image-link-card');
  const imgLinkBody = document.getElementById('image-link-body');
  const copyBtn = document.getElementById('copy-image-link-btn');

  if (imageUrl) {
    outImg.src = imageUrl;
    outImgContainer.style.display = 'block';
    imgLinkBody.textContent = imageUrl;
    imgLinkCard.style.display = 'block';
    copyBtn.onclick = () => {
      copyValue(imageUrl, copyBtn, 'Link de la imagen');
    };
  } else {
    outImg.src = '';
    outImgContainer.style.display = 'none';
    imgLinkBody.textContent = '';
    imgLinkCard.style.display = 'none';
    copyBtn.onclick = null;
  }
}

async function copyToClipboard(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (e) {
    const ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try { ok = document.execCommand('copy'); } catch (err) { ok = false; }
    document.body.removeChild(ta);
    return ok;
  }
}

function buildCopyAllText() {
  const cards = sectionListEl.querySelectorAll('.section-card');
  const lines = [];
  for (const c of cards) {
    const name = c.dataset.sectionName;
    const value = c.dataset.sectionValue;
    const emoji = sectionEmoji(name);
    const header = `${emoji} ${name}:`.trim();
    lines.push(header);
    lines.push(value);
    lines.push('');
  }
  return lines.join('\n').trim();
}

function buildCopyHtml() {
  const cards = sectionListEl.querySelectorAll('.section-card');
  const parts = [];
  for (const c of cards) {
    const name = c.dataset.sectionName;
    const value = c.dataset.sectionValue;
    const safe = value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    parts.push(`<h3>${name}</h3>`);
    parts.push(`<p>${safe.replace(/\n/g, '</p><p>')}</p>`);
  }
  return parts.join('\n');
}

async function postJson(url, payload) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 90000);
  try {
    const r = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    const data = await r.json();
    return { status: r.status, data };
  } finally {
    clearTimeout(timeoutId);
  }
}

document.querySelectorAll('.chip').forEach(chip => {
  chip.addEventListener('click', () => {
    refineInput.value = chip.dataset.prompt || chip.textContent;
    refineInput.focus();
  });
});

function appendChat(role, text, ok = true) {
  const div = document.createElement('div');
  div.className = 'chat-msg ' + role + (role === 'ai' ? (ok ? ' ok' : '') : '');
  div.textContent = text;
  chatLogEl.appendChild(div);
  chatLogEl.scrollTop = chatLogEl.scrollHeight;
}

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  setLoading(true);
  noKeysNotice.hidden = true;

  currentFormat = document.getElementById('format').value;
  let url = '';
  let text = '';

  try {
    let result;

    if (currentMode === 'url') {
      url = (sourceUrlInput.value || '').trim();
      if (!url) {
        errorCard.hidden = false;
        errorMsg.textContent = 'Pegá una URL primero';
        errorExtra.innerHTML = '';
        errorCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
        return;
      }
      if (!/^https?:\/\//i.test(url)) {
        url = 'https://' + url;
        sourceUrlInput.value = url;
      }
      console.log('[nexaa] URL:', url);
      const expectedTitleEl = document.getElementById('expected-title');
      const expectedTitle = expectedTitleEl ? expectedTitleEl.value.trim() : '';
      const payload = { url, force: false };
      if (expectedTitle) payload.expected_title = expectedTitle;
      const { status, data } = await postJson('/api/scrape-and-generate', payload);
      result = { status, data };
      lastSourcePayload = { type: 'url', url, format: currentFormat };
    } else {
      text = (sourceTextInput.value || '').trim();
      if (text.length < 20) {
        errorCard.hidden = false;
        errorMsg.textContent = 'Pegá un texto de al menos 20 caracteres';
        errorExtra.innerHTML = '';
        errorCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
        return;
      }
      console.log('[nexaa] Texto length:', text.length);
      const { status, data } = await postJson('/api/generate', {
        mode: 'idea',
        format: currentFormat,
        categoria: '',
        ciudad: 'Chillán',
        region: 'Región de Ñuble',
        fecha: '',
        titulo_corto: '',
        que_paso: text,
        por_que_importa: '',
        contexto: '',
        impacto: '',
        fuentes: [],
        source_url: '',
      });
      result = { status, data };
      lastSourcePayload = { type: 'text', text, format: currentFormat };
    }

    const { status, data } = result;
    if (!data || data.ok === false) {
      const msg = data?.detail || data?.reason || `HTTP ${status}`;
      errorCard.hidden = false;
      errorMsg.textContent = msg;
      const urlInfo = (data && data.url) || (currentMode === 'url' ? url : '(modo texto)');
      errorExtra.innerHTML = `<small class="muted">Enviado: <code>${urlInfo.substring(0, 200)}</code></small>`;
      output.hidden = true;
      errorCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
      return;
    }

    currentFormat = data.format || currentFormat;
    lastSections = data.sections || {};
    lastProvider = data.provider;
    loaderStop();
    renderMeta(data);
    renderAlerts(data);
    renderSections(lastSections);
    renderQuality(data);
    renderNoKeysNotice(data);

    // Render image preview
    updateImagePreview(data.image_url);

    chatLogEl.innerHTML = '';
    output.hidden = false;
    output.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (err) {
    loaderError();
    errorCard.hidden = false;
    errorMsg.textContent = 'Error de red: ' + String(err);
    errorExtra.innerHTML = `<small class="muted">Modo: ${currentMode}, input length: ${(url + text).length}</small>`;
    output.hidden = true;
    errorCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
  } finally {
    setLoading(false);
  }
});

refineBtn.addEventListener('click', async () => {
  const msg = refineInput.value.trim();
  if (!msg) { refineStatus.textContent = 'escribí una instrucción'; return; }
  if (!lastSections || !Object.keys(lastSections).length) { refineStatus.textContent = 'primero generá una noticia'; return; }

  appendChat('user', msg);
  refineInput.value = '';
  refineBtn.disabled = true;
  refineSpinner.hidden = false;
  refineStatus.textContent = '';

  try {
    let payload;
    if (lastSourcePayload && lastSourcePayload.type === 'url') {
      payload = {
        format: currentFormat,
        source_url: lastSourcePayload.url,
        current_sections: lastSections,
        user_message: msg,
      };
    } else {
      payload = {
        format: currentFormat,
        que_paso: lastSourcePayload ? lastSourcePayload.text : '',
        current_sections: lastSections,
        user_message: msg,
      };
    }

    const { status, data } = await postJson('/api/refine', payload);
    if (!data.ok) {
      appendChat('ai', 'Error: ' + (data.reason || data.detail || `HTTP ${status}`), false);
      return;
    }
    lastSections = data.sections || {};
    lastProvider = data.provider;
    renderSections(lastSections);
    renderMeta({ ...data, source_site: (lastSourcePayload && lastSourcePayload.url) || '' });
    renderAlerts(data);

    // Render image preview after refinement
    updateImagePreview(data.image_url);

    appendChat('ai', `Refinado por ${data.provider} en ${Math.round(data.elapsed_ms)} ms. Issues: ${(data.issues || []).length}.`, true);
    output.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (err) {
    appendChat('ai', 'Error: ' + err, false);
  } finally {
    refineBtn.disabled = false;
    refineSpinner.hidden = true;
  }
});

copyAllBtn.addEventListener('click', async () => {
  const text = buildCopyAllText();
  const ok = await copyToClipboard(text);
  copyStatus.textContent = ok ? 'todo copiado ✓' : 'falló la copia';
  setTimeout(() => { copyStatus.textContent = ''; }, 2000);
});

copyHtmlBtn.addEventListener('click', async () => {
  const text = buildCopyHtml();
  const ok = await copyToClipboard(text);
  copyStatus.textContent = ok ? 'HTML copiado ✓' : 'falló la copia';
  setTimeout(() => { copyStatus.textContent = ''; }, 2000);
});

copyErrorBtn.addEventListener('click', async () => {
  const text = `Nexaa error\nMensaje: ${errorMsg.textContent}\n${errorExtra.textContent}\nHora: ${new Date().toISOString()}\nVersión: v9`;
  try {
    await navigator.clipboard.writeText(text);
    copyErrorBtn.textContent = '✓ copiado';
    setTimeout(() => copyErrorBtn.textContent = 'Copiar detalles del error', 1800);
  } catch (e) {
    copyErrorBtn.textContent = 'falló';
  }
});

statusBtn.addEventListener('click', async () => {
  try {
    const r = await fetch('/api/status');
    const data = await r.json();
    const provs = (data.available_providers || []).join(', ') || '(ninguno)';
    alert(`Proveedores activos: ${provs}\n\nCircuit:\n${JSON.stringify(data.circuit_breaker, null, 2)}`);
  } catch (e) {
    alert('Error al consultar estado: ' + e);
  }
});

// Lógica de búsqueda integrada
const searchBtn = document.getElementById('search-btn');
const searchInput = document.getElementById('search-input');
const searchSpinner = document.getElementById('search-spinner');
const searchResults = document.getElementById('search-results');

let currentSearchScope = 'local';
const searchScopeHint = document.getElementById('search-scope-hint');
const SCOPE_HINTS = {
    local: 'Buscará solo en medios de la Región de Ñuble + feeds regionales.',
    national: 'Buscará en medios nacionales chilenos (Cooperativa, La Tercera, BioBio, etc).',
    international: 'Buscará en medios internacionales (CNN, NYT, BBC, etc).',
};

document.querySelectorAll('.scope-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.scope-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        currentSearchScope = btn.dataset.scope;
        if (searchScopeHint) {
            searchScopeHint.textContent = SCOPE_HINTS[currentSearchScope] || '';
        }
    });
});

async function performSearch() {
  const query = searchInput.value.trim();

  searchBtn.disabled = true;
  searchSpinner.hidden = false;
  searchResults.innerHTML = '';
  try {
    const r = await fetch(`/api/search?q=${encodeURIComponent(query)}&scope=${currentSearchScope}`);
    if (!r.ok) {
      const errData = await r.json();
      const errMsg = errData.detail || `HTTP ${r.status}`;
      searchResults.innerHTML = `<div class="empty-state" style="color: var(--err);">Error al buscar: ${errMsg}</div>`;
      return;
    }
    const data = await r.json();
    if (!Array.isArray(data) || data.length === 0) {
      searchResults.innerHTML = '<div class="empty-state">No se encontraron noticias. Intenta con otras palabras clave.</div>';
      return;
    }
    searchResults.innerHTML = data.map(item => `
      <div class="search-result-item">
        <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 2px;">
          <span class="tag" style="font-size: 10px; padding: 2px 6px; border: 1px solid var(--border); border-radius: 4px; color: var(--accent); background: rgba(56, 189, 248, 0.05); font-weight: 600;">${item.source || 'Fuente'}</span>
        </div>
        <h4 style="margin-top: 2px;">${item.title}</h4>
        <p>${item.snippet || '(sin descripción)'}</p>
        <div class="actions">
          <button type="button" class="btn-sm primary btn-auto-generate" data-url="${item.url}" data-title="${(item.title || '').replace(/"/g, '&quot;')}">✍️ Redactar con IA</button>
          <a href="${item.url}" target="_blank" rel="noopener noreferrer" class="btn-sm ghost">🌐 Abrir fuente</a>
        </div>
      </div>
    `).join('');

    searchResults.querySelectorAll('.btn-auto-generate').forEach(btn => {
      btn.addEventListener('click', () => {
        const url = btn.dataset.url;
        const expectedTitle = btn.dataset.title || '';
        // 1. Cambiar a la pestaña de URL
        const urlTab = document.querySelector('.tab[data-mode="url"]');
        if (urlTab) urlTab.click();
        // 2. Rellenar input
        sourceUrlInput.value = url;
        // 3. Guardar título esperado en campo oculto
        let expectedTitleInput = document.getElementById('expected-title');
        if (!expectedTitleInput) {
          expectedTitleInput = document.createElement('input');
          expectedTitleInput.type = 'hidden';
          expectedTitleInput.id = 'expected-title';
          expectedTitleInput.name = 'expected_title';
          form.appendChild(expectedTitleInput);
        }
        expectedTitleInput.value = expectedTitle;
        // 4. Forzar submit automático
        sourceUrlInput.focus();
        form.dispatchEvent(new Event('submit'));
      });
    });
  } catch (e) {
    searchResults.innerHTML = `<div class="empty-state" style="color: var(--err);">Error al buscar: ${e.message}</div>`;
  } finally {
    searchBtn.disabled = false;
    searchSpinner.hidden = true;
  }
}

searchBtn.addEventListener('click', performSearch);
searchInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    e.preventDefault();
    performSearch();
  }
});
