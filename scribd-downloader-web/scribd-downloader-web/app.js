// Scribd downloader UI — wired to the FastAPI backend.
const API = (window.SCRIBD_API_BASE || '').replace(/\/$/, '');
const $ = (selector) => document.querySelector(selector);

const views = {
  login: $('#view-login'),
  home: $('#view-home'),
  loading: $('#view-loading'),
  error: $('#view-error'),
  history: $('#view-history'),
  users: $('#view-users'),
};

const FORMAT_LABELS = { pdf: 'PDF', docx: 'DOCX', txt: 'TXT' };
const PHASE_LABELS = {
  queued: 'QUEUED',
  starting: 'STARTING',
  browser: 'STARTING',
  pages: 'CONVERTING',
  merging: 'MERGING',
  writing: 'SAVING',
  done: 'DONE',
};
const PHASE_LEADS = {
  queued: 'Unduhanmu masuk antrean. Job akan mulai otomatis — jangan tutup halaman ini.',
  starting: 'Menyiapkan browser headless dan membuka dokumen Scribd…',
  browser: 'Membuka dokumen Scribd di browser headless…',
  pages: 'Sedang mengambil halaman dokumen dan menyusunnya jadi file. Jangan tutup halaman ini.',
  merging: 'Semua halaman sudah diambil — menggabungkan jadi satu file…',
  writing: 'Menyusun file akhir. Hampir selesai…',
};
const ERROR_KICKERS = {
  invalid_url: 'ERROR — INVALID LINK',
  empty_url: 'ERROR — INVALID LINK',
  not_found: 'ERROR — DOCUMENT NOT FOUND',
  blocked: 'ERROR — ACCESS BLOCKED',
  private: 'ERROR — DOCUMENT LOCKED',
  login_required: 'ERROR — DOCUMENT LOCKED',
  bad_password: 'ERROR — DOCUMENT LOCKED',
  timeout: 'ERROR — TIMEOUT',
  browser_error: 'ERROR — SERVER PROBLEM',
  backend_unavailable: 'ERROR — SERVER PROBLEM',
  internal: 'ERROR — SERVER PROBLEM',
  network: 'ERROR — SERVER OFFLINE',
};
const ERROR_HEADLINES = {
  invalid_url: '<span class="red">OOPS.</span><br>LINK<br><span class="outline">BROKEN.</span>',
  empty_url: '<span class="red">OOPS.</span><br>LINK<br><span class="outline">BROKEN.</span>',
  not_found: '<span class="red">OOPS.</span><br>DOCUMENT<br><span class="outline">GONE.</span>',
  blocked: '<span class="red">OOPS.</span><br>ACCESS<br><span class="outline">BLOCKED.</span>',
  private: '<span class="red">OOPS.</span><br>DOCUMENT<br><span class="outline">LOCKED.</span>',
  login_required: '<span class="red">OOPS.</span><br>DOCUMENT<br><span class="outline">LOCKED.</span>',
  bad_password: '<span class="red">OOPS.</span><br>DOCUMENT<br><span class="outline">LOCKED.</span>',
  timeout: '<span class="red">OOPS.</span><br>TAKING<br><span class="outline">TOO LONG.</span>',
  default: '<span class="red">OOPS.</span><br>DOWNLOAD<br><span class="outline">FAILED.</span>',
};

const state = {
  format: 'PDF',
  pendingFormat: 'pdf',
  jobId: null,
  pollTimer: null,
  pollFailures: 0,
  currentUrl: '',
  username: null,
};

function show(name) {
  Object.entries(views).forEach(([key, view]) => {
    view.hidden = key !== name;
  });
  window.scrollTo({ top: 0 });
}

function setAuthenticated(username) {
  state.username = username;
  $('#navUserName').textContent = `@${username}`;
  $('#readySection').hidden = true;
  document.querySelectorAll('.app-only').forEach((element) => {
    element.hidden = false;
  });
  show('home');
}

function setSignedOut() {
  stopPolling();
  state.username = null;
  document.querySelectorAll('.app-only').forEach((element) => {
    element.hidden = true;
  });
  $('#navLinks').classList.remove('open');
  $('#readySection').hidden = true;
  $('#loginPassword').value = '';
  $('#loginError').hidden = true;
  show('login');
  $('#loginUsername').focus();
}

async function api(path, options = {}) {
  const { skipAuthRedirect = false, ...fetchOptions } = options;
  let response;
  try {
    response = await fetch(`${API}${path}`, { cache: 'no-store', ...fetchOptions });
  } catch (cause) {
    const error = new Error('Tidak bisa menghubungi server.');
    error.code = 'network';
    throw error;
  }

  let payload = null;
  try {
    payload = await response.json();
  } catch (cause) {
    payload = null;
  }

  if (!response.ok) {
    const detail = payload && typeof payload.detail === 'string' ? payload.detail : null;
    const error = new Error(
      (payload && payload.error) || detail || `Server error (${response.status})`
    );
    error.code = (payload && payload.code) || 'http_error';
    error.status = response.status;
    if (response.status === 401 && !skipAuthRedirect) {
      setSignedOut();
    }
    throw error;
  }
  return payload;
}

function formatSize(bytes) {
  const value = Number(bytes);
  if (!Number.isFinite(value) || value <= 0) return '0 MB';
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 * 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(1)} MB`;
  return `${(value / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function formatDate(value) {
  const date = value ? new Date(value) : null;
  if (!date || Number.isNaN(date.getTime())) return '—';
  return date
    .toLocaleString('id-ID', {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
    .toUpperCase();
}

function clamp(value, low, high) {
  return Math.min(high, Math.max(low, value));
}

// ------------------------------------------------------------------ navigation
$('#burger').addEventListener('click', () => $('#navLinks').classList.toggle('open'));

document.querySelectorAll('[data-nav]').forEach((link) => {
  link.addEventListener('click', (event) => {
    event.preventDefault();
    $('#navLinks').classList.remove('open');
    if (!state.username) {
      show('login');
      return;
    }
    const target = link.dataset.nav;
    if (target === 'history') {
      show('history');
      renderHistory();
      return;
    }
    if (target === 'users') {
      show('users');
      renderUsers();
      return;
    }
    show('home');
    if (target === 'home-how') {
      setTimeout(() => $('#how').scrollIntoView({ behavior: 'smooth' }), 50);
    }
  });
});

// --------------------------------------------------------------------- formats
const chips = [...document.querySelectorAll('#formatChips .chip')];

function selectFormat(format) {
  state.format = String(format || 'PDF').toUpperCase();
  chips.forEach((chip) => {
    const selected = chip.dataset.format === state.format;
    chip.classList.toggle('selected', selected);
    chip.setAttribute('aria-checked', String(selected));
  });
}

chips.forEach((chip) => {
  chip.addEventListener('click', () => selectFormat(chip.dataset.format));
});

// ----------------------------------------------------------------------- submit
$('#downloadForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const url = $('#urlInput').value.trim();
  const inlineError = $('#inlineError');
  inlineError.hidden = true;
  $('#urlInput').style.borderColor = '';

  if (!url) {
    inlineError.textContent = '✕ TEMPEL TAUTAN SCRIBD DULU.';
    inlineError.hidden = false;
    $('#urlInput').style.borderColor = 'var(--signal)';
    $('#urlInput').focus();
    return;
  }

  await submitJob(url, state.format.toLowerCase());
});

function setBusy(busy) {
  const button = $('#downloadForm .btn-download');
  button.disabled = busy;
  button.textContent = busy ? 'STARTING…' : 'DOWNLOAD ↓';
}

async function submitJob(url, format) {
  setBusy(true);
  stopPolling();
  state.pendingFormat = String(format || 'pdf').toLowerCase();
  $('#readySection').hidden = true;
  try {
    const job = await api('/api/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, format: state.pendingFormat }),
    });
    state.jobId = job.id;
    state.currentUrl = job.url || url;
    resetLoading();
    show('loading');
    renderLoading(job);
    schedulePoll(500);
  } catch (error) {
    if (error.status === 401) return;
    const message =
      error.code === 'network'
        ? 'Tidak bisa menghubungi server. Pastikan layanan sedang berjalan.'
        : error.message;
    showError(message, error.code, url);
  } finally {
    setBusy(false);
  }
}

function resumeJob(job) {
  stopPolling();
  state.jobId = job.id;
  state.currentUrl = job.url || '';
  state.pendingFormat = job.format || 'pdf';
  resetLoading();
  show('loading');
  renderLoading(job);
  schedulePoll(300);
}

// ---------------------------------------------------------------------- loading
function resetLoading() {
  $('#percentText').textContent = '0%';
  $('#progressFill').style.width = '0%';
  $('#pagesText').textContent = 'MENGHITUNG HALAMAN…';
  $('#loadingLead').textContent = PHASE_LEADS.starting;
  $('#loadingPhaseText').textContent = 'STEP 02 OF 03 — STARTING';
  $('#phaseLabel').textContent = 'MENYIAPKAN…';
  $('#etaText').textContent = 'MENGHUBUNGI SERVER…';
  $('#progressTrack').setAttribute('aria-valuenow', '0');
  const convert = $('#checkConvert');
  convert.className = 'doing';
  convert.innerHTML = '● &nbsp;CONVERT — sedang berjalan';
  const save = $('#checkSave');
  save.className = 'waiting';
  save.innerHTML = '○ &nbsp;SAVE — menunggu';
  const cancel = $('#cancelBtn');
  cancel.disabled = false;
  cancel.textContent = 'CANCEL';
}

function etaText(job) {
  if (job.status === 'queued') {
    return job.queue_position
      ? `ANTRIAN #${job.queue_position} — MENUNGGU WORKER`
      : 'MENUNGGU ANTRIAN';
  }
  if (!job.started_at || !job.progress || job.progress < 4) return 'MENGHITUNG…';

  const started = Date.parse(job.started_at);
  if (!Number.isFinite(started)) return 'MENGHITUNG…';
  const elapsed = (Date.now() - started) / 1000;
  if (elapsed < 2) return 'MENGHITUNG…';

  const remaining = (elapsed * (100 - job.progress)) / job.progress;
  if (!Number.isFinite(remaining) || remaining <= 0) return 'HAMPIR SELESAI…';
  if (remaining > 120) return `EST. ${Math.ceil(remaining / 60)} MENIT LEFT`;
  return `EST. ${Math.max(1, Math.ceil(remaining))} DETIK LEFT`;
}

function renderLoading(job) {
  const progress = clamp(Number(job.progress) || 0, 0, 100);
  const rounded = Math.round(progress);
  $('#percentText').textContent = `${rounded}%`;
  $('#progressFill').style.width = `${progress}%`;
  $('#progressTrack').setAttribute('aria-valuenow', String(rounded));

  const total = Number(job.pages_total) || 0;
  const done = Number(job.pages_done) || 0;
  if (job.status === 'queued') {
    $('#pagesText').textContent = total ? `${done} / ${total} PAGES` : 'MENUNGGU ANTRIAN';
  } else if (total) {
    $('#pagesText').textContent = `${done} / ${total} PAGES`;
  } else {
    $('#pagesText').textContent = 'MENGHITUNG HALAMAN…';
  }

  const phase = job.phase || 'starting';
  $('#loadingPhaseText').textContent = `STEP 02 OF 03 — ${PHASE_LABELS[phase] || 'CONVERTING'}`;
  $('#loadingLead').textContent = PHASE_LEADS[phase] || PHASE_LEADS.pages;
  $('#phaseLabel').textContent = String(job.message || PHASE_LABELS[phase] || 'MENYIAPKAN…').toUpperCase();
  $('#etaText').textContent = etaText(job);

  const convert = $('#checkConvert');
  if (phase === 'merging' || phase === 'writing' || progress >= 94) {
    convert.className = 'done';
    convert.innerHTML = '✓ &nbsp;CONVERT — selesai';
  } else if (job.status === 'queued') {
    convert.className = 'doing';
    convert.innerHTML = '● &nbsp;CONVERT — dalam antrean';
  } else {
    convert.className = 'doing';
    convert.innerHTML = '● &nbsp;CONVERT — sedang berjalan';
  }

  const save = $('#checkSave');
  const saving = phase === 'merging' || phase === 'writing' || progress >= 94;
  save.className = saving ? 'doing' : 'waiting';
  save.innerHTML = saving
    ? '● &nbsp;SAVE — menyiapkan file'
    : '○ &nbsp;SAVE — menunggu';
}

// ---------------------------------------------------------------------- polling
function schedulePoll(delay = 700) {
  if (state.pollTimer) clearTimeout(state.pollTimer);
  state.pollTimer = setTimeout(pollJob, delay);
}

function stopPolling(clearJob = true) {
  if (state.pollTimer) clearTimeout(state.pollTimer);
  state.pollTimer = null;
  state.pollFailures = 0;
  if (clearJob) state.jobId = null;
}

async function pollJob() {
  const jobId = state.jobId;
  if (!jobId) return;
  state.pollTimer = null;

  let job;
  try {
    job = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
    state.pollFailures = 0;
  } catch (error) {
    if (error.status === 401) {
      stopPolling();
      return;
    }
    if (error.status === 404) {
      stopPolling();
      showError('Unduhan tidak ditemukan di server.', 'not_found', state.currentUrl);
      return;
    }
    state.pollFailures += 1;
    if (state.pollFailures > 12) {
      stopPolling();
      showError('Koneksi ke server terputus saat memantau unduhan.', 'network', state.currentUrl);
      return;
    }
    $('#etaText').textContent = 'KONEKSI TERTUNDA — MENCOBA LAGI…';
    schedulePoll(1500);
    return;
  }

  if (job.status === 'completed') {
    stopPolling();
    if (!views.history.hidden) {
      renderHistory();
    } else if (views.error.hidden) {
      renderReady(job);
    }
    return;
  }

  if (job.status === 'failed') {
    stopPolling();
    if (!views.history.hidden) {
      renderHistory();
    } else if (views.error.hidden) {
      showError(job.error || 'Unduhan gagal.', job.error_code, job.url || state.currentUrl, job.error_detail);
    }
    return;
  }

  if (job.status === 'cancelled') {
    stopPolling();
    if (!views.history.hidden) {
      renderHistory();
    } else if (!views.loading.hidden) {
      show('home');
    }
    return;
  }

  renderLoading(job);
  schedulePoll(job.status === 'queued' ? 1200 : 700);
}

// ------------------------------------------------------------------------ ready
function renderReady(job) {
  stopPolling();
  state.currentUrl = job.url || state.currentUrl;
  state.pendingFormat = job.format || state.pendingFormat;

  const pages = job.pages_total ?? job.pages_done ?? 0;
  $('#readyTitle').textContent = job.title || job.filename || 'Scribd Document';
  $('#readyMeta').textContent = `${FORMAT_LABELS[job.format] || String(job.format || '').toUpperCase()} • ${pages} PAGES • ${formatSize(job.size_bytes)}`;

  const link = $('#getFileBtn');
  if (job.download_url) {
    link.href = `${API}${job.download_url}`;
    link.hidden = false;
  } else {
    link.href = '#';
    link.hidden = true;
  }

  $('#readySection').hidden = false;
  show('home');
  setTimeout(() => $('#readySection').scrollIntoView({ behavior: 'smooth', block: 'start' }), 60);
}

// ------------------------------------------------------------------------ error
function showError(message, code, url, detail) {
  stopPolling();
  const key = code || 'default';
  $('#errorKickerText').textContent = ERROR_KICKERS[key] || ERROR_KICKERS.default;
  $('#errorHeadline').innerHTML = ERROR_HEADLINES[key] || ERROR_HEADLINES.default;
  $('#errorMessage').textContent = message || 'Unduhan gagal. Silakan coba lagi.';
  $('#errorInput').value = url || '(kosong)';
  state.currentUrl = url || '';

  if (detail) {
    $('#errorDetail').textContent = String(detail);
    $('#errorDetails').hidden = false;
    $('#errorDetails').open = false;
  } else {
    $('#errorDetail').textContent = '';
    $('#errorDetails').hidden = true;
  }
  show('error');
}

$('#tryAgainBtn').addEventListener('click', () => {
  const url = state.currentUrl || $('#errorInput').value;
  if (!url || url === '(kosong)') {
    show('home');
    $('#urlInput').focus();
    return;
  }
  submitJob(url, state.pendingFormat || state.format.toLowerCase());
});

$('#pasteNewBtn').addEventListener('click', () => {
  show('home');
  $('#urlInput').value = '';
  $('#urlInput').focus();
});

function clearErrorLink() {
  show('home');
  $('#urlInput').value = '';
  $('#urlInput').focus();
}

$('#clearError').addEventListener('click', clearErrorLink);
$('#clearError').addEventListener('keydown', (event) => {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault();
    clearErrorLink();
  }
});

// ----------------------------------------------------------------------- cancel
$('#cancelBtn').addEventListener('click', async () => {
  const jobId = state.jobId;
  if (!jobId) {
    show('home');
    return;
  }

  const cancel = $('#cancelBtn');
  cancel.disabled = true;
  cancel.textContent = 'CANCELLING…';
  try {
    await api(`/api/jobs/${encodeURIComponent(jobId)}/cancel`, { method: 'POST' });
  } catch (error) {
    // The job may have finished between the click and the request.
    if (error.status === 401) return;
  }
  stopPolling();
  show('home');
});

// ---------------------------------------------------------------------- history
function historyRow(job, index) {
  const row = document.createElement('div');
  row.className = 'history-row';

  const number = document.createElement('p');
  number.className = 'index';
  number.textContent = String(index + 1).padStart(2, '0');

  const info = document.createElement('div');
  const title = document.createElement('h3');
  title.textContent = job.title || job.filename || 'Scribd Document';
  const meta = document.createElement('p');
  meta.className = 'meta';

  const format = FORMAT_LABELS[job.format] || String(job.format || '').toUpperCase();
  const pages = job.pages_total ?? job.pages_done ?? 0;
  const parts = [format];
  if (job.status === 'completed') {
    parts.push(`${pages} PAGES`, formatSize(job.size_bytes));
  } else if (job.status === 'failed') {
    parts.push('FAILED');
  } else {
    parts.push(`${Math.round(Number(job.progress) || 0)}%`, job.status === 'queued' ? 'QUEUED' : 'RUNNING');
  }
  parts.push(formatDate(job.created_at));
  meta.textContent = parts.join(' • ');
  info.append(title, meta);

  if (job.status === 'failed' && job.error) {
    const error = document.createElement('p');
    error.className = 'history-error';
    error.textContent = job.error;
    info.append(error);
  }

  const status = document.createElement('span');
  status.className = `status ${job.status}`;
  status.textContent =
    job.status === 'completed'
      ? 'DONE'
      : job.status === 'failed'
        ? 'FAILED'
        : job.status === 'queued'
          ? 'QUEUED'
          : 'RUNNING';

  let action;
  if (job.status === 'completed' && job.download_url) {
    action = document.createElement('a');
    action.className = 'btn-redownload';
    action.href = `${API}${job.download_url}`;
    action.textContent = 'RE-DOWNLOAD ↓';
  } else if (job.status === 'failed') {
    action = document.createElement('button');
    action.type = 'button';
    action.className = 'btn-redownload';
    action.textContent = 'RETRY ↓';
    action.addEventListener('click', () => {
      selectFormat(job.format);
      submitJob(job.url, job.format);
    });
  } else {
    action = document.createElement('button');
    action.type = 'button';
    action.className = 'btn-redownload';
    action.textContent = 'LIHAT →';
    action.addEventListener('click', () => resumeJob(job));
  }

  row.append(number, info, status, action);
  return row;
}

async function renderHistory() {
  const list = $('#historyList');
  const empty = $('#historyEmpty');
  $('#historyMeta').textContent = 'MEMUAT RIWAYAT…';
  $('#clearAllBtn').hidden = true;

  let jobs;
  try {
    jobs = await api('/api/jobs');
  } catch (error) {
    if (error.status === 401) return;
    list.replaceChildren();
    empty.hidden = false;
    empty.textContent = 'Gagal memuat riwayat dari server. Coba lagi nanti.';
    $('#historyMeta').textContent = 'SERVER TIDAK TERJANGKAU';
    return;
  }

  const visible = jobs.filter((job) => job.status !== 'cancelled');
  empty.hidden = visible.length > 0;
  empty.textContent = 'Belum ada unduhan. Tempel tautan pertamamu di HOME.';
  list.replaceChildren();
  visible.forEach((job, index) => list.appendChild(historyRow(job, index)));

  const completed = visible.filter((job) => job.status === 'completed');
  const totalBytes = completed.reduce((sum, job) => sum + (Number(job.size_bytes) || 0), 0);
  $('#historyMeta').textContent = `${completed.length} FILES • TOTAL ${formatSize(totalBytes)}`;
  $('#clearAllBtn').hidden = !visible.some((job) => !['queued', 'running'].includes(job.status));
}

$('#clearAllBtn').addEventListener('click', async () => {
  if (!window.confirm('Hapus semua riwayat dan file dari server?')) return;
  const button = $('#clearAllBtn');
  button.disabled = true;
  try {
    await api('/api/jobs', { method: 'DELETE' });
    await renderHistory();
  } catch (error) {
    if (error.status === 401) return;
    window.alert(error.message);
  } finally {
    button.disabled = false;
  }
});

// ------------------------------------------------------------------------ auth
$('#loginForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const username = $('#loginUsername').value.trim();
  const password = $('#loginPassword').value;
  const errorElement = $('#loginError');
  errorElement.hidden = true;

  if (!username || !password) {
    errorElement.textContent = '✕ USERNAME DAN PASSWORD WAJIB DIISI.';
    errorElement.hidden = false;
    return;
  }

  const button = $('#loginForm .btn-download');
  button.disabled = true;
  button.textContent = 'SIGNING IN…';
  try {
    const me = await api('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
      skipAuthRedirect: true,
    });
    $('#loginPassword').value = '';
    setAuthenticated(me.username);
  } catch (error) {
    errorElement.textContent = `✕ ${error.message}`;
    errorElement.hidden = false;
    $('#loginPassword').select();
  } finally {
    button.disabled = false;
    button.textContent = 'SIGN IN →';
  }
});

$('#signOutBtn').addEventListener('click', async () => {
  try {
    await api('/api/auth/logout', { method: 'POST', skipAuthRedirect: true });
  } catch (error) {
    // Sign out locally even when the request cannot reach the server.
  }
  setSignedOut();
});

function setUserMessage(text, ok = false) {
  const element = $('#userFormMessage');
  element.textContent = text || '';
  element.hidden = !text;
  element.classList.toggle('inline-error', !ok);
  element.classList.toggle('inline-ok', ok);
}

function userRow(user, index) {
  const row = document.createElement('div');
  row.className = 'user-row';

  const number = document.createElement('p');
  number.className = 'index';
  number.textContent = String(index + 1).padStart(2, '0');

  const info = document.createElement('div');
  const title = document.createElement('h3');
  title.textContent = user.username;
  const meta = document.createElement('p');
  meta.className = 'meta';
  meta.textContent = `DIBUAT ${formatDate(user.created_at)} • OLEH ${String(
    user.created_by || '—'
  ).toUpperCase()}`;
  info.append(title, meta);

  const status = document.createElement('span');
  status.className = 'status';
  status.textContent = 'ACTIVE';

  row.append(number, info, status);
  return row;
}

async function renderUsers() {
  const list = $('#usersList');
  const meta = $('#usersMeta');
  meta.textContent = 'MEMUAT USERS…';

  let users;
  try {
    users = await api('/api/auth/users');
  } catch (error) {
    if (error.status === 401) return;
    list.replaceChildren();
    meta.textContent = 'GAGAL MEMUAT USERS';
    setUserMessage(`✕ ${error.message}`);
    return;
  }

  list.replaceChildren();
  users.forEach((user, index) => list.appendChild(userRow(user, index)));
  meta.textContent = `${users.length} USER${users.length === 1 ? '' : 'S'}`;
}

$('#addUserForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const username = $('#newUsername').value.trim();
  const password = $('#newPassword').value;
  setUserMessage('');

  if (!username || !password) {
    setUserMessage('✕ USERNAME DAN PASSWORD WAJIB DIISI.');
    return;
  }

  const button = $('#addUserForm .btn-download');
  button.disabled = true;
  button.textContent = 'ADDING…';
  try {
    const user = await api('/api/auth/users', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    $('#addUserForm').reset();
    setUserMessage(`✓ USER "${user.username}" DITAMBAHKAN.`, true);
    await renderUsers();
  } catch (error) {
    if (error.status === 401) return;
    setUserMessage(`✕ ${error.message}`);
  } finally {
    button.disabled = false;
    button.textContent = 'ADD USER +';
  }
});

(async function bootstrapAuth() {
  try {
    const me = await api('/api/auth/me', { skipAuthRedirect: true });
    setAuthenticated(me.username);
  } catch (error) {
    setSignedOut();
  }
})();
