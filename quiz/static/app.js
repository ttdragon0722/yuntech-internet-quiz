'use strict';

const $app = document.getElementById('app');
const KEYS = 'ABCDEF';
const SETTINGS_KEY = 'quiz.settings.v1';
const DEFAULT_SETTINGS = Object.freeze({ mode: 'practice', shuffleQuestions: true, shuffleOptions: true });

let session = null;        // 進行中的作答
let pendingPractice = null; // 從錯題本／紀錄帶過來要練習的題目

// ---------- 工具 ----------
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[c]));

function shuffled(arr) {
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

function fmtDuration(sec) {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return m ? `${m} 分 ${s} 秒` : `${s} 秒`;
}

const fmtTime = (iso) => (iso ? iso.replace('T', ' ').slice(0, 16) : '');

function toast(msg, isError = false) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = `toast${isError ? ' error' : ''}`;
  el.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { el.hidden = true; }, isError ? 6000 : 2500);
}

async function api(path, options = {}) {
  let res;
  try {
    res = await fetch(`/api/${path}`, { headers: { 'Content-Type': 'application/json' }, ...options });
  } catch {
    throw new Error('連不到伺服器，請確認終端機的 python quiz/server.py 還在執行');
  }
  let body;
  try {
    body = await res.json();
  } catch {
    throw new Error(`伺服器回應格式錯誤（HTTP ${res.status}）`);
  }
  if (!body.success) throw new Error(body.error || '發生未知錯誤');
  return body.data;
}

function loadSettings() {
  try {
    return { ...DEFAULT_SETTINGS, ...JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}') };
  } catch {
    return { ...DEFAULT_SETTINGS };
  }
}

function saveSettings(settings) {
  try { localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings)); } catch { /* 無痕模式等，忽略即可 */ }
}

function showError(err) {
  $app.innerHTML = `<div class="card empty"><p>${esc(err.message)}</p><a class="btn" href="#/">回題庫</a></div>`;
}

// ---------- 建立作答 ----------
function buildSession(title, rawQuestions, settings, retake = null) {
  const ordered = settings.shuffleQuestions ? shuffled(rawQuestions) : rawQuestions;
  const questions = ordered.map((q) => {
    const opts = q.options.map((text, orig) => ({ text, orig }));
    return { ...q, display: settings.shuffleOptions ? shuffled(opts) : opts };
  });
  return {
    title,
    mode: settings.mode,
    questions,
    answers: questions.map(() => null),
    revealed: questions.map(() => false),
    idx: 0,
    startedAt: Date.now(),
    retake,
    submitting: false,
  };
}

const fromQuiz = (quiz) => quiz.questions.map((q) => ({ ...q, quizId: quiz.id, qid: q.id }));

function updateSession(patch) {
  session = { ...session, ...patch };
  renderTake();
}

function choose(displayIdx) {
  const q = session.questions[session.idx];
  const opt = q.display[displayIdx];
  if (!opt) return;
  if (session.mode === 'practice' && session.revealed[session.idx]) return;
  const answers = session.answers.map((a, i) => (i === session.idx ? opt.orig : a));
  const revealed = session.mode === 'practice'
    ? session.revealed.map((r, i) => (i === session.idx ? true : r))
    : session.revealed;
  updateSession({ answers, revealed });
}

function go(delta) {
  const idx = Math.min(Math.max(session.idx + delta, 0), session.questions.length - 1);
  if (idx !== session.idx) updateSession({ idx });
}

async function submit() {
  if (session.submitting) return;
  const unanswered = session.answers.filter((a) => a === null).length;
  if (unanswered && !confirm(`還有 ${unanswered} 題沒作答，確定要交卷嗎？`)) return;
  session = { ...session, submitting: true };
  renderTake();
  const items = session.questions.map((q, i) => ({ quizId: q.quizId, qid: q.qid, choice: session.answers[i] }));
  try {
    const attempt = await api('attempts', {
      method: 'POST',
      body: JSON.stringify({
        title: session.title,
        durationSec: Math.round((Date.now() - session.startedAt) / 1000),
        items,
      }),
    });
    session = null;
    location.hash = `#/attempt/${attempt.id}`;
  } catch (err) {
    session = { ...session, submitting: false };
    renderTake();
    toast(`儲存失敗：${err.message}`, true);
  }
}

// ---------- 作答畫面 ----------
function optionClass(q, opt, i) {
  const chosen = session.answers[i] === opt.orig;
  if (session.mode === 'practice' && session.revealed[i]) {
    if (opt.orig === q.answer) return 'correct';
    if (chosen) return 'wrong';
    return '';
  }
  return chosen ? 'chosen' : '';
}

function renderFeedback(q, i) {
  if (session.mode !== 'practice' || !session.revealed[i]) return '';
  const ok = session.answers[i] === q.answer;
  const correctKey = KEYS[q.display.findIndex((o) => o.orig === q.answer)];
  return `<div class="explain ${ok ? 'ok' : 'bad'}">
    <strong>${ok ? '答對了！' : `答錯了，正解是 ${correctKey}`}</strong>
    ${q.explanation ? `\n${esc(q.explanation)}` : ''}</div>`;
}

function renderNav(i, last) {
  const answered = session.answers.filter((a) => a !== null).length;
  const prev = `<button data-act="prev" ${i === 0 ? 'disabled' : ''}>← 上一題</button>`;
  const finish = `<button class="primary" data-act="submit" ${session.submitting ? 'disabled' : ''}>
    ${session.submitting ? '儲存中…' : `交卷（已答 ${answered}/${session.questions.length}）`}</button>`;
  if (session.mode === 'practice') {
    const canNext = session.revealed[i];
    const next = last
      ? finish
      : `<button class="primary" data-act="next" ${canNext ? '' : 'disabled'}>下一題 →</button>`;
    return `<div class="nav-row">${prev}<span class="spacer"></span>${next}</div>`;
  }
  const next = `<button data-act="next" ${last ? 'disabled' : ''}>下一題 →</button>`;
  const dots = session.questions.map((_, k) => `<button data-jump="${k}"
    class="${session.answers[k] !== null ? 'done' : ''} ${k === i ? 'cur' : ''}">${k + 1}</button>`).join('');
  return `<div class="nav-row">${prev}${next}<span class="spacer"></span>${finish}</div>
    <div class="dots" aria-label="題號">${dots}</div>`;
}

function renderTake() {
  if (!session) return;
  const i = session.idx;
  const q = session.questions[i];
  const total = session.questions.length;
  const last = i === total - 1;
  const options = q.display.map((opt, d) => `
    <button class="option ${optionClass(q, opt, i)}" data-choose="${d}">
      <span class="key">${KEYS[d]}</span><span>${esc(opt.text)}</span>
    </button>`).join('');
  $app.innerHTML = `<div class="narrow">
    <div class="row"><h1>${esc(session.title)}</h1><span class="spacer"></span>
      <span class="chip">${session.mode === 'practice' ? '練習模式' : '考試模式'}</span></div>
    <div class="progress"><div style="width:${((i + 1) / total) * 100}%"></div></div>
    <div class="card">
      <div class="q-meta">第 ${i + 1} / ${total} 題 · 第 ${q.chapter} 章 ${esc(q.section || '')}</div>
      <div class="q-text">${esc(q.question)}</div>
      <div class="options">${options}</div>
      ${renderFeedback(q, i)}
    </div>
    ${renderNav(i, last)}
    <p class="muted">鍵盤：A–D 或 1–4 選答，Enter / → 下一題，← 上一題</p></div>`;
}

$app.addEventListener('click', (e) => {
  if (!session) return;
  const btn = e.target.closest('button');
  if (!btn || !$app.contains(btn)) return;
  if (btn.dataset.choose !== undefined) choose(Number(btn.dataset.choose));
  else if (btn.dataset.jump !== undefined) updateSession({ idx: Number(btn.dataset.jump) });
  else if (btn.dataset.act === 'prev') go(-1);
  else if (btn.dataset.act === 'next') go(1);
  else if (btn.dataset.act === 'submit') submit();
});

document.addEventListener('keydown', (e) => {
  if (!session || e.ctrlKey || e.metaKey || e.altKey || e.target.matches('input, select, textarea')) return;
  const k = e.key.toUpperCase();
  const byLetter = KEYS.indexOf(k);
  const byNumber = '123456'.indexOf(k);
  if (byLetter >= 0 && k.length === 1) choose(byLetter);
  else if (byNumber >= 0) choose(byNumber);
  else if (e.key === 'ArrowLeft') go(-1);
  else if (e.key === 'ArrowRight' || e.key === 'Enter') {
    const last = session.idx === session.questions.length - 1;
    const blocked = session.mode === 'practice' && !session.revealed[session.idx];
    if (blocked) return;
    e.preventDefault();
    if (last) submit(); else go(1);
  }
});

window.addEventListener('beforeunload', (e) => {
  if (session && session.answers.some((a) => a !== null)) e.preventDefault();
});

// ---------- 各頁面 ----------
function settingsHtml(s) {
  return `<div class="card settings">
    <label><input type="radio" name="mode" value="practice" ${s.mode === 'practice' ? 'checked' : ''}>
      練習模式（每題立即對答＋解析）</label>
    <label><input type="radio" name="mode" value="exam" ${s.mode === 'exam' ? 'checked' : ''}>
      考試模式（交卷才看答案）</label>
    <label><input type="checkbox" name="shuffleQuestions" ${s.shuffleQuestions ? 'checked' : ''}>打亂題目順序</label>
    <label><input type="checkbox" name="shuffleOptions" ${s.shuffleOptions ? 'checked' : ''}>打亂選項順序</label>
  </div>`;
}

function bindSettings() {
  $app.querySelector('.settings').addEventListener('change', (e) => {
    const s = loadSettings();
    const next = e.target.name === 'mode'
      ? { ...s, mode: e.target.value }
      : { ...s, [e.target.name]: e.target.checked };
    saveSettings(next);
  });
}

async function viewHome() {
  const [{ quizzes, errors }, attempts] = await Promise.all([api('quizzes'), api('attempts')]);
  const byQuiz = (id) => attempts.filter((a) => a.quizIds.length === 1 && a.quizIds[0] === id);
  const cards = quizzes.map((q) => {
    const tries = byQuiz(q.id);
    const best = tries.length ? Math.max(...tries.map((t) => t.score)) : null;
    const chips = q.chapters.map((c) => `<span class="chip">第 ${c} 章</span>`).join(' ');
    const record = tries.length
      ? `<span class="chip ${best >= 80 ? 'ok' : 'bad'}">最佳 ${best} 分 · ${tries.length} 次</span>`
      : '<span class="chip">未作答</span>';
    return `<div class="card quiz-card">
      <div class="row"><span class="title">${esc(q.title)}</span><span class="spacer"></span>
        <label class="muted"><input type="checkbox" class="pick" value="${esc(q.id)}"> 合併</label>
        <a class="btn primary" href="#/take/${esc(q.id)}">開始</a></div>
      <div class="row muted">${chips} <span>${q.count} 題</span> <span>${esc(q.created)}</span> ${record}</div>
      ${q.description ? `<div class="muted">${esc(q.description)}</div>` : ''}
    </div>`;
  }).join('');
  const errorHtml = errors.length
    ? `<div class="card" style="border-color:var(--bad)"><strong>有題庫檔讀取失敗：</strong>
       <pre class="code">${esc(errors.join('\n'))}</pre></div>` : '';
  const empty = `<div class="card empty">
    <p>目前還沒有題庫。</p>
    <p>到 Claude Code 說：「出第 3 章 10 題選擇題」，題目就會出現在這裡（重新整理頁面）。</p></div>`;
  $app.innerHTML = `<h1>題庫</h1><p class="sub">選一份題目開始練習；作答結果會自動存進歷史紀錄與錯題本。</p>
    ${settingsHtml(loadSettings())}${errorHtml}
    ${quizzes.length > 1 ? `<div class="row" style="margin-bottom:12px">
      <span class="muted">勾選多份題庫可以一起考</span><span class="spacer"></span>
      <button class="primary" id="combine" disabled>合併作答</button></div>` : ''}
    <div class="grid">${quizzes.length ? cards : empty}</div>`;
  bindSettings();
  const $combine = document.getElementById('combine');
  if (!$combine) return;
  const picked = () => [...$app.querySelectorAll('.pick:checked')].map((el) => el.value);
  $app.querySelector('.grid').addEventListener('change', () => {
    const ids = picked();
    const total = quizzes.filter((q) => ids.includes(q.id)).reduce((n, q) => n + q.count, 0);
    $combine.disabled = ids.length < 2;
    $combine.textContent = ids.length < 2 ? '合併作答' : `合併作答（${ids.length} 份，共 ${total} 題）`;
  });
  $combine.addEventListener('click', () => { location.hash = `#/take/${picked().join(',')}`; });
}

async function viewTake(idsText) {
  const ids = [...new Set(idsText.split(',').filter(Boolean))];
  const quizzes = await Promise.all(ids.map((id) => api(`quizzes/${encodeURIComponent(id)}`)));
  const title = quizzes.length === 1
    ? quizzes[0].title
    : `合併：${quizzes.map((q) => q.title).join(' ＋ ')}`.slice(0, 190);
  session = buildSession(title, quizzes.flatMap(fromQuiz), loadSettings());
  renderTake();
}

function viewPractice() {
  if (!pendingPractice) { location.hash = '#/wrong'; return; }
  session = buildSession(pendingPractice.title, pendingPractice.questions, loadSettings());
  pendingPractice = null;
  renderTake();
}

function startPractice(title, rows) {
  pendingPractice = {
    title,
    questions: rows.map((r) => ({
      quizId: r.quizId, qid: r.qid, chapter: r.chapter, section: r.section,
      question: r.question, options: r.options, answer: r.answer, explanation: r.explanation,
    })),
  };
  location.hash = '#/practice';
}

function chapterBreakdown(items) {
  const map = new Map();
  items.forEach((it) => {
    const [t, c] = map.get(it.chapter) || [0, 0];
    map.set(it.chapter, [t + 1, c + (it.correct ? 1 : 0)]);
  });
  return [...map.entries()].sort((a, b) => a[0] - b[0]).map(([ch, [t, c]]) => `
    <div class="row"><span style="width:70px">第 ${ch} 章</span>
      <div class="bar"><div style="width:${(c / t) * 100}%"></div></div>
      <span class="muted" style="width:70px">${c}/${t}</span></div>`).join('');
}

/**
 * 完整列出選項，標示正解與作答者的選擇。
 * @param {string[]} options
 * @param {number} answer 正解索引
 * @param {number|null} choice 作答者選的索引
 */
function optionListHtml(options, answer, choice) {
  const items = options.map((text, k) => {
    const isAnswer = k === answer;
    const isChoice = k === choice;
    let cls = '';
    let badge = '';
    if (isAnswer && isChoice) { cls = 'correct'; badge = '<span class="chip ok">你的答案 ✓</span>'; }
    else if (isAnswer) { cls = 'correct'; badge = '<span class="chip ok">正解</span>'; }
    else if (isChoice) { cls = 'wrong'; badge = '<span class="chip bad">你的答案 ✗</span>'; }
    return `<li class="opt-row ${cls}"><span class="key">${KEYS[k]}</span>
      <span class="opt-text">${esc(text)}</span>${badge}</li>`;
  }).join('');
  return `<ol class="opt-list">${items}</ol>`;
}

/**
 * 檢討卡片（作答紀錄與錯題本共用）。
 * @param {{chapter:number, section:string, question:string, options:string[], answer:number,
 *   choice:number|null, correct:boolean, explanation?:string}} it
 * @param {string} heading 卡片左上角標題
 * @param {string} status 右上角狀態 chip 的 HTML
 */
function reviewCardHtml(it, heading, status) {
  return `<article class="card rcard ${it.correct ? 'ok' : 'bad'}" data-correct="${it.correct}">
    <header class="rcard-head"><strong>${heading}</strong>
      <span class="muted">第 ${it.chapter} 章 ${esc(it.section)}</span>
      <span class="spacer"></span>${status}</header>
    <div class="rcard-q">${esc(it.question)}</div>
    ${optionListHtml(it.options, it.answer, it.choice)}
    ${it.explanation ? `<div class="explain">${esc(it.explanation)}</div>` : ''}
  </article>`;
}

function reviewItemHtml(it, n) {
  let status = '<span class="chip ok">答對</span>';
  if (it.choice === null) status = '<span class="chip bad">未作答</span>';
  else if (!it.correct) status = '<span class="chip bad">答錯</span>';
  return reviewCardHtml(it, `第 ${n} 題`, status);
}

async function viewAttempt(id) {
  const a = await api(`attempts/${encodeURIComponent(id)}`);
  const wrong = a.items.filter((it) => !it.correct);
  const retakeIds = a.quizIds.join(',');
  $app.innerHTML = `
    <div class="card"><div class="row">
      <div><div class="muted">${esc(fmtTime(a.finishedAt))} · ${fmtDuration(a.durationSec)}</div>
        <h1>${esc(a.title)}</h1></div><span class="spacer"></span>
      <div class="score ${a.score >= 80 ? 'good' : 'bad'}">${a.score}<span class="muted"> 分</span></div></div>
      <p class="muted">答對 ${a.correct} / ${a.total} 題</p>
      <div class="grid">${chapterBreakdown(a.items)}</div>
      <div class="row" style="margin-top:14px">
        ${wrong.length ? `<button class="primary" id="redo-wrong">重練這次的 ${wrong.length} 題錯題</button>` : ''}
        ${a.title.startsWith('錯題') ? '' : `<a class="btn" href="#/take/${esc(retakeIds)}">整份再考一次</a>`}
        <span class="spacer"></span>
        <label class="muted"><input type="checkbox" id="only-wrong"> 只看錯題</label>
      </div></div>
    <h2>逐題檢討</h2>
    <div class="review-grid" id="items">${a.items.map((it, k) => reviewItemHtml(it, k + 1)).join('')}</div>`;
  document.getElementById('redo-wrong')?.addEventListener('click', () => startPractice(`錯題重練：${a.title}`, wrong));
  document.getElementById('only-wrong').addEventListener('change', (e) => {
    $app.querySelectorAll('#items [data-correct="true"]').forEach((el) => { el.hidden = e.target.checked; });
  });
}

async function viewHistory() {
  const attempts = await api('attempts');
  const rows = attempts.map((a) => `<tr>
    <td>${esc(fmtTime(a.finishedAt))}</td>
    <td><a href="#/attempt/${esc(a.id)}">${esc(a.title)}</a></td>
    <td><span class="chip ${a.score >= 80 ? 'ok' : 'bad'}">${a.score}</span></td>
    <td>${a.correct}/${a.total}</td><td class="muted">${fmtDuration(a.durationSec)}</td></tr>`).join('');
  $app.innerHTML = `<h1>歷史紀錄</h1><p class="sub">共 ${attempts.length} 次作答，點標題看逐題檢討。</p>
    ${attempts.length
    ? `<div class="card" style="overflow-x:auto"><table>
        <thead><tr><th>時間</th><th>題目</th><th>分數</th><th>答對</th><th>用時</th></tr></thead>
        <tbody>${rows}</tbody></table></div>`
    : '<div class="card empty">還沒有作答紀錄</div>'}`;
}

async function viewWrong() {
  const [all, stats] = await Promise.all([api('wrong'), api('stats')]);
  const chapterBars = stats.chapters.map((r) => `
    <div class="row"><span style="width:70px">第 ${r.key} 章</span>
      <div class="bar"><div style="width:${r.rate}%"></div></div>
      <span class="muted" style="width:110px">${r.rate}%（${r.correct}/${r.total}）</span></div>`).join('');
  const chapters = [...new Set(all.map((w) => w.chapter))].sort((a, b) => a - b);
  $app.innerHTML = `<h1>錯題本</h1>
    <p class="sub">答錯過的題目都在這裡；之後再答對就算「已訂正」。</p>
    ${stats.chapters.length ? `<div class="card"><strong>各章累計正確率</strong>
      <div class="grid" style="margin-top:8px">${chapterBars}</div></div>` : ''}
    <div class="row" style="margin:18px 0 10px">
      <select id="ch-filter"><option value="">全部章節</option>
        ${chapters.map((c) => `<option value="${c}">第 ${c} 章</option>`).join('')}</select>
      <label><input type="checkbox" id="unfixed" checked> 只看尚未訂正</label>
      <span class="spacer"></span><button class="primary" id="practice"></button>
    </div>
    <div class="review-grid" id="wrong-list"></div>`;
  const $list = document.getElementById('wrong-list');
  const $btn = document.getElementById('practice');
  const current = () => {
    const ch = document.getElementById('ch-filter').value;
    const unfixed = document.getElementById('unfixed').checked;
    return all.filter((w) => (!ch || String(w.chapter) === ch) && (!unfixed || !w.lastCorrect));
  };
  const render = () => {
    const rows = current();
    $btn.textContent = `練習這 ${rows.length} 題`;
    $btn.disabled = rows.length === 0;
    $list.innerHTML = rows.length ? rows.map((w) => reviewCardHtml(
      { ...w, choice: w.lastChoice, correct: w.lastCorrect },
      `錯 ${w.wrong} / 答 ${w.seen} 次`,
      `<span class="chip ${w.lastCorrect ? 'ok' : 'bad'}">${w.lastCorrect ? '已訂正' : '未訂正'}</span>`,
    )).join('') : '<div class="card empty">沒有符合的錯題 🎉</div>';
  };
  document.getElementById('ch-filter').addEventListener('change', render);
  document.getElementById('unfixed').addEventListener('change', render);
  $btn.addEventListener('click', () => startPractice('錯題本練習', current()));
  render();
}

// ---------- 路由 ----------
const routes = [
  [/^#?\/?$/, () => viewHome(), 'home'],
  [/^#\/take\/([\w,-]+)$/, (m) => viewTake(m[1]), 'home'],
  [/^#\/practice$/, () => viewPractice(), 'wrong'],
  [/^#\/attempt\/([\w-]+)$/, (m) => viewAttempt(m[1]), 'history'],
  [/^#\/history$/, () => viewHistory(), 'history'],
  [/^#\/wrong$/, () => viewWrong(), 'wrong'],
];

let lastHash = location.hash;

async function route() {
  const hash = location.hash;
  if (session && session.answers.some((a) => a !== null) && !confirm('作答尚未交卷，離開會遺失進度，確定離開？')) {
    history.replaceState(null, '', lastHash || '#/');
    return;
  }
  session = null;
  lastHash = hash;
  const found = routes.find(([re]) => re.test(hash));
  const [re, view, nav] = found || routes[0];
  document.querySelectorAll('[data-nav]').forEach((a) => a.classList.toggle('active', a.dataset.nav === nav));
  $app.innerHTML = '<div class="empty">載入中…</div>';
  try {
    await view(hash.match(re));
    window.scrollTo(0, 0);
  } catch (err) {
    showError(err);
  }
}

window.addEventListener('hashchange', route);
route();
