// Configs tab (radar-40): browse every saved (config/user/) and shipped (config/system, config/radar) configuration, promote a
// saved setup to a shipped one, delete saved or shipped files. GET /api/configs, /api/configs/file, POST /api/configs/promote
// and /api/configs/delete (each with ?dry=1 for the exact preview shown before any confirm). All server text goes in through
// textContent. The GUI never runs git: it shows what changed in the tree and says what to commit. A server without these
// endpoints shows a "restart the GUI" hint and nothing else breaks.
import { $ } from './state.js';
import { api, detailText } from './session.js';

const C = { items: [], sel: new Set(), cur: null, ready: false, filter: '', data: null, plan: null };
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; };
const fmtSize = n => n < 1024 ? `${n} B` : `${(n / 1024).toFixed(1)} KiB`;
const missing = res => res.status === 404 || res.status === 405 || res.status === 0;
const byId = id => C.items.find(i => i.id === id);
const label = id => { const i = byId(id); return i ? `${i.group === 'user' ? 'saved' : 'shipped'} ${i.rel.replace(/^(system|radar)\//, '')}` : id; };
const writesOff = () => C.data && C.data.shipped_writes && !C.data.shipped_writes.enabled;

function msg(text, cls) { const m = $('cgMsg'); m.hidden = !text; m.textContent = text || ''; m.className = 'runmsg ' + (cls || 'bad'); }
// error text of a response: a string detail, or an object {message, exists, referenced_by, refused}
function errText(res) {
  const d = res.j && res.j.detail;
  if (d && typeof d === 'object' && !Array.isArray(d)) {
    const out = [d.message || 'refused'];
    if (d.exists) out.push('Already exists: ' + d.exists.map(label).join(', '));
    if (d.referenced_by) {
      if (Array.isArray(d.referenced_by)) { if (d.referenced_by.length) out.push('Referenced by: ' + d.referenced_by.map(label).join(', ')); }
      else for (const [k, v] of Object.entries(d.referenced_by)) out.push(`${label(k)} is referenced by: ${v.map(x => (x.includes(':') ? label(x) : x)).join(', ')}`);
    }
    if (d.refused) for (const x of d.refused) out.push(`${label(x.id)}: ${x.why}`);
    if (d.shipped) out.push('Shipped: ' + d.shipped.map(label).join(', '));
    return out.join('\n');
  }
  return detailText(res);
}

async function load(keepMsg) {
  const res = await api('/api/configs');
  if (!res.ok) { msg(missing(res) ? 'This GUI server is older than the Configs tab: restart the GUI to enable it.' : errText(res)); return; }
  if (keepMsg !== true) msg('');
  C.data = res.j; C.items = res.j.configs || [];
  C.sel = new Set([...C.sel].filter(id => byId(id) && !byId(id).in_use));
  if (C.cur && !byId(C.cur)) C.cur = null;
  $('cgRoot').textContent = res.j.config_dir || '';
  status(); render(); if (!C.cur) { $('cgText').textContent = 'Choose a file and press its name.'; $('cgTitle').textContent = 'File'; $('cgPromote').hidden = true; }
}

function status() {
  const g = C.data.git || {}, w = C.data.shipped_writes || {}, box = $('cgStatus'); box.textContent = '';
  if (g.available) {
    const n = (g.dirty || []).length;
    box.append(el('div', n ? 'cgwarn' : 'cgok', n
      ? `${n} uncommitted config change${n > 1 ? 's' : ''} in CPSL_TI_Radar${g.branch ? ` (${g.branch})` : ''}: commit them (git add / git commit in the CPSL_TI_Radar folder), or the Sensors picker will consider this repo dirty and refuse to deinitialise it.`
      : `No uncommitted changes in the shipped configs${g.branch ? ` (${g.branch})` : ''}.`));
    if (n) { const pre = el('pre', 'cgdirty', g.dirty.join('\n')); box.append(pre); }
  } else box.append(el('div', 'muted', 'git status unavailable' + (g.note ? `: ${g.note}` : '') + '. Changes to shipped files are not shown here.'));
  box.append(el('div', w.enabled ? 'cgok' : 'cgwarn', w.enabled
    ? 'Shipped configs are writable from this GUI (promote and delete need an explicit confirm). The GUI never commits.'
    : `Shipped configs are read-only from this GUI: ${w.reason}`));
}

function chips(i) {
  const d = el('span', 'cgchips');
  const add = (t, cls, title) => { const b = el('span', 'badge ' + (cls || ''), t); if (title) b.title = title; d.append(' ', b); };
  if (i.gui_board) add(i.gui_board);
  if (i.firmware) add(i.firmware);
  if (i.kind === 'system_json') {
    for (const o of (i.outputs || [])) add(o);
    if (i.valid === false) add('invalid JSON', 'bad');
    else if (!i.cfg_exists) add('cfg missing', 'bad', 'radar_cfg does not resolve to a file: ' + (i.cfg_ref || ''));
  } else if ((i.referenced_by || []).length) add(`used by ${i.referenced_by.length}`, 'ok', i.referenced_by.map(label).join('\n'));
  else add('unreferenced', 'warn');
  if (i.template_of && i.template_of.length) add('firmware template', 'warn', 'Used by firmware ' + i.template_of.join(', '));
  if (i.in_use) add('in use', 'bad', 'A running driver session uses this file');
  return d;
}

function section(tbl, items, group) {
  tbl.textContent = '';
  const f = C.filter.toLowerCase();
  const rows = items.filter(i => !f || (i.rel + ' ' + (i.firmware || '') + ' ' + (i.gui_board || '')).toLowerCase().includes(f));
  if (!rows.length) { const tr = el('tr'); const td = el('td', 'muted', items.length ? 'Nothing matches the filter.' : 'Nothing here.'); td.colSpan = 3; tr.append(td); tbl.append(tr); }
  for (const i of rows) {
    const tr = el('tr'); if (C.cur === i.id) tr.className = 'cur';
    const cb = el('input'); cb.type = 'checkbox'; cb.checked = C.sel.has(i.id); cb.disabled = !!i.in_use || (group === 'shipped' && writesOff());
    cb.title = i.in_use ? 'In use by a running session' : (cb.disabled ? 'Shipped configs are read-only here' : 'Select ' + i.rel); cb.setAttribute('aria-label', 'Select ' + i.rel);
    cb.onchange = () => { if (cb.checked) C.sel.add(i.id); else C.sel.delete(i.id); buttons(); };
    const c0 = el('td'); c0.append(cb);
    const c1 = el('td', 'cgname'); const a = el('button', 'btn linkbtn', i.rel.replace(/^system\//, '').replace(/^radar\//, ''));
    a.onclick = () => view(i.id); a.title = i.path;
    c1.append(el('span', 'cgicon', i.kind === 'system_json' ? '{ } ' : '≋ '), a, chips(i));
    const c2 = el('td', 'muted', fmtSize(i.size));
    tr.append(c0, c1, c2); tbl.append(tr);
  }
}
function render() {
  section($('cgUser'), C.items.filter(i => i.group === 'user'), 'user');
  section($('cgShipped'), C.items.filter(i => i.group === 'shipped'), 'shipped');
  $('cgCounts').textContent = `${C.items.filter(i => i.group === 'user').length} saved, ${C.items.filter(i => i.group === 'shipped').length} shipped`;
  buttons();
}
function buttons() {
  const n = C.sel.size; $('cgDelete').disabled = !n; $('cgDelete').textContent = n ? `Delete selected (${n})…` : 'Delete selected…';
}

async function view(id) {
  C.cur = id; render(); closePlan();
  const i = byId(id); $('cgTitle').textContent = id;
  const res = await api('/api/configs/file?id=' + encodeURIComponent(id));
  $('cgText').textContent = res.ok ? res.j.text + (res.j.truncated ? '\n[truncated]' : '') : errText(res);
  const canPromote = i && i.group === 'user' && i.kind === 'system_json';
  $('cgPromote').hidden = !canPromote;
  if (canPromote) {
    const nm = i.name.replace(/\.json$/, '');
    $('cgName').value = nm; $('cgNote').value = '';
    $('cgFolder').textContent = `config/radar/${i.gui_board || '?'}/${i.firmware || '(no firmware)'}/`;
    $('cgPreview').disabled = !i.firmware || writesOff();
    $('cgPreview').title = !i.firmware ? 'No firmware in this JSON: use "Add firmware" on the Radar tab first' : (writesOff() ? 'Shipped configs are read-only here' : '');
  }
}

// ---- action panel (preview + confirm), shared by promote and delete ----
function closePlan() { C.plan = null; $('cgAction').hidden = true; $('cgAction').textContent = ''; }
function panel(title, lines, confirmText, onConfirm, extra) {
  const box = $('cgAction'); box.textContent = ''; box.hidden = false;
  box.append(el('h3', '', title));
  for (const l of lines) box.append(el('div', l.cls || '', l.text));
  if (extra) box.append(extra);
  const row = el('div', 'btnrow');
  const ok = el('button', 'btn danger', confirmText); ok.onclick = onConfirm;
  const no = el('button', 'btn', 'Cancel'); no.onclick = closePlan;
  row.append(ok, ' ', no); box.append(row); box.scrollIntoView({ block: 'nearest' });
  return ok;
}

async function previewPromote() {
  const id = C.cur; if (!id) return;
  const body = { id, name: $('cgName').value.trim() || undefined, note: $('cgNote').value.trim() || undefined };
  const res = await api('/api/configs/promote?dry=1', body);
  if (!res.ok) { closePlan(); msg(errText(res)); return; }
  msg(''); const j = res.j, lines = [];
  lines.push({ text: 'This writes two tracked files:' });
  for (const w of j.would_write) lines.push({ cls: 'cgfile', text: w.replace(/^shipped:/, 'config/') });
  lines.push({ text: 'The cfg is copied byte for byte; the JSON is the saved one with radar_cfg ../radar/... and no data port when the serial stream is off. This index row is added to config/README.md:' });
  lines.push({ cls: 'cgfile', text: j.readme_row.replace('<note>', body.note || 'promoted from config/user (date)') });
  let confirmText = 'Promote to shipped';
  if (j.would_replace.length) {
    lines.push({ cls: 'cgwarn', text: `This replaces existing shipped file${j.would_replace.length > 1 ? 's' : ''}: ${j.would_replace.map(x => x.replace(/^shipped:/, 'config/')).join(', ')}. The previous bytes are kept under config/user/.promote_backups/.` });
    confirmText = 'Replace shipped files';
  }
  if (j.referenced_by.length) lines.push({ cls: 'cgwarn', text: `Other shipped JSONs use the cfg being written and will change behaviour: ${j.referenced_by.map(x => x.replace(/^shipped:/, 'config/')).join(', ')}` });
  lines.push({ cls: 'muted', text: 'Nothing is committed. Afterwards commit the new files in CPSL_TI_Radar, then bump the pins in Sensors and console.' });
  panel('Promote ' + id, lines, confirmText, async () => {
    const r = await api('/api/configs/promote', { ...body, confirm_overwrite: j.would_replace.length > 0 });
    closePlan();
    if (!r.ok) { msg(errText(r)); await load(true); return; }
    msg(`${r.j.result === 'created' ? 'Created' : 'Replaced'} ${r.j.files.map(f => f.id.replace(/^shipped:/, 'config/')).join(' and ')}.`
      + (r.j.readme_updated ? ' README index updated.' : '') + (r.j.notes.length ? ' ' + r.j.notes.join(' ') : '') + ` To record it: ${r.j.commit_hint}`, 'ok');
    await load(true);
  });
}

async function previewDelete() {
  const ids = [...C.sel]; if (!ids.length) return;
  const opts = { with_cfg: false, force_referenced: false };
  const run = async () => {
    const res = await api('/api/configs/delete?dry=1', { ids, with_cfg: opts.with_cfg });
    if (!res.ok) { closePlan(); msg(errText(res)); return; }
    msg(''); const j = res.j, lines = [];
    const shipped = j.would_remove.filter(x => x.group === 'shipped'), user = j.would_remove.filter(x => x.group === 'user');
    for (const x of j.would_remove) {
      lines.push({ cls: 'cgfile', text: `${x.group === 'user' ? 'moved to config/user/.trash/' : 'deleted'}: ${label(x.id)}` });
      if (x.referenced_by.length) lines.push({ cls: 'cgwarn', text: `   referenced by: ${x.referenced_by.map(y => (y.includes(':') ? label(y) : y)).join(', ')}` });
    }
    if (shipped.length) {
      lines.push({ cls: 'cgwarn', text: 'This file is tracked in git. Deleting shows up as a change in CPSL_TI_Radar; it only reaches other machines after you commit and push it. Undo: ' + shipped.map(x => x.restore).join('; ') });
      lines.push({ cls: 'cgwarn', text: 'Console radar setups may reference a shipped JSON by name: a deleted file breaks such an entry.' });
    }
    if (user.length) lines.push({ cls: 'muted', text: 'Saved files are moved, not erased: config/user/.trash/<UTC>/ (move them back by hand to restore).' });
    for (const x of j.refused) lines.push({ cls: 'cgbad', text: `Cannot delete ${label(x.id)}: ${x.why}` });
    const extra = el('div', 'cgopts');
    const mk = (key, text) => {
      const lab = el('label', 'inl'); const cb = el('input'); cb.type = 'checkbox'; cb.checked = opts[key];
      cb.onchange = async () => { opts[key] = cb.checked; if (key === 'with_cfg') await run(); else okBtn.disabled = j.refused.length > 0 || (j.needs_force_referenced && !opts.force_referenced); };
      lab.append(cb, ' ', text); extra.append(lab);
    };
    if (ids.some(i => (byId(i) || {}).kind === 'system_json')) mk('with_cfg', 'Also delete the cfg a JSON uses, when nothing else uses it');
    if (j.needs_force_referenced) mk('force_referenced', 'Delete even though other files reference these');
    const okBtn = panel(`Delete ${j.would_remove.length} file${j.would_remove.length > 1 ? 's' : ''}`, lines, 'Delete', async () => {
      const r = await api('/api/configs/delete', { ids, confirm: true, confirm_shipped: shipped.length > 0, with_cfg: opts.with_cfg, force_referenced: opts.force_referenced });
      closePlan();
      if (!r.ok) { msg(errText(r)); await load(true); return; }
      C.sel.clear();
      const bad = r.j.results.filter(x => !x.ok);
      msg(`Deleted ${r.j.results.length - bad.length} file${r.j.results.length - bad.length === 1 ? '' : 's'}.` + (bad.length ? ' Failed: ' + bad.map(x => `${label(x.id)} (${x.error})`).join('; ') : '')
        + (r.j.notes.length ? ' ' + r.j.notes.join(' ') : ''), bad.length ? 'bad' : 'ok');
      await load(true);
    }, extra);
    okBtn.disabled = j.refused.length > 0 || (j.needs_force_referenced && !opts.force_referenced);
  };
  await run();
}

export function showConfigs() {
  if (!C.ready) {
    C.ready = true;
    $('cgRefresh').onclick = () => load(); $('cgDelete').onclick = previewDelete; $('cgPreview').onclick = previewPromote;
    $('cgFilter').oninput = () => { C.filter = $('cgFilter').value.trim(); render(); };
  }
  load();
}
