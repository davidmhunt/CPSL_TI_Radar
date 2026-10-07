// Live tab Source card (gui-06): switch the running source (mock / replay / serial) via /api/source*.
// Serial: board + cfg pickers, CLI/data ports defaulting to the board's usual by-id paths, skip-cfg for
// once-per-boot boards. Status text arrives through main.js (setStatus) -> srcStatus().
import { $ } from './state.js';
import { mountCliPanel } from './cli_panel.js';

const C = { kind: 'mock', boards: [], cfgs: [], files: [], cur: null, ready: false, busy: false };
let cmdPanel = null;
const KIND_LABEL = { mock: 'Mock', replay: 'Replay', serial: 'Serial' };

async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  let j = null; try { j = await r.json(); } catch (e) { /* non-JSON */ }
  return { ok: r.ok, status: r.status, j };
}
function detail(res) {
  const d = res.j && res.j.detail;
  if (typeof d === 'string') return d;
  if (Array.isArray(d)) return d.map(x => (x.loc ? x.loc.join('.') + ': ' : '') + x.msg).join('; ');
  return `request failed (HTTP ${res.status})`;
}
function msg(text, cls) { const m = $('srcMsg'); m.hidden = !text; m.textContent = text || ''; m.className = 'runmsg ' + (cls || 'bad'); }
const board = () => C.boards.find(b => b.board === $('srcBoard').value);

function layout() {
  [...$('srcKind').children].forEach(b => b.classList.toggle('on', b.dataset.k === C.kind));
  $('srcFileRow').hidden = C.kind !== 'replay';
  $('srcSerial').hidden = C.kind !== 'serial';
  const b = board();
  $('srcSkipRow').hidden = !(C.kind === 'serial' && b && b.once_per_boot);
  $('srcBoardNote').textContent = b ? `${b.tlv_dialect} TLV, CLI ${b.cli_baud} baud, data ${b.data_baud} baud` +
    (b.once_per_boot ? '. Accepts a cfg once per power-up.' : '') : '';
  const live = C.cur && C.cur.kind;
  $('srcStop').disabled = C.busy || !live;
  $('srcStart').disabled = C.busy || (C.kind === 'serial' && !$('srcCfg').value) || (C.kind === 'replay' && !$('srcFile').value);
  $('srcStart').textContent = C.kind === 'serial' ? (live === 'serial' ? 'Restart' : 'Start serial') : `Use ${KIND_LABEL[C.kind].toLowerCase()}`;
}
function fillCfgs() {
  const b = board(), sel = $('srcCfg'), keep = sel.value; sel.innerHTML = '';
  const items = C.cfgs.filter(c => b && c.board === b.board);
  for (const [g, label] of [['user', 'Saved from Configure'], ['shipped', 'Shipped']]) {
    const xs = items.filter(c => c.group === g); if (!xs.length) continue;
    const og = document.createElement('optgroup'); og.label = label;
    for (const c of xs) og.append(new Option(c.name, c.id));
    sel.append(og);
  }
  if (!items.length) sel.append(new Option('(no cfgs for this board)', ''));
  if (items.some(c => c.id === keep)) sel.value = keep;
}
function boardChanged() {
  const b = board();
  if (b) { $('srcCli').value = b.cli_port; $('srcData').value = b.data_port; }
  fillCfgs(); layout();
}
function describeNow() {
  const c = C.cur; if (!c) return;
  const sp = c.spec || {};
  let t = `Live: ${c.kind}`;
  if (c.kind === 'serial') t += ` · ${sp.board || ''}${sp.skip_configure ? ' (cfg skipped)' : ''}`;
  if (c.kind === 'replay' && sp.file) t += ` · ${sp.file.split('/').pop()}`;
  $('srcNow').textContent = t;
}
export async function refreshSource() {
  const { j } = await api('/api/source');
  if (j) { C.cur = j; describeNow(); if (cmdPanel && j.kind === 'serial') cmdPanel.update(j.cli); else if (cmdPanel) cmdPanel.clear(); if (!C.ready) { C.kind = j.kind; } layout(); }
}
export async function initSource() {
  const [b, c, f] = await Promise.all([api('/api/source/boards'), api('/api/cfgs'), api('/api/source/files')]);
  C.boards = (b.j && b.j.boards) || []; C.cfgs = (c.j && c.j.cfgs) || []; C.files = (f.j && f.j.files) || [];
  const sb = $('srcBoard'); sb.innerHTML = '';
  for (const x of C.boards) sb.append(new Option(x.board, x.board));
  const fs = $('srcFile'); fs.innerHTML = '';
  for (const g of ['fixtures', 'dumps', 'startup']) {
    const xs = C.files.filter(x => x.group === g); if (!xs.length) continue;
    const og = document.createElement('optgroup'); og.label = { fixtures: 'tests/fixtures', dumps: 'GUI captures (runs/gui/dumps)', startup: 'Started with' }[g];
    for (const x of xs) og.append(new Option(x.name, x.path));
    fs.append(og);
  }
  if (!C.files.length) fs.append(new Option('(no replay files found)', ''));
  cmdPanel = mountCliPanel($('srcCmds'), { compact: true });
  await refreshSource();
  C.ready = true; boardChanged();
}

async function start() {
  msg(''); C.busy = true; layout();
  const body = { kind: C.kind };
  if (C.kind === 'replay') body.file = $('srcFile').value;
  if (C.kind === 'serial') {
    Object.assign(body, { board: $('srcBoard').value, cfg_id: $('srcCfg').value, cli_port: $('srcCli').value.trim() || null,
      data_port: $('srcData').value.trim() || null, skip_configure: !$('srcSkipRow').hidden && $('srcSkip').checked });
    if ($('srcDump').checked) body.dump = `${body.board}_${new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)}.bin`;
  }
  const res = await api('/api/source', body);
  C.busy = false;
  if (!res.ok) {
    const t = detail(res);
    msg(res.status === 409 ? (/busy|in use|held|already/i.test(t) ? 'Ports busy: ' : 'Refused: ') + t : res.status === 422 ? 'Not started: ' + t : t);
  } else { C.cur = res.j; describeNow(); }
  layout();
}
async function stop() {
  msg(''); C.busy = true; layout();
  const res = await api('/api/source/stop', {});
  C.busy = false;
  if (!res.ok) msg(detail(res)); else { C.cur = res.j; describeNow(); }
  C.cur = (await api('/api/source')).j || C.cur; layout();
}

// Called by main.js on every status message: the source's progress / hints (configuring i/N, cfg_failed + power-cycle
// hint, stalled, no_board, compact-points) are shown in the card as well as the header.
const BAD = ['error', 'cfg_failed', 'no_board', 'stalled', 'disconnected'];
let lastState = null;
export function srcStatus(state, text) {
  // the transcript is fetched when the configure attempt resolves (not on every "configuring i/N" tick)
  if (state !== lastState && ['cfg_failed', 'waiting', 'streaming', 'stalled'].includes(state) && C.ready) refreshSource();
  lastState = state;
  const el = $('srcStat'); const show = !!text || BAD.includes(state);
  el.hidden = !show; el.textContent = show ? `${state.replace('_', ' ')}${text ? ': ' + text : ''}` : '';
  el.className = 'runmsg ' + (BAD.includes(state) ? 'bad' : state === 'streaming' ? 'ok' : 'warn');
}
// A new source resets the header counters until its first frame.
export function resetStats() { for (const id of ['sFrame', 'sPts', 'sRate', 'sGaps', 'sErr']) $(id).textContent = '–'; refreshSource(); }

$('srcKind').addEventListener('click', e => { const b = e.target.closest('button'); if (!b) return; C.kind = b.dataset.k; msg(''); layout(); });
$('srcBoard').addEventListener('change', boardChanged);
$('srcCfg').addEventListener('change', layout);
$('srcFile').addEventListener('change', layout);
$('srcStart').onclick = start;
$('srcStop').onclick = stop;
