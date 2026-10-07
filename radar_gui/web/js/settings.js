// Settings tab (gui-32): read-only serial-port list grouped by board + DCA1000 host checks (/api/settings/*).
// "Use" buttons only fill the existing port fields (Configure -> Save, Live Source card); nothing is written to a radar or the host.
import { $ } from './state.js';

const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; };
async function get(path) { try { const r = await fetch(path); return { ok: r.ok, j: await r.json().catch(() => null) }; } catch (e) { return { ok: false, j: null }; } }

function setPorts(id, cli, data, where) {
  if (where === 'save') { $('sCli').value = cli; $('sData').value = data; }
  else { $('srcCli').value = cli; $('srcData').value = data; $('srcKind').querySelector('button[data-k=serial]').click(); dispatchEvent(new CustomEvent('goto-tab', { detail: 'live' })); }
}
function renderPorts(j) {
  const box = $('setPorts'); box.innerHTML = '';
  if (!j) { box.append(el('div', 'runmsg bad', 'Could not read /api/settings/ports (this backend is older than the Settings tab).')); return; }
  if (!j.boards.length) { box.append(el('div', 'runmsg warn', j.present ? `No serial devices in ${j.by_id_dir}: is a radar plugged in?` : `${j.by_id_dir} does not exist: no USB serial devices on this host.`)); return; }
  for (const b of j.boards) {
    const d = el('div', 'setboard'); d.append(el('h3', '', `${b.label} · serial ${b.serial}`));
    const t = el('table', 'ftbl'); t.innerHTML = '<tr><th>Role</th><th>by-id path</th><th>Node</th><th>If</th><th>Held by</th></tr>';
    for (const p of b.ports) {
      const tr = el('tr'); tr.append(el('td', '', p.role || '?'), el('td', 'cmd', p.by_id), el('td', '', p.tty), el('td', '', p.interface),
        el('td', '', p.holders.length ? p.holders.map(h => `${h.pid} ${h.comm}`).join(', ') : 'free'));
      t.append(tr);
    }
    d.append(t);
    const cli = b.ports.find(p => p.role === 'cli'), data = b.ports.find(p => p.role === 'data');
    if (cli && data) {
      const row = el('div', 'btnrow');
      for (const [where, label] of [['save', 'Use for Configure → Save'], ['live', 'Use for Live serial source']]) {
        const bt = el('button', 'btn', label); bt.onclick = () => setPorts(b.serial, cli.by_id, data.by_id, where); row.append(bt);
      }
      d.append(row);
    }
    box.append(d);
  }
}
function renderDca(j, ok) {
  const box = $('setDca'); box.innerHTML = '';
  if (!j || !ok) { box.append(el('div', 'runmsg bad', (j && typeof j.detail === 'string') ? j.detail : 'DCA check unavailable (backend older than the Settings tab).')); return; }
  const sel = $('setNic'), keep = sel.value; sel.innerHTML = ''; sel.append(new Option('(auto: sole candidate)', ''));
  for (const n of j.candidates || []) sel.append(new Option(n, n));
  sel.value = [...sel.options].some(o => o.value === keep) ? keep : '';
  for (const c of j.checks || []) {
    const cls = c.status === 'OK' ? 'ok' : c.status === 'MISSING' ? 'bad' : 'warn';
    const m = el('div', 'runmsg ' + cls, `${c.name}: ${c.status} — ${c.detail}`);
    for (const n of c.notes || []) m.append(el('div', '', n));
    for (const f of [...(c.fix_cmds || []), ...(c.manual || [])]) m.append(el('div', 'cmd', '$ ' + f));
    box.append(m);
  }
}
async function loadPorts() { const r = await get('/api/settings/ports'); renderPorts(r.ok ? r.j : null); }
async function loadDca() {
  const q = new URLSearchParams(); if ($('setNic').value) q.set('nic', $('setNic').value); if ($('setPing').checked) q.set('ping', '1');
  $('setDcaRun').disabled = true; const r = await get('/api/settings/dca?' + q); $('setDcaRun').disabled = false; renderDca(r.j, r.ok);
}
export function showSettings() { loadPorts(); loadDca(); }
$('setRefresh').onclick = showSettings;
$('setDcaRun').onclick = loadDca;
