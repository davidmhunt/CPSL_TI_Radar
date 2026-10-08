// Configure tab: "Detection (CFAR)" card, rendered only from the schema the backend sends (gui-35).
// renderDetection(d, issues, onEdit): d = the `detection` block of /api/cfg/{analyze,params,detection}
// ({schema, values, editable, note, context}); onEdit(group, key, value) reports a user edit
// (group range|doppler|shared; group fov: key null, value {mode, range, doppler}).
import { $ } from './state.js';

const D = { key: '', inputs: {}, fov: null, userMode: null };   // userMode: the FOV toggle the user chose (a manual window equal to auto reads back as auto)
export function resetDetectionUi() { D.userMode = null; }
const LEVEL = { bench: 'bench-verified', source: 'source-derived', unverified: 'unverified' };
const mk = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const pow2 = n => { let p = 1; while (p < n) p *= 2; return p; };

function tip(f) { return `${f.help}  [${f.cite}]`; }

function control(f, group, onEdit) {
  let inp;
  if (f.type === 'enum') {
    inp = mk('select');
    for (const [v, txt] of Object.entries(f.options)) { const o = mk('option', null, `${v}  ${txt}`); o.value = v; inp.append(o); }
    inp.addEventListener('change', () => onEdit(group, f.key, +inp.value));
  } else if (f.type === 'bool') {
    inp = mk('input'); inp.type = 'checkbox';
    inp.addEventListener('change', () => onEdit(group, f.key, inp.checked ? 1 : 0));
  } else {
    inp = mk('input'); inp.type = 'number';
    if (f.min != null) inp.min = f.min;
    if (f.max != null) inp.max = f.max;
    inp.step = f.step != null ? f.step : (f.type === 'int' ? 1 : 'any');
    inp.addEventListener('input', () => { if (inp.value !== '' && isFinite(+inp.value)) onEdit(group, f.key, +inp.value); });
  }
  inp.setAttribute('aria-label', `${f.label}${group === 'shared' ? '' : ' (' + group + ')'}`);
  inp.title = tip(f);
  inp.dataset.group = group; inp.dataset.key = f.key;
  D.inputs[group + '/' + f.key] = { inp, f };
  return inp;
}

function build(s, onEdit) {
  const body = $('detBody'); body.replaceChildren(); D.inputs = {}; D.fov = null;
  const dirs = s.directions.length ? s.directions : ['shared'];
  const grid = mk('div', 'detgrid'); grid.style.gridTemplateColumns = `minmax(110px, 1.3fr) repeat(${dirs.length}, minmax(0, 1fr))`;
  grid.append(mk('span', 'dh', ''));
  for (const d of dirs) grid.append(mk('span', 'dh', d === 'shared' ? 'Value' : d === 'range' ? 'Range' : 'Doppler'));
  for (const f of s.fields) {
    const name = mk('span', 'dl', f.label); name.title = tip(f);
    if (f.unit) name.append(mk('small', 'unit', ' ' + f.unit));
    const help = mk('span', 'dhelp', '?'); help.title = tip(f); help.setAttribute('aria-label', 'Help: ' + f.label);
    name.append(help);
    grid.append(name);
    if (f.per_direction) for (const d of s.directions) grid.append(control(f, d, onEdit));
    else grid.append(control(f, 'shared', onEdit));
  }
  body.append(grid);
  if (s.fov) {
    const fv = mk('div', 'detfov');
    const head = mk('label', 'chk'); const man = mk('input'); man.type = 'checkbox'; man.id = 'detFovManual';
    head.append(man, document.createTextNode(' Manual field of view (' + s.fov.command + ')')); head.title = `${s.fov.help}  [${s.fov.cite}]`;
    fv.append(head);
    const row = mk('div', 'detfovrow'); const nums = {};
    for (const d of ['range', 'doppler']) {
      for (const [i, w] of [[0, 'min'], [1, 'max']]) {
        const l = mk('label', null, `${d === 'range' ? 'Range' : 'Doppler'} ${w} `); l.append(mk('small', 'unit', s.fov.units[d]));
        const n = mk('input'); n.type = 'number'; n.step = 'any'; n.id = `detFov_${d}_${w}`; l.append(n); row.append(l); nums[d + i] = n;
      }
    }
    fv.append(row, mk('div', 'muted detfovhint', ''));
    body.append(fv);
    const send = () => { D.userMode = man.checked ? 'manual' : 'auto'; onEdit('fov', null, {
      mode: man.checked ? 'manual' : 'auto',
      range: [+nums.range0.value, +nums.range1.value], doppler: [+nums.doppler0.value, +nums.doppler1.value] }); };
    man.addEventListener('change', send);
    for (const n of Object.values(nums)) n.addEventListener('input', () => { if (man.checked && n.value !== '' && isFinite(+n.value)) send(); });
    D.fov = { man, nums, hint: fv.lastChild };
  }
  const notes = mk('ul', 'detnotes'); notes.id = 'detNotes';
  for (const n of s.notes || []) notes.append(mk('li', 'muted', n));
  body.append(notes, mk('ul', 'issues detissues'));
}

function fill(values, s, ctx) {
  const active = document.activeElement;
  for (const [id, { inp, f }] of Object.entries(D.inputs)) {
    const [group, key] = id.split('/');
    const v = values && values[group] ? values[group][key] : null;
    if (inp === active || v == null) continue;
    if (f.type === 'bool') inp.checked = !!v; else inp.value = v;
  }
  const raw = D.inputs['shared/thresholdRaw'];
  if (raw && ctx && ctx.n_virtual) {      // 1443: raw log2-Q9 threshold, show the dB it means for this cfg's antenna count
    const db = values.shared.thresholdRaw * 6 / 512 * pow2(ctx.n_virtual) / ctx.n_virtual;
    const dl = raw.inp.previousElementSibling;
    if (!dl.querySelector('.dbnote')) dl.append(mk('small', 'dbnote', ''));
    dl.querySelector('.dbnote').textContent = ` = ${db.toFixed(1)} dB (${ctx.n_virtual} virtual ch.)`;
  }
  if (D.fov && values && values.fov) {
    const fv = values.fov, manual = fv.mode === 'manual' || D.userMode === 'manual';
    if (D.fov.man !== active) D.fov.man.checked = manual;
    for (const d of ['range', 'doppler']) for (const [i, w] of [[0, 'min'], [1, 'max']]) {
      const n = D.fov.nums[d + i]; n.disabled = !D.fov.man.checked; if (n !== active && fv[d]) n.value = fv[d][i];
    }
    D.fov.hint.textContent = D.fov.man.checked ? '' : 'Auto: follows the cfg\'s max range and +-max velocity.';
  }
}

export function renderDetection(d, issues, onEdit) {
  const card = $('detCard');
  if (!d) { card.hidden = true; return; }          // a backend without `detection`
  card.hidden = false;
  const s = d.schema;
  $('detBadge').textContent = s ? (LEVEL[s.level] || s.level) : '';
  $('detBadge').hidden = !s;
  const note = $('detNote');
  note.textContent = d.note || ''; note.hidden = !d.note;
  if (!s || !d.editable || !d.values) {
    D.key = ''; $('detBody').replaceChildren(); D.inputs = {}; D.fov = null;
    $('detSub').textContent = s ? 'read-only' : 'not available';
    return;
  }
  $('detSub').textContent = `${s.firmware} / ${s.variant}`;
  const key = [s.firmware, s.variant].join('/');
  if (key !== D.key) { build(s, onEdit); D.key = key; D.userMode = null; }
  fill(d.values, s, d.context);
  const ul = document.querySelector('#detBody .detissues');
  if (ul) {
    ul.replaceChildren();
    for (const i of (issues || []).filter(i => String(i.code).startsWith('cfar_'))) {
      const li = mk('li', i.level); li.title = i.source ? 'source: ' + i.source : '';
      li.append(mk('span', 'lv', i.level), document.createTextNode(i.message), mk('span', 'code', i.code)); ul.append(li);
    }
  }
}
