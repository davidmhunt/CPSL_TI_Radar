// Point cloud tab "Now showing" card (gui-06, gui-37). Board = the C++ driver session: a compact picker bound to the same
// setup as the Radar tab (session.js `spec`) plus Start/Stop. Replay = a recorded TLV file shown through /api/source.
// Status text arrives through main.js (setStatus) -> srcStatus().
import { $ } from './state.js';
import { mountCliPanel } from './cli_panel.js';
import { api, detailText, D, SS, spec, specChanged, specReady, specLabel, specBoard, onceBoard, skipEffective, skipSupported, cfgSentHere,
  cfgsFor, boardInfo, FLAGS, flagEff, hasSetup, caps, fill, splitBy, view, onSession, startSession, stopSession, refreshSrc, boardLive, blockedReason } from './session.js';

const C = { kind: 'board', files: [], ready: false, busy: false, userKind: false };
let cmdPanel = null, cliSig = '';

function msg(text, cls) { const m = $('srcMsg'); m.hidden = !text; m.textContent = text || ''; m.className = 'runmsg ' + (cls || 'bad'); }

// gui-09 D16: the dialect follows the capture (backend `dialect`) or its file name; editable.
function autoDialect() {
  const f = C.files.find(x => x.path === $('srcFile').value);
  if (f) $('srcDialect').value = f.dialect || (/^awr2243_cascade/i.test(f.name) ? 'mcuplus_cascade' : /^iwr1443/i.test(f.name) ? 'sdk2' : 'sdk3');
}
function fillFiles() {
  C.files = D.files;
  const groups = splitBy(C.files, 'group', [['runs', 'Run captures (runs/gui/*/serial_data.bin)'], ['fixtures', 'tests/fixtures'], ['dumps', 'GUI captures (runs/gui/dumps)'], ['startup', 'Started with']])
    .map(([l, xs]) => [l, xs.map(x => [x.path, x.name])]);
  fill($('srcFile'), groups.length ? groups : [[null, [['', '(no replay files found)']]]], $('srcFile').value);
  autoDialect();
}
function renderPicker() {
  const quick = spec.mode === 'quick' && hasSetup();
  $('srcMode').hidden = !hasSetup();
  [...$('srcMode').children].forEach(b => b.classList.toggle('on', b.dataset.m === (quick ? 'quick' : 'saved')));
  $('srcSavedRow').hidden = quick; $('srcQuickRow').hidden = !quick;
  fill($('srcCfgSel'), D.configs.length ? splitBy(D.configs, 'group', [['user', 'Saved from Configure'], ['system', 'Shipped']])
    .map(([l, xs]) => [l, xs.map(c => [c.path, c.name + (c.board ? `  [${c.board}]` : '')])]) : [[null, [['', '(no system JSONs found)']]]], spec.config);
  if (D.boards.length) {
    fill($('srcBoard'), [[null, D.boards.map(x => [x.board, x.board])]], spec.board);
    const cf = cfgsFor(spec.board), grp = splitBy(cf, 'group', [['user', 'Saved from Configure'], ['shipped', 'Shipped']]);
    fill($('srcCfg'), cf.length ? grp.map(([l, xs]) => [l, xs.map(c => [c.id, c.name])]) : [[null, [['', '(no cfgs for this board)']]]], spec.cfg_id);
    const b = boardInfo(spec.board);
    $('srcBoardNote').textContent = b ? `${b.tlv_dialect} TLV, CLI ${b.cli_baud} baud, data ${b.data_baud} baud` + (b.once_per_boot ? '. Accepts a cfg once per power-up.' : '') +
      '. Ports, firmware and DCA1000 are in the Radar tab.' : '';
  }
  renderState();
}
const recSummary = () => {
  if (!hasSetup()) return '';
  const on = FLAGS.filter(([k, ovk]) => flagEff(k, ovk)).map(f => f[2]);
  return on.length ? `Recording: ${on.join(', ')} (change in Radar)` : 'Recording: off (change in Radar)';
};
// gui-33: the driver's firmware check; its verdict is in the log until the driver reports it as a field.
function showFirmware() {
  const el = $('srcFw'), d = SS.drv, show = boardLive() || ['exited', 'failed'].includes(d.state);
  const fw = d.firmware; el.hidden = !(show && fw);
  if (el.hidden) return;
  el.textContent = `Firmware: ${fw} · ` + (caps().firmware_check ? 'checked by the driver at start (verdict in the Radar log)' : 'not checked (this driver build has no firmware check)');
  el.className = 'runmsg ' + (caps().firmware_check ? 'ok' : 'warn');
}
function renderState() {
  const v = view(), live = boardLive(), repl = v.kind === 'replay';
  if (!C.userKind) C.kind = repl ? 'replay' : 'board';
  [...$('srcKind').children].forEach(b => { b.classList.toggle('on', b.dataset.k === C.kind); b.disabled = live; });
  $('srcBoardBox').hidden = C.kind !== 'board'; $('srcFileRow').hidden = C.kind !== 'replay';
  $('srcNow').textContent = v.kind === 'none' ? 'Nothing is running.' : `Now showing: ${v.pill}` + (v.desc && v.kind === 'board' ? ` — ${v.desc}` : '');
  const once = C.kind === 'board' && onceBoard();
  $('srcSkipRow').hidden = !once; $('srcSkip').checked = skipEffective() && skipSupported(); $('srcSkip').disabled = live || !skipSupported();
  $('srcSkipRow').lastElementChild.textContent = !skipSupported() ? 'Skip cfg unavailable: rebuild the driver' : cfgSentHere(specBoard()) ? 'Restart without the cfg (this GUI configured the board; untick after a power-cycle)' : 'Already configured this power-up (skip cfg)';
  $('srcRec').textContent = recSummary();
  for (const id of ['srcMode', 'srcCfgSel', 'srcBoard', 'srcCfg']) { const e = $(id); if (id === 'srcMode') [...e.children].forEach(b => { b.disabled = live; }); else e.disabled = live; }
  const why = blockedReason();
  if (C.kind === 'board') {
    $('srcStart').disabled = C.busy || SS.busy || live || !specReady();
    $('srcStart').textContent = live ? why : (once && skipEffective() && skipSupported() ? 'Restart (skip cfg)' : `Start ${specLabel()}`.trim());
    $('srcStop').disabled = C.busy || !(v.kind === 'board' && live && v.canStop);
  } else {
    $('srcStart').disabled = C.busy || live || !$('srcFile').value;
    $('srcStart').textContent = live ? why : 'Start replay';
    $('srcStop').disabled = C.busy || v.kind !== 'replay';
  }
  $('srcStop').textContent = C.kind === 'replay' ? 'Stop replay' : 'Stop';
  const sig = JSON.stringify(SS.cli.map(e => [e.seq, e.verdict, e.ms]));
  if (cmdPanel && sig !== cliSig) { cliSig = sig; cmdPanel.update(SS.cli); }
  showFirmware();
}

async function start() {
  msg(''); C.busy = true; renderState();
  let ok = true;
  if (C.kind === 'board') {
    const r = await startSession(); if (!r.ok) { ok = false; msg(r.text); }
  } else {
    const res = await api('/api/source', { kind: 'replay', file: $('srcFile').value, dialect: $('srcDialect').value });
    if (!res.ok) { ok = false; const t = detailText(res); msg(res.status === 409 ? 'Refused: ' + t : res.status === 422 ? 'Not started: ' + t : t); }
    else { SS.src = res.j; SS.stream = { state: 'streaming', msg: '' }; }
  }
  C.busy = false; C.userKind = false; if (ok) msg('');
  await refreshSrc(); renderState();
}
async function stop() {
  msg(''); C.busy = true; renderState();
  const r = await stopSession(); if (!r.ok) msg(r.text);
  C.busy = false; renderState();
}

// Called by main.js on every status message: the source's progress / hints (starting, ended, error, ...) are shown in the
// card as well as in the header bar.
const BAD = ['error', 'cfg_failed', 'wrong_firmware', 'no_board', 'stalled', 'disconnected'];
export function srcStatus(state, text) {
  const el = $('srcStat'); const show = !!text || BAD.includes(state);
  el.hidden = !show; el.textContent = show ? `${state.replace('_', ' ')}${text ? ': ' + text : ''}` : '';
  el.className = 'runmsg ' + (BAD.includes(state) ? 'bad' : state === 'streaming' ? 'ok' : 'warn');
}
// A new source resets the header counters until its first frame.
export function resetStats() { for (const id of ['sFrame', 'sPts', 'sRate', 'sGaps', 'sErr']) $(id).textContent = '–'; refreshSrc(); }

export function initSource() {
  cmdPanel = mountCliPanel($('srcCmds'), { compact: true });
  $('srcKind').addEventListener('click', e => { const b = e.target.closest('button'); if (!b || b.disabled) return; C.kind = b.dataset.k; C.userKind = true; msg(''); renderState(); });
  $('srcMode').addEventListener('click', e => { const b = e.target.closest('button'); if (!b || b.disabled) return; spec.mode = b.dataset.m; spec.skipSet = false; specChanged(); });
  $('srcCfgSel').addEventListener('change', () => { spec.config = $('srcCfgSel').value; spec.skipSet = false; specChanged(); });
  $('srcBoard').addEventListener('change', () => {
    spec.board = $('srcBoard').value; const b = boardInfo(spec.board) || {};
    spec.firmware = b.default_firmware || ''; spec.cfg_id = (cfgsFor(spec.board)[0] || {}).id || ''; spec.cli_port = spec.data_port = ''; spec.dca1000 = null; spec.skipSet = false; specChanged();
  });
  $('srcCfg').addEventListener('change', () => { spec.cfg_id = $('srcCfg').value; specChanged(); });
  $('srcSkip').addEventListener('change', () => { spec.skip = $('srcSkip').checked; spec.skipSet = true; specChanged(); });
  $('srcFile').addEventListener('change', () => { autoDialect(); renderState(); });
  $('srcStart').onclick = start; $('srcStop').onclick = stop;
  $('srcMore').onclick = () => dispatchEvent(new CustomEvent('goto-tab', { detail: 'run' }));
  addEventListener('spec-changed', () => { fillFiles(); renderPicker(); });
  onSession(renderState);
  C.ready = true; fillFiles(); renderPicker();
}
