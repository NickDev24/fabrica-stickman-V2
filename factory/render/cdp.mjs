// Driver CDP headless para el motor de actuación (factory/render/actor_page.html).
// Cero dependencias npm: usa el WebSocket y fetch globales de Node >= 22 y Chrome del sistema.
//
//   node factory/render/cdp.mjs --frames 30 --fps 30 --out /tmp/bench [--glb x.glb] [--w 1280 --h 720]
//
// Inyecta CONFIG en el placeholder __CONFIG__ de la página, sirve el repo por HTTP local,
// llama actorFrame(t) por frame y guarda PNG. Reporta métricas de tiempo y RAM en JSON.
import { spawn } from 'node:child_process';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..', '..');

function arg(name, def = undefined) {
  const i = process.argv.indexOf('--' + name);
  return i >= 0 ? process.argv[i + 1] : def;
}
const N = parseInt(arg('frames', '30'), 10);
const DESDE = parseInt(arg('desde', '0'), 10);   // reanudido: salta frames ya en disco
const FPS = parseFloat(arg('fps', '30'));
const W = parseInt(arg('w', '1280'), 10);
const H = parseInt(arg('h', '720'), 10);
const OUT = arg('out', '/tmp/cdp-out');
const GLB = arg('glb', '');
const TIMELINE = arg('timeline', '');
const LIPSYNC = arg('lipsync', '');
const RIGMAP = arg('rigmap', '');
const PORT = parseInt(arg('port', '9333'), 10);
const FLAGS = arg('flags', '--enable-unsafe-swiftshader --use-angle=swiftshader --use-gl=angle');
const CHROME = arg('chrome', process.env.CHROME || 'google-chrome');

fs.mkdirSync(OUT, { recursive: true });

const VISAMA = { A: 0.85, B: 0.15, C: 0.55, D: 0.6, E: 0.45, F: 0.5, G: 0.35, H: 0.6, I: 0.25,
                 J: 0.4, K: 0.6, L: 0.3, M: 0.7, N: 0.4, O: 0.9, P: 0.2, Q: 0.85, R: 0.3,
                 S: 0.35, T: 0.5, U: 0.8, V: 0.45, W: 0.6, X: 0.1, Y: 0.2, Z: 0.1 };

const config = {
  w: W, h: H, visema: VISAMA,
  glb: GLB ? '/__avatar.glb' : null,
  rig_map: { morfos: {}, huesos: {} },
};
if (GLB) {
  // Con GLB se ejercitan las rutas reales de actuación: morph de boca por visema y
  // rotación de cabeza por hueso (nombres del proxy; el cloak man los reemplaza).
  config.rig_map = {
    morfos: { ojo_apertura: ['mouthRound'] },
    huesos: { cabeza_pitch: [['head', 'x', 1]], cabeza_yaw: [['chest', 'y', 1]] },
    visema_morphs: ['mouthOpen'],
  };
}
// El contrato (factory/specs/timeline_actuacion.schema.json) lo produce el director; el motor
// consume otra forma (rig/v). Adaptador en un solo punto: nadie duplica la lógica de tiempos.
function adaptar(tl, lips) {
  const segmentos = (tl.segmentos || []).map((s) => ({
    t0: s.t0, t1: s.t1, rig: s.rig || s.expresion || {},
  }));
  if (!segmentos.length) throw new Error('timeline sin segmentos');
  let cues = (tl.cues || []).map((c) => ({ t: c.t, v: c.v ?? c.visema }));
  if (!cues.length && lips && lips.mouthCues) {
    cues = lips.mouthCues.map((c) => ({ t: c.start, v: c.value }));
  }
  const dur = tl.duracion_s || segmentos[segmentos.length - 1].t1;
  const camara = (tl.camara && tl.camara.length ? tl.camara : []).map((p) => ({
    t0: p.t0, t1: p.t1, tipo: p.tipo || 'medio', mov: p.mov || 'fijo',
  }));
  return {
    total_s: dur, trans_s: tl.trans_s ?? 0.45, fps: tl.fps || FPS,
    segmentos, camara: camara.length ? camara : [{ t0: 0, t1: dur, tipo: 'medio', mov: 'fijo' }],
    cues, blinks: tl.blinks || [],
  };
}

if (RIGMAP) config.rig_map = JSON.parse(fs.readFileSync(RIGMAP, 'utf-8'));
if (TIMELINE) {
  const tl = JSON.parse(fs.readFileSync(TIMELINE, 'utf-8'));
  const lips = LIPSYNC && fs.existsSync(LIPSYNC)
    ? JSON.parse(fs.readFileSync(LIPSYNC, 'utf-8')) : null;
  config.timeline = adaptar(tl, lips);
} else {
  // Timeline sintética de benchmark: cubre el rango a renderizar con 2 estados
  // emocionales y 2 planos, para que el costo mida rig + cámara + visemas reales.
  const total = Math.max(2, N / FPS);
  const rig = (extra) => Object.assign({
    postura_roll: 0, peso: 0.1, manos_levantadas: 0, cabeza_pitch: 2, cabeza_yaw: 0,
    cabeza_roll: 0, mirada_dx: 0, mirada_dy: 0, ojo_apertura: 1, ceja_izq: 0, ceja_der: 0,
    velocidad_gesto: 1, brazo_izq: 0.1, brazo_der: 0.1, codo_izq: 0.2, codo_der: 0.2,
    respiracion: 14,
  }, extra);
  config.timeline = {
    total_s: total, trans_s: 0.45,
    segmentos: [
      { t0: 0, t1: total / 2, rig: rig({}) },
      { t0: total / 2, t1: total, rig: rig({ ojo_apertura: 1.25, ceja_izq: 0.4, cabeza_pitch: -4, manos_levantadas: 0.6 }) },
    ],
    camara: [
      { t0: 0, t1: total / 2, tipo: 'medio', mov: 'zoom_lento' },
      { t0: total / 2, t1: total, tipo: 'primer_plano', mov: 'acercamiento_lento' },
    ],
    cues: Array.from({ length: Math.round(total * 12) }, (_, i) => ({ t: i / 12, v: 'AEIOX'[i % 5] })),
    blinks: Array.from({ length: Math.max(1, Math.round(total / 4)) }, (_, i) => 2 + i * 4),
  };
}

const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.json': 'application/json',
               '.glb': 'model/gltf-binary', '.gltf': 'model/gltf+json', '.png': 'image/png',
               '.bin': 'application/octet-stream', '.wasm': 'application/wasm' };

const server = http.createServer((req, res) => {
  const rel = decodeURIComponent(req.url.split('?')[0]);
  if (rel === '/__avatar.glb') {
    // El GLB puede vivir fuera del repo (benchmarks en /tmp); se sirve solo esta ruta.
    const f = path.resolve(ROOT, GLB);
    if (!GLB || !fs.existsSync(f)) { res.writeHead(404); return res.end('no glb'); }
    res.writeHead(200, { 'Content-Type': 'model/gltf-binary' });
    return fs.createReadStream(f).pipe(res);
  }
  const file = path.join(ROOT, rel);
  if (!file.startsWith(ROOT)) { res.writeHead(403); return res.end(); }
  if (rel === '/' || rel === '/actor') {
    let html = fs.readFileSync(path.join(HERE, 'actor_page.html'), 'utf-8');
    const json = JSON.stringify(config);
    if (!html.includes('const CONFIG = __CONFIG__;')) {
      throw new Error('actor_page.html perdió el ancla "const CONFIG = __CONFIG__;"');
    }
    html = html.replace('const CONFIG = __CONFIG__;', 'const CONFIG = ' + json + ';');
    res.writeHead(200, { 'Content-Type': 'text/html' });
    return res.end(html);
  }
  if (!fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404); return res.end('404'); }
  res.writeHead(200, { 'Content-Type': MIME[path.extname(file)] || 'application/octet-stream' });
  fs.createReadStream(file).pipe(res);
});
await new Promise((ok) => server.listen(0, '127.0.0.1', ok));
const BASE = `http://127.0.0.1:${server.address().port}`;

const PERFIL = fs.mkdtempSync(path.join(os.tmpdir(), 'actor-cdp-'));
const chrome = spawn(CHROME, [
  '--headless=new', `--remote-debugging-port=${PORT}`, `--user-data-dir=${PERFIL}`,
  '--remote-allow-origins=*',
  '--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu-sandbox',
  '--hide-scrollbars', '--mute-audio', '--disable-extensions', '--no-first-run',
  '--disable-background-timer-throttling', '--disable-renderer-backgrounding',
  '--window-size=' + W + ',' + H, ...FLAGS.split(' ').filter(Boolean), 'about:blank',
], { stdio: ['ignore', 'ignore', 'pipe'] });
let chromeErr = '';
chrome.stderr.on('data', (d) => { chromeErr += d.toString(); });

// RAM pico del árbol de procesos de Chrome, muestreada cada 200 ms
import { spawnSync } from 'node:child_process';
function treeRSS(rootPid) {
  const r = spawnSync('ps', ['-eo', 'pid,ppid,rss,comm'], { encoding: 'utf-8' });
  if (r.status !== 0) return 0;
  const kids = new Map();
  for (const line of r.stdout.split('\n').slice(1)) {
    const [pid, ppid, rss] = line.trim().split(/\s+/);
    if (!kids.has(ppid)) kids.set(ppid, []);
    kids.get(ppid).push([pid, Number(rss) || 0]);
  }
  let total = 0;
  const stack = [String(rootPid)];
  while (stack.length) {
    const pid = stack.pop();
    for (const [k, rss] of kids.get(pid) || []) { stack.push(k); total += rss; }
    const self = r.stdout.split('\n').find((l) => l.trim().startsWith(pid + ' '));
    if (self) total += Number(self.trim().split(/\s+/)[2]) || 0;
  }
  return total;
}
let peakRSS = 0;
const memTimer = setInterval(() => {
  const v = treeRSS(chrome.pid);
  if (v > peakRSS) peakRSS = v;
}, 200);

async function waitTarget(timeoutMs = 30000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    try {
      const r = await fetch(`http://127.0.0.1:${PORT}/json/version`);
      if (r.ok) return r.json();
    } catch { /* aún no escucha */ }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error('Chrome no respondió por CDP\n' + chromeErr.slice(-800));
}

const version = await waitTarget();
const ws = new WebSocket(version.webSocketDebuggerUrl);
await new Promise((ok, no) => { ws.onopen = ok; ws.onerror = no; });

let msgId = 0;
const pending = new Map();
const consola = [];
ws.onmessage = (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); return; }
  if (m.method === 'Runtime.consoleAPICalled') {
    consola.push((m.params.type || 'log') + ': ' + m.params.args.map((a) => a.value ?? a.description ?? a.type).join(' '));
  }
  if (m.method === 'Runtime.exceptionThrown') {
    const d = m.params.exceptionDetails;
    consola.push('EXCEPCIÓN: ' + (d.exception && (d.exception.description || d.exception.value) || d.text));
  }
  if (m.method === 'Log.entryAdded') consola.push('LOG: ' + m.params.entry.text);
};
function send(method, params = {}, sessionId = undefined) {
  return new Promise((ok, no) => {
    const id = ++msgId;
    pending.set(id, (m) => (m.error ? no(new Error(`${method}: ${m.error.message}`)) : ok(m.result || {})));
    ws.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
  });
}

const created = await send('Target.createTarget', { url: 'about:blank' });
const attached = await send('Target.attachToTarget', { targetId: created.targetId, flatten: true });
const sessionId = attached.sessionId;
if (!sessionId) throw new Error('Target.attachToTarget no devolvió sessionId: ' + JSON.stringify(attached));
await send('Runtime.enable', {}, sessionId);
await send('Page.enable', {}, sessionId);
await send('Log.enable', {}, sessionId).catch(() => {});
const evalIn = async (expr, ap = false) => {
  const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: ap, returnByValue: true }, sessionId);
  if (r.exceptionDetails) {
    throw new Error('JS página: ' + JSON.stringify(r.exceptionDetails.exception || r.exceptionDetails).slice(0, 700));
  }
  return r.result.value;
};

const t0 = Date.now();
await send('Page.navigate', { url: BASE + '/actor' }, sessionId);
let listo = false, ultimoErr = null;
for (let i = 0; i < 120; i++) {
  try { listo = await evalIn('typeof window.actorInit === "function"'); }
  catch (e) { ultimoErr = e; }
  if (listo) break;
  await new Promise((r) => setTimeout(r, 250));
}
if (!listo) throw new Error('la página no expuso actorInit:\n' + consola.join('\n') + '\nchrome: ' + chromeErr.slice(-600));
if (config.timeline) await evalIn(`window.actorCargar(${JSON.stringify(config.timeline)})`);
const init = await evalIn('window.actorInit()', true);
const loadMs = Date.now() - t0;
if (GLB && init.modo !== 'glb') {
  throw new Error('se pidió --glb pero el motor cayó a ' + init.modo + ' (GLB NO cargó):\n'
    + consola.slice(-15).join('\n'));
}

const tl = config.timeline;
const perFrame = [];
const aperturas = [];
let blackFrames = 0;
for (let i = DESDE; i < N; i++) {
  const t = tl ? Math.min(tl.total_s || (i / FPS), i / FPS) : i / FPS;
  const f0 = Date.now();
  const okFrame = await evalIn(`window.actorFrame(${t})`);
  if (!okFrame) throw new Error(`actorFrame(${t}) devolvió false`);
  const b64 = await evalIn('window.actorSnapshot()');
  const buf = Buffer.from(b64, 'base64');
  fs.writeFileSync(path.join(OUT, `frame_${String(i).padStart(5, '0')}.png`), buf);
  perFrame.push(Date.now() - f0);
  if (buf.length < 3000) blackFrames++;
  if (i % 4 === 0) aperturas.push(await evalIn('window.actorEstado().apertura_boca'));
}
const renderMs = perFrame.reduce((a, b) => a + b, 0);
const nRend = perFrame.length || 1;

clearInterval(memTimer);
ws.close();
chrome.kill('SIGTERM');
server.close();

const sorted = [...perFrame].sort((a, b) => a - b);
const report = {
  chrome: CHROME, flags: FLAGS, resolucion: `${W}x${H}`, frames: N, fps: FPS,
  frames_desde: DESDE, frames_renderizados: perFrame.length,
  modo_render: init && init.modo,
  morfos_detectados: init && init.registro ? init.registro.morfos.length : 0,
  huesos_detectados: init && init.registro ? init.registro.huesos.length : 0,
  carga_inicial_ms: loadMs,
  render_total_ms: renderMs,
  frame_ms_mediana: sorted[Math.floor(sorted.length / 2)],
  frame_ms_p95: sorted[Math.floor(sorted.length * 0.95)],
  fps_real: +(1000 / (renderMs / nRend)).toFixed(2),
  proyeccion_30s_ms: Math.round((renderMs / nRend) * 30 * FPS),
  ram_pico_mb: Math.round(peakRSS / 1024),
  frames_sospechosos_negros: blackFrames,
  boca: {
    muestreada: aperturas.length,
    activas: aperturas.filter((a) => a > 0.15).length,
    apertura_max: aperturas.length ? +Math.max(...aperturas).toFixed(3) : 0,
    reposo: aperturas.filter((a) => a <= 0.15).length,
  },
  cpu_nucleos: os.cpus().length,
  glb: GLB || null,
  salida_frames: OUT,
  tiempos_por_frame_ms: perFrame,
};
fs.writeFileSync(path.join(OUT, 'benchmark.json'), JSON.stringify(report, null, 1));
try {
  fs.rmSync(PERFIL, { recursive: true, force: true, maxRetries: 10, retryDelay: 300 });
} catch (e) {
  console.error('aviso: perfil temporal sin borrar', PERFIL, e.code);
}
console.log(JSON.stringify(report, null, 1));
