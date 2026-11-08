/* ═══ OFICINA 3D V2 — CARRUSEL DE ESTACIONES ═══════════════════════════════
   Reescribe la oficina completa: se va la sala rectangular (paredes, techo,
   pasillo, mesa de reuniones) y entra una CENTRAL DE OPERACIONES circular.

   · Un dais circular flotante sobre un piso reflectante oscuro.
   · N estaciones de trabajo (una por agente) alrededor del círculo,
     cada una con su plataforma, su trim de color de estado, su personaje
     con animación, su pantalla (atlas canvas, un solo draw para todas)
     y su rótulo con nombre y rol.
   · Rotación automática lenta (≈ 45 s por vuelta). El usuario puede
     arrastrar horizontal para recorrer los agentes; al soltar queda la
     inercia y, luego del silencio, vuelve el giro automático.
   · Click / doble-click sobre una estación: el carrusel la trae al frente,
     un spot de escenario la ilumina y las demás siguen visibles alrededor.
   · Núcleo holográfico al centro: colimador de la fábrica con el resumen
     vivo (medio, agentes por estado) y el cartel del medio.

   Se conserva sin cambios el contrato con la app:
   montar(caja, datos, {onSeleccion}) / actualizar(datos) / focar(id) /
   pausar / reanudar / destruir / motivo / soportado,
   y los ganchos __OF3D_LISTO__ / __OF3D_FOCAR__ / __OF3D_PC__ /
   __OF3D_ATLAS__ / __OF3D_AUDIT__ / __OF3D_INFO__.
   Los datos siguen viniendo de /api/oficina: nada es decorativo — nombre,
   rol, estado, tarea en curso, hoy, y turnos perdidos son del payload. */

import * as THREE from '../vendor/three/three.module.min.js';
import { GLTFLoader } from '../vendor/three/jsm/loaders/GLTFLoader.js';
import { CSS2DRenderer, CSS2DObject } from '../vendor/three/jsm/renderers/CSS2DRenderer.js';
import { clone as clonarEsqueleto } from '../vendor/three/jsm/utils/SkeletonUtils.js';
import { mergeGeometries } from '../vendor/three/jsm/utils/BufferGeometryUtils.js';

/* ── geometría del carrusel ────────────────────────────────────────────────── */
const SEP_IDEAL = 3.5;      // ancho cómodo de un puesto sobre el anillo (m)
const RADIO_MIN = 4.6;      // a esta distancia ya se respiran 6 puestos
const RADIO_MAX = 15;       // roster gigante: se aprieta el paso, no el kiddie
const ALTURA_DAI_S = 0.34;  // el dais del carrusel está levemente elevado
const TORNA = 0.138;        // rad/s del giro automático (≈ 45 s la vuelta)
const FALTA_S = 3.2;        // segundos de silencio antes de volver a girar
const DUREZA_FOCO = 4.2;    // cuán rápido la estación vía al frente
const FRICCION = 3.1;       // inercia tras soltar el arrastre (1/s)

/* ── la central de operaciones ─────────────────────────────────────────────── */
const CB = {
  dais: '#0d141e',        // el disco grande
  pedestal: '#131c28',    // el pedestal de cada estación
  piso: '#070a10',        // el piso exterior, reflectante y lejano
  marca: '#131f2b',       // anillos guía sobre el dais
  acento: '#22d3ee',      // cian del núcleo + marcas
  acento2: '#3b82f6',     // azul de los faros remotos
  metal: '#232f3d',
};
// El fondo es una gradación vertical — nunca una pared ni un color plano.
// La niebla funde el horizonte al mismo tono, así no hay borde duro jamás.
const CIELO = ['#04060c', '#0a1220', '#0e1728', '#050810'];
const NIEBLA = { color: '#050810', cerca: 26, lejos: 120 };

const LUZ = {
  clave: '#dbe7ff', intensidadClave: 1.35,     // key fría, estilo estudio
  hemisferio: 0.85, cielo: '#9db8e8', suelo: '#05070c',
  nucleo: '#35e0ff', intensidadNucleo: 1.5,    // colimador central
  fosa: '#4c6bff', intensidadFosa: 0.5,        // contraluz
  exposicion: 1.12,
};

/* Estados: los mismos 5 colores que la Lista y los anillos históricos. */
const COLOR = { ok: 0x4f9d69, error: 0xd94141, reposo: 0x8a8a8a, sinturno: 0xd9a441,
                 curso: 0x2f7ad1 };

const RUTA = '/oficina3d/';
const MUEBLE = {
  escritorio: 'furniture/pub-workstation-v1.glb',
  silla: 'furniture/office-chair-v1.glb',
};
const PERSONAJES = ['characters/office-bomi.glb', 'characters/office-seo.glb',
                    'characters/office-tae.glb'];

let R = null;                             // la escena montada, o null

/* ── estado de un agente → visual ──────────────────────────────────────────── */
// El backend desplegado manda estados 'ok' | 'reposo' | 'curso' (factoryd);
// el payload histórico de los medios mandaba 'activo'. Ambos contratos viven.
function activoDe(a){
  return a.estado === 'ok' || a.estado === 'activo';
}
function colorDe(a){
  // El azul es el latido: el anillo dice "está corriendo AHORA".
  if(a.en_curso) return 'curso';
  if(a.estado === 'reposo') return 'reposo';
  if(activoDe(a)){
    const u = a.ultima;
    if(u && (u.ok === false || u.perdido)) return 'error';
    return 'ok';
  }
  return 'sinturno';
}

// El globo SOLO grita lo que hay que mirar: un turno que terminó mal.
function globoDe(a){
  const u = a.ultima;
  if(!u) return null;
  if(u.ok === false || u.perdido)
    return { txt: '⚠ ' + String(u.error || 'turno perdido').slice(0, 46), mal: true };
  return null;
}

// La identidad visual depende del id, no del lugar que ocupa en el payload.
function modeloDe(id){
  let h = 0;
  for(const c of String(id)) h = (Math.imul(h, 31) + c.charCodeAt(0)) >>> 0;
  return h % PERSONAJES.length;
}

function acotado(v, min, max){ return Math.min(max, Math.max(min, v)); }

/* ── las texturas que se generan en canvas, una vez por página ─────────────── */
// Compartidas entre montajes: `desarmarEscena()` dispone los MATERIALES pero
// nunca sus `map`.
const TEX = { limpiar: null, sombra: null, cielo: null, piso: null };

function texturaSombra(){
  if(TEX.sombra) return TEX.sombra;
  const c = document.createElement('canvas');
  c.width = c.height = 128;
  const g = c.getContext('2d');
  const gr = g.createRadialGradient(64, 64, 4, 64, 64, 62);
  gr.addColorStop(0, 'rgba(0,0,0,.42)');
  gr.addColorStop(1, 'rgba(0,0,0,0)');
  g.fillStyle = gr; g.fillRect(0, 0, 128, 128);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  TEX.sombra = t;
  return t;
}

function texturaCielo(){
  if(TEX.cielo) return TEX.cielo;
  const c = document.createElement('canvas');
  c.width = 8; c.height = 256;
  const g = c.getContext('2d');
  const gr = g.createLinearGradient(0, 0, 0, 256);
  CIELO.forEach((col, i) => gr.addColorStop(i / (CIELO.length - 1), col));
  g.fillStyle = gr; g.fillRect(0, 0, 8, 256);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  TEX.cielo = t;
  return t;
}

// El piso circular del dais: no parquet — grano técnico. Concentricidad y
// marcas radiales tenues le dan a la sala de control su escala.
function texturaPlato(){
  if(TEX.piso) return TEX.piso;
  const T = 1024, c = document.createElement('canvas');
  c.width = c.height = T;
  const g = c.getContext('2d'), C = T / 2;
  g.fillStyle = CB.piso; g.fillRect(0, 0, T, T);
  // Vetas finas horizontales: metal cepillado, refleja sin espejar.
  for(let i = 0; i < 90; i++){
    g.strokeStyle = 'rgba(120,160,200,' + (0.012 + Math.random() * 0.02) + ')';
    g.lineWidth = 1;
    const y = Math.random() * T;
    g.beginPath(); g.moveTo(0, y); g.lineTo(T, y); g.stroke();
  }
  // Anillos concéntricos al dais (el UV de la elipse se mapea polar después).
  for(let r = 60; r < C; r += 78){
    g.strokeStyle = 'rgba(90,140,190,' + (0.05 + Math.random() * 0.05) + ')';
    g.lineWidth = r % (78 * 2) < 78 ? 1.5 : 4;
    g.beginPath(); g.arc(C, C, r, 0, Math.PI * 2); g.stroke();
  }
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 4;
  TEX.piso = t;
  return t;
}

/* ── la PC de cada agente: UN atlas, UN draw ───────────────────────────────── */
// La pantalla NO es un objeto del GLB: el mueble viene instanciado y una
// pantalla por agente sería n meshes, n materiales y n texturas. Acá es un
// canvas compartido en grilla —una celda por estación— y la geometría de los
// vidrios es UN solo mesh fusionado: 1 draw y 1 subida de textura por
// repintado, no por agente.
//
// `PANTALLA` está medido sobre `pub-workstation-v1.glb`: la cara visible del
// monitor mira al −Z local de la estación, que es el lado que después queda
// mirando a la cámara: la estación se orienta con fase π (ver FASE) y así el
// personaje queda detrás del escritorio, al lado del núcleo, y su pantalla
// se lee desde afuera del anillo.
const PANTALLA = { w: 0.26, h: 0.47, x: -0.62, y: 1.1495, z: 0.06, cara: 'camara', caja: false };
const CELDA = { w: 128, h: 232, cols: 4 };        // 128/232 ≈ la proporción del vidrio

const Pantallas = { atlas: null };

function css(hex){ return '#' + Number(hex).toString(16).padStart(6, '0'); }

function asegurarAtlas(n){
  const cols = CELDA.cols, rows = Math.max(1, Math.ceil(n / cols));
  const ancho = cols * CELDA.w, alto = rows * CELDA.h;
  if(!Pantallas.atlas){
    const c = document.createElement('canvas');
    Pantallas.atlas = { canvas: c, ctx: c.getContext('2d'), tex: null,
                        cols, rows, firmas: [], x: 0, y: 0 };
  }
  const at = Pantallas.atlas;
  if(at.canvas.width !== ancho || at.canvas.height < alto || at.rows !== rows){
    at.canvas.width = ancho; at.canvas.height = alto;
    at.firmas = [];
  }
  at.cols = cols; at.rows = rows;
  if(!at.tex){
    at.tex = new THREE.CanvasTexture(at.canvas);
    at.tex.colorSpace = THREE.SRGBColorSpace;
    at.tex.flipY = false;              // la fila 0 del canvas es la fila 0 de la textura
    at.tex.anisotropy = 4;             // el vidrio se mira de costado y con zoom
  }
  at.tex.image = at.canvas;
  return at;
}

// UVs horneadas por celda: el quad de la pantalla k muestrea SOLO su casilla.
// Con `cara:'camara'` el plano está girado π para mirar al espectador, así que
// se espeja `u` — si no, todo el texto saldría al revés.
function hornearUVs(geo, k, at){
  const cx = k % at.cols, cy = Math.floor(k / at.cols);
  const u0 = cx / at.cols, du = 1 / at.cols;
  const v0 = cy / at.rows, dv = 1 / at.rows;
  const uv = geo.attributes.uv;
  for(let i = 0; i < uv.count; i++){
    const ox = uv.getX(i), oy = uv.getY(i);
    const u = PANTALLA.cara === 'camara' ? u0 + (1 - ox) * du : u0 + ox * du;
    uv.setXY(i, u, v0 + dv - oy * dv);
  }
  uv.needsUpdate = true;
}

/* ── qué se pinta en cada vidrio (solo lo que llegó del backend) ────────────── */
function firmaDePantalla(p){
  const a = p.a;
  // `segundos` se redondea a 30: sin eso cada refresco reescribiría la celda.
  const s = a.segundos == null ? '' : Math.round(a.segundos / 30);
  return [a.rol || '', a.estado || '', a.en_curso ? 1 : 0, s, a.faena || '',
          a.hoy == null ? '' : a.hoy, a.hoy_texto || '', p.aviso || '',
          (a.ultima || {}).en || ''].join('|');
}

function envolver(ctx, txt, ancho){
  // Un token que no cabe solo (`laburo_changa_rosario`, una URL en un error) se
  // parte a la fuerza: si no, desborda la celda y el vecino lo borra.
  const partes = [];
  for(const w of String(txt).split(/\s+/)){
    if(!w) continue;
    if(ctx.measureText(w).width <= ancho){ partes.push(w); continue; }
    let cur = '';
    for(const ch of w){
      if(cur && ctx.measureText(cur + ch).width > ancho){ partes.push(cur); cur = ch; }
      else cur += ch;
    }
    if(cur) partes.push(cur);
  }
  const lineas = [];
  let suelto = '';
  for(const w of partes){
    const prueba = suelto ? suelto + ' ' + w : w;
    if(ctx.measureText(prueba).width > ancho && suelto){ lineas.push(suelto); suelto = w; }
    else suelto = prueba;
  }
  if(suelto) lineas.push(suelto);
  return lineas;
}

function pintarPantalla(at, p, forzar){
  const a = p.a, k = p.celda;
  const firma = firmaDePantalla(p);
  if(!forzar && at.firmas[k] === firma) return false;
  at.firmas[k] = firma;
  const g = at.ctx, X = (k % at.cols) * CELDA.w, Y = Math.floor(k / at.cols) * CELDA.h;
  const dormido = !activoDe(a);
  const borde = css(COLOR[colorDe(a)] ?? COLOR.sinturno);
  // La celda se pinta ENTERA: si no, el texto viejo del refresco anterior queda
  // encima y la pantalla muestra dos faenas a la vez.
  g.fillStyle = a.estado === 'reposo' ? '#14161a' : '#0b1016';
  if(dormido && a.estado !== 'reposo') g.fillStyle = '#14161a';
  g.fillRect(X, Y, CELDA.w, CELDA.h);
  g.strokeStyle = borde; g.lineWidth = 3;
  g.strokeRect(X + 1.5, Y + 1.5, CELDA.w - 3, CELDA.h - 3);
  g.fillStyle = dormido ? '#4a5157' : borde;
  g.fillRect(X + 3, Y + 3, CELDA.w - 6, 26);
  g.textBaseline = 'top';
  g.fillStyle = dormido ? '#7d858c' : '#08090b';
  g.font = 'bold 12px system-ui, sans-serif';
  const rol = envolver(g, (a.rol || a.nombre || '').toUpperCase(), CELDA.w - 12).slice(0, 2);
  rol.forEach((l, i) => g.fillText(l, X + 6, Y + 8 + i * 11));

  let y = Y + 36;
  g.font = '13px system-ui, sans-serif';
  if(p.aviso){
    // La franja de lo que espera un humano: es HEURÍSTICA del frente, dice "red".
    g.fillStyle = css(COLOR.sinturno);
    g.fillRect(X + 3, y, CELDA.w - 6, 20);
    g.fillStyle = '#1a1408'; g.font = 'bold 10.5px system-ui, sans-serif';
    envolver(g, p.aviso, CELDA.w - 12).slice(0, 2)
      .forEach((l, i) => g.fillText(l, X + 6, y + 4 + i * 11));
    y += 26;
    g.font = '13px system-ui, sans-serif';
  }
  if(dormido){
    g.fillStyle = '#8d959c';
    g.fillText(a.estado === 'reposo' ? 'EN REPOSO' : 'SIN TURNO', X + 6, y + 6);
    g.font = '11px system-ui, sans-serif';
    g.fillStyle = '#5f676e';
    envolver(g, a.porque || 'el gate está apagado por decisión', CELDA.w - 12).slice(0, 4)
      .forEach((l, i) => g.fillText(l, X + 6, y + 26 + i * 13));
    return true;
  }
  if(a.en_curso){
    g.fillStyle = '#e8f2ff';
    g.font = 'bold 13px system-ui, sans-serif';
    const cuerpo = envolver(g, a.faena || 'procesando…', CELDA.w - 12).slice(0, 6);
    cuerpo.forEach((l, i) => g.fillText(l, X + 6, y + i * 15));
    y += Math.max(1, cuerpo.length) * 15 + 8;
    g.fillStyle = borde; g.font = 'bold 11px system-ui, sans-serif';
    g.fillText('TRABAJANDO', X + 6, y);
    if(a.segundos != null){
      g.fillText('⏱ ' + Math.round(a.segundos / 30) * 30 + 's', X + 6, y + 13);
    }
  }else{
    g.fillStyle = a.hoy == null ? '#6f777e' : '#cfe3d6';
    const lineas = a.hoy == null
      ? envolver(g, 'sin medida', CELDA.w - 12)
      : envolver(g, a.hoy + ' ' + (a.hoy_texto || ''), CELDA.w - 12);
    lineas.slice(0, 3).forEach((l, i) => g.fillText(l, X + 6, y + i * 15));
    y += Math.max(1, Math.min(3, lineas.length)) * 15 + 10;
    const u = a.ultima;
    if(u && (u.ok === false || u.perdido)){
      g.fillStyle = css(COLOR.error); g.font = '11px system-ui, sans-serif';
      envolver(g, '⚠ ' + String(u.error || 'turno perdido').slice(0, 60),
               CELDA.w - 12).slice(0, 5)
        .forEach((l, i) => g.fillText(l, X + 6, y + i * 13));
    }else if(u && u.en){
      g.fillStyle = '#6f777e'; g.font = '11px system-ui, sans-serif';
      envolver(g, 'última corrida: ' + horaDe(u.en), CELDA.w - 12).slice(0, 2)
        .forEach((l, i) => g.fillText(l, X + 6, y + i * 13));
    }
  }
  return true;
}

function horaDe(iso){
  const d = new Date(iso);
  return isNaN(d) ? String(iso).slice(11, 16)
                  : d.toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' });
}

function repintarPantallas(forzar){
  const pc = R && R.pantallas;
  if(!pc) return;
  let toca = false;
  for(const p of pc.conPc){
    if(pintarPantalla(pc.atlas, p, forzar)) toca = true;
  }
  if(toca) pc.atlas.tex.needsUpdate = true;
}

/* ── instancias de muebles: N puestos en pocos draws ───────────────────────── */
function Instanciador(padre){
  const grupos = new Map();
  const clave = o => o.geometry.uuid + '|' +
    (Array.isArray(o.material) ? o.material : [o.material]).map(m => m.uuid).join(',');
  return {
    agregar(raiz, matriz){
      raiz.updateMatrixWorld(true);
      raiz.traverse(o => {
        if(!o.isMesh || !o.geometry || !o.material) return;
        const k = clave(o);
        let g = grupos.get(k);
        if(!g){ g = { geo: o.geometry, mat: o.material, m: [] }; grupos.set(k, g); }
        g.m.push(new THREE.Matrix4().multiplyMatrices(matriz, o.matrixWorld));
      });
    },
    construir(){
      for(const g of grupos.values()){
        const im = new THREE.InstancedMesh(g.geo, g.mat, g.m.length);
        g.m.forEach((m, i) => im.setMatrixAt(i, m));
        im.instanceMatrix.needsUpdate = true;
        im.castShadow = true; im.receiveShadow = true;
        // La geometría y el material son de la caché: NO se disponen acá.
        padre.add(im);
      }
    },
  };
}

/* ── los modelos, una sola pasada por red ──────────────────────────────────── */
// Se cachea a nivel módulo: cambiar de medio o salir y volver de la vista no
// vuelve a bajar 2 MB. Por eso el `dispose()` de la escena NUNCA toca estos
// recursos: son de la caché compartida, no de la instancia.
let ASSETS = null;
const BAJADO = new Map();
const TOTAL_GLB = 2 + PERSONAJES.length;
let COMPARTIDO = null;              // uuids de geometría/material que son de la caché

function bajar(c, ruta, intentos){
  if(!BAJADO.has(ruta)){
    const pedido = new Promise((res, rej) =>
      c.load(RUTA + ruta, res, undefined, e => rej(e)));
    BAJADO.set(ruta, pedido.catch(e => {
      BAJADO.delete(ruta);                 // un archivo truncado no queda como bueno
      if(intentos <= 1) throw e;
      return new Promise(r => setTimeout(r, 800)).then(() => bajar(c, ruta, intentos - 1));
    }));
  }
  return BAJADO.get(ruta);
}

function cargar(alProgreso){
  if(ASSETS) return ASSETS;
  const c = new GLTFLoader();
  const rutas = [MUEBLE.escritorio, MUEBLE.silla, ...PERSONAJES];
  let hechos = 0;
  const conProgreso = r => bajar(c, r, 3).then(g => {
    hechos++; if(alProgreso) alProgreso(hechos, TOTAL_GLB, r); return g;
  });
  ASSETS = Promise.all(rutas.map(conProgreso)).then(([esc, silla, ...cuerpos]) => {
    const propios = { escritorio: esc, silla, cuerpos };
    const COMPARTIDO_ = new Set();
    for(const gltf of [esc, silla, ...cuerpos]){
      gltf.scene.traverse(o => {
        if(!o.isMesh) return;
        COMPARTIDO_.add(o.geometry.uuid);
        for(const m of (Array.isArray(o.material) ? o.material : [o.material])) COMPARTIDO_.add(m.uuid);
      });
    }
    COMPARTIDO = COMPARTIDO_;
    return propios;
  }).catch(e => { ASSETS = null; COMPARTIDO = null; throw e; });
  return ASSETS;
}

/* ── API pública ───────────────────────────────────────────────────────────── */
// three r180 NO habla WebGL1: pedir webgl2 explícitamente y decir el motivo.
export function motivo(){
  try{
    if(!window.WebGLRenderingContext) return 'este navegador no tiene WebGL';
    const c = document.createElement('canvas');
    if(c.getContext('webgl2')) return '';
    if(c.getContext('webgl')) return 'solo tiene WebGL 1 y la escena necesita WebGL 2';
    return 'no logra abrir un contexto WebGL 2';
  }catch(e){ return 'WebGL bloqueado en este navegador (' + String(e.message || e).slice(0, 40) + ')'; }
}

export function soportado(){ return motivo() === ''; }

/* ── montar/destruir serializados ───────────────────────────────────────────── */
// Cambiar de vista mientras la escena está bajando dispara un segundo `montar`
// antes de que el primero termine. La cola hace que el montaje nuevo espere al
// anterior y lo destruya, en vez de pisarlo.
let cola = Promise.resolve();
function enCola(f){
  const corrida = cola.then(f, f);
  cola = corrida.catch(() => {});          // un fallo no enchastra la cola
  return corrida;
}

export function montar(caja, datos, opciones = {}){
  return enCola(() => montarReal(caja, datos, opciones));
}

function tamanoDe(caja){
  return [Math.max(320, caja.clientWidth), Math.max(240, caja.clientHeight)];
}

// Dos frames: el primero dispara el layout pendiente, el segundo lo ve asentado.
const esperarLayout = () => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));

/* Radio del anillo: n puestos no pueden pisarse. */
function radioDe(n){
  if(n <= 0) return RADIO_MIN;
  return acotado(n * SEP_IDEAL / (Math.PI * 2), RADIO_MIN, RADIO_MAX);
}

async function montarReal(caja, datos, opciones = {}){
  await destruirReal();
  const raz = motivo();
  if(raz) throw new Error(raz);
  // La caja se mide DESPUÉS de la espera: cambiar de vista mientras la escena
  // está bajando deja el hueco sin layout un instante, y un renderer que nace
  // con el mínimo de 320×240 se queda chico para siempre si nadie lo rectifica.
  await esperarLayout();
  const [ancho, alto] = tamanoDe(caja);
  const movil = window.innerWidth < 720 || Math.min(ancho, alto) < 460;
  const aviso = caja.querySelector('.of-3d-aviso');

  const renderer = new THREE.WebGLRenderer({ antialias: !movil, powerPreference: 'high-performance' });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, movil ? 1.25 : 1.75));
  renderer.setSize(ancho, alto);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  // El carrusel GIRA: la sombra tiene que refrescarse. Resolución baja y áreas
  // de sombra acotadas: el costo queda dominado por la escena, no por la luz.
  renderer.shadowMap.autoUpdate = true;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = LUZ.exposicion;
  caja.appendChild(renderer.domElement);

  const etiquetas = new CSS2DRenderer();
  etiquetas.setSize(ancho, alto);
  etiquetas.domElement.className = 'of-3d-capa';
  caja.appendChild(etiquetas.domElement);

  const scene = new THREE.Scene();
  scene.background = texturaCielo();
  scene.fog = new THREE.Fog(NIEBLA.color, NIEBLA.cerca, NIEBLA.lejos);

  const camara = new THREE.PerspectiveCamera(44, ancho / alto, 0.1, 260);

  // Llanura de iluminación de estudio: key fría + hemisferio suave + contraluz.
  // El núcleo aporta su colimador propio (PointLight cian) y el spot de
  // escenario viaja con la estación del frente. Ni sol calido ni paredes.
  const clave = new THREE.DirectionalLight(LUZ.clave, LUZ.intensidadClave);
  clave.position.set(-6, 14, 9);
  clave.castShadow = movil ? false : true;
  clave.shadow.mapSize.set(1024, 1024);
  clave.shadow.bias = -0.0006;
  clave.shadow.normalBias = 0.03;
  const fosa = new THREE.DirectionalLight(LUZ.fosa, LUZ.intensidadFosa * 0.45);
  fosa.position.set(9, 5, -11);

  const foco = new THREE.SpotLight('#bfe3ff', 2.4, 18, 0.55, 0.5, 1.4);
  foco.position.set(0, 7.5, 12);
  foco.castShadow = false;
  const focoObjetivo = new THREE.Object3D();
  foco.target = focoObjetivo;

  R = {
    caja, renderer, etiquetas, scene, camara, clave, fosa, foco, focoObjetivo,
    datos, movil, modo: 'carrusel',
    onSeleccion: opciones.onSeleccion || (() => {}),
    mov: !window.matchMedia('(prefers-reduced-motion: reduce)').matches,
    puestos: [], mixers: [],
    carrusel: null, radio: RADIO_MIN, dias: null, nucleo: null,
    anillos: null, sombras: null, trims: null, faros: null, polvo: null,
    pantallas: null, cajas: null, cajasGeo: null, cartel: null,
    previos: {}, tiempo: 0,
    // Geometría y meshes creados POR ESTE armado (piso, dais, guía, núcleo,
    // faros, polvo): se disponen al desarmar, sin tocar la caché de GLB.
    descartables: [],
    reloj: new THREE.Clock(), raf: 0, corriendo: false, sel: '',
    al: null, ro: null, ids: '', ancho, alto,
    // θ actual del carrusel (rad). El frente del anillo mira hacia +Z.
    teta: 0, vueltas: 0, agarrado: null, ultimoToque: 0,
    tetaPrev: -1,
    // Girar de la pantalla a la escena buscando instancias con matriz NaN
    // (la GPU las descarta en silencio) y emisivos sobre el umbral.
    instanciasRotas(){
      const mala = [];
      scene.traverse(o => {
        if(!o.isInstancedMesh) return;
        const a = o.instanceMatrix.array;
        for(let i = 0; i < a.length; i++)
          if(!Number.isFinite(a[i])){
            const n = Math.floor(i / 16);
            mala.push(o.uuid.slice(0, 8) + '#' + n);
            break;
          }
      });
      return mala;
    },
    emisivosAltos(limite = 0.9){
      const fuera = [];
      scene.traverse(o => {
        for(const m of (Array.isArray(o.material) ? o.material : [o.material]))
          if(m && m.emissiveIntensity > limite &&
             m.emissive && m.emissive.getHex() !== 0) fuera.push(m.uuid.slice(0, 8));
      });
      return [...new Set(fuera)];
    },
  };

  // 45 s: son ~2 MB de mobiliario pasando por el gate del dominio, y un plazo
  // corto mataba descargas que iban por buen camino.
  const poner = txt => { if(aviso) aviso.textContent = txt; };
  poner('Bajando el mobiliario 0/' + TOTAL_GLB + '…');
  const assets = await Promise.race([
    cargar((hechos, total) => poner('Bajando el mobiliario ' + hechos + '/' + total + '…')),
    new Promise((_, rej) => setTimeout(
      () => rej(new Error('los modelos tardaron más de 45 s en bajar')), 45000)),
  ]);
  if(!R) throw new Error('la escena se destruyó durante la carga');   // salimos entre tanto
  R.assets = assets;

  armar();
  encuadrar();
  aplicarCamara();
  enlazar();
  reanudar();
  // El aviso "Armándola…" vive en la plantilla: si no se apaga queda encima.
  caja.querySelector('.of-3d-aviso')?.setAttribute('hidden', '');

  window.__OF3D_LISTO__ = true;
  // El hook de prueba hace lo que un click: centra Y dispara selección.
  window.__OF3D_FOCAR__ = id => {
    focar(id);
    const p = id && R && R.puestos.find(x => x.a.id === id);
    if(p) R.onSeleccion(p.a);
  };
  // El arnés mide el costo real de las pantallas: apagando la malla se ve el
  // delta EXACTO de draws. Todos los vidrios fusionados cuestan un draw.
  window.__OF3D_PC__ = v => { if(R && R.pantallas) R.pantallas.malla.visible = !!v; };
  // Y puede leer el atlas: es literalmente lo que hay en los vidrios.
  window.__OF3D_ATLAS__ = () => (R && R.pantallas ? R.pantallas.atlas.canvas : null);
  window.__OF3D_AUDIT__ = () => ({
    instanciasNaN: [...(R ? R.instanciasRotas() : [])],
    emisivosAltos: [...(R ? R.emisivosAltos() : [])],
  });
  informar();
  return R;
}

/* ═══ ARMADO DE LA ESCENA ═════════════════════════════════════════════════ */
const D2R = Math.PI / 180;

/* Marca un mesh/grupo creado por `armar()` para disponerlo en `desarmarEscena`.
   Nunca pasa por acá nada propio de la caché de GLB (`ASSETS`). */
function descartar(o){
  if(o && R) R.descartables.push(o);
}

/* Desarma un objeto descartable: sale de la escena y libera sus buffers. */
function deshacer(o){
  o.parent?.remove(o);
  o.traverse?.(m => {                      // los grupos (núcleo) tienen hijos
    m.geometry?.dispose?.();
    const mats = Array.isArray(m.material) ? m.material : [m.material];
    for(const mt of mats) mt?.dispose?.();
  });
}

function armar(){
  const agentes = (R.datos.agentes || []).filter(a => a && a.id);
  const n = agentes.length;
  const radio = radioDe(n);
  R.radio = radio;
  // Cota del piso exterior: coincide con la base del dais, para que el disco
  // apoye limpio sobre la plancha (sin cortes flotantes).
  const FLOOR = -(ALTURA_DAI_S + 0.9);

  // ── el carrusel entero es UN grupo que gira ──────────────────────────────
  const carrusel = new THREE.Group();
  R.carrusel = carrusel;

  // Splash del piso exterior: un plano circular enorme y bajo, reflectante y
  // oscuro. Con la niebla al tono del fondo, el horizonte funde sin bordes.
  const pisoGeo = new THREE.CircleGeometry(radio * 5.2, 48);
  pisoGeo.rotateX(-Math.PI / 2);
  const piso = new THREE.Mesh(pisoGeo, new THREE.MeshStandardMaterial({
    color: CB.piso, roughness: 0.6, metalness: 0.08,
  }));
  piso.position.y = FLOOR;
  piso.receiveShadow = true;
  R.scene.add(piso);
  descartar(piso);

  // ── el dais: el disco donde viven las estaciones ─────────────────────────
  const daiGeo = new THREE.CylinderGeometry(radio + 2.6, radio + 2.9, ALTURA_DAI_S + 0.9, 64);
  const dais = new THREE.Mesh(daiGeo, new THREE.MeshStandardMaterial({
    color: CB.dais, roughness: 0.42, metalness: 0.55,
  }));
  // El disco baja entero hasta que su cara superior quede en y = 0 y su base
  // apoye en el piso exterior: las estaciones viven sobre esa superficie.
  dais.position.y = -(ALTURA_DAI_S + 0.9) / 2;
  dais.receiveShadow = true; dais.castShadow = false;
  R.scene.add(dais);
  descartar(dais);

  // Superficie superior del dais: la textura técnica (un círculo con la
  // textura ya polar) — mesh separado para que el UV llene y los reflectores
  // no se peleen con los anillos de marca.
  const caraGeo = new THREE.CircleGeometry(radio + 2.55, 64);
  caraGeo.rotateX(-Math.PI / 2);
  const cara = new THREE.Mesh(caraGeo, new THREE.MeshStandardMaterial({
    map: texturaPlato(), roughness: 0.34, metalness: 0.18,
  }));
  cara.receiveShadow = true;
  R.scene.add(cara);
  descartar(cara);

  // Anillo guía: la circunferencia por donde pasan las estaciones.
  const guiaGeo = new THREE.TorusGeometry(radio, 0.012, 6, 96);
  guiaGeo.rotateX(-Math.PI / 2);
  const guia = new THREE.Mesh(guiaGeo, new THREE.MeshBasicMaterial({
    color: CB.acento, transparent: true, opacity: 0.22, toneMapped: false,
  }));
  guia.position.y = 0.012;
  R.scene.add(guia);
  descartar(guia);
  // Dos concéntricos exteriores, cada vez más tenues: profundidad.
  for(let i = 1; i <= 2; i++){
    const rg = new THREE.TorusGeometry(radio + 1.7 + i * 0.55, 0.008, 6, 96);
    rg.rotateX(-Math.PI / 2);
    const rm = new THREE.Mesh(rg, new THREE.MeshBasicMaterial({
      color: CB.acento, transparent: true, opacity: 0.1 / i, toneMapped: false,
    }));
    rm.position.y = 0.01;
    R.scene.add(rm);
    descartar(rm);
  }

  // ── el núcleo: colimador de la fábrica ───────────────────────────────────
  const nucleo = new THREE.Group();
  const base = new THREE.Mesh(new THREE.CylinderGeometry(0.62, 0.78, 0.5, 28),
    new THREE.MeshStandardMaterial({ color: CB.metal, roughness: 0.3, metalness: 0.85 }));
  base.position.y = 0.25;
  const tubo = new THREE.Mesh(new THREE.CylinderGeometry(0.5, 0.5, 2.5, 24, 1, true),
    new THREE.MeshStandardMaterial({
      color: '#0a141e', roughness: 0.12, metalness: 0.4, transparent: true,
      opacity: 0.24, emissive: CB.acento, emissiveIntensity: 0.16,
      side: THREE.DoubleSide,
    }));
  tubo.position.y = 1.7;
  const esfera = new THREE.Mesh(new THREE.IcosahedronGeometry(0.36, 2),
    new THREE.MeshStandardMaterial({
      color: '#062430', emissive: CB.acento, emissiveIntensity: 1.35,
      roughness: 0.15, metalness: 0.1,
    }));
  esfera.position.y = 1.7;
  // Dos anillos orbitando la esfera, cada uno en un eje y al contrario.
  const anilloA = new THREE.Mesh(new THREE.TorusGeometry(0.85, 0.02, 6, 64),
    new THREE.MeshBasicMaterial({ color: CB.acento, transparent: true, opacity: 0.75, toneMapped: false }));
  anilloA.rotation.x = Math.PI / 2.6;
  anilloA.position.y = 1.7;
  const anilloB = new THREE.Mesh(new THREE.TorusGeometry(1.12, 0.014, 6, 64),
    new THREE.MeshBasicMaterial({ color: CB.acento2, transparent: true, opacity: 0.55, toneMapped: false }));
  anilloB.rotation.set(Math.PI / 1.9, 0.3, 0);
  anilloB.position.y = 1.7;
  const luzNucleo = new THREE.PointLight(LUZ.nucleo, LUZ.intensidadNucleo, 30, 1.6);
  luzNucleo.position.y = 2.0;
  nucleo.add(base, tubo, esfera, anilloA, anilloB, luzNucleo);
  R.scene.add(nucleo);
  R.nucleo = { grupo: nucleo, esfera, anilloA, anilloB, tubo };
  descartar(nucleo);

  // ── faros del horizonte: la ciudad de operaciones móvil al fondo ────────
  // Postes finos y tenues, fuera del anillo, de alturas variadas: dan
  // profundidad SIN ser paredes y la niebla los funde en banda de color.
  // Cuidado con la exageración: emisivo alto × piso reflectante vuelve el
  // plano un espejo azul; acá van casi al límite de lo visible.
  const FAROS = 12;
  const faroGeo = new THREE.BoxGeometry(0.09, 1, 0.09);
  R.faros = new THREE.InstancedMesh(faroGeo,
    new THREE.MeshStandardMaterial({
      color: '#101b28', emissive: CB.acento2, emissiveIntensity: 0.16, roughness: 0.6,
    }), FAROS);
  {
    const s = new THREE.Object3D();
    for(let i = 0; i < FAROS; i++){
      const a = i / FAROS * Math.PI * 2 + 0.4;
      const rr = radio * 2.6 + (i % 4) * radio * 0.4;
      const h = 1.1 + (i % 5) * 0.55;
      s.position.set(Math.sin(a) * rr, FLOOR + h / 2 + (i % 3) * 0.5, Math.cos(a) * rr);
      s.scale.set(1, h, 1);
      s.updateMatrix();
      R.faros.setMatrixAt(i, s.matrix);
    }
    R.faros.instanceMatrix.needsUpdate = true;
  }
  R.scene.add(R.faros);
  descartar(R.faros);

  // ── polvo luminoso: motas flotando lentas — vive de la escena ────────────
  if(R.mov){
    const MAX_DUST = 170;
    const pos = new Float32Array(MAX_DUST * 3);
    for(let i = 0; i < MAX_DUST; i++){
      const a = Math.random() * Math.PI * 2;
      const rr = radio * (0.25 + Math.random() * 1.6);
      pos[i * 3] = Math.sin(a) * rr;
      pos[i * 3 + 1] = 0.2 + Math.random() * 5.4;
      pos[i * 3 + 2] = Math.cos(a) * rr;
    }
    const dustGeo = new THREE.BufferGeometry();
    dustGeo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    R.polvo = new THREE.Points(dustGeo, new THREE.PointsMaterial({
      color: '#7fdcff', size: 0.055, transparent: true, opacity: 0.35,
      sizeAttenuation: true, depthWrite: false, blending: THREE.AdditiveBlending,
    }));
    R.scene.add(R.polvo);
    descartar(R.polvo);
  }

  // ── iluminación en escena ────────────────────────────────────────────────
  // Las luces nacen en montarReal y viajan por R: acá se cuelgan a la escena.
  R.scene.add(R.clave, R.fosa,
    new THREE.HemisphereLight(LUZ.cielo, LUZ.suelo, LUZ.hemisferio),
    R.foco, R.focoObjetivo);
  R.scene.add(R.foco.target);

  // ── instancias por estación (matrices en el ESPACIO DEL CARRUSEL) ────────
  // Las plataformas, los trims, los anillos y las sombras son InstancedMesh
  // hijos del carrusel: girar el grupo gira TODO con un solo tercio de costo.
  const inst = new Instanciador(carrusel);

  // Pedestal circular por estación.
  const pedGeo = new THREE.CylinderGeometry(PLATA_R, PLATA_R + 0.09, PLATA_H, 28);
  R.plataformas = new THREE.InstancedMesh(pedGeo,
    new THREE.MeshStandardMaterial({ color: CB.pedestal, roughness: 0.5, metalness: 0.5 }),
    Math.max(n, 1));
  R.plataformas.count = n;
  R.plataformas.castShadow = false; R.plataformas.receiveShadow = true;
  carrusel.add(R.plataformas);

  // Trim de color alrededor del pedestal: es el semáforo del puesto.
  const trimGeo = new THREE.TorusGeometry(PLATA_R + 0.03, 0.025, 8, 40);
  trimGeo.rotateX(-Math.PI / 2);
  R.trims = new THREE.InstancedMesh(trimGeo, new THREE.MeshBasicMaterial({
    toneMapped: false,
  }), Math.max(n, 1));
  R.trims.count = n;
  // Los trims SIEMPRE brillan un poco por cuenta propia (basic material).
  R.trims.castShadow = false; R.trims.receiveShadow = false;
  carrusel.add(R.trims);

  // Anillo de estado de cada personaje (el mismo torus de siempre).
  const geoAnillo = new THREE.TorusGeometry(0.44, 0.035, 8, 28);
  geoAnillo.rotateX(-Math.PI / 2);
  R.anillos = new THREE.InstancedMesh(geoAnillo,
    new THREE.MeshStandardMaterial({ roughness: 0.55 }), Math.max(n, 1));
  R.anillos.count = n;
  R.anillos.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
  carrusel.add(R.anillos);

  // Sombra falsa del personaje (con la sombra real no se mezcla: es la base).
  const geoSombra = new THREE.CircleGeometry(0.48, 20);
  geoSombra.rotateX(-Math.PI / 2);
  R.sombras = new THREE.InstancedMesh(geoSombra, new THREE.MeshBasicMaterial({
    map: texturaSombra(), transparent: true, depthWrite: false,
  }), Math.max(n, 1));
  R.sombras.count = n;
  carrusel.add(R.sombras);

  R.scene.add(carrusel);

  const tmp = new THREE.Object3D();
  const SRATCH_MAT = new THREE.Matrix4();
  const jl = n > 0 ? Math.PI * 2 / n : 1;

  // ── sentar a los agentes ──────────────────────────────────────────────────
  agentes.forEach((a, k) => {
    const fi = k * jl;                       // ángulo de la estación en el anillo
    const x = Math.sin(fi) * radio, z = Math.cos(fi) * radio;
    // FASE (π) aparte: define qué lado de la estación mira a la cámara.
    grupoEstacion(a, k, fi, x, z, tmp, SRATCH_MAT, inst);
  });

  // Las matrices recién escritas ya se usaron con needsUpdate implícito por
  // ser la primera subida; para rebuilds hay que marcarlas otra vez.
  for(const im of [R.plataformas, R.trims, R.anillos, R.sombras]){
    if(im) im.instanceMatrix.needsUpdate = true;
  }

  // El roster quedó fijado: `actualizar()` compara contra esta firma para no
  // reconstruir la escena si llegan los mismos agentes (solo cambian estados).
  R.ids = firmaRoster(agentes);

  // Heurística del frente: qué puesto tiene un pedido humano a la vista.
  for(const p of R.puestos) p.aviso = avisoDe(p, R.datos);

  // Construcción de instancias + pantallas + rótulos.
  inst.construir();
  transiciones();
  armarPantallas();
  armarRotulos();
  armarGlobos();
  pintarAcentos();

  // El cartel vivo del núcleo: qué fábrica es esta y cómo está su gente.
  // Sale del payload (factoryd respin /api/oficina), no se inventa acá.
  const d = R.datos, r = (d.resumen || {});
  const titulo = d.medio ? (d.medio_nombre || d.medio) : 'Central de operaciones';
  const cuenta = conteoEstados(agentes);
  const sub = r.del_medio === undefined
    ? `${cuenta.activos} activos · ${cuenta.curso} trabajando`
    : `${r.del_medio} del medio · ${r.de_la_red || 0} de la red`;
  R.cartel = new CSS2DObject(cartelDe(titulo, sub));
  R.cartel.position.set(0, 3.35, 0);
  R.scene.add(R.cartel);

  // La sombra proyecta el anillo completo.
  sombrear(radio);
}

/* Pedestales de la estación: casi el alto del puesto. */
const PLATA_R = 1.42, PLATA_H = 0.14;

/* Fase del carrusel: la estación gira fi + FASE. Con FASE = π el frente de la
   estación (donde está la cara del personaje y la pantalla legible, que miran
   al −Z local) apunta hacia afuera del anillo, que es donde está la cámara. */
const FASE = Math.PI;

/* Pone UNA estación: personajes, muebles y anclas en su grupo propio. */
function grupoEstacion(a, k, fi, x, z, tmp, SCRATCH_MAT, inst){
  const carrusel = R.carrusel;
  const unidad = new THREE.Group();
  unidad.position.set(x, 0, z);
  unidad.rotation.y = fi + FASE;          // la cara del puesto mira hacia afuera
  carrusel.add(unidad);
  // La matriz se congela acá: `unidad.matrix` sirve de base para las matrices
  // de los muebles y de los vidrios de pantalla, y sin `updateMatrix` three
  // la deja sin escribir (matrixAutoUpdate es perezoso).
  unidad.updateMatrix();

  // Pedestal y trim no necesitan rotación (radial simetría): van por instancias
  // en el espacio del carrusel — girar el grupo los lleva igual.
  tmp.position.set(x, PLATA_H / 2, z); tmp.scale.set(1, 1, 1); tmp.rotation.set(0, 0, 0);
  tmp.updateMatrix();
  R.plataformas.setMatrixAt(k, tmp.matrix);
  tmp.position.set(x, PLATA_H - 0.012, z); tmp.updateMatrix();
  R.trims.setMatrixAt(k, tmp.matrix);

  // Escritorio en el centro de la estación. El monitor (que se agrega aparte,
  // como vidrio del atlas) queda mirando al −Z local de la estación: ese es el
  // lado que, con FASE = π, apunta hacia la cámara.
  inst.agregar(R.assets.escritorio.scene, unidad.matrix.clone());

  // Silla + personaje en el +Z local de la estación (el lado del núcleo):
  // sentado en su silla, mirando a su monitor y a la vez de frente al
  // espectador cuando la estación viene al frente.
  const sillaMat = unidad.matrix.clone().multiply(new THREE.Matrix4()
    .makeTranslation(0, 0, 0.62).multiply(new THREE.Matrix4().makeRotationY(Math.PI)));
  inst.agregar(R.assets.silla.scene, sillaMat);

  // Personaje: clon con esqueleto propio para que cada agente tenga su
  // animación independiente. Vive en el GRUPO de la estación: girar el
  // carrusel lo mueve entero, rótulo incluido.
  const modelo = R.assets.cuerpos[modeloDe(a.id)];
  const cuerpo = clonarEsqueleto(modelo.scene);
  cuerpo.position.set(0, 0, 0.62);
  cuerpo.rotation.y = Math.PI;      // el modelo mira a +Z local; él mira al −Z
  cuerpo.traverse(o => { if(o.isMesh){ o.castShadow = true; o.receiveShadow = false; } });
  unidad.add(cuerpo);

  const clips = modelo.animations;
  const mixer = new THREE.AnimationMixer(cuerpo);
  const acc = nombre => {
    const clip = THREE.AnimationClip.findByName(clips, nombre);
    return clip ? mixer.clipAction(clip) : null;
  };
  const p = { a, i: k, fi, x, z, giro: Math.PI, cuerpo, grupo: unidad,
              etiqueta: null, rotulo: null,
              color: colorDe(a), escritorio: true,
              mix: { mixer, sit: acc('sit'), idle: acc('idle'), cur: null },
              aviso: null, celda: -1 };
  const arrancar = p.mix.sit || p.mix.idle;
  if(arrancar){
    arrancar.play();
    p.mix.cur = arrancar;
    // La pose sentada solo se anima mientras el job está realmente corriendo.
    arrancar.time = 0.2;
    arrancar.paused = !R.mov || !a.en_curso;
    mixer.update(0);
    R.mixers.push({ mixer, acc: arrancar });
  }

  // Anillo + sombra falsa, también instanciados (espacio del carrusel).
  tmp.position.set(x, 0.02, z); tmp.scale.setScalar(1); tmp.rotation.set(0, 0, 0);
  tmp.updateMatrix();
  R.anillos.setMatrixAt(k, tmp.matrix);
  tmp.position.set(x, PLATA_H + 0.004, z); tmp.scale.set(1.1, 1, 1.1); tmp.updateMatrix();
  R.sombras.setMatrixAt(k, tmp.matrix);

  // La caja de click: se mide en espacio LOCAL de la estación (mismo origen),
  // y por frame se pasa al mundo con la matriz mundial de la estación.
  cuerpo.updateMatrixWorld(true);
  const caja = new THREE.Box3().setFromObject(cuerpo);
  caja.expandByScalar(0.2);
  p.desc0 = caja;
  // La caja de la mesa entera (desk + pantalla) también descubre el click.
  p.descEscritorio = new THREE.Box3(
    new THREE.Vector3(-0.95, 0, -0.85),
    new THREE.Vector3(0.95, 1.55, 0.62));
  p.box = caja.clone();
  p.boxEscritorio = p.descEscritorio.clone();
  R.puestos.push(p);
  return p;
}

// La frustum de sombra cubre el anillo entero; con el default de three los
// puestos del fondo quedan sin sombra.
function sombrear(radio){
  const e = radio + 4;
  Object.assign(R.clave.shadow.camera, { left: -e, right: e, top: e, bottom: -e, near: 0.5, far: e * 5 });
  R.clave.shadow.camera.updateProjectionMatrix();
  R.clave.target.position.set(0, 0, 0);
  R.scene.add(R.clave.target);
  R.renderer.shadowMap.needsUpdate = true;
}

// La PC de cada agente: UN mesh con los quads de TODAS las estaciones, orneado
// en el espacio del CARRUSEL: al girar el grupo, los vidrios giran con él.
// 26 vidrios cuestan un draw, no veintiséis.
function armarPantallas(){
  const conPc = R.puestos.filter(p => p.escritorio);
  if(!conPc.length) return;
  const atlas = asegurarAtlas(conPc.length);
  // Cada vidrio es un quad horneado en el espacio LOCAL de su estación y
  // llevado a espacio del CARRUSEL con la matriz de esa estación, ANTES del
  // merge: así el mesh fusionado queda fijo en el carrusel y gira con él.
  const partes = [];
  conPc.forEach((p, k) => {
    p.celda = k;
    const g = new THREE.PlaneGeometry(PANTALLA.w, PANTALLA.h);
    hornearUVs(g, k, atlas);
    const local = new THREE.Matrix4()
      .makeTranslation(PANTALLA.x, PANTALLA.y, PANTALLA.z);
    if(PANTALLA.cara === 'camara') local.multiply(new THREE.Matrix4().makeRotationY(Math.PI));
    p.grupo.updateMatrix();
    g.applyMatrix4(local);
    g.applyMatrix4(p.grupo.matrix);
    partes.push(g);
    pintarPantalla(atlas, p, true);
  });
  const mallaGeo = mergeGeometries(partes, false);
  partes.forEach(gg => gg.dispose());
  const malla = new THREE.Mesh(mallaGeo, new THREE.MeshBasicMaterial({
    map: atlas.tex, toneMapped: false,      // una pantalla brilla sola
  }));
  malla.castShadow = false; malla.receiveShadow = false;
  R.carrusel.add(malla);
  R.pantallas = { malla, atlas, conPc };
  if(PANTALLA.caja){
    const ga = new THREE.BoxGeometry(PANTALLA.w * 1.1, PANTALLA.h * 1.06, 0.29);
    const aristas = new THREE.EdgesGeometry(ga);
    const ma = new THREE.LineBasicMaterial({ color: 0xff00ff });
    R.cajas = conPc.map(p => {
      const c = new THREE.LineSegments(aristas, ma);
      c.position.set(PANTALLA.x, PANTALLA.y, PANTALLA.z);
      p.grupo.add(c);
      return c;
    });
    R.cajasGeo = [ga, aristas];              // compartidas: se disponen una sola vez
  }
}

// Rótulo con NOMBRE y ROL del agente: personas con oficio, no tarjetas. Va
// pegado al GRUPO de la estación, así que girar el carrusel lo lleva.
function armarRotulos(){
  for(const p of R.puestos){
    if(!p.rotulo){
      const obj = new CSS2DObject(rotuloDe(p.a));
      const arriba = (p.desc0 || p.box).max.y;
      obj.position.set(0, arriba + 0.28, 0.62);
      p.grupo.add(obj);
      p.rotulo = obj;
    }else{
      // Refresco: misma estación, datos nuevos. Se reescribe el texto.
      llenarRotulo(p.rotulo.element, p.a);
    }
  }
}

function rotuloDe(a){
  const div = document.createElement('div');
  div.className = 'of-label';
  const b = document.createElement('b'), i = document.createElement('i');
  div.append(b, i);
  llenarRotulo(div, a);
  return div;
}

function llenarRotulo(div, a){
  div.children[0].textContent = a.nombre || a.rol;
  div.children[1].textContent = a.rol;
  div.dataset.estado = colorDe(a);
  div.title = a.en_curso ? 'Trabajando ahora' :
    a.estado === 'reposo' ? 'En reposo' :
    !activoDe(a) ? 'Sin turno' :
    colorDe(a) === 'error' ? 'Última corrida con error' : 'En turno, sin corrida en curso';
}

// El cartel del núcleo: DOM puro con textContent, porque el nombre de la
// fábrica viene del backend y no hay que darle ninguna ventaja de marcado.
function cartelDe(titulo, sub){
  const div = document.createElement('div');
  div.className = 'of-cartel';
  const b = document.createElement('b'); div.append(b);
  const i = document.createElement('i'); div.append(i);
  b.textContent = titulo;
  i.textContent = sub || '';
  i.hidden = !sub;
  return div;
}

// Los globos se rehacen enteros en cada rebuild: pocos, sin estados fantasma.
function armarGlobos(){
  for(const p of R.puestos){
    if(!p.etiqueta) continue;
    p.grupo.remove(p.etiqueta);
    p.etiqueta.element?.remove();
    p.etiqueta = null;
  }
  for(const p of R.puestos){
    const mal = globoDe(p.a);
    const globo = mal || (p.a.en_curso && p.a.faena
      ? { txt: '● ' + String(p.a.faena).slice(0, 80), mal: false, clase: 'curso' } : null);
    if(!globo) continue;
    const div = document.createElement('div');
    div.className = 'of-globo ' + (globo.clase || (globo.mal ? 'mal' : 'ok'));
    div.textContent = globo.txt;
    const obj = new CSS2DObject(div);
    obj.position.set(0, (p.desc0 || p.box).max.y + 0.78, 0.62);
    p.grupo.add(obj);
    p.etiqueta = obj;
  }
}

/* Los colores que dependen del ESTADO: anillos + trims de pedestal. Un solo
   repintado por Refresh, ambos instanciados. */
function pintarAcentos(){
  const c = new THREE.Color();
  for(const p of R.puestos){
    c.setHex(COLOR[p.color] ?? COLOR.sinturno);
    const sel = R.sel && p.a.id === R.sel;
    if(sel) c.multiplyScalar(1.55);          // el seleccionado se ve
    if(R.anillos) R.anillos.setColorAt(p.i, c);
    if(R.trims) R.trims.setColorAt(p.i, c);
  }
  if(R.anillos?.instanceColor) R.anillos.instanceColor.needsUpdate = true;
  if(R.trims?.instanceColor) R.trims.instanceColor.needsUpdate = true;
}

function conteoEstados(agentes){
  const c = { activos: 0, curso: 0, error: 0, reposo: 0 };
  for(const a of agentes){
    const e = colorDe(a);
    if(e === 'curso'){ c.curso++; c.activos++; }
    else if(e === 'error'){ c.error++; c.activos++; }
    else if(e === 'ok'){ c.activos++; }
    else if(e === 'reposo') c.reposo++;
  }
  return c;
}

/* ── dinamica del carrusel ─────────────────────────────────────────────────── */
// El carrusel gira SOLO cuando nadie está interactuando (drag / foco / sel
// reciente). Al soltar queda inercia y, vencido el silencio, vuelve el giro.
// Con prefers-reduced-motion no girà solo: el usuario manda siempre.

// Sella el ángulo objetivo que deja al frente a la estación k: el frente de la
// estación es fi + FASE, y queda al frente cuando fi + teta = FASE… es decir
// teta = FASE − fi. Se elige la vuelta más corta desde teta actual.
function targetPara(k){
  const n = R.puestos.length;
  if(!n) return R.teta;
  const fi = R.puestos[k].fi;
  let objetivo = FASE - fi;
  const dosPi = Math.PI * 2;
  while(objetivo - R.teta > Math.PI) objetivo -= dosPi;
  while(objetivo - R.teta < -Math.PI) objetivo += dosPi;
  return objetivo;
}

function adelante(){
  const n = R.puestos.length;
  if(!n) return -1;
  let mejor = 0, mejorD = Infinity;
  for(let i = 0; i < n; i++){
    // Distancia angular del frente de la estación (fi + FASE) a la cámara.
    let d = Math.abs(((R.puestos[i].fi + R.teta - FASE) % (Math.PI * 2) +
      Math.PI * 2) % (Math.PI * 2));
    if(d > Math.PI) d = Math.PI * 2 - d;
    if(d < mejorD){ mejorD = d; mejor = i; }
  }
  return mejor;
}

function encuadrar(){
  // Encuadre inicial: carrusel mirando al frente, cámara en su sitio.
  R.teta = 0; R.vueltas = 0; R.sel = ''; R.modo = 'auto'; R.selObj = null;
  R.vista = { dist: distanciaDeEncaje(), alturaFactor: 0.42 };
}

// Cuánto hay que retroceder para que el anillo entre entero. Three mide el
// campo vertical: en un teléfono vertical la misma escena pide casi el triple
// de distancia que en un monitor.
function distanciaDeEncaje(){
  const radio = R.radio;
  const vf = 2 * Math.tan(THREE.MathUtils.degToRad(R.camara.fov / 2));
  const porAlto = (radio * 2 + 4) / Math.max(0.55, vf);
  const porAncho = (radio * 2 + 4) / (vf * Math.max(0.35, R.camara.aspect));
  return Math.min(64, Math.max(porAlto, porAncho) + 3.5);
}

/* ── cámara ────────────────────────────────────────────────────────────────── */
function aplicarCamara(){
  const v = R.vista;
  const dist = v.dist, altura = 1.4 + dist * v.alturaFactor;
  // Parallax mínimo con el mouse: la cámara respira sin perder el encuadre.
  const px = R.parallax?.x || 0, py = R.parallax?.y || 0;
  R.camara.position.set(px * dist * 0.05, altura + py * 0.4, dist);
  // Mirar un pelito más alto que el centro para que no aplaste la cabeza.
  R.camara.lookAt(0, Math.min(2.0, altura * 0.28 + 0.4), 0);
}

/* ── entrada: drag con inercia, click, doucle-click, rueda, pellizco ──────── */
function enlazar(){
  const lienzo = R.renderer.domElement;
  const señal = (R.al = new AbortController()).signal;
  let arrastre = null;
  const puntos = new Map();          // puntero activo → para pellizco en el celular
  let pellizco = 0;

  lienzo.addEventListener('pointerdown', e => {
    puntos.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if(puntos.size > 1){ arrastre = null; return; }
    arrastre = { x: e.clientX, y: e.clientY, movido: 0, th: performance.now(), dt: R.teta, acel: 0, avance: 0 };
    R.ultimoToque = performance.now();
    lienzo.setPointerCapture?.(e.pointerId);
  }, { signal: señal });

  lienzo.addEventListener('pointermove', e => {
    R.parallax = { x: (e.clientX - R.ancho / 2) / R.ancho * 2,
                   y: (e.clientY - R.alto / 2) / R.alto * 2 };
    if(puntos.has(e.pointerId)) puntos.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if(puntos.size === 2){
      const [a, b] = [...puntos.values()];
      const d = Math.hypot(a.x - b.x, a.y - b.y);
      if(pellizco) R.vista.dist = acotado(R.vista.dist * pellizco / Math.max(1, d),
        R.radio * 0.9, distanciaDeEncaje() * 2.2);
      pellizco = d;
      return;
    }
    pellizco = 0;
    if(!arrastre) return;
    const dx = e.clientX - arrastre.x, dy = e.clientY - arrastre.y;
    const desplazamiento = Math.abs(dx) + Math.abs(dy);
    arrastre.movido = Math.max(arrastre.movido, desplazamiento);
    if(desplazamiento < 2) return;
    // El drag horizontal GIRA EL MUNDO (no la cámara): más natural en un carrusel.
    const dTeta = -dx * 0.0042;
    R.modo = 'mano';
    R.teta += dTeta;
    const ahora = performance.now();
    const dtms = Math.max(16, ahora - arrastre.th);
    arrastre.acel = acotado(dTeta / dtms, -1.4, 1.4);      // rad/ms — clamp de locura
    arrastre.th = ahora;
    arrastre.avance = dTeta;
    arrastre.x = e.clientX; arrastre.y = e.clientY;
    // Drag vertical: leve pitch de cámara, sin romance.
    R.vista.alturaFactor = acotado(R.vista.alturaFactor + dy * 0.0004, 0.16, 0.72);
    R.ultimoToque = ahora;
  }, { signal: señal });

  lienzo.addEventListener('pointerup', e => {
    puntos.delete(e.pointerId);
    const fueClick = arrastre && arrastre.movido < 6 && puntos.size === 0;
    if(arrastre && arrastre.movido >= 6 && puntos.size === 0){
      // Inercia: la velocidad del último tramo del arrastre sigue sola.
      R.modo = 'vuelta';
      R.vueltas = acotado(arrastre.acel, -0.9, 0.9) * 16;      // rad/s
      R.ultimoToque = performance.now();
    }
    arrastre = null; pellizco = 0;
    if(fueClick) seleccionar(e, false);
  }, { signal: señal });

  lienzo.addEventListener('pointercancel', e => {
    puntos.delete(e.pointerId); arrastre = null; pellizco = 0;
  }, { signal: señal });

  lienzo.addEventListener('wheel', e => {
    e.preventDefault();
    R.vista.dist = acotado(R.vista.dist * (1 + (e.deltaY > 0 ? 0.12 : -0.12)),
      R.radio * 0.9, distanciaDeEncaje() * 2.2);
  }, { passive: false, signal: señal });
  lienzo.addEventListener('dblclick', e => seleccionar(e, true), { signal: señal });

  // Los botones que ya trae la plantilla: +/− y ⤢ (ver el anillo entero).
  R.caja.querySelectorAll('.of-3d-cam [data-cam]').forEach(b => b.addEventListener('click', () => {
    if(!R) return;
    const v = R.vista;
    if(b.dataset.cam === 'mas') v.dist = Math.max(R.radio * 0.9, v.dist * 0.78);
    else if(b.dataset.cam === 'menos') v.dist = Math.min(distanciaDeEncaje() * 2.2, v.dist * 1.28);
    else focar('');
  }, { signal: señal }));

  document.addEventListener('visibilitychange', () => {
    if(document.hidden) pausar(); else reanudar();
  }, { signal: señal });

  // Girar el teléfono o colapsar un sidebar cambia el hueco: re-encuadrar.
  R.ro = new ResizeObserver(ajustar);
  R.ro.observe(R.caja);
}

function ajustar(){
  if(!R) return;
  const a = Math.max(320, R.caja.clientWidth), b = Math.max(240, R.caja.clientHeight);
  if(a === R.ancho && b === R.alto) return;
  R.ancho = a; R.alto = b;
  R.renderer.setSize(a, b);
  R.etiquetas.setSize(a, b);
  R.camara.aspect = a / b;
  R.camara.updateProjectionMatrix();
  // Si hay una estación seleccionada se respeta el zoom que eligió la persona.
  if(!R.sel) R.vista.dist = distanciaDeEncaje();
  R.renderer.shadowMap.needsUpdate = true;
}

function seleccionar(e, enfocar){
  const r = R.renderer.domElement.getBoundingClientRect();
  const ray = new THREE.Raycaster();
  ray.setFromCamera(new THREE.Vector2(
    ((e.clientX - r.left) / r.width) * 2 - 1,
    -((e.clientY - r.top) / r.height) * 2 + 1), R.camara);
  // Se prueba contra la caja propia de cada estación (recalculada por frame
  // con la matriz mundial): no hace falta malla invisible extra.
  const punto = new THREE.Vector3();
  let mejor = null, dmin = Infinity;
  for(const p of R.puestos){
    for(const box of [p.box, p.boxEscritorio]){
      if(!box || !ray.ray.intersectBox(box, punto)) continue;
      const d = punto.distanceTo(R.camara.position);
      if(d < dmin){ dmin = d; mejor = p; }
    }
  }
  if(!mejor){ if(enfocar) focar(''); return; }
  R.sel = mejor.a.id;
  pintarAcentos();
  promover(mejor.i);                        // la estación va al frente
  if(enfocar) R.vista.dist = Math.max(R.radio * 1.35, R.vista.dist * 0.62);
  R.onSeleccion(mejor.a);
}

export function focar(id){
  if(!R || !R.carrusel) return;
  R.sel = id || '';
  pintarAcentos();
  if(!id){ encuadrar(); return; }
  const k = R.puestos.findIndex(x => x.a.id === id);
  if(k < 0) return;
  promover(k);
  R.vista.dist = Math.max(R.radio * 1.35, R.radio * 0.95);
}

/* ── el loop ───────────────────────────────────────────────────────────────── */
function cuadro(){
  if(!R) return;
  R.raf = requestAnimationFrame(cuadro);
  // dt con clamp: una pestaña dormida devuelve un delta enorme.
  const dt = Math.min(0.05, R.reloj.getDelta());
  const ahora = performance.now();

  if(R.mov) for(const m of R.mixers) m.mixer.update(dt);

  // 1. DINÁMICA DEL CARRUSEL — cuatro modos: auto (giro lento), mano
  //    (agarrado por el drag), vuelta (inercia tras soltar) y foco (una
  //    estación seleccionada viaja al frente).
  if(R.modo === 'auto' && R.mov && R.selObj == null &&
     ahora - R.ultimoToque > FALTA_S * 1000){
    R.teta -= TORNA * dt * 1.0;
  }else if(R.modo === 'vuelta'){
    R.teta += R.vueltas * dt;
    R.vueltas *= Math.exp(-dt * FRICCION);
    if(Math.abs(R.vueltas) < 0.012) R.modo = 'auto';
  }

  // 2. FOCO: interpolar theta hacia el objetivo de la estación seleccionada.
  if(R.selObj != null){
    const objetivo = targetPara(R.selObj);
    const f = 1 - Math.exp(-dt * DUREZA_FOCO);
    R.teta += (objetivo - R.teta) * f;
  }else if(R.sel){
    const k = R.puestos.findIndex(x => x.a.id === R.sel);
    if(k >= 0){ R.selObj = k; }             // siguió vivo en el reparto
  }

  if(R.carrusel) R.carrusel.rotation.y = R.teta;

  // 3. CAJAS de click al día: solo si el carrusel se movió.
  if(Math.abs(R.teta - R.tetaPrev) > 1e-5 && R.puestos.length){
    R.tetaPrev = R.teta;
    for(const p of R.puestos){
      p.grupo.updateWorldMatrix(true, false);
      p.box.copy(p.desc0).applyMatrix4(p.grupo.matrixWorld);
      p.boxEscritorio.copy(p.descEscritorio).applyMatrix4(p.grupo.matrixWorld);
      // Rótulos y globos se desvanecen si la estación mira al fondo: sin
      // sopa de texto al lado de la estación del frente. El frente de la
      // estación es fi + FASE; cos(Δ) = 1 cuando apunta a la cámara.
      const frente = Math.cos(p.fi + R.teta - FASE);
      if(p.rotulo) p.rotulo.element.style.opacity =
        (0.32 + 0.68 * Math.max(0, frente)).toFixed(2);
      if(p.etiqueta) p.etiqueta.element.style.opacity =
        (0.35 + 0.65 * Math.max(0, frente)).toFixed(2);
    }
  }

  // 4. Núcleo vivo + faros + polvo.
  const t = ahora / 1000;
  if(R.nucleo){
    const pulso = 1 + 0.06 * Math.sin(t * 1.9);
    R.nucleo.esfera.scale.setScalar(pulso);
    R.nucleo.anilloA.rotation.z = t * 0.5;
    R.nucleo.anilloA.rotation.y = t * 0.22;
    R.nucleo.anilloB.rotation.z = -t * 0.33;
    R.nucleo.anilloB.rotation.x = Math.PI / 1.9 + t * 0.15;
    if(R.nucleo.tubo) R.nucleo.tubo.rotation.y = t * 0.1;
  }
  if(R.polvo){
    R.polvo.rotation.y = t * 0.012;
  }

  // 5. Spot de escenario: viaja con la estación del frente (o la elegida).
  const focal = R.sel ? R.puestos.findIndex(x => x.a.id === R.sel) : adelante();
  if(focal >= 0 && R.puestos[focal]){
    const p = R.puestos[focal];
    p.grupo.updateWorldMatrix(true, false);
    const punto = new THREE.Vector3().setFromMatrixPosition(p.grupo.matrixWorld);
    punto.y = 1.2;
    R.focoObjetivo.position.copy(punto);
    // El spot viaja un poco detrás del espectador: es una luz de escenario.
    R.foco.position.set(punto.x * 0.35, 7.5, Math.max(R.radio + 4.5, punto.z + 8));
    // En modo paseo es apenas un latido; al seleccionar una estación sí
    // se enciende de verdad. Intensidad alta sin selección = charco de luz
    // sobre el piso que le roba contraste al anillo.
    const flojo = 0.9 + 0.22 * Math.sin(t * 2.2);
    R.foco.intensity = R.sel ? 2.1 : flojo;
  }

  aplicarCamara();
  R.renderer.render(R.scene, R.camara);
  R.etiquetas.render(R.scene, R.camara);
  informarLiviano();
}

/* Los focos del carrusel: una estación seleccionada viaja al frente; sin
   selección, el giro automático vuelve a dominar. */
function promover(kObj){
  R.selObj = (kObj != null) ? kObj : null;
}

export function pausar(){
  if(!R) return;
  R.corriendo = false;
  if(R.raf) cancelAnimationFrame(R.raf);
  R.raf = 0;
}

export function reanudar(){
  if(!R || R.corriendo) return;
  R.corriendo = true;
  R.reloj.getDelta();                    // descarta el tiempo que estuvo pausado
  cuadro();
}

// Un cambio de ámbito o de atención cambia físicamente la estructura.
function firmaRoster(agentes){
  return JSON.stringify(agentes.filter(a => a && a.id)
    .map(a => [a.id, a.ambito || '', a.atiende !== false]));
}

export function actualizar(datos){
  if(!R || !datos) return;
  R.datos = datos;
  const ids = firmaRoster(datos.agentes || []);
  if(ids !== R.ids){
    R.ids = ids;
    desarmarEscena();
    armar();
    encuadrar();
    R.pantallas && repintarPantallas(true);
  }else{
    // Mismos agentes: cambian los estados, y con eso el color del anillo, del
    // trim, del rótulo y qué globos están a la vista. La geometría no se toca.
    const porId = new Map((datos.agentes || []).filter(a => a && a.id).map(a => [a.id, a]));
    R.puestos.forEach(p => {
      const a = porId.get(p.a.id);
      if(!a) return;
      p.a = a; p.color = colorDe(a);
      p.aviso = avisoDe(p, datos);          // puede aparecer o desaparecer
      if(p.rotulo) llenarRotulo(p.rotulo.element, a);
      if(p.mix.cur) p.mix.cur.paused = !R.mov || !a.en_curso;
    });
    transiciones();
    pintarAcentos();
    armarGlobos();
  }
  R.renderer.shadowMap.needsUpdate = true;
}

function transiciones(){
  if(!R || !R.puestos.length) return;
  repintarPantallas(false);
}

/* El bloqueo NO es por agente: `bloqueos_humanos()` habla de la red. Emparejar
   un bloqueo con una estación es HEURÍSTICA de este archivo. */
const AVISOS = [
  { agente: 'ia_reintento_listos', texto: 'ideas listas: falta un humano (red)',
    cuenta: b => (b.ideas_atascadas_listo || []).reduce((s, x) => s + (x.n || 0), 0) },
  { agente: 'router_ciclo', texto: 'hay placas en borrador: falta aprobación',
    cuenta: b => (b.en_modo_borrador || []).length },
  { agente: 'ia_reel_automatico', texto: 'canales sin autorizar (red)',
    cuenta: b => Math.max((b.canales_monitoreados || 0) - (b.canales_autorizados || 0), 0) },
];

function avisoDe(p, datos){
  const b = (datos && datos.bloqueos_humanos) || {};
  for(const a of AVISOS){
    if(a.agente === p.a.id && a.cuenta(b) > 0) return a.texto;
  }
  return null;
}

function desarmarEscena(){
  if(!R || !R.carrusel) return;
  const g = R.carrusel;
  R.scene.remove(g);
  R.scene.remove(R.clave?.target);
  // 1. Todo lo que armó esta escena fuera del carrusel: piso, dais, cara,
  //    anillos guía, núcleo, faros y polvo. Nada de esto es de la caché.
  R.descartables.forEach(deshacer);
  R.descartables = [];
  R.nucleo = null; R.faros = null; R.polvo = null;
  // 2. El carrusel: mallas, instancias y elementos DOM de los rótulos/globos.
  //    Se dispone SOLO lo que esta escena creó: la geometría y los materiales
  //    de los GLB son de la caché compartida (`COMPARTIDO`).
  g.traverse(o => {
    if(o.isCSS2DObject){ o.element?.remove(); return; }
    if(o.isInstancedMesh) o.dispose?.();    // libera los buffers de instancia
    if(!o.isMesh && !o.isInstancedMesh && !o.isPoints) return;
    let propio = !o.geometry || !COMPARTIDO?.has(o.geometry.uuid);
    if(propio) o.geometry?.dispose?.();
    const mats = Array.isArray(o.material) ? o.material : [o.material];
    for(const m of mats) if(m && !COMPARTIDO?.has(m.uuid)) m?.dispose?.();
  });
  ['plataformas', 'trims', 'faros'].forEach(k => { R[k] = null; });
  // CSS2D de elementos fuera del carrusel (cartel del núcleo).
  R.cartel?.element?.remove();
  R.cartel = null;
  R.puestos = []; R.mixers = []; R.anillos = null; R.sombras = null;
  R.trims = null; R.plataformas = null;
  if(R.cajas) for(const c of R.cajas){ c.parent?.remove(c); c.material?.dispose?.(); }
  (R.cajasGeo || []).forEach(gg => gg?.dispose?.());
  R.pantallas = null; R.cajas = null; R.cajasGeo = null;
  R.previos = {}; R.selObj = null; R.tetaPrev = -1; R.teta = 0; R.vueltas = 0;
  R.carrusel = null;
}

export function destruir(){
  return enCola(destruirReal);
}

function destruirReal(){
  if(!R) return Promise.resolve();
  const r = R;
  pausar();
  window.__OF3D_LISTO__ = false;
  r.al?.abort();
  r.ro?.disconnect();
  desarmarEscena();
  r.etiquetas.domElement.remove();
  r.renderer.domElement.remove();
  r.renderer.dispose();
  r.caja.querySelector('.of-3d-aviso')?.removeAttribute('hidden');
  R = null;
  return Promise.resolve();
}

/* Contadores livianos cada 2 s: información de arnés sin spam por frame. */
let ultimoInforme = 0;
function informarLiviano(){
  if(!R || performance.now() - ultimoInforme < 2000) return;
  ultimoInforme = performance.now();
  informar();
}

function informar(){
  if(!R || !R.carrusel) return;
  const i = R.renderer.info;
  const cuenta = conteoEstados((R.datos.agentes || []));
  window.__OF3D_INFO__ = {
    modo: R.modo,
    mov: R.mov,
    draws: i.render.calls, geometrias: i.memory.geometries, texturas: i.memory.textures,
    radio: R.radio, teta: R.teta,
    cols: R.puestos.length, rows: 1,
    agentes: R.puestos.length,
    propios: R.puestos.length, enLaRed: 0,
    activos: cuenta.activos, trabajando: cuenta.curso, errores: cuenta.error,
    rotulos: R.puestos.filter(p => p.rotulo).length,
    globos: R.puestos.filter(p => p.etiqueta).length,
    animados: R.mixers.length,
    pantallas: R.pantallas ? R.pantallas.conPc.length : 0,
    frente: adelante(),
    ejemploRotulo: R.puestos[0]?.rotulo?.element?.textContent || '',
  };
}
