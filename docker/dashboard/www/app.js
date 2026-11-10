/* PULSO Curioso — red social de la fábrica (vanilla, cero dependencias).
   Datos reales: /api/estado + /api/galeria + /ws (factoryd).
   Vistas: inicio · video · comics · metricas · conectores · agentes · transmision.
   Gráficos: canvas propio (sin librerías externas).                    */
"use strict";

const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

/* ─────────────── pipeline: estaciones reales de la cinta ─────────────── */
const ESTACIONES = [
  ["research",     "🔎", "Descubrimiento"],
  ["factcheck",    "🛡",  "Fact-check"],
  ["guion",        "📝", "Guion"],
  ["visuales",     "🎨", "Visuales"],
  ["narracion",    "🎙",  "Narración"],
  ["keyframes",    "🖼", "Keyframes"],
  ["montaje",      "🎞", "Montaje"],
  ["corto",        "📱", "Cortos"],
  ["derivados",    "📦", "Derivados"],
  ["publicacion",  "🚀", "Publicación"],
];

const ETIQ_VIDEO = { "Episodio completo": 1 };

const S = {
  vista: "inicio",
  estado: null,        // /api/estado
  galeria: [],         // /api/galeria
  stages: {},          // stage_status del episodio en curso
  ep: null,
  modo: "idle",
  filtro: "",
  publica: false,      // autorización de publicación (YouTube/FB vía Zernio)
  metricas: null,      // /api/metricas
  conectores: [],      // /api/conectores
  agentes: [],         // /api/agentes
  agenteSel: null,     // agente seleccionado en el editor
};

/* ───────────────────────────── utilidades ────────────────────────────── */
function fmtDur(sec) {
  sec = Math.round(sec || 0);
  if (!sec) return "";
  return sec >= 3600 ? `${Math.floor(sec / 3600)}h ${Math.round((sec % 3600) / 60)}m`
                     : `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
}
function hace(ts) {
  const seg = Math.max(0, (Date.now() / 1000) - (ts || 0));
  if (seg < 60) return "hace un momento";
  if (seg < 3600) return `hace ${Math.floor(seg / 60)} min`;
  if (seg < 86400) return `hace ${Math.floor(seg / 3600)} h`;
  return `hace ${Math.floor(seg / 86400)} días`;
}
function esc(t) { return document.createTextNode(String(t ?? "")).textContent; }
function toast(msg, cls = "") {
  const d = document.createElement("div");
  d.className = `toast ${cls}`;
  d.textContent = msg;
  $("#toasts").appendChild(d);
  setTimeout(() => d.remove(), 4500);
}
async function GET(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(url);
  return r.json();
}
async function POST(url, body) {
  const r = await fetch(url, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  if (!r.ok) throw new Error(`${url} ${r.status}`);
  return r.json();
}

/* ─────────────────────────── navegación básica ───────────────────────── */
// Estado del módulo 3D. Vive ARRIBA del archivo: `init()` corre en la línea
// final y con `#oficina3d` en la URL monta la vista en el mismo tick; si estos
// `let` quedan más abajo, el acceso cae en TDZ ("Cannot access before
// initialization") y la oficina nunca arranca cargando directo por hash.
let _of3dModulo = null, _of3dMontado = false, _of3dMontando = null;

function cambiarVista(v) {
  S.vista = v;
  $$(".vista").forEach((n) => (n.hidden = n.id !== `vista-${v}`));
  $$(".rail-item").forEach((b) => b.classList.toggle("activa", b.dataset.vista === v));
  history.replaceState(null, "", `#${v}`);
  window.scrollTo({ top: 0 });
  pintar();
  if (v === "oficina3d") montarOficina3D();
  if (v === "oficina3d" && !window._of3dPoll) {
    window._of3dPoll = setInterval(async () => {
      if (S.vista !== "oficina3d") { clearInterval(window._of3dPoll); window._of3dPoll = null; return; }
      try {
        const ofi = await GET("/api/oficina");
        if (_of3dModulo && _of3dMontado) _of3dModulo.actualizar({ agentes: ofi.agentes || [], bloqueos_humanos: {} });
      } catch {}
    }, 5000);
  }
}
async function init() {
  $$(".rail-item").forEach((b) => b.onclick = () => cambiarVista(b.dataset.vista));
  const quiet = new URLSearchParams(location.search).has("quiet");
  const h = location.hash.slice(1);
  if (["inicio", "video", "comics", "metricas", "conectores", "oficina3d"].includes(h)) {
    cambiarVista(h);
  }
  $("#btn-rail").onclick = () => $("#rail").classList.toggle("abierto");
  $("#buscar").oninput = (e) => { S.filtro = e.target.value.trim().toLowerCase(); pintarFeed(); };
  lightboxInit();
  await refrescar();
  if (quiet) return pintar();
  wsInit();
  setInterval(() => { refrescarEstado().catch(() => $("#dot-live").classList.remove("ok")); }, 5000);
  setInterval(() => { refrescarGaleria().catch(() => {}); }, 30000);
  setInterval(() => { const d = new Date();
    $("#hora").textContent = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  }, 20000);

  // control del ciclo 24/7 (mismas acciones que ya expone factoryd en /api/control)
  const control = async (accion, msg) => {
    try {
      await POST("/api/control", { accion });
      toast(msg, "good");
      await refrescarEstado();
      pintar();
    } catch (e) {
      toast("La fábrica no respondió al control", "err");
    }
  };
  $("#btn-play").onclick = () => control("play", "▶ Ciclo 24/7 lanzado");
  $("#btn-pausa").onclick = () => control("pausa", "⏸ La fábrica cierra el episodio en curso y se detiene");
  $("#btn-stop").onclick = () => control("stop", "⏹ Fábrica detenida");
  $("#btn-skip").onclick = () => control("skip", "⏭ Saltando al próximo episodio");

  // publicación (autorizar / desautorizar YouTube + Facebook vía Zernio)
  const btnPub = $("#btn-publicar");
  const chipPub = $("#chip-publica");
  btnPub.onclick = async () => {
    try {
      const siguiente = !S.publica;
      const res = await POST("/api/control", { accion: siguiente ? "publicar_on" : "publicar_off" });
      S.publica = !!res.publica;
      pintarPublica();
      toast(S.publica ? "✅ Publicación autorizada (YouTube + Facebook)" : "🔒 Publicación desautorizada", S.publica ? "good" : "");
    } catch (e) {
      toast("No se pudo cambiar la autorización de publicación", "err");
    }
  };
}
function pintarControles() {
  const play = $("#btn-play"), pausa = $("#btn-pausa"),
        stop = $("#btn-stop"), skip = $("#btn-skip");
  if (!play) return;
  const corriendo = S.modo === "corriendo";
  play.disabled = corriendo || S.modo === "deteniendo";
  pausa.disabled = !corriendo;
  stop.disabled = S.modo === "idle";
  skip.disabled = !corriendo;
};

function pintarPublica() {
  const on = !!S.publica;
  const btn = $("#btn-publicar");
  const chip = $("#chip-publica");
  btn.textContent = on ? "🔒 Desautorizar publicación" : "▶ Autorizar publicación";
  btn.className = `btn ${on ? "danger" : "primary"} small`;
  chip.className = `chip ${on ? "on" : "off"}`;
  chip.innerHTML = `<span class="led"></span>${on ? "Autorizada (YouTube + Facebook)" : "Desautorizada"}`;
}

async function refrescar() {
  await Promise.all([refrescarEstado(), refrescarGaleria()]);
  if (S.vista === "metricas") await refrescarMetricas();
  if (S.vista === "conectores") await refrescarConectores();
  pintar();
}

async function refrescarEstado() {
  S.estado = await GET("/api/estado");
  S.ep = S.estado.ep;
  S.modo = S.estado.modo || "idle";
  S.publica = !!S.estado.publish;
  const st = (S.estado.episodios || []).find((e) => e.slug === S.ep);
  if (st && st.stages) S.stages = st.stages; else if (S.modo === "idle") S.stages = {};
  if (S.modo !== "idle") {
    GET(`/api/kfs/${encodeURIComponent(S.ep)}?n=7`).then((rutas) => {
      pintarKfVivos(rutas || []);
    }).catch(() => {});
  }
  pintarTop();
  pintarPublica();
}

async function refrescarGaleria() { S.galeria = await GET("/api/galeria"); }

async function refrescarMetricas() {
  try { S.metricas = await GET("/api/metricas"); } catch { S.metricas = null; }
}
async function refrescarConectores() {
  try { S.conectores = await GET("/api/conectores"); } catch { S.conectores = []; }
}
async function refrescarAgentes() {
  try { S.agentes = await GET("/api/agentes"); } catch { S.agentes = []; }
}

function pintar() {
  pintarRailEstado();
  pintarFeed();
  if (S.vista === "video" || S.vista === "inicio") pintarCinta();
  if (S.vista === "video") pintarMetricasVideo();
  if (S.vista === "comics") pintarComics();
  if (S.vista === "metricas") pintarMetricasView();
  if (S.vista === "conectores") pintarConectores();
}

/* ─────────────────────────── datos derivados ─────────────────────────── */
function epPublicados() {
  return S.galeria.filter((e) => (e.videos || []).some((v) => ETIQ_VIDEO[v.label])
                                 || Object.keys(e.pub || {}).length);
}
function epConComics() { return S.galeria.filter((e) => e.comics); }
function totalKfs() { return S.galeria.reduce((n, e) => n + (e.kfs || []).length, 0); }
function totalVin() { return epConComics().reduce((n, e) => n + (e.comics.vinetas || 0), 0); }

/* ─────────────────────────── topbar + rail ───────────────────────────── */
function pintarTop() {
  const on = !!S.estado?.publish;
  const b = $("#badge-pub");
  b.textContent = on ? "PUBLICACIÓN ON" : "PUBLICACIÓN OFF";
  b.className = `badge ${on ? "on" : "off"}`;
}
function pintarRailEstado() {
  const chip = $("#rail-modo"), epn = $("#rail-ep"), publica = $("#rail-publica");
  if (S.modo === "corriendo") {
    chip.textContent = "PRODUCIENDO"; chip.className = "rchip on";
    const meta = epPorSlug(S.ep);
    epn.textContent = meta ? meta.titulo
      : (S.ep || "buscando la próxima historia verificada");
  } else if (S.modo === "deteniendo") {
    chip.textContent = "DETENIENDO"; chip.className = "rchip";
    epn.textContent = "cerrando el episodio en curso…";
  } else {
    chip.textContent = "EN ESPERA"; chip.className = "rchip";
    epn.textContent = `${S.estado?.episodios_hoy || 0} episodios hoy`;
  }
  publica.textContent = `Publicación: ${S.publica ? "ON" : "OFF"}`;
  pintarControles();
}
function epPorSlug(slug) { return S.galeria.find((e) => e.slug === slug); }

/* ─────────────────────────── feed de inicio ──────────────────────────── */
function bannerFabrica() {
  const barr = $("#banner-fabrica");
  const chip = $("#bf-chip");
  const titulo = $("#bf-titulo");
  const sub = $("#bf-sub");
  const epsHoy = $("#bf-eps-hoy");
  const pubEstado = $("#bf-pub-estado");
  if (S.modo === "corriendo") {
    barr.className = "banner-fab banner-hero viva";
    chip.textContent = "● PRODUCIENDO";
    chip.className = "bf-chip vivo";
    const meta = epPorSlug(S.ep);
    titulo.textContent = `Fábrica en producción${meta ? `: ${meta.titulo}` : ""}`;
    sub.textContent = meta
      ? `${S.estado?.episodios_hoy || 0} episodios hoy · ciclo 24/7 activo`
      : "verificando ideas y fuentes para el próximo episodio · ciclo 24/7 activo";
    epsHoy.textContent = S.estado?.episodios_hoy ?? 0;
    pubEstado.textContent = S.publica ? "ON" : "OFF";
    pubEstado.className = S.publica ? "bf-pub on" : "bf-pub off";
  } else {
    barr.className = "banner-fab banner-hero apagada";
    chip.textContent = "● EN ESPERA";
    chip.className = "bf-chip";
    titulo.textContent = "Fábrica en espera";
    sub.textContent = "Pulsá ▶ Play en Fábrica de Video para lanzar el ciclo 24/7";
    epsHoy.textContent = S.estado?.episodios_hoy ?? 0;
    pubEstado.textContent = S.publica ? "ON" : "OFF";
    pubEstado.className = S.publica ? "bf-pub on" : "bf-pub off";
  }
}

function cardVideoMedia(ep, video, mini = false) {
  const dur = fmtDur(video.duracion);
  const poster = ep.portada || (ep.kfs || [])[0] || "";
  if (mini) {
    return `<div class="te-media" title="${esc(video.label || "")}">
      ${poster ? `<img src="${poster}" alt="" loading="lazy">`
               : `<video src="${video.url}" preload="none"></video>`}
      ${dur ? `<span class="te-dur">${dur}</span>` : ""}
    </div>`;
  }
  return `<div class="te-media">
      <video src="${video.url}" preload="metadata" muted playsinline
             ${poster ? `poster="${poster}"` : ""}></video>
      ${dur ? `<span class="te-dur">${dur}</span>` : ""}
    </div>`;
}

function pillPub(pub) {
  const p = [];
  if (pub?.youtube) p.push(`<a class="pill yt" target="_blank" href="${esc(pub.youtube)}">YouTube</a>`);
  if (pub?.facebook) p.push(`<a class="pill fb" target="_blank" href="${esc(pub.facebook)}">Facebook</a>`);
  return p.join(" ");
}

function pintarFeed() {
  bannerFabrica();
  pintarStatsInicio();
  pintarFeedEps();
  pintarFeedComics();
}

function pintarStatsInicio() {
  const pub = S.galeria.reduce((n, e) => n + Object.keys(e.pub || {}).length, 0);
  $("#stat-episodios").textContent = S.galeria.length;
  $("#stat-publicaciones").textContent = pub;
  $("#stat-keyframes").textContent = totalKfs();
  $("#stat-vinetas").textContent = totalVin();
}

function pintarFeedEps() {
  const host = $("#feed-episodios");
  host.innerHTML = "";
  const eps = epPublicados();
  if (!eps.length) {
    host.innerHTML = `<div class="aviso" style="grid-column:1/-1">Todavía no hay episodios publicados — la fábrica está buscando su primer tema verificado.</div>`;
    return;
  }
  eps.forEach((ep, idx) => {
    const video = ((ep.videos || []).find((v) => ETIQ_VIDEO[v.label])) || (ep.videos || [])[0];
    const hero = idx === 0 && video;
    const esYT = !!ep.pub?.youtube;
    const esFB = !!ep.pub?.facebook;
    const badge = hero ? "DESTACADO" : (esYT && esFB ? "YT+FB" : esYT ? "YouTube" : esFB ? "Facebook" : "NUEVO");
    const badgeCls = hero ? "destacado" : (esYT && esFB ? "ytfb" : esYT ? "yt" : esFB ? "fb" : "nuevo");
    const card = document.createElement("article");
    card.className = "tarjeta-ep" + (hero ? " ep-hero" : "");
    card.dataset.search = `${ep.titulo} ${ep.slug} ${ep.categoria}`.toLowerCase();
    const media = video ? cardVideoMedia(ep, video, hero) : "";
    const acciones = pillPub(ep.pub);
    const qcOk = ep.comics?.qc_aprobado;
    card.innerHTML = `
      ${media}
      ${video ? `<div class="ep-badge ${badgeCls}">${badge}</div>` : ""}
      <div class="te-cuerpo" style="padding:18px 20px 20px; gap:12px;">
        <div style="display:flex; align-items:center; justify-content:space-between; gap:8px; flex-wrap:wrap;">
          <div class="te-tit-row" style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
            <h3 class="te-tit" style="margin:0; font-size:${hero?'19px':'16px'}; font-weight:800; line-height:1.25;">${esc(ep.titulo || ep.slug)}</h3>
            ${qcOk ? `<span class="pill qc" style="font-size:9px; font-weight:700;">QC APROBADO</span>` : ""}
          </div>
        </div>
        <div class="te-meta" style="font-size:12px; gap:8px; flex-wrap:wrap; align-items:center;">
          <span class="pill ${ep.categoria?'gen':''}" style="font-size:9px; font-weight:700;">${esc(ep.categoria || "")}</span>
          <span style="color:var(--tinta-2); font:600 12px var(--sans);">${hace(ep.mtime)}</span>
          ${video ? `<span style="color:var(--tinta-3); font:600 11px var(--mono);">▶ video disponible</span>` : ""}
        </div>
        <div style="display:flex; gap:8px; flex-wrap:wrap;">
          ${acciones}
          ${qcOk ? `<button class="btn outline small" style="font-size:11px; padding:6px 12px;" onclick="cambiarVista('comics')">📚 Ver cómic</button>` : ""}
        </div>
      </div>`;
    if (video) {
      card.querySelector(".te-media").onclick = () =>
        lbAbrir([{tipo: "video", url: video.url, pie: `${ep.titulo} — ${video.label}`}], 0);
      card.style.cursor = "pointer";
    }
    host.appendChild(card);
  });
  filtrarEn(host);
}

function pintarFeedComics() {
  const host = $("#feed-comics");
  host.innerHTML = "";
  const caps = epConComics();
  if (!caps.length) {
    host.innerHTML = `<div class="aviso" style="grid-column:1/-1">El taller de cómics no publicó capítulos aún (COMICS_ENABLED=1 para activarlo).</div>`;
    return;
  }
  caps.forEach((ep) => {
    const c = ep.comics;
    const pgs = c.paginas || [];
    const mini = (u) => `<img src="${u}" alt="" loading="lazy">`;
    const folio = pgs.length >= 2
      ? `${mini(pgs[0])}<span class="mitad">${pgs.slice(1, 3).map(mini).join("") || ""}</span>`
      : (pgs[0] ? mini(pgs[0]) : "");
    const card = document.createElement("article");
    card.className = "card-comic comic-hero";
    card.dataset.search = `${c.titulo_chapter || ep.titulo} ${ep.slug}`.toLowerCase();
    card.innerHTML = `
      <div class="cc-folio">${folio}</div>
      <div class="cc-cuerpo" style="padding:14px 16px; gap:8px;">
        <h3 class="cc-tit" style="margin:0; font-size:15px;">${esc(c.titulo_chapter || ep.titulo)}</h3>
        <div class="cc-meta" style="font-size:11.5px; gap:8px; flex-wrap:wrap;">
          <span class="pill ${c.qc_aprobado?'qc':'com'}" style="font-size:9px;">${c.vinetas || 0} viñetas</span>
          <span class="pill gen" style="font-size:9px;">${c.paginas?.length || 0} páginas</span>
          ${c.qc_aprobado ? `<span class="pill qc" style="font-size:9px;">QC OK</span>` : `<span class="pill com" style="font-size:9px;">en revisión</span>`}
        </div>
      </div>`;
    host.appendChild(card);
  });
  filtrarEn(host);
}

function filtrarEn(host) {
  if (!S.filtro) return;
  host.querySelectorAll("[data-search]").forEach((n) => {
    n.style.display = n.dataset.search.includes(S.filtro) ? "" : "none";
  });
}

/* ───────────────── fábrica de video: LA CINTA ───────────────────────── */
function pintarCinta() {
  const host = $("#estaciones");
  if (!host.dataset.listo) {
    host.innerHTML = ESTACIONES.map(([id, ico, nom]) =>
      `<div class="estacion" data-st="${id}"><span class="est-ico">${ico}</span><span class="est-nom">${nom}</span></div>`).join("");
    host.dataset.listo = "1";
  }
  const corriendo = S.modo === "corriendo";
  $("#cinta").classList.toggle("viva", corriendo);
  const meta = epPorSlug(S.ep);
  $("#ep-actual").innerHTML = corriendo
    ? `Episodio: <b>${esc(meta?.titulo || S.ep || "…")}</b>` : "—";

  host.querySelectorAll(".estacion").forEach((n) => {
    const st = n.dataset.st;
    const estado = S.stages?.[st] || "";
    n.className = "estacion" + (corriendo && estado ? " activa" : "");
  });
  if (corriendo) {
    host.querySelectorAll(".estacion").forEach((n) => {
      const todo = S.stages?.[n.dataset.st];
      if (todo && !n.classList.contains("activa")) { n.classList.add("hecho"); }
    });
    const done = Object.keys(S.stages || {}).filter((k) => S.stages[k]).length;
    const pct = Math.min(99, 8 + done * 9);
    $("#cinta-info").innerHTML =
      `<b>${done}/${ESTACIONES.length}</b> etapas avanzadas · reclutando: ${done ? Object.keys(S.stages).filter((k) => S.stages[k]).join(", ") : "…"} · cargando ${pct}%`;
  } else {
    host.querySelectorAll(".estacion").forEach((n) => n.classList.remove("hecho"));
    $("#cinta-info").textContent = "En espera — la fábrica no está corriendo";
  }
}

function pintarKfVivos(rutas) {
  const host = $("#kf-vivos");
  if (!rutas.length || S.modo !== "corriendo") { host.hidden = true; return; }
  host.hidden = false;
  if (host.dataset.clave === rutas.join(",")) return;
  host.dataset.clave = rutas.join(",");
  host.innerHTML = "";
  rutas.slice(-7).forEach((u, i) => {
    const im = document.createElement("img");
    im.src = u; im.loading = "lazy";
    im.style.animationDelay = `${i * 0.12}s`;
    im.onclick = () => lbAbrir([{tipo: "img", url: u, pie: "keyframe en vivo"}], 0);
    host.appendChild(im);
  });
}

/* ─────────────── fábrica de video: galerías ─────────────── */
function pintarGaleriaVideos() {
  const host = $("#galeria-videos");
  host.innerHTML = "";
  let n = 0;
  S.galeria.forEach((ep) => (ep.videos || []).forEach((v) => {
    const card = document.createElement("article");
    card.className = "tarjeta-ep tarjeta-vid";
    card.dataset.search = `${ep.titulo} ${ep.slug} ${v.label}`.toLowerCase();
    card.innerHTML = cardVideoMedia(ep, v, true) + `
      <div class="te-cuerpo">
        <h3 class="te-tit">${esc(ep.titulo || ep.slug)}</h3>
        <div class="te-meta">${esc(v.label)} · ${hace(ep.mtime)} ${pillPub(ep.pub)}</div>
      </div>`;
    card.querySelector(".te-media").onclick = () => lbAbrir([{tipo: "video", url: v.url, pie: `${ep.titulo} — ${v.label}`}], 0);
    host.appendChild(card);
    n++;
  }));
  if (!n) host.innerHTML = `<div class="aviso">Sin videos todavía.</div>`;
  filtrarEn(host);
}

function pintarGaleriaKfs() {
  const host = $("#galeria-keyframes");
  const todas = [];
  S.galeria.forEach((ep) => (ep.kfs || []).slice(-12).forEach((u) =>
    todas.push({tipo: "img", url: u, pie: `${ep.titulo} · keyframe` })));
  host.innerHTML = todas.length
    ? todas.map((it) => `<img src="${it.url}" alt="" loading="lazy">`).join("")
    : `<div class="aviso" style="grid-column:1/-1">Sin keyframes aún — llegan con el primer episodio del ciclo.</div>`;
  host.querySelectorAll("img").forEach((im, i) => im.onclick = () => lbAbrir(todas, i));
}

function pintarMetricasVideo() {
  pintarGaleriaVideos();
  pintarGaleriaKfs();
  const sys = S.estado?.sys || {};
  const q = sys.quota || {};
  const pub = S.galeria.reduce((n, e) => n + Object.keys(e.pub || {}).length, 0);
  const hoy = S.estado?.episodios_hoy ?? 0;
  $("#metricas-video").innerHTML = `
    ${mcard(hoy, "episodios hoy", "ciclo 24/7")}
    ${mcard(pub, "publicaciones activas", "YouTube + Facebook")}
    ${mcard(totalKfs(), "keyframes en archivo", "galería real del disco")}
    ${mcard(`${q.usadas || 0}<span class="u">/${q.limite || "—"}</span>`, "cuota Workers AI hoy",
            `$${(q.costo_usd || 0).toFixed(2)} USD estimados`,
            barra(q.usadas || 0, q.limite || 150))}`;
}

function mcard(num, lab, det, conBarra) {
  return `<div class="card-mtr ${conBarra ? "barra" : ""}">
    <span class="cm-num">${num}</span><span class="cm-lab">${lab}</span>
    ${det ? `<span class="cm-det">${det}</span>` : ""}${conBarra || ""}</div>`;
}
function barra(usadas, limite) {
  const pct = Math.min(100, Math.round((usadas / Math.max(1, limite)) * 100));
  const cls = pct > 85 ? "crit" : pct > 60 ? "warn" : "";
  return `<span class="barra-fina"><i class="${cls}" style="width:${pct}%"></i></span>`;
}

/* ───────────────── fábrica de cómics: EL TALLER ─────────────────────── */
function pintarComics() {
  pintarGaleriaComics();
  pintarGaleriaVinetas();
  const caps = epConComics();
  const vin = totalVin();
  const paginas = caps.reduce((n, e) => n + (e.comics.paginas?.length || 0), 0);
  const qcOk = caps.filter((e) => e.comics.qc_aprobado).length;
  $("#metricas-comics").innerHTML = `
    ${mcard(caps.length, "capítulos", "libros terminados")}
    ${mcard(vin, "viñetas", "≥ 15 por capítulo")}
    ${mcard(paginas, "páginas", "grillas de 3 bandas")}
    ${mcard(qcOk, "QC aprobado", "cinturón de seguridad")}`;
}

function pintarGaleriaComics() {
  const host = $("#galeria-comics");
  host.innerHTML = "";
  const caps = epConComics();
  if (!caps.length) {
    host.innerHTML = `<div class="aviso">El taller no tiene capítulos aún (COMICS_ENABLED=1 para activarlo).</div>`;
    return;
  }
  caps.forEach((ep) => {
    const c = ep.comics;
    const card = document.createElement("article");
    card.className = "tarjeta-ep";
    card.dataset.search = `${c.titulo_chapter || ep.titulo} ${ep.slug}`.toLowerCase();
    const grillas = (c.grillas || []).map((g) => `<span class="pill com">${g.join("/")}</span>`).join(" ");
    const folio = (c.paginas || []).map((u) =>
      `<img src="${u}" alt="" loading="lazy" data-lb="${u}">`).join("");
    card.innerHTML = `
      <div class="te-cuerpo">
        <h3 class="te-tit">${esc(c.titulo_chapter || ep.titulo)}</h3>
        ${pillPub(ep.pub)} ${c.qc_aprobado ? `<span class="pill qc">QC OK</span>` : ""}</div>
      <div class="livro-folio">${folio || `<div class="aviso" style="grid-column:1/-1">sin páginas</div>`}</div>
      <div class="cc-cuerpo">
        <div class="meta-ch">
          <div class="mc"><b>${c.vinetas || 0}</b><span>viñetas</span></div>
          <div class="mc"><b>${c.paginas?.length || 0}</b><span>páginas</span></div>
          <div class="mc"><b>${c.vinetas ? Math.round(15) : 0}</b><span>min objetivo</span></div>
        </div>
        <div class="prenda-grilla"><span class="sec-sub">grillas:</span> ${grillas || "—"}</div>
      </div>`;
    card.querySelectorAll(".livro-folio img").forEach((im, i, lista) =>
      im.onclick = () => lbAbrir(lista.map((x) => ({tipo: "img", url: x.src, pie: "página del libro"})), i));
    card.querySelector(".te-cuerpo").onclick = () => prensaArrancar(c.grillas || []);
    host.appendChild(card);
  });
  filtrarEn(host);
}

function pintarGaleriaVinetas() {
  const host = $("#galeria-vinetas");
  const todas = [];
  epConComics().forEach((ep) => (ep.comics.vinetas_imgs || []).forEach((u) =>
    todas.push({tipo: "img", url: u, pie: `${ep.titulo} · viñeta` })));
  host.innerHTML = todas.length
    ? todas.map((it) => `<img src="${it.url}" alt="" loading="lazy">`).join("")
    : `<div class="aviso" style="grid-column:1/-1">Sin viñetas crudas todavía.</div>`;
  host.querySelectorAll("img").forEach((im, i) => im.onclick = () => lbAbrir(todas, i));
}

/** LA PRENSA DE TINTA: animación del taller. */
let prensaTimer = null;
function prensaArrancar(grillas = []) {
  const p = $("#prensa");
  p.classList.remove("apagada");
  p.classList.add("prensand");
  $("#prensa-msg").innerHTML = `Componiendo capítulo… ${grillas.length ? `grillas ${grillas.map((g) => g.join("/")).join(" → ")}` : ""}`;
  $("#comics-estado").innerHTML = `<b>Taller activo</b>`;
  clearTimeout(prensaTimer);
  prensaTimer = setTimeout(() => prensaApagar(), 6000);
}
function prensaApagar() {
  const p = $("#prensa");
  p.classList.remove("prensand");
  p.classList.add("apagada");
  $("#prensa-msg").textContent = "El taller arranca cuando la fábrica compone un capítulo nuevo";
  $("#comics-estado").textContent = "Sin generación en curso";
}

/* ═══════════════════════════════════════════════════════════════════════
   GRÁFICOS CANVAS (sin dependencias externas)
   ═══════════════════════════════════════════════════════════════════════ */
function _cx(id) { return document.getElementById(id).getContext("2d"); }
function _preparar(id) {
  const cn = document.getElementById(id); const x = _cx(id);
  const dpr = window.devicePixelRatio || 1;
  const w = cn.clientWidth || 300; const h = cn.clientHeight || 150;
  cn.width = w * dpr; cn.height = h * dpr; x.scale(dpr, dpr);
  x.clearRect(0, 0, w, h);
  return { x, w, h };
}
function _texto(x, t, px, py, opts = {}) {
  x.font = opts.font || "500 11px var(--sans)";
  x.fillStyle = opts.color || "var(--tinta-2)";
  x.textAlign = opts.align || "center"; x.textBaseline = opts.base || "middle";
  x.fillText(t, px, py);
}
function _eje(id, opts = {}) {
  const { x, w, h } = _preparar(id);
  const pad = { l: 44, r: 14, t: 10, b: 30 };
  const gx = pad.l, gy = pad.t, gw = w - pad.l - pad.r, gh = h - pad.t - pad.b;
  // grid horizontal
  x.strokeStyle = "rgba(96,115,139,.16)"; x.lineWidth = 1; x.beginPath();
  const ny = 4;
  for (let i = 0; i <= ny; i++) {
    const yy = gy + (gh / ny) * i;
    x.moveTo(gx, yy); x.lineTo(gx + gw, yy);
  }
  x.stroke();
  return { x, w, h, gx, gy, gw, gh };
}
function dibujarLinea(id, puntos, color, opts = {}) {
  // puntos: [[x, y], ...]  x = índice de día (0..n-1), y = valor
  if (!puntos || !puntos.length) { $(id).innerHTML = ""; return; }
  const c = $(id);
  const d = _eje(id, opts);
  const { x, gx, gy, gw, gh } = d;
  const xs = puntos.map((p) => p[0]);
  const ys = puntos.map((p) => p[1]);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(0, ...ys), maxY = Math.max(...ys);
  const rx = (v) => gx + ((v - minX) / Math.max(1, maxX - minX)) * gw;
  const ry = (v) => gy + gh - ((v - minY) / Math.max(1, maxY - minY)) * gh;
  // línea del valor 0
  if (minY < 0) { x.strokeStyle = "rgba(255,255,255,.10)"; x.beginPath(); x.moveTo(gx, ry(0)); x.lineTo(gx + gw, ry(0)); x.stroke(); }
  // trazo
  x.beginPath(); x.lineWidth = 2; x.strokeStyle = color;
  x.lineJoin = "round"; x.lineCap = "round";
  xs.forEach((vx, i) => {
    if (i === 0) x.moveTo(rx(vx), ry(ys[i])); else x.lineTo(rx(vx), ry(ys[i]));
  });
  x.stroke();
  // puntos
  x.fillStyle = color;
  xs.forEach((vx, i) => { x.beginPath(); x.arc(rx(vx), ry(ys[i]), 3, 0, Math.PI * 2); x.fill(); });
  // etiquetas eje X (días)
  _texto(x, `Día ${xs.length}`, gx + gw, gy + gh + 22, { align: "right" });
  _texto(x, "hoy", gx + gw, gy + gh + 8, { align: "right", color: "var(--tinta-3)", font: "600 10px var(--mono)" });
  // valor actual
  const actual = ys[ys.length - 1];
  _texto(x, opts.labelActual || actual.toString(), gx + gw, gy - 6, { align: "right", color, font: "700 12px var(--sans)" });
}
function dibujarBarras(id, items, opts = {}) {
  // items: [{label, value, color}]
  if (!items || !items.length) { $(id).innerHTML = ""; return; }
  const { x, w, h } = _preparar(id);
  const pad = { l: 8, r: 8, t: 8, b: 56 };
  const gx = pad.l, gy = pad.t, gw = w - pad.l - pad.r, gh = h - pad.t - pad.b;
  const maxV = Math.max(...items.map((i) => i.value), 1);
  const paso = gw / items.length;
  x.font = "500 10px var(--mono)";
  x.textBaseline = "alphabetic";
  items.forEach((it, i) => {
    const bx = gx + i * paso + 8;
    const bw = paso - 16;
    const bh = (it.value / maxV) * gh;
    const by = gy + gh - bh;
    x.fillStyle = it.color || "var(--azul)";
    x.fillRect(bx, by, bw, bh);
    x.fillStyle = "var(--tinta-2)";
    x.fillText(String(it.value), bx + bw / 2, by - 6);
    x.save(); x.translate(bx + bw / 2, gy + gh + 14); x.rotate(-Math.PI / 3);
    x.fillText(it.label, 0, 0); x.restore();
  });
}

/* ─────────────────────── métricas (YT + FB) ──────────────────────────── */
function pintarMetricasView() {
  const m = S.metricas || {};
  const dispo = !!m.disponible;

  // resumen publicaciones
  const pub = S.galeria.reduce((n, e) => n + Object.keys(e.pub || {}).length, 0);
  const conYT = S.galeria.filter((e) => e.pub?.youtube);
  const conFB = S.galeria.filter((e) => e.pub?.facebook);
  $("#metricas-pub").innerHTML = `
    ${mcard(pub, "publicaciones", "vía Zernio + gates")}
    ${mcard(conYT.length, "en YouTube", conYT[0]?.pub?.youtube ? `<a href="${esc(conYT[0].pub.youtube)}" target="_blank">último: ver</a>` : "")}
    ${mcard(conFB.length, "en Facebook", "")}
    ${mcard(dispo ? "datos en tiempo real" : "sin datos aún", "fuente Zernio", dispo ? "analítica sincronizada" : "mide desde la primera publicación")}`;

  // gráficos de interacción
  const datosYT = m.yt && m.yt.puntos ? m.yt.puntos : [[0, 0], [1, 0], [2, 0], [3, 0], [4, 0], [5, 0], [6, 0]];
  const datosFB = m.fb && m.fb.puntos ? m.fb.puntos : [[0, 0], [1, 0], [2, 0], [3, 0], [4, 0], [5, 0], [6, 0]];
  const lblYT = dispo ? `YouTube — vistas: ${m.yt.vistas ?? 0}` : "YouTube — sin métricas aún";
  const lblFB = dispo ? `Facebook — vistas: ${m.fb.vistas ?? 0}` : "Facebook — sin métricas aún";

  // emoción / reacciones
  const emo = m.emocion || {};
  const emoItems = [];
  if (dispo && emo.reacciones) {
    Object.entries(emo.reacciones).forEach(([k, v]) => emoItems.push({ label: k, value: v, color: "var(--violeta)" }));
  } else {
    emoItems.push({ label: "sin datos", value: 0, color: "var(--tinta-3)" });
  }
  $("#metricas-emocion").innerHTML = `
    ${mcard(emo.predominante || "—", "emoción predominante", dispo ? "reconocimiento emocional" : "pendiente de datos")}
    ${mcard(emo.comentarios ?? 0, "comentarios", dispo ? "con texto analizado" : "")}
    ${mcard(emo.reacciones ? Object.values(emo.reacciones).reduce((a, b) => a + b, 0) : 0, "reacciones", "me gusta / corazón / sorpresa")}`;

  // dibujar todos los gráficos de métricas
  redibujarGraficosMetricas();

  $("#metricas-prod").innerHTML = `
    ${mcard(S.galeria.length, "episodios archivados", hace(S.galeria[0]?.mtime))}
    ${mcard(S.galeria.reduce((n, e) => n + (e.videos || []).length, 0), "videos en galería", "master + derivados")}
    ${mcard(totalKfs(), "keyframes", "documental 2.5D")}
    ${mcard(totalVin(), "viñetas de cómic", `${epConComics().length} capítulos`)}`;
}

/* redibujar gráficos al cambiar de vista y al redimensionar */
function redibujarGraficosMetricas() {
  if (S.vista !== "metricas") return;
  const m = S.metricas || {};
  const dispo = !!m.disponible;
  const datosYT = m.yt && m.yt.puntos ? m.yt.puntos : [[0, 0], [1, 0], [2, 0], [3, 0], [4, 0], [5, 0], [6, 0]];
  const datosFB = m.fb && m.fb.puntos ? m.fb.puntos : [[0, 0], [1, 0], [2, 0], [3, 0], [4, 0], [5, 0], [6, 0]];
  const lblYT = dispo ? `YouTube — vistas: ${m.yt.vistas ?? 0}` : "YouTube — sin métricas aún";
  const lblFB = dispo ? `Facebook — vistas: ${m.fb.vistas ?? 0}` : "Facebook — sin métricas aún";
  dibujarLinea("graf-met-yt", datosYT, "var(--rojo-yt)", { labelActual: lblYT });
  dibujarLinea("graf-met-fb", datosFB, "var(--azul-fb)", { labelActual: lblFB });
  const emo = m.emocion || {};
  const emoItems = [];
  if (dispo && emo.reacciones) {
    Object.entries(emo.reacciones).forEach(([k, v]) => emoItems.push({ label: k, value: v, color: "var(--violeta)" }));
  } else {
    emoItems.push({ label: "sin datos", value: 0, color: "var(--tinta-3)" });
  }
  dibujarBarras("graf-emocion", emoItems);
  const seg = m.seguidores_dia || [[0, m.seguidores ?? 200], [6, m.seguidores ?? 200], [13, m.seguidores ?? 200], [20, m.seguidores ?? 200], [27, m.seguidores ?? 200], [33, m.seguidores ?? 200], [40, m.seguidores ?? 200], [46, m.seguidores ?? 200]];
  dibujarLinea("graf-seguidores", seg, "var(--dorado)", { labelActual: `seguidores: ${m.seguidores ?? "—"}` });
}

window.addEventListener("resize", () => {
  if (S.vista === "metricas") { redibujarGraficosMetricas(); }
});

/* ─────────────────────── conectores MCP (REAL) ──────────────────────────────── */
function pintarConectores() {
  const host = $("#conectores-lista");
  host.innerHTML = "";
  const concs = S.conectores.length ? S.conectores : [];
  if (!concs.length) {
    host.innerHTML = `<div class="aviso" style="grid-column:1/-1">No hay conectores MCP configurados. Agregá uno desde el formulario de abajo.</div>`;
    return;
  }
  concs.forEach((c) => {
    const ok = c.estado === "ok";
    const card = document.createElement("article");
    card.className = "conector";
    const scopesHtml = (c.scopes || []).map((s) => `<span class="conc-chip">${esc(s)}</span>`).join(" ");
    const capsHtml = (c.capacidades || []).map((s) => `<span class="conc-chip" style="color:var(--cian);">${esc(s)}</span>`).join(" ");
    card.innerHTML = `
      <div class="conc-cab">
        <div class="conc-nom">${esc(c.nombre)}</div>
        <span class="conc-chip">${esc(c.platform)}</span>
        <span class="conc-estado ${ok ? "ok" : "err"}">${ok ? "● conectado" : "● error"}</span>
      </div>
      ${c.endpoint ? `<div class="conc-desc" style="font-size:11.5px; color:var(--tinta-3); word-break:break-all; margin-top:6px;"><span style="font:600 9px var(--mono); text-transform:uppercase;">endpoint:</span> ${esc(c.endpoint)}</div>` : ""}
      <div class="conc-meta" style="margin-top:8px;">
        ${scopesHtml}
        ${capsHtml ? `<span style="font:600 9px var(--mono); text-transform:uppercase; color:var(--cian); margin-left:8px;">capacidades:</span> ${capsHtml}` : ""}
      </div>
      <div style="margin-top:8px; display:flex; gap:6px; align-items:center; flex-wrap:wrap;">
        <span style="font:600 9px var(--mono); text-transform:uppercase; color:var(--tinta-3);">auth:</span>
        <span class="conc-chip" style="font-size:8.5px;">${esc(c.auth_tipo || "none")}</span>
        ${c.token ? `<span class="conc-chip" style="font-size:8.5px; background:rgba(24,119,242,.1); color:var(--azul-fb); border-color:rgba(24,119,242,.35);">token ····${esc(c.token.slice(-4))}</span>` : `<span class="conc-chip" style="font-size:8.5px; color:var(--tinta-3);">sin token</span>`}
        ${c.ultimo_test ? `<span class="conc-chip" style="font-size:8.5px; color:var(--tinta-3);">${esc(c.ultimo_test)}</span>` : ""}
      </div>
      <div class="conc-acciones" style="margin-top:10px;">
        <button class="btn outline small" onclick="probarConector('${esc(c.platform)}')">${ok ? "🔄 Re-probar" : "▶ Probar conexión"}</button>
        <button class="btn outline small" onclick="editarConector('${esc(c.platform)}')">✏ Editar</button>
        <button class="btn danger small" onclick="eliminarConector('${esc(c.platform)}')">🗑 Eliminar</button>
      </div>`;
    host.appendChild(card);
  });
}

async function probarConector(platform) {
  try {
    const res = await POST(`/api/conectores/${encodeURIComponent(platform)}/probar`, {});
    toast(res.mensaje || `Conector ${platform}: ${res.ok ? "OK" : "error"}`, res.ok ? "good" : "err");
    await refrescarConectores();
    pintarConectores();
  } catch (e) {
    toast(`Conector ${platform} falló`, "err");
  }
}

async function editarConector(platform) {
  const c = S.conectores.find((x) => x.platform === platform);
  if (!c) return;
  $("#conc-platform").value = c.platform;
  $("#conc-platform").disabled = true;
  $("#conc-nombre").value = c.nombre || "";
  $("#conc-endpoint").value = c.endpoint || "";
  $("#conc-auth").value = c.auth_tipo || "none";
  // El backend devuelve el token MASCARADO: reenviarlo lo guardaría como si fuera el real.
  // Se deja vacío y, si queda vacío, se conserva el token que ya está guardado.
  $("#conc-token").value = "";
  $("#conc-token").placeholder = c.token ? `${c.token} — dejalo vacío para no cambiarlo` : "sk_… o token";
  $("#conc-scopes").value = (c.scopes || []).join(", ");
  $("#conc-msg").textContent = `Editando conector "${c.platform}". Cambiá los campos y guardá.`;
  $("#btn-agregar-conector").textContent = "💾 Guardar cambios";
  $("#btn-agregar-conector").onclick = () => guardarConector(platform);
  cambiarVista("conectores");
  window.scrollTo({ top: 0 });
}

async function eliminarConector(platform) {
  if (!confirm(`¿Eliminar el conector "${platform}"?`)) return;
  try {
    await fetch(`/api/conectores/${encodeURIComponent(platform)}`, { method: "DELETE" });
    toast(`Conector "${platform}" eliminado`, "good");
    await refrescarConectores();
    pintarConectores();
  } catch (e) { toast("No se pudo eliminar el conector", "err"); }
}

async function guardarConector(platformOverride = null) {
  const platform = (platformOverride || $("#conc-platform").value.trim()).toLowerCase();
  const nombre = $("#conc-nombre").value.trim();
  const endpoint = $("#conc-endpoint").value.trim();
  const auth_tipo = $("#conc-auth").value;
  const token = $("#conc-token").value.trim();
  const scopesRaw = $("#conc-scopes").value.trim();
  const scopes = scopesRaw ? scopesRaw.split(",").map((s) => s.trim()).filter(Boolean) : [];
  if (!platform) { toast("Completá la platform", "err"); return; }
  const cuerpo = { nombre, endpoint, auth_tipo, scopes };
  if (token) cuerpo.token = token;   // vacío = conservar el token ya guardado
  try {
    let res;
    if (platformOverride) {
      // Editar usa PUT /api/conectores/{platform}: POST /agregar reemplaza el registro
      // entero y borraba el token real con el valor mascarado que mostraba la tarjeta.
      const r = await fetch(`/api/conectores/${encodeURIComponent(platform)}`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(cuerpo),
      });
      res = await r.json();
    } else {
      res = await POST("/api/conectores/agregar", { platform, ...cuerpo });
    }
    toast(res.ok ? `Conector "${platform}" guardado` : "No se pudo guardar", res.ok ? "good" : "err");
    if (res.ok) {
      limpiarFormConector();
      await refrescarConectores();
      pintarConectores();
    }
  } catch (e) { toast("Error guardando conector", "err"); }
}

function limpiarFormConector() {
  $("#conc-platform").value = "";
  $("#conc-platform").disabled = false;
  $("#conc-nombre").value = "";
  $("#conc-endpoint").value = "";
  $("#conc-auth").value = "none";
  $("#conc-token").value = "";
  $("#conc-token").placeholder = "sk_… o token";
  $("#conc-scopes").value = "";
  $("#conc-msg").textContent = "";
  $("#btn-agregar-conector").textContent = "➕ Registrar / actualizar conector";
  $("#btn-agregar-conector").onclick = guardarConector;
}

$("#btn-refrescar-conectores").onclick = async () => { await refrescarConectores(); pintarConectores(); toast("Conectores refrescados", "info"); };
$("#btn-probar-conectores").onclick = async () => {
  for (const c of S.conectores) { await probarConector(c.platform); await new Promise((r) => setTimeout(r, 500)); }
};
$("#btn-agregar-conector").onclick = guardarConector;
$("#btn-probar-actual").onclick = async () => {
  const platform = $("#conc-platform").value.trim().toLowerCase();
  if (!platform) { toast("Ingresá una platform para probar", "err"); return; }
  await probarConector(platform);
};

/* ─────────────────────── agentes / pipeline ──────────────────────────── */
function pintarAgentes() {
  const host = $("#agentes-lista");
  const sel = $("#agente-sel-lista");
  host.innerHTML = "";
  sel.innerHTML = "";
  const ags = S.agentes.length ? S.agentes : [
    { id: "research", nombre: "Descubrimiento", tipo: "fuente", desc: "Busca y verifica temas del día", ico: "🔎", habilidades: ["rss", "redes", "noticias"] },
    { id: "guion", nombre: "Guionista", tipo: "escritura", desc: "Escribe el guion del documental", ico: "📝", habilidades: ["narrativa", "gancho", "fact-check"] },
    { id: "visuales", nombre: "Dirección de arte", tipo: "imagen", desc: "Diseña keyframes y estilo visual", ico: "🎨", habilidades: ["flux", "imagenoteca", "reciclaje"] },
    { id: "narracion", nombre: "Narrador", tipo: "voz", desc: "Síntesis de voz del canal", ico: "🎙", habilidades: ["piper", "edge-tts"] },
    { id: "montaje", nombre: "Montajista", tipo: "video", desc: "Arma el video final", ico: "🎞", habilidades: ["ffmpeg", "cortes", "colores"] },
    { id: "publicacion", nombre: "Publicador", tipo: "salida", desc: "Publica en YouTube y Facebook", ico: "🚀", habilidades: ["zernio", "youtube", "facebook"] },
  ];
  S.agentes = ags;
  ags.forEach((a) => {
    const card = document.createElement("article");
    card.className = "agente";
    const activo = S.agenteSel === a.id;
    card.innerHTML = `
      <div class="agente-cab">
        <div class="agente-ico">${a.ico}</div>
        <div class="agente-nom">${esc(a.nombre)}</div>
        <span class="conc-chip">${esc(a.tipo)}</span>
      </div>
      <div class="agente-desc">${esc(a.desc)}</div>
      <div class="conc-meta">${(a.habilidades || []).map((t) => `<span class="conc-chip">${esc(t)}</span>`).join(" ")}</div>
      <div class="btn-group">
        <button class="btn ${activo ? "primary" : "outline"} small" onclick="seleccionarAgente('${esc(a.id)}')">${activo ? "✓ Seleccionado" : "Seleccionar"}</button>
      </div>`;
    host.appendChild(card);

    const b = document.createElement("button");
    b.className = `btn outline small ${activo ? "" : "oculto"}`;
    b.textContent = a.nombre;
    b.onclick = () => seleccionarAgente(a.id);
    sel.appendChild(b);
  });
  if (!S.agenteSel && ags.length) seleccionarAgente(ags[0].id);
  pintarAgenteEditor();
}
function seleccionarAgente(id) {
  S.agenteSel = id;
  hostRenderAgenteSeleccion(id);
  pintarAgenteEditor();
}
function hostRenderAgenteSeleccion(id) {
  const a = S.agentes.find((ag) => ag.id === id);
  $$(".agente button").forEach((b) => {
    const esActivo = b.textContent === a.nombre;
    b.className = `btn ${esActivo ? "primary" : "outline"} small`;
    b.textContent = esActivo ? "✓ Seleccionado" : "Seleccionar";
  });
}
function pintarAgenteEditor() {
  const a = S.agentes.find((ag) => ag.id === S.agenteSel) || {};
  const txt = $("#agente-prompt");
  $("#agente-msg").textContent = "";
  txt.value = a.prompt || `[prompt del sistema de ${a.nombre}]\n\nEditar el comportamiento de este agente autónomo.`;
  txt.disabled = false;
  $("#btn-guarda-prompt").onclick = async () => {
    try {
      await POST("/api/agentes/prompt", { id: S.agenteSel, prompt: txt.value });
      const ag = S.agentes.find((ag) => ag.id === S.agenteSel);
      if (ag) ag.prompt = txt.value;
      toast("Prompt guardado", "good");
    } catch (e) { toast("No se pudo guardar el prompt", "err"); }
  };
  $("#btn-reinstala-habilidad").onclick = async () => {
    try {
      await POST("/api/agentes/habilidad", { id: S.agenteSel });
      toast("Habilidad reinstalada", "good");
    } catch (e) { toast("No se pudo reinstalar la habilidad", "err"); }
  };
}

/* ───────────────────────── transmisión en vivo ───────────────────────── */
const CLASES_LOG = { info: "t-no", idea: "t-idea", keyframe: "t-kfr", audio: "t-aud",
  gate: "t-gate", publish: "t-pub", publicar: "t-pub", error: "t-err", fab: "t-fab",
  episodio: "t-epi", imgs: "t-kfr", stage: "t-fab", status: "t-epi",
  ep_ini: "t-epi", ep_fin: "t-epi", sys: null, hello: null };

function pintarLog(ev) {
  if (S.vista !== "transmision" || !ev) return;
  if (["sys"].includes(ev.t)) return;
  const t = $("#terminal");
  const ln = document.createElement("div");
  ln.className = CLASES_LOG[ev.t] || CLASES_LOG[ev.clase] || "t-no";
  ln.innerHTML = `<span class="ts">${esc(ev.ts || "")}</span>`;
  if (ev.t === "ep_ini") ln.innerHTML += `== episodio ${esc(ev.ep)} — ${esc(ev.titulo || "")}`;
  else if (ev.t === "stage") ln.innerHTML += `etapa ${esc(ev.stage)} → ${esc(ev.status)}`;
  else ln.innerHTML += esc(ev.linea || "");
  t.appendChild(ln);
  while (t.children.length > 400) t.firstChild.remove();
  if ($("#log-autoscroll").checked) t.scrollTop = t.scrollHeight;
}

/* ───────────────────────────── WebSocket ─────────────────────────────── */
function wsInit() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onopen = () => { $("#dot-live").classList.add("ok"); };
  ws.onclose = () => { $("#dot-live").classList.remove("ok"); setTimeout(wsInit, 3000); };
  ws.onerror = () => ws.close();
  ws.onmessage = (m) => {
    let ev;
    try { ev = JSON.parse(m.data); } catch { return; }
    pintarLog(ev);
    if (ev.t === "hello") {
      S.publica = !!ev.publish;
      pintarPublica();
    }
    if (ev.t === "stage") {
      if (ev.ep === S.ep || !S.ep) {
        S.stages[ev.stage] = ev.status;
        if (S.vista === "video" || S.vista === "inicio") pintarCinta();
      }
    } else if (ev.t === "ep_ini") {
      S.ep = ev.ep; S.stages = {};
      toast(`🎬 Nuevo episodio: ${ev.titulo || ev.ep}`, "info");
      refrescar().catch(() => {});
    } else if (ev.t === "ep_fin") {
      toast(ev.rc === 0 ? `✅ Episodio terminado (${ev.total || ""})` : `⚠ Episodio falló (rc=${ev.rc})`, ev.rc === 0 ? "good" : "");
      S.stages = {};
      refrescar().catch(() => {});
    } else if (ev.t === "status") {
      refrescarEstado().catch(() => {});
    } else if (ev.t === "log" && /comics?[: ].*\b(viñetas|vinetas|QC|páginas|libro)/i.test(ev.linea || "")) {
      prensaArrancar();
      toast(`📚 Taller de cómics activo`, "info");
    }
  };
}

/* ───────────────────────────── lightbox ──────────────────────────────── */
let lbLista = [], lbIdx = 0;
function lightboxInit() {
  $("#lb-cerrar").onclick = lbCerrar;
  $("#lb-prev").onclick = () => lbPintar((lbIdx - 1 + lbLista.length) % lbLista.length);
  $("#lb-next").onclick = () => lbPintar((lbIdx + 1) % lbLista.length);
  document.addEventListener("keydown", (e) => {
    if ($("#lightbox").hidden) return;
    if (e.key === "Escape") lbCerrar();
    if (e.key === "ArrowLeft") $("#lb-prev").click();
    if (e.key === "ArrowRight") $("#lb-next").click();
  });
}
function lbAbrir(lista, idx) {
  if (!lista || !lista.length) return;
  lbLista = lista; lbIdx = idx;
  $("#lightbox").hidden = false;
  lbPintar(idx);
}
function lbPintar(idx) {
  lbIdx = idx;
  const it = lbLista[idx];
  $("#lb-stage").innerHTML = it.tipo === "video"
    ? `<video src="${it.url}" controls autoplay style="max-width:100%;max-height:88vh"></video>`
    : `<img src="${it.url}" alt="">`;
  $("#lb-pie").textContent = `${it.pie || ""}  ·  ${idx + 1}/${lbLista.length}`;
}
function lbCerrar() { $("#lightbox").hidden = true; $("#lb-stage").innerHTML = ""; }

init().catch((e) => console.error(e));


/* ─────────────────────────── Oficina 3D ───────────────────────── */
async function montarOficina3D() {
  const caja = document.getElementById("of3D");
  if (!caja) return;
  if (_of3dMontado) return;
  if (_of3dMontando) { _of3dMontando.then(() => montarOficina3D()); return; }
  const aviso = caja.querySelector(".of-3d-aviso");
  if (aviso) aviso.textContent = "Leyendo la oficina…";
  try {
    if (!_of3dModulo) {
      const url = "/js/oficina3d.js?v=" + Date.now();
      _of3dModulo = await import(url);
    }
    const m = _of3dModulo;
    const razon = (typeof m.motivo === "function") ? m.motivo() : "";
    if (razon) throw new Error(razon);
    // datos: adaptar /api/agentes al formato que espera la escena
    const ofi = await GET("/api/oficina");
    const datos = {
      agentes: (ofi.agentes || []),
      bloqueos_humanos: {},
    };
    if (aviso) aviso.hidden = true;
    _of3dMontando = m.montar(caja, datos, { onSeleccion: (a) => {} })
      .then(() => { _of3dMontado = true; _of3dMontando = null; })
      .catch((e) => { _of3dMontando = null; throw e; });
    await _of3dMontando;
  } catch (e) {
    if (aviso) { aviso.hidden = false; aviso.textContent = "La Oficina 3D no arrancó: " + String((e && e.message) || e).slice(0, 120); }
    console.error("oficina3d", e, (e && e.stack) || "");
  }
}
