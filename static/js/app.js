// ══════════════════════════════════════════════════════════════
// STĀVOKLIS
// ══════════════════════════════════════════════════════════════
const S = {
  token: null,
  userEmail: null,
  currentQuiz: null,

  // saimnieks
  hostSessionId: null,
  hostEventSource: null,
  hostCurrentQ: null,
  hostTimerInterval: null,

  // spēlētājs
  playerToken: null,
  playerSessionId: null,
  playerEventSource: null,
  playerScore: 0,
  playerCurrentQId: null,
  playerTimerInterval: null,

  // gaidāmā pievienošanās
  pendingSessionId: null,
  pendingQuizTitle: null,
};

// ══════════════════════════════════════════════════════════════
// PALAIŠANA
// ══════════════════════════════════════════════════════════════
window.addEventListener('DOMContentLoaded', () => {
  const saved = sessionStorage.getItem('qb_token');
  const email = sessionStorage.getItem('qb_email');
  if (saved) {
    S.token = saved;
    S.userEmail = email;
    document.getElementById('nav-email').textContent = email || '';
    showScreen('screen-dashboard');
    loadDashboard();
  } else {
    showScreen('screen-auth');
  }
});

// ══════════════════════════════════════════════════════════════
// EKRĀNU PĀRSLĒGŠANA
// ══════════════════════════════════════════════════════════════
function showScreen(id) {
  document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
  document.getElementById(id).classList.add('active');
}

// ══════════════════════════════════════════════════════════════
// API
// ══════════════════════════════════════════════════════════════

/** API statusa koda latvisks nosaukums (DB vērtību API nosaukumi). */
function statusaTeksts(kods) {
  const k = {
    MELNRAKSTS: 'Melnraksts',
    PUBLICETS: 'Publicēts',
    GAIDA: 'Gaida',
    NOTIEK: 'Notiek',
    PABEIGTS: 'Pabeigts',
    DRAFT: 'Melnraksts',
    PUBLISHED: 'Publicēts',
    WAITING: 'Gaida',
    ACTIVE: 'Notiek',
    FINISHED: 'Pabeigts',
  };
  return k[kods] || kods;
}
function jautajumaTipaTeksts(tips) {
  const t = { SINGLE_CHOICE: 'Viena atbilde', TRUE_FALSE: 'Patiess / Nepatiess' };
  return t[tips] || tips;
}
async function api(method, path, body, token) {
  const headers = {'Content-Type': 'application/json'};
  if (token || S.token) headers['Authorization'] = `Bearer ${token || S.token}`;
  const res = await fetch('/api/v1' + path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.zinojums || data.message || 'Kļūda');
    err.kludas_kods = data.kludas_kods || data.code;
    throw err;
  }
  return data;
}

// ══════════════════════════════════════════════════════════════
// PIERAKSTS
// ══════════════════════════════════════════════════════════════
function switchAuthTab(tab) {
  document.querySelectorAll('.auth-tab').forEach((t,i) => {
    t.classList.toggle('active', (i===0 && tab==='login') || (i===1 && tab==='register'));
  });
  document.getElementById('auth-form-login').classList.toggle('hidden', tab !== 'login');
  document.getElementById('auth-form-register').classList.toggle('hidden', tab !== 'register');
  document.getElementById('auth-error').classList.add('hidden');
}

function showAuthError(msg) {
  const el = document.getElementById('auth-error');
  el.textContent = msg;
  el.classList.remove('hidden');
}

async function doLogin() {
  const email = document.getElementById('login-email').value.trim();
  const password = document.getElementById('login-password').value;
  try {
    const data = await api('POST', '/auth/login', {epasts: email, parole: password});
    setAuth(data.piekļuves_zetons, data.lietotajs.epasts);
  } catch(e) {
    showAuthError(e.message || 'Pierakstīšanās neizdevās');
  }
}

async function doRegister() {
  const email = document.getElementById('reg-email').value.trim();
  const password = document.getElementById('reg-password').value;
  try {
    const data = await api('POST', '/auth/register', {epasts: email, parole: password});
    setAuth(data.piekļuves_zetons, data.lietotajs.epasts);
  } catch(e) {
    showAuthError(e.message || 'Reģistrācija neizdevās');
  }
}

function setAuth(token, email) {
  S.token = token;
  S.userEmail = email;
  sessionStorage.setItem('qb_token', token);
  sessionStorage.setItem('qb_email', email);
  document.getElementById('nav-email').textContent = email;
  showScreen('screen-dashboard');
  loadDashboard();
}

function doLogout() {
  S.token = null;
  S.userEmail = null;
  sessionStorage.clear();
  showScreen('screen-auth');
}

// ══════════════════════════════════════════════════════════════
// PANELIS
// ══════════════════════════════════════════════════════════════
async function loadDashboard() {
  const grid = document.getElementById('quiz-grid');
  grid.innerHTML = '<div class="loading-overlay"><div class="spinner"></div></div>';
  try {
    const quizzes = await api('GET', '/quizzes');
    renderDashboard(quizzes);
  } catch(e) {
    grid.innerHTML = `<p class="text-muted text-sm">Neizdevās ielādēt viktorīnas.</p>`;
  }
}

function renderDashboard(quizzes) {
  const grid = document.getElementById('quiz-grid');
  if (!quizzes.length) {
    grid.innerHTML = `
      <div class="empty-state">
        <div class="icon">🧩</div>
        <p>Vēl nav nevienas viktorīnas. Izveido pirmo!</p>
      </div>`;
    return;
  }
  grid.innerHTML = quizzes.map(q => `
    <div class="card card-hover quiz-card" onclick="openEditor('${q.id}')">
      <div class="quiz-card-title">${esc(q.nosaukums)}</div>
      <div style="margin-top:6px;">
        <span class="badge badge-${q.statuss.toLowerCase()}">${statusaTeksts(q.statuss)}</span>
      </div>
      <div class="quiz-card-footer">
        <span class="text-xs text-muted text-mono">${q.skaits?.jautajumi ?? 0} jautājumi</span>
        <div class="flex gap-2">
          <button class="btn btn-ghost btn-sm" onclick="event.stopPropagation();confirmDeleteQuiz('${q.id}','${esc(q.nosaukums)}')">Dzēst</button>
          <button class="btn btn-primary btn-sm" onclick="event.stopPropagation();openEditor('${q.id}')">Labot →</button>
        </div>
      </div>
    </div>
  `).join('');
}

function openCreateQuizModal() {
  document.getElementById('new-quiz-title').value = '';
  openModal('modal-create-quiz');
}

async function doCreateQuiz() {
  const title = document.getElementById('new-quiz-title').value.trim();
  if (!title) return;
  try {
    const quiz = await api('POST', '/quizzes', {nosaukums: title});
    closeModal('modal-create-quiz');
    openEditor(quiz.id);
  } catch(e) {
    document.getElementById('create-quiz-error').textContent = e.message || 'Kļūda';
    document.getElementById('create-quiz-error').classList.remove('hidden');
  }
}

async function confirmDeleteQuiz(id, title) {
  if (!confirm(`Dzēst „${title}”?`)) return;
  try {
    await api('DELETE', `/quizzes/${id}`);
    loadDashboard();
  } catch(e) { alert('Neizdevās dzēst'); }
}

// ══════════════════════════════════════════════════════════════
// REDAKTORS
// ══════════════════════════════════════════════════════════════
let editingQuestionId = null;

async function openEditor(qid) {
  try {
    const quiz = await api('GET', `/quizzes/${qid}`);
    S.currentQuiz = quiz;
    renderEditor(quiz);
    showScreen('screen-editor');
  } catch(e) { alert('Neizdevās ielādēt viktorīnu'); }
}

function renderEditor(quiz) {
  document.getElementById('editor-title').textContent = quiz.nosaukums;
  const badge = document.getElementById('editor-badge');
  badge.textContent = statusaTeksts(quiz.statuss);
  badge.className = `badge badge-${quiz.statuss.toLowerCase()}`;
  document.getElementById('editor-status-text').textContent =
    quiz.statuss === 'PUBLICETS' ? 'Publicēta — var vadīt spēli' : 'Melnraksts — spēlētājiem neredzams';

  const publishBtn = document.getElementById('btn-publish');
  publishBtn.textContent = quiz.statuss === 'PUBLICETS' ? 'Atcelt publicēšanu' : 'Publicēt';
  publishBtn.className = quiz.statuss === 'PUBLICETS' ? 'btn btn-ghost btn-sm' : 'btn btn-success btn-sm';

  const ql = document.getElementById('question-list');
  if (!quiz.jautajumi.length) {
    ql.innerHTML = '<p class="text-sm text-muted mb-4">Vēl nav jautājumu. Pievieno zemāk!</p>';
    return;
  }
  ql.innerHTML = quiz.jautajumi.map((q, i) => `
    <div class="question-item">
      <div class="q-number">${i+1}</div>
      <div class="q-info">
        <div class="q-text">${esc(q.teksts)}</div>
        <div class="q-meta">${jautajumaTipaTeksts(q.tips)} · ${q.laika_limits_sekundes}s · ${q.punkti} punkti · ${q.atbilzu_varianti.length} varianti</div>
      </div>
      <div class="q-actions">
        <button class="btn btn-ghost btn-sm btn-icon" onclick="openEditQuestion('${q.id}')" title="Labot">✏️</button>
        <button class="btn btn-danger btn-sm btn-icon" onclick="deleteQuestion('${q.id}')" title="Dzēst">🗑</button>
      </div>
    </div>
  `).join('');
}

function editQuizMeta() {
  document.getElementById('meta-title').value = S.currentQuiz.nosaukums;
  document.getElementById('meta-desc').value = S.currentQuiz.apraksts || '';
  openModal('modal-edit-meta');
}

async function doSaveMeta() {
  const title = document.getElementById('meta-title').value.trim();
  const description = document.getElementById('meta-desc').value.trim();
  if (!title) return;
  try {
    const quiz = await api('PATCH', `/quizzes/${S.currentQuiz.id}`, {nosaukums: title, apraksts: description});
    S.currentQuiz = {...S.currentQuiz, ...quiz};
    closeModal('modal-edit-meta');
    renderEditor(S.currentQuiz);
  } catch(e) {}
}

async function togglePublish() {
  const newStatus = S.currentQuiz.statuss === 'PUBLICETS' ? 'MELNRAKSTS' : 'PUBLICETS';
  try {
    const quiz = await api('PATCH', `/quizzes/${S.currentQuiz.id}`, {statuss: newStatus});
    S.currentQuiz = {...S.currentQuiz, ...quiz};
    renderEditor(S.currentQuiz);
  } catch(e) { alert(e.message || 'Kļūda'); }
}

// ── Jautājuma modālais logs ──
function openQuestionModal() {
  editingQuestionId = null;
  document.getElementById('q-modal-title').textContent = 'Jauns jautājums';
  document.getElementById('q-text').value = '';
  document.getElementById('q-type').value = 'SINGLE_CHOICE';
  document.getElementById('q-time').value = '20';
  document.getElementById('q-points').value = '1000';
  document.getElementById('q-modal-error').classList.add('hidden');
  renderOptionFields();
  openModal('modal-question');
}

function openEditQuestion(qid) {
  const q = S.currentQuiz.jautajumi.find(x => x.id === qid);
  if (!q) return;
  editingQuestionId = qid;
  document.getElementById('q-modal-title').textContent = 'Labot jautājumu';
  document.getElementById('q-text').value = q.teksts;
  document.getElementById('q-type').value = q.tips;
  document.getElementById('q-time').value = q.laika_limits_sekundes;
  document.getElementById('q-points').value = q.punkti;
  document.getElementById('q-modal-error').classList.add('hidden');
  renderOptionFields(q.atbilzu_varianti);
  openModal('modal-question');
}

function renderOptionFields(existing) {
  const type = document.getElementById('q-type').value;
  const list = document.getElementById('options-list');
  document.getElementById('btn-add-option').style.display = type === 'TRUE_FALSE' ? 'none' : '';

  if (type === 'TRUE_FALSE') {
    list.innerHTML = `
      ${optionRow('Patiess', existing ? (existing[0]?.pareizi ?? existing[0]?.isCorrect) : true, true)}
      ${optionRow('Nepatiess', existing ? (existing[1]?.pareizi ?? existing[1]?.isCorrect) : false, true)}
    `;
  } else {
    const opts = existing || [{teksts:'',pareizi:true},{teksts:'',pareizi:false}];
    list.innerHTML = opts.map(o => optionRow(o.teksts ?? o.text, o.pareizi ?? o.isCorrect, false)).join('');
  }
}

function startHostTimer(seconds) {
  console.log(`[HOST TIMER] Starting timer for ${seconds}s. Session: ${S.hostSessionId}`);
  let remaining = seconds;
  const fill = document.getElementById('host-timer-fill');
  if (fill) fill.style.width = '100%';

  clearInterval(S.hostTimerInterval);
  S.hostTimerInterval = setInterval(async () => {
    remaining--;

    if (remaining % 5 === 0 || remaining <= 3) {
      console.log(`[HOST TIMER] T-minus: ${remaining}s`);
    }

    if (fill) {
      fill.style.width = Math.max(0, (remaining / seconds) * 100) + '%';
    }

    if (remaining <= 0) {
      console.warn('[HOST TIMER] TIME IS UP — auto-ending question.');
      clearInterval(S.hostTimerInterval);
      S.hostTimerInterval = null;

      const sessionId = S.hostSessionId;
      if (!sessionId) {
        console.error('[HOST TIMER] Auto-end FAILED: S.hostSessionId is null/undefined.');
        return;
      }

      console.log(`[HOST TIMER] POST /api/v1/sessions/${sessionId}/end-question`);
      try {
        const resp = await fetch(`/api/v1/sessions/${sessionId}/end-question`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + S.token,
          },
        });
        if (resp.ok) {
          const body = await resp.json();
          console.log('[HOST TIMER] Auto-end OK. Server response:', body);
        } else {
          const errBody = await resp.json().catch(() => ({}));
          console.error('[HOST TIMER] Auto-end rejected by server:', resp.status, errBody);
        }
      } catch (err) {
        console.error('[HOST TIMER] Network error on auto-end:', err);
      }
    }
  }, 1000);
}

async function autoEndQuestion() {
  const sessionId = S.currentSession.id;
  // Call your existing endpoint that handles ending the question
  await apiFetch(`/api/v1/game/sessions/${sessionId}/next`, { method: 'POST' });
}

function optionRow(text, correct, readonlyText) {
  return `
    <div class="option-row">
      <div class="option-correct ${correct?'checked':''}" onclick="toggleCorrect(this)">
        ${correct?'✓':''}
      </div>
      <input type="text" value="${esc(text)}" placeholder="Atbildes teksts…" ${readonlyText?'readonly':''} style="${readonlyText?'color:var(--teksts2)':''}"/>
      ${readonlyText?'':'<button class="option-remove" onclick="this.closest(\'.option-row\').remove()">×</button>'}
    </div>`;
}

function addOptionField() {
  const list = document.getElementById('options-list');
  const div = document.createElement('div');
  div.innerHTML = optionRow('', false, false);
  list.appendChild(div.firstElementChild);
}

function toggleCorrect(el) {
  const type = document.getElementById('q-type').value;
  if (type === 'SINGLE_CHOICE') {
    document.querySelectorAll('#options-list .option-correct').forEach(c => {
      c.classList.remove('checked');
      c.textContent = '';
    });
  }
  el.classList.toggle('checked');
  el.textContent = el.classList.contains('checked') ? '✓' : '';
}

async function doSaveQuestion() {
  const text = document.getElementById('q-text').value.trim();
  if (!text) { showQError('Jautājuma teksts ir obligāts'); return; }
  const type = document.getElementById('q-type').value;
  const timeLimitSeconds = parseInt(document.getElementById('q-time').value) || 20;
  const points = parseInt(document.getElementById('q-points').value) || 1000;
  const rows = document.querySelectorAll('#options-list .option-row');
  const atbilzu_varianti = Array.from(rows).map(row => ({
    teksts: row.querySelector('input[type=text]').value.trim(),
    pareizi: row.querySelector('.option-correct').classList.contains('checked'),
  })).filter(o => o.teksts);
  if (!atbilzu_varianti.length) { showQError('Pievieno vismaz vienu atbildes variantu'); return; }
  if (!atbilzu_varianti.some(o => o.pareizi)) { showQError('Vismaz vienam jābūt atzīmētam kā pareizam'); return; }
  try {
    if (editingQuestionId) {
      await api('PATCH', `/questions/${editingQuestionId}`, {teksts: text, laika_limits_sekundes: timeLimitSeconds, punkti: points, atbilzu_varianti});
    } else {
      await api('POST', `/quizzes/${S.currentQuiz.id}/questions`, {teksts: text, tips: type, laika_limits_sekundes: timeLimitSeconds, punkti: points, atbilzu_varianti});
    }
    const quiz = await api('GET', `/quizzes/${S.currentQuiz.id}`);
    S.currentQuiz = quiz;
    renderEditor(quiz);
    closeModal('modal-question');
  } catch(e) { showQError(e.message || 'Neizdevās saglabāt jautājumu'); }
}

function showQError(msg) {
  const el = document.getElementById('q-modal-error');
  el.textContent = msg;
  el.classList.remove('hidden');
}

async function deleteQuestion(qid) {
  if (!confirm('Dzēst šo jautājumu?')) return;
  try {
    await api('DELETE', `/questions/${qid}`);
    const quiz = await api('GET', `/quizzes/${S.currentQuiz.id}`);
    S.currentQuiz = quiz;
    renderEditor(quiz);
  } catch(e) {}
}

// ══════════════════════════════════════════════════════════════
// SAIMNIEKS
// ══════════════════════════════════════════════════════════════
async function startHostSession() {
  if (S.currentQuiz.statuss !== 'PUBLICETS') {
    alert('Vispirms publicē viktorīnu.');
    return;
  }
  if (!S.currentQuiz.jautajumi.length) {
    alert('Vispirms pievieno jautājumus.');
    return;
  }
  try {
    const data = await api('POST', '/sessions', {viktorinas_id: S.currentQuiz.id});
    S.hostSessionId = data.sesijas_id;
    document.getElementById('host-pin').textContent = data.pina_kods;
    document.getElementById('host-status-badge').className = 'badge badge-gaida';
    document.getElementById('host-status-badge').textContent = 'Gaida';
    resetHostUI();
    showScreen('screen-host');
    connectHostSSE(data.sesijas_id);
  } catch(e) { alert(e.message || 'Neizdevās sākt sesiju'); }
}

function resetHostUI() {
  document.getElementById('host-lobby').classList.remove('hidden');
  document.getElementById('host-question').classList.add('hidden');
  document.getElementById('host-leaderboard-panel').classList.add('hidden');
  document.getElementById('host-chips').innerHTML = '<span class="text-sm text-muted">Gaida, kamēr spēlētāji pievienojas…</span>';
  document.getElementById('participant-count').textContent = '(0)';
  document.getElementById('btn-start-game').disabled = true;
}

function connectHostSSE(sid) {
  console.log(`[HOST SSE] Connecting to session ${sid}...`);
  if (S.hostEventSource) S.hostEventSource.close();
  const es = new EventSource(`/api/v1/sessions/${sid}/events`);
  S.hostEventSource = es;
  es.onopen = () => console.log('[HOST SSE] Connection opened.');
  es.onmessage = (e) => {
    console.log('[HOST SSE] Raw message:', e.data);
    let msg;
    try { msg = JSON.parse(e.data); } catch(err) { console.error('[HOST SSE] Parse error:', err); return; }
    handleHostEvent(msg.notikums || msg.event, msg.dati || msg.data);
  };
  es.onerror = (err) => console.error('[HOST SSE] Connection error:', err);
}

function handleHostEvent(event, data) {
  console.log(`[HOST SSE] Event: "${event}"`, data);
  switch(event) {
    case 'sesijas_stavoklis':
    case 'session:state':
      renderHostParticipants(data.dalibnieki || data.participants || []);
      break;
    case 'gaiditava_dalibnieki':
    case 'lobby:participant_list':
      renderHostParticipants(data.dalibnieki || data.participants || []);
      break;
    case 'spele_jautajums_sakas':
    case 'game:question_started':
      console.log(`[HOST SSE] Question started: idx=${data.jautajuma_indekss ?? data.questionIndex} id=${data.id} timeLimit=${data.laika_limits_sekundes ?? data.timeLimitSeconds}s`);
      S.hostCurrentQ = data;
      showHostQuestion(data);
      break;
    case 'spele_jautajums_beidzas':
    case 'game:question_ended':
      console.log('[HOST SSE] Question ended — showing results.');
      showHostResults(data);
      break;
    case 'spele_lideru_tabula':
    case 'game:leaderboard':
      console.log('[HOST SSE] Leaderboard update:', data.lideru_tabula || data.leaderboard);
      renderHostLeaderboard(data.lideru_tabula || data.leaderboard);
      break;
    case 'spele_beigusies':
    case 'game:ended':
      console.log('[HOST SSE] Game ended.');
      showHostFinal(data.lideru_tabula || data.leaderboard);
      break;
    default:
      console.log(`[HOST SSE] Unhandled event: "${event}"`);
  }
}

function renderHostParticipants(list) {
  const chips = document.getElementById('host-chips');
  const count = document.getElementById('participant-count');
  count.textContent = `(${list.length})`;
  document.getElementById('btn-start-game').disabled = list.length === 0;
  if (!list.length) {
    chips.innerHTML = '<span class="text-sm text-muted">Gaida, kamēr spēlētāji pievienojas…</span>';
    return;
  }
  chips.innerHTML = list.map(p => `<div class="chip">${esc(p.segvards || p.nickname)}</div>`).join('');
}

async function hostStartGame() {
  try {
    await api('POST', `/sessions/${S.hostSessionId}/start`);
    document.getElementById('host-status-badge').className = 'badge badge-notiek';
    document.getElementById('host-status-badge').textContent = 'Notiek';
    document.getElementById('host-lobby').classList.add('hidden');
  } catch(e) { alert(e.message || 'Neizdevās sākt spēli'); }
}

function showHostQuestion(data) {
  const idx = data.jautajuma_indekss ?? data.questionIndex;
  const total = data.jautajumu_kopskaits ?? data.totalQuestions;
  const teksts = data.teksts ?? data.text;
  const laiks = data.laika_limits_sekundes ?? data.timeLimitSeconds;
  const arPareizo = data.atbilzu_varianti_ar_pareizo || data.answerOptionsWithCorrect || [];

  document.getElementById('host-lobby').classList.add('hidden');
  document.getElementById('host-leaderboard-panel').classList.add('hidden');
  document.getElementById('host-question').classList.remove('hidden');
  document.getElementById('btn-end-q').classList.remove('hidden');
  document.getElementById('btn-next-q').classList.add('hidden');
  document.getElementById('btn-finish-game').classList.add('hidden');
  document.getElementById('host-q-stats').style.display = 'none';

  document.getElementById('host-q-progress').textContent =
    `Jautājums ${idx + 1} no ${total}`;
  document.getElementById('host-q-text').textContent = teksts;

  const labels = ['A','B','C','D'];
  document.getElementById('host-q-options').innerHTML =
    arPareizo.map((o,i) => `
      <div class="answer-option ${(o.pareizi ?? o.isCorrect)?'correct':''}">
        <div class="opt-label">${labels[i]||i+1}</div>
        ${esc(o.teksts ?? o.text)}
      </div>
    `).join('');

  // Timer — delegate to startHostTimer() so expiry triggers auto end-question
  startHostTimer(laiks);
}

function showHostResults(data) {
  clearInterval(S.hostTimerInterval);
  document.getElementById('host-timer-fill').style.width = '0%';
  document.getElementById('btn-end-q').classList.add('hidden');

  const h = S.hostCurrentQ;
  const qIdx = h ? (h.jautajuma_indekss ?? h.questionIndex) : 0;
  const qTot = h ? (h.jautajumu_kopskaits ?? h.totalQuestions) : 0;
  const isLast = h && qIdx + 1 >= qTot;
  if (isLast) {
    document.getElementById('btn-finish-game').classList.remove('hidden');
  } else {
    document.getElementById('btn-next-q').classList.remove('hidden');
  }

  // Stats
  const statsEl = document.getElementById('host-q-stats');
  statsEl.style.display = 'flex';
  const labels = ['A','B','C','D'];
  const st = data.statistika || data.stats || {};
  const total = st.kopat_dalibnieki || st.totalParticipants || 1;
  const byOpt = st.pec_opcijas || st.byOption || {};
  const pareizas = data.pareizo_opciju_id || data.correctOptionIds || [];
  const opts = data.atbilzu_varianti || data.answerOptions || [];
  statsEl.innerHTML = opts.map((o,i) => {
    const oid = o.id;
    const count = byOpt[oid] || 0;
    const pct = Math.round(count / total * 100);
    const isCorrect = pareizas.includes(oid);
    return `
      <div class="stat-option-bar">
        <span class="stat-label">${labels[i]||i+1}</span>
        <div class="stat-fill-wrap">
          <div class="stat-fill ${isCorrect?'correct':''}" style="width:${pct}%"></div>
        </div>
        <span class="text-xs text-mono text-muted">${count}</span>
      </div>`;
  }).join('');
}

function renderHostLeaderboard(lb) {
  document.getElementById('host-leaderboard-panel').classList.remove('hidden');
  document.getElementById('host-leaderboard').innerHTML = lb.slice(0,10).map(p => {
    const vieta = p.vieta ?? p.rank;
    const rc = vieta===1?'gold':vieta===2?'silver':vieta===3?'bronze':'';
    const seg = p.segvards ?? p.nickname;
    const punkti = p.punkti ?? p.score;
    return `
      <div class="lb-row">
        <div class="lb-rank ${rc}">#${vieta}</div>
        <div class="lb-name">${esc(seg)}</div>
        <div class="lb-score">${punkti.toLocaleString()}</div>
      </div>`;
  }).join('');
}

function showHostFinal(lb) {
  clearInterval(S.hostTimerInterval);
  document.getElementById('host-question').classList.add('hidden');
  document.getElementById('host-status-badge').className = 'badge badge-pabeigts';
  document.getElementById('host-status-badge').textContent = 'Pabeigts';
  renderHostLeaderboard(lb);
}

async function hostEndQuestion() {
  try { await api('POST', `/sessions/${S.hostSessionId}/end-question`); }
  catch(e) {}
}

async function hostNextQuestion() {
  document.getElementById('host-leaderboard-panel').classList.add('hidden');
  try { await api('POST', `/sessions/${S.hostSessionId}/next-question`); }
  catch(e) {}
}

async function hostEndGame() {
  try { await api('POST', `/sessions/${S.hostSessionId}/end-game`); }
  catch(e) {}
}

function endAndLeave() {
  if (S.hostEventSource) { S.hostEventSource.close(); S.hostEventSource = null; }
  clearInterval(S.hostTimerInterval);
  showScreen('screen-dashboard');
  loadDashboard();
}

// ══════════════════════════════════════════════════════════════
// SPĒLĒTĀJA PLŪSMA
// ══════════════════════════════════════════════════════════════
async function doJoinPin() {
  const pin = document.getElementById('join-pin').value.trim();
  const errEl = document.getElementById('join-error');
  errEl.classList.add('hidden');
  if (pin.length < 6) { errEl.textContent='Ievadi 6 ciparu PIN'; errEl.classList.remove('hidden'); return; }
  try {
    const data = await api('POST', '/join', {pina_kods: pin});
    S.pendingSessionId = data.sesijas_id;
    S.pendingQuizTitle = data.viktorinas_nosaukums;
    document.getElementById('nick-quiz-title-modal').textContent = data.viktorinas_nosaukums;
    document.getElementById('nickname-input').value = '';
    document.getElementById('nick-error').classList.add('hidden');
    openModal('modal-nickname');
  } catch(e) {
    errEl.textContent = e.message || 'Spēle nav atrasta';
    errEl.classList.remove('hidden');
  }
}

async function doIdentify() {
  const nickname = document.getElementById('nickname-input').value.trim();
  const errEl = document.getElementById('nick-error');
  errEl.classList.add('hidden');
  if (!nickname) { errEl.textContent='Ievadi segvārdu'; errEl.classList.remove('hidden'); return; }
  try {
    const data = await api('POST', `/join/${S.pendingSessionId}/identify`, {segvards: nickname});
    S.playerToken = data.dalibnieka_zetons;
    S.playerSessionId = S.pendingSessionId;
    S.playerScore = 0;
    S.playerCurrentQId = null;
    closeModal('modal-nickname');
    document.getElementById('lobby-quiz-title').textContent = S.pendingQuizTitle;
    document.getElementById('lobby-me').textContent = nickname;
    document.getElementById('lobby-players').innerHTML = '';
    document.getElementById('lobby-count').textContent = '1';
    showScreen('screen-lobby');
    connectPlayerSSE(S.pendingSessionId);
  } catch(e) {
    errEl.textContent = e.message || 'Neizdevās pievienoties';
    errEl.classList.remove('hidden');
  }
}

function connectPlayerSSE(sid) {
  if (S.playerEventSource) S.playerEventSource.close();
  const es = new EventSource(`/api/v1/sessions/${sid}/events`);
  S.playerEventSource = es;
 es.onmessage = (e) => {
    console.log("New Event:", e.data); // Add this
    try { 
      let msg = JSON.parse(e.data); 
      handlePlayerEvent(msg.notikums || msg.event, msg.dati || msg.data);
    } catch (err) { 
      console.error("Parse error:", err); 
    }
  };
  es.onerror = (err) => {
    console.error("SSE Connection Failed:", err); // Add this
  };
}

function handlePlayerEvent(event, data) {
  console.log(`[PLAYER SSE] Event received: "${event}"`, data);
  switch(event) {
    case 'gaiditava_dalibnieki':
    case 'lobby:participant_list':
      document.getElementById('lobby-players').innerHTML =
        (data.dalibnieki || data.participants).map(p => `<div class="chip">${esc(p.segvards || p.nickname)}</div>`).join('');
      document.getElementById('lobby-count').textContent = String((data.dalibnieki || data.participants).length);
      break;
    case 'spele_sakusies':
    case 'game:started':
      console.log('[PLAYER SSE] Game started — waiting for question_started.');
      break;
    case 'spele_jautajums_sakas':
    case 'game:question_started':
      console.log(`[PLAYER SSE] New question: id=${data.id} timeLimit=${data.laika_limits_sekundes ?? data.timeLimitSeconds}s`);
      showPlayerQuestion(data);
      break;
    case 'atbilde_apstiprinata':
    case 'answer:acknowledged': {
      const pid = data.dalibnieka_id ?? data.participantId;
      console.log(`[PLAYER SSE] Answer acknowledged: participantId=${pid} isCorrect=${data.pareizi ?? data.isCorrect} pts=${data.iegutie_punkti ?? data.pointsEarned}`);
      if (pid === getPlayerIdFromToken()) {
        showPlayerResult(data);
      }
      break;
    }
    case 'spele_jautajums_beidzas':
    case 'game:question_ended':
      console.log('[PLAYER SSE] Question ended — revealing correct answers.');
      clearInterval(S.playerTimerInterval);
      showPlayerAnswerReveal(data);
      break;
    case 'spele_lideru_tabula':
    case 'game:leaderboard':
      console.log('[PLAYER SSE] Mid-game leaderboard received:', data.lideru_tabula || data.leaderboard);
      renderPlayerMidLeaderboard(data.lideru_tabula || data.leaderboard);
      break;
    case 'spele_beigusies':
    case 'game:ended':
      console.log('[PLAYER SSE] Game ended. Final leaderboard:', data.lideru_tabula || data.leaderboard);
      showFinalScreen(data.lideru_tabula || data.leaderboard);
      break;
    default:
      console.log(`[PLAYER SSE] Unhandled event: "${event}"`);
  }
}

function getPlayerIdFromToken() {
  try {
    const payload = JSON.parse(atob(S.playerToken.split('.')[1]));
    return payload.dalibnieka_id || payload.participant_id;
  } catch { return null; }
}

function showPlayerQuestion(data) {
  S.playerCurrentQId = data.id;
  showScreen('screen-player-game');
  document.getElementById('player-score').textContent = S.playerScore.toLocaleString();
  document.getElementById('player-question-area').classList.remove('hidden');
  document.getElementById('player-result-area').classList.add('hidden');
  document.getElementById('player-mid-leaderboard-panel').classList.add('hidden');
  const teksts = data.teksts ?? data.text;
  const laiks = data.laika_limits_sekundes ?? data.timeLimitSeconds;
  const varianti = data.atbilzu_varianti || data.answerOptions;
  document.getElementById('player-q-text').textContent = teksts;

  const labels = ['A','B','C','D'];
  const opts = document.getElementById('player-q-options');
  opts.innerHTML = varianti.map((o,i) => `
    <button class="player-option" onclick="submitAnswer('${o.id}', this)">
      <div class="opt-label">${labels[i]||i+1}</div>
      ${esc(o.teksts ?? o.text)}
    </button>
  `).join('');

  // Timer
  clearInterval(S.playerTimerInterval);
  const fill = document.getElementById('player-timer-fill');
  const total = laiks * 1000;
  const start = Date.now();
  fill.style.width = '100%';
  console.log(`[PLAYER TIMER] Starting ${laiks}s timer for question ${data.id}`);
  S.playerTimerInterval = setInterval(() => {
    const elapsed = Date.now() - start;
    const pct = Math.max(0, 100 - (elapsed / total * 100));
    fill.style.width = pct + '%';
    if (pct <= 0) {
      clearInterval(S.playerTimerInterval);
      console.warn('[PLAYER TIMER] TIME IS UP — registering timeout as wrong answer.');
      // Submit null option so server counts this as an unanswered (0 pts) entry
      const anyBtn = document.querySelectorAll('.player-option')[0];
      submitTimeoutAnswer();
    }
  }, 200);
}

// NEW: Render the mid-game leaderboard for the player
function renderPlayerMidLeaderboard(lb) {
  const panel = document.getElementById('player-mid-leaderboard-panel');
  if (panel) panel.classList.remove('hidden');

  const container = document.getElementById('player-mid-leaderboard');
  const myId = getPlayerIdFromToken();
  
  if (container) {
    // Show top 5 players to save space on mobile
    container.innerHTML = lb.slice(0, 5).map(p => {
      const isMe = p.id === myId;
      const vieta = p.vieta ?? p.rank;
      const rankClass = vieta===1?'gold':vieta===2?'silver':vieta===3?'bronze':'';
      const highlightStyle = isMe ? 'border: 1px solid var(--akcents); background: rgba(124,107,255,0.15);' : '';
      const seg = p.segvards ?? p.nickname;
      const punkti = p.punkti ?? p.score;
      
      return `
        <div class="lb-row" style="${highlightStyle}">
          <div class="lb-rank ${rankClass}">#${vieta}</div>
          <div class="lb-name">${esc(seg)} ${isMe ? '<span class="text-xs text-muted">(Tu)</span>' : ''}</div>
          <div class="lb-score">${punkti.toLocaleString()}</div>
        </div>`;
    }).join('');
  }
}

async function submitTimeoutAnswer() {
  // Check if player already answered (race condition: answer submitted just before timer fired)
  const btns = document.querySelectorAll('.player-option');
  const alreadyAnswered = Array.from(btns).some(b => b.disabled);
  if (alreadyAnswered) {
    console.log('[PLAYER TIMER] Timeout fired but player already answered — skipping null submit.');
    return;
  }
  console.log('[PLAYER TIMER] Submitting null answer (timeout) for question', S.playerCurrentQId);
  // Disable all buttons to show time is up
  btns.forEach(b => b.disabled = true);
  try {
    const result = await api('POST', '/answer', {opcijas_id: null}, S.playerToken);
    console.log('[PLAYER TIMER] Timeout answer accepted by server:', result);
    showPlayerResult({...result, pareizi: false, iegutie_punkti: 0});
  } catch(e) {
    // Already answered or session ended — both are fine
    console.warn('[PLAYER TIMER] Timeout submit rejected (likely already answered or session ended):', e);
  }
}

async function submitAnswer(optionId, btn) {
  console.log(`[PLAYER] Submitting answer optionId=${optionId} for question ${S.playerCurrentQId}`);
  // Disable all options immediately to prevent double-submit
  document.querySelectorAll('.player-option').forEach(b => b.disabled = true);
  btn.classList.add('selected');
  try {
    const result = await api('POST', '/answer', {opcijas_id: optionId}, S.playerToken);
    console.log('[PLAYER] Answer acknowledged by server:', result);
  } catch(e) {
    console.error('[PLAYER] Answer submission failed:', e);
  }
}

function showPlayerResult(data) {
  clearInterval(S.playerTimerInterval);
  const kopejie = data.kopejie_punkti ?? data.totalScore;
  const pareizi = data.pareizi ?? data.isCorrect;
  const iegutie = data.iegutie_punkti ?? data.pointsEarned;
  S.playerScore = kopejie;
  document.getElementById('player-score').textContent = kopejie.toLocaleString();
  document.getElementById('player-question-area').classList.add('hidden');
  document.getElementById('player-result-area').classList.remove('hidden');
  document.getElementById('result-emoji').textContent = pareizi ? '🎉' : '😬';
  const pts = document.getElementById('result-points');
  pts.textContent = pareizi ? `+${iegutie}` : 'Nepareizi';
  pts.className = `result-points ${pareizi?'correct':'incorrect'}`;
  document.getElementById('result-total').textContent = `Kopā: ${kopejie.toLocaleString()} punkti`;
}

function showPlayerAnswerReveal(data) {
  // Highlight correct answers if still on question screen
  const opts = document.querySelectorAll('.player-option');
  // Already showing result — just stay
}

function showFinalScreen(leaderboard) {
  clearInterval(S.playerTimerInterval);
  if (S.playerEventSource) { S.playerEventSource.close(); S.playerEventSource = null; }
  const lb = document.getElementById('final-leaderboard');
  lb.innerHTML = leaderboard.map(p => {
    const vieta = p.vieta ?? p.rank;
    const rankClass = vieta===1?'gold':vieta===2?'silver':vieta===3?'bronze':'';
    const seg = p.segvards ?? p.nickname;
    const punkti = p.punkti ?? p.score;
    return `
      <div class="lb-row">
        <div class="lb-rank ${rankClass}">#${vieta}</div>
        <div class="lb-name">${esc(seg)}</div>
        <div class="lb-score">${punkti.toLocaleString()}</div>
      </div>`;
  }).join('');
  showScreen('screen-final');
}

// ══════════════════════════════════════════════════════════════
// MODUĀŁU PALĪGFUNKCIJAS
// ══════════════════════════════════════════════════════════════
function openModal(id) {
  document.getElementById(id).classList.add('open');
}
function closeModal(id) {
  document.getElementById(id).classList.remove('open');
}
// Close on overlay click
document.querySelectorAll('.modal-overlay').forEach(el => {
  el.addEventListener('click', e => {
    if (e.target === el) el.classList.remove('open');
  });
});

// ══════════════════════════════════════════════════════════════
// RĪKI
// ══════════════════════════════════════════════════════════════
function esc(str) {
  return String(str||'')
    .replace(/&/g,'&amp;')
    .replace(/</g,'&lt;')
    .replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;');
}
