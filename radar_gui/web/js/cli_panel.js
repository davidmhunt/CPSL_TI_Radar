// Board command transcript panel, shared by the Radar tab (under the log) and the Live Source card.
// Entry shape (driver `cli` list): {seq, i, n, tag, cmd, ok, verdict: DONE|ERROR|TIMEOUT|SKIP, reply, ms}.
// Collapsed when every command was answered Done; auto-opened (once per failure) with the first failing row red and
// scrolled into view. Tolerates a backend that sends no transcript: the panel just stays hidden.
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const isProbe = e => !!e.probe || e.tag === 'id';   // firmware identify questions, not cfg commands
const bad = e => !isProbe(e) && (e.verdict === 'ERROR' || e.verdict === 'TIMEOUT');

export function mountCliPanel(host, opts = {}) {   // opts.compact: stacked rows for a narrow card (Live Source)
  if (!host) return { setFirmware() {}, update() {}, merge() {}, upsert() {}, clear() {} };
  host.hidden = true; host.className = 'clipanel';
  host.innerHTML = '<details><summary></summary><div class="cliscroll"><table class="clitbl"></table></div></details>';
  host.classList.toggle('compact', !!opts.compact);
  const det = host.querySelector('details'), sum = host.querySelector('summary'), tbl = host.querySelector('table');
  let list = [], lastFail = null, fw = null;   // fw: the driver's firmware verdict ({verdict, expected, found}) for the probe rows
  function render() {
    if (!list.length) { host.hidden = true; lastFail = null; return; }
    host.hidden = false;
    const ff = list.find(bad), sent = list.filter(e => e.verdict !== 'SKIP' && !isProbe(e)).length, probes = list.filter(isProbe).length, skipped = list.filter(e => e.verdict === 'SKIP').length;
    sum.innerHTML = `Board commands (${sent} sent${skipped ? ` · ${skipped} skipped` : ''}${probes ? ` · ${probes} firmware probe${probes > 1 ? 's' : ''}` : ''} · ` +
      (ff ? `<span class="clibad">first failure: line ${ff.seq}</span>` : 'all Done') + ')';
    // a probe's outcome comes from the driver's `firmware:` verdict, never from the reply text (a "not recognized" reply is the normal answer)
    const probeText = e => 'firmware probe' + (fw && fw.verdict ? `: ${fw.verdict}` + (fw.expected ? ` (expected ${fw.expected})` : '') : '');
    const label = e => isProbe(e) ? probeText(e) : e.verdict === 'SKIP' ? 'skipped' : e.verdict.toLowerCase().replace(/^./, c => c.toUpperCase());
    const tagOf = e => e.tag && e.tag !== 'skip' && e.tag !== 'id' ? ` <span class="muted">[${esc(e.tag)}]</span>` : '';
    const cls = e => bad(e) ? 'clirow bad' : isProbe(e) ? 'clirow probe' : e.verdict === 'SKIP' ? 'clirow skip' : 'clirow';
    tbl.innerHTML = opts.compact
      ? list.map(e => `<tbody class="${cls(e)}" data-seq="${e.seq}"><tr><td class="clin">${e.seq}</td><td class="clicmd">${esc(e.cmd)}${tagOf(e)}</td>` +
          `<td class="cliv">${label(e)}${e.ms == null ? '' : ` <span class="muted">${esc(e.ms)} ms</span>`}</td></tr>` +
          (e.reply ? `<tr><td class="clin"></td><td colspan="2" class="clirep">${esc(e.reply)}</td></tr>` : '') + '</tbody>').join('')
      : '<tr><th>#</th><th>command</th><th>result</th><th>board reply</th><th>ms</th></tr>' + list.map(e =>
          `<tr class="${cls(e)}" data-seq="${e.seq}"><td>${e.seq}</td><td class="clicmd">${esc(e.cmd)}${tagOf(e)}</td><td class="cliv">${label(e)}</td>` +
          `<td class="clirep">${esc(e.reply)}</td><td>${e.ms == null ? '' : esc(e.ms)}</td></tr>`).join('');
    const failSeq = ff ? ff.seq : null;
    if (failSeq && failSeq !== lastFail) {          // a new failure: open and scroll to it (a user collapse is respected after that)
      det.open = true;
      const row = tbl.querySelector(`[data-seq="${failSeq}"]`);
      if (row) setTimeout(() => row.scrollIntoView({ block: 'nearest' }), 0);
    } else if (!failSeq && lastFail) det.open = false;
    lastFail = failSeq;
  }
  return {
    setFirmware(f) { fw = f || null; render(); },
    update(entries) { list = Array.isArray(entries) ? entries.slice() : []; render(); },
    merge(entries) { if (!Array.isArray(entries)) return; for (const e of entries) { const k = list.findIndex(x => x.seq === e.seq); if (k >= 0) list[k] = e; else list.push(e); } list.sort((a, b) => a.seq - b.seq); render(); },
    upsert(entry) { if (!entry || entry.seq == null) return; const k = list.findIndex(e => e.seq === entry.seq); if (k >= 0) list[k] = entry; else list.push(entry); render(); },
    clear() { list = []; lastFail = null; det.open = false; render(); },
  };
}
