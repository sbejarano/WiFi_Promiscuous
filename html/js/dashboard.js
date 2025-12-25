sbejarano@raspberry-01:/var/www/html/wifi/js $ cat dashboard.js
/*  WiFi Promiscuous Dashboard – 70 mph trilateration eye
 *  Reads the JSON keys your Python service produces:
 *   _node, _ts, sweep, sample, etc.
 *  - LEFT / RIGHT : 6-cycle buffer (8 s)  – directional discrimination
 *  - Hybrid       : 3-s rolling buffer   – all 12 XIAO promisc
 *  - Node column visible, NO manufacturer column
 * --------------------------------------------------------------- */
const DATA = {
  gps:    "data/gps.json",
  system: "data/system.json",
  leftNode:  "data/wifi_node_LEFT.json",
  rightNode: "data/wifi_node_RIGHT.json",
  hybrid: "data/wifi_devices.json"   // not used – we build from nodes 1-12
};

const POLL_MS            = 1000; // browser poll
const MAX_LR_CYCLES      = 6;    // LEFT / RIGHT
const LR_CYCLE_MS        = 8000; // 8-s window
const HYBRID_WINDOW_MS   = 3000; // 3-s speed buffer

/* ---------- caches ---------- */
const leftCycles   = new Map(); // cycle -> Map<bssid, record>
const rightCycles  = new Map();
const hybridBuffer = new Map(); // bssid -> record  (3-s rolling)

/* ---------- helpers ---------- */
function nowMs() { return Date.now(); }

function rssiClass(rssi) {
  if (rssi >= -60) return "rssi-strong";
  if (rssi >= -75) return "rssi-medium";
  return "rssi-weak";
}

function toNum(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function fixDec(v, decimals = 6) {
  const n = toNum(v);
  if (n === null) return "---";
  return n.toFixed(decimals);
}

async function fetchJSON(url) {
  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

function normalizeRecord(obj, fallbackNode = null) {
  if (!obj || typeof obj !== "object") return null;

  let bssid = (obj.bssid || obj.BSSID || "").toString().trim();
  if (!bssid) return null;
  bssid = bssid.replace(/:/g, "").toUpperCase();

  let ssid = (obj.ssid ?? obj.SSID ?? "").toString().trim();
  if (!ssid || ssid.toLowerCase() === "hidden") return null;
  if (ssid.length > 20) ssid = ssid.slice(0, 20);

  const rssi = toNum(obj.rssi ?? obj.RSSI);
  const ch   = obj.ch ?? obj.chan ?? obj.channel ?? obj.CH;
  const node = obj._node ?? obj.node ?? fallbackNode;
  const cycle = obj.sweep ?? obj.scan_cycle ?? Math.floor(Date.now() / LR_CYCLE_MS);
  const ts   = obj._ts   ?? nowMs() / 1000; // PPS time if present

  return {
    bssid,
    ssid,
    rssi: (rssi === null ? -999 : Math.trunc(rssi)),
    ch:   (ch === undefined || ch === null || ch === "" ? "" : String(ch)),
    node: (node === undefined || node === null || node === "" ? "" : String(node)),
    seen: ts * 1000, // ms for browser
    cycle
  };
}

/* ---------- LEFT / RIGHT rolling buffer ---------- */
function ingestLR(buffer, rec) {
  if (!rec) return;
  const cycle = rec.cycle ?? Math.floor(Date.now() / LR_CYCLE_MS);
  if (!buffer.has(cycle)) buffer.set(cycle, new Map());
  const map = buffer.get(cycle);
  const old = map.get(rec.bssid);
  if (!old || rec.rssi > old.rssi) map.set(rec.bssid, rec);
  if (buffer.size > MAX_LR_CYCLES) {
    const oldest = [...buffer.keys()].sort()[0];
    buffer.delete(oldest);
  }
}

function buildLRCache(buffer) {
  const out = new Map();
  for (const map of buffer.values()) {
    for (const [bssid, rec] of map) {
      const old = out.get(bssid);
      if (!old || rec.rssi > old.rssi) out.set(bssid, rec);
    }
  }
  return out;
}

/* ---------- Hybrid 3-s speed buffer ---------- */
function ingestHybrid(rec) {
  if (!rec) return;
  const old = hybridBuffer.get(rec.bssid);
  if (!old || rec.rssi > old.rssi) hybridBuffer.set(rec.bssid, rec);
}

function buildHybridCache() {
  const cut = nowMs() - HYBRID_WINDOW_MS;
  for (const [k, v] of hybridBuffer.entries()) {
    if (v.seen < cut) hybridBuffer.delete(k);
  }
  return hybridBuffer;
}

/* ---------- renderers ---------- */
function renderGPS(gps, system) {
  const fix  = (gps && gps.fix) ? gps.fix : "---";
  const pps  = (gps && gps.pps_epoch) ? "LOCKED" : "NO LOCK";
  const sats = (gps && gps.sats !== undefined) ? gps.sats : "---";

  const lat = fixDec(gps ? gps.lat : null, 6);
  const lon = fixDec(gps ? gps.lon : null, 6);

  const altN = toNum(gps ? gps.alt : null);
  const alt  = (altN === null) ? "---" : altN.toFixed(1);

  const hb = (system && system.heartbeat) ? system.heartbeat : {};
  const hbKeys = [...Array.from({ length: 12 }, (_, i) => String(i + 1)), "gps","GPS","LEFT","RIGHT","pps","PPS"];

  function hbDot(ts) {
    const t = toNum(ts);
    if (t === null) return `<span class="dot off">○</span>`;
    return ((Date.now()/1000 - t) < 2)
      ? `<span class="dot on">●</span>`
      : `<span class="dot off">○</span>`;
  }

  return `
    <h2>GPS / PPS</h2>
    <div class="kv">
      <div class="k">Fix:</div><div class="v">${fix}</div>
      <div class="k">PPS:</div><div class="v">${pps}</div>
      <div class="k">Sats:</div><div class="v">${sats}</div>
      <div class="k">Lat:</div><div class="v">${lat}</div>
      <div class="k">Lon:</div><div class="v">${lon}</div>
      <div class="k">Alt:</div><div class="v">${alt}</div>
    </div>
    <div class="hb-title">ESP32 Heartbeat</div>
    ${hbKeys.map(k => `<div class="hb-row"><span>Node ${k}:</span>${hbDot(hb[k])}</div>`).join("")}`;
}

function sortByRssiDesc(arr) {
  return arr.sort((a, b) => (b.rssi ?? -999) - (a.rssi ?? -999));
}

function renderDirectional(title, cache) {
  const rows = sortByRssiDesc(Array.from(cache.values()));
  if (!rows.length) return `<h2>${title}</h2><div class="muted">No data</div>`;

  return `
    <h2>${title}</h2>
    <table>
      <thead>
        <tr><th>BSSID</th><th>RSSI</th><th>CH</th><th class="ssid">SSID</th></tr>
      </thead>
      <tbody>
        ${rows.map(d => `
          <tr>
            <td>${d.bssid}</td>
            <td class="${rssiClass(d.rssi)}">${d.rssi}</td>
            <td>${d.ch}</td>
            <td class="ssid">${d.ssid}</td>
          </tr>`).join("")}
      </tbody>
    </table>`;
}

function renderHybrid(cache) {
  const rows = sortByRssiDesc(Array.from(cache.values()));
  if (!rows.length) return `<h2>Hybrid / Promiscuous Devices</h2><div class="muted">No data</div>`;

  return `
    <h2>Hybrid / Promiscuous Devices</h2>
    <table>
      <thead>
        <tr><th>BSSID</th><th>RSSI</th><th>Node</th><th>CH</th><th class="ssid">SSID</th></tr>
      </thead>
      <tbody>
        ${rows.map(d => `
          <tr>
            <td>${d.bssid}</td>
            <td class="${rssiClass(d.rssi)}">${d.rssi}</td>
            <td>${d.node ?? ''}</td>
            <td>${d.ch}</td>
            <td class="ssid">${d.ssid}</td>
          </tr>`).join("")}
      </tbody>
    </table>`;
}

/* ---------- polling ---------- */
async function pollOnce() {
  const [gps, system] = await Promise.all([
    fetchJSON(DATA.gps),
    fetchJSON(DATA.system)
  ]);

  /* ----- LEFT / RIGHT directional ----- */
  const [lRaw, rRaw] = await Promise.all([
    fetchJSON(DATA.leftNode),
    fetchJSON(DATA.rightNode)
  ]);
  ingestLR(leftCycles,  normalizeRecord(lRaw, "LEFT"));
  ingestLR(rightCycles, normalizeRecord(rRaw, "RIGHT"));
  const cacheLeft  = buildLRCache(leftCycles);
  const cacheRight = buildLRCache(rightCycles);

  /* ----- 12 XIAO promiscuous (1 channel each) ----- */
  const nodeUrls = Array.from({ length: 12 }, (_, i) => `data/wifi_node_${i+1}.json`);
  const nodeJsons = await Promise.all(nodeUrls.map(fetchJSON));
  nodeJsons.forEach((obj, idx) => {
    const rec = normalizeRecord(obj, String(idx + 1));
    if (rec) ingestHybrid(rec);
  });
  const cacheHybrid = buildHybridCache();

  /* ----- paint ----- */
  document.getElementById("gps-panel").innerHTML    = renderGPS(gps, system);
  document.getElementById("left-panel").innerHTML   = renderDirectional("LEFT", cacheLeft);
  document.getElementById("right-panel").innerHTML  = renderDirectional("RIGHT", cacheRight);
  document.getElementById("hybrid-panel").innerHTML = renderHybrid(cacheHybrid);
}

/* ---------- DB button → systemd ---------- */
const dbBtn   = document.getElementById('dbBtn');
const dbStat  = document.getElementById('dbStatus');

dbBtn.onclick = async () => {
  const cmd = dbBtn.textContent === 'Start DB' ? 'start' : 'stop';
  await fetch(`db_ctl.php?cmd=${cmd}`);
  // toggle UI
  dbBtn.textContent = cmd === 'start' ? 'Stop DB' : 'Start DB';
  dbBtn.style.background = cmd === 'start' ? 'red' : 'green';
  dbStat.textContent = cmd === 'start' ? 'DB ON' : 'DB OFF';
};

/* ---------- main loop ---------- */
(async function loop() {
  await pollOnce();
  setTimeout(loop, POLL_MS);
})();
