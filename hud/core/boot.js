/* ============================================================
   Boot readout: the lines that type out under "RAYO" while the HUD starts.
   The typing and timing are CSS (index.html, STARTUP SEQUENCE). This file
   only writes the text: placeholders at once, then real stats from the first
   live update (hud.js fires rayo:data), then it stops listening. No loops.
   ============================================================ */
(() => {
  'use strict';
  const box = document.getElementById('bootlog');
  if (!box) return;
  const esc = (x) => String(x).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  // each line: [label, value, state] — state '' | 'warn' | 'bad'
  // The six line elements (and their timing) live in index.html, so the typing runs from
  // page load; only their text changes here, which never restarts the animation.
  function render(lines) {
    lines.forEach(([k, v, st = ''], i) => {
      const n = box.children[i]; if (!n) return;
      n.innerHTML = `&gt; ${esc(k)} <b class="${st}">${esc(v)}</b>`;
    });
  }

  render([
    ['SYSTEMS CHECK', '...'], ['CORE', '...'], ['POWER', '...'],
    ['LINK', '...'], ['SECURITY', '...'], ['RAYO', 'ONLINE · READY AT YOUR ORDERS'],
  ]);

  function fill(e) {
    const d = e.detail || {};
    if (d.mock) return;
    removeEventListener('rayo:data', fill);
    const hot = d.sys_state === 'HOT';
    const pw = d.charging ? `${Math.round(d.battery)}% · CHARGING`
      : d.plugged ? `${Math.round(d.battery)}% · PLUGGED IN${d.charge_limit ? ` · HELD AT ${d.charge_limit}%` : ''}`
      : `${Math.round(d.battery)}% · ON BATTERY${d.batt_min ? ` · ~${d.batt_min} MIN` : ''}`;
    const t = d.threat || {};
    const sec = t.bad ? [`${t.bad} PROBLEM${t.bad > 1 ? 'S' : ''} OPEN`, 'bad']
      : t.warn ? [`CLEAR · ${t.warn} NOTE${t.warn > 1 ? 'S' : ''}`, ''] : ['CLEAR', ''];
    render([
      ['SYSTEMS CHECK', hot ? 'RUNNING HOT' : 'NOMINAL', hot ? 'warn' : ''],
      ['CORE', `${d.cpu_temp != null ? d.cpu_temp + '°C · ' : ''}CPU ${Math.round(d.cpu || 0)}% · MEM ${d.mem_used}/${d.mem_total} GB`, ''],
      ['POWER', pw, d.power === 'low' ? 'bad' : ''],
      ['LINK', d.ssid ? `${d.ssid.slice(0, 22)} · ${d.signal ?? '--'}%` : 'OFFLINE', d.ssid ? '' : 'warn'],
      ['SECURITY', ...sec],
      ['RAYO', 'ONLINE · READY AT YOUR ORDERS', ''],
    ]);
  }
  addEventListener('rayo:data', fill);
})();
