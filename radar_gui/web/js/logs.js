// Logs tab (gui-37 Step 2b): list / view / delete the run folders under runs/gui/ (GET /api/logs, /api/logs/<name>/file,
// POST /api/logs/delete). All server text goes in through textContent (never innerHTML). Delete needs a confirm that names
// the folders and their total size; the running session cannot be selected. Replay opens a run's serial_data.bin in the
// Point cloud tab. A server without these endpoints shows a "restart the GUI" hint and nothing else breaks.
import { $ } from './state.js';
import { api, detailText, boardLive, refreshSrc } from './session.js';

const L = { sessions: [], sel: new Set(), cur: null, file: 'driver.log', ready: false };
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; };
export const fmtSize = n => n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KiB` : n < 1073741824 ? `${(n / 1048576).toFixed(1)} MiB` : `${(n / 1073741824).toFixed(2)} GiB`;
function msg(text, cls) { const m = $('lgMsg'); m.hidden = !text; m.textContent = text || ''; m.className = 'runmsg ' + (cls || 'bad'); }
const missing = res => res.status === 404 || res.status === 405 || res.status === 0;

async function load() {
  const res = await api('/api/logs');
  if (!res.ok) { msg(missing(res) ? 'This GUI server is older than the Logs tab: restart the GUI to enable it.' : detailText(res)); return; }
  msg('');
  L.sessions = res.j.sessions || []; L.running = res.j.running;
  L.sel = new Set([...L.sel].filter(n => L.sessions.some(s => s.name === n && !s.running)));
  $('lgRoot').textContent = res.j.root || '';
  $('lgTotal').textContent = `${L.sessions.length} sessions, ${fmtSize(res.j.total_size || 0)} in total`;
  render();
}
function render() {
  const t = $('lgTable'); t.textContent = '';
  const head = el('tr'); for (const h of ['', 'Session', 'Started (UTC)', 'Board / firmware', 'Size', 'Files', '']) head.append(el('th', '', h)); t.append(head);
  if (!L.sessions.length) { const tr = el('tr'); const td = el('td', 'muted', 'No sessions yet: every Start writes a folder here.'); td.colSpan = 7; tr.append(td); t.append(tr); }
  for (const s of L.sessions) {
    const tr = el('tr'); if (L.cur === s.name) tr.className = 'cur';
    const cb = el('input'); cb.type = 'checkbox'; cb.checked = L.sel.has(s.name); cb.disabled = s.running;
    cb.title = s.running ? 'The running session cannot be deleted' : 'Select ' + s.name; cb.setAttribute('aria-label', 'Select ' + s.name);
    cb.onchange = () => { if (cb.checked) L.sel.add(s.name); else L.sel.delete(s.name); buttons(); };
    const c0 = el('td'); c0.append(cb);
    const c1 = el('td', '', s.label); c1.title = s.name;
    if (s.running) c1.append(' ', el('span', 'badge ok', 'running'));
    if (Object.values(s.saving || {}).some(Boolean)) c1.append(' ', el('span', 'badge warn', 'saving'));
    const c2 = el('td', '', (s.started || '').replace('T', ' ').slice(0, 19));
    const c3 = el('td', '', [s.board, s.firmware].filter(Boolean).join(' / ') || '–');
    const c4 = el('td', '', fmtSize(s.size));
    const c5 = el('td', 'muted', (s.files || []).map(f => f.name).join(', '));
    const c6 = el('td', 'lgact');
    const v = el('button', 'btn mini', 'View'); v.onclick = () => view(s.name); c6.append(v);
    if (s.replayable) { const r = el('button', 'btn mini', 'Replay'); r.title = 'Show this run\'s serial_data.bin in the Point cloud tab'; r.disabled = boardLive(); r.onclick = () => replay(s); c6.append(' ', r); }
    tr.append(c0, c1, c2, c3, c4, c5, c6); t.append(tr);
  }
  buttons();
}
function buttons() {
  const n = L.sel.size;
  $('lgDelete').disabled = !n; $('lgDelete').textContent = n ? `Delete selected (${n})` : 'Delete selected';
  $('lgAll').textContent = L.sessions.filter(s => !s.running).every(s => L.sel.has(s.name)) && L.sessions.some(s => !s.running) ? 'Select none' : 'Select all';
}
async function view(name) {
  L.cur = name; render();
  $('lgTitle').textContent = name;
  const res = await api(`/api/logs/${encodeURIComponent(name)}/file?file=${encodeURIComponent(L.file)}&tail=${$('lgTail').value}`);
  const pre = $('lgText');
  if (!res.ok) { pre.textContent = res.status === 404 ? `${name} has no ${L.file}.` : detailText(res); return; }
  pre.textContent = (res.j.truncated ? `[showing the last ${$('lgTail').value} lines of ${res.j.lines}]\n` : '') + res.j.text;
  pre.scrollTop = pre.scrollHeight;
}
async function replay(s) {
  const res = await api('/api/source', { kind: 'replay', file: s.capture, dialect: s.dialect || 'sdk3' });
  if (!res.ok) { msg(detailText(res)); return; }
  msg(''); await refreshSrc(); dispatchEvent(new CustomEvent('goto-tab', { detail: 'live' }));
}
async function del() {
  const names = [...L.sel], list = L.sessions.filter(s => L.sel.has(s.name)), size = list.reduce((a, s) => a + s.size, 0);
  if (!names.length) return;
  if (!confirm(`Delete ${names.length} session folder${names.length > 1 ? 's' : ''} permanently (${fmtSize(size)})?\n\n${names.join('\n')}\n\nOnly these folders under runs/gui/ are removed.`)) return;
  const res = await api('/api/logs/delete', { names });
  if (!res.ok) { msg(detailText(res)); await load(); return; }
  L.sel.clear(); if (names.includes(L.cur)) { L.cur = null; $('lgText').textContent = 'Choose a session and press View.'; $('lgTitle').textContent = 'Log'; }
  msg(`Deleted ${res.j.deleted.length} session${res.j.deleted.length > 1 ? 's' : ''}, freed ${fmtSize(res.j.freed)}.`, 'ok');
  await load();
}
export function showLogs() {
  if (!L.ready) {
    L.ready = true;
    $('lgRefresh').onclick = load; $('lgDelete').onclick = del;
    $('lgAll').onclick = () => { const all = L.sessions.filter(s => !s.running); if (all.every(s => L.sel.has(s.name))) L.sel.clear(); else all.forEach(s => L.sel.add(s.name)); render(); };
    $('lgFile').addEventListener('click', e => { const b = e.target.closest('button'); if (!b) return; L.file = b.dataset.f; [...$('lgFile').children].forEach(x => x.classList.toggle('on', x === b)); if (L.cur) view(L.cur); });
    $('lgTail').onchange = () => { if (L.cur) view(L.cur); };
  }
  load();
}
