/* ═══ OFICINA 3D — agentes y actividad desde /radar/oficina ═══ */

import * as THREE from '../vendor/three/three.module.min.js';
import { GLTFLoader } from '../vendor/three/jsm/loaders/GLTFLoader.js';
import { RoundedBoxGeometry } from '../vendor/three/jsm/geometries/RoundedBoxGeometry.js';
import { CSS2DRenderer, CSS2DObject } from '../vendor/three/jsm/renderers/CSS2DRenderer.js';
import { clone as clonarEsqueleto } from '../vendor/three/jsm/utils/SkeletonUtils.js';
import { mergeGeometries } from '../vendor/three/jsm/utils/BufferGeometryUtils.js';

/* ── la oficina de un medio ─────────────────────────────────────────────────── */
const CELDA_X = 3.2, CELDA_Z = 3.6;      // puesto amplio, premium
const MAX_COLS = 4;                       // sala amplia, menos hacinamiento
const BANDA = 5.2;                        // gran sala de reuniones
const PARED = 0.30, ALTO_FONDO = 4.2, ALTO_LATERAL = 3.0;

/* ── el edificio que lo contiene todo ───────────────────────────────────────── */
// Sin PASILLO la sala terminaba en una losa cortada y se veía el color del fog:
// eso es el "fondo blanco vacío" que vio el operator. El edificio envuelve la
// sala con piso corrido, muro perimetral y luminarias, y la niebla pasa al tono
// de pared, así que nunca hay un hueco de color plano en el encuadre.
const PASILLO = 5.0, ALTO_EDIF = 5.0, ESPESOR = 0.40;

const PAL = {
  piso: '#2a2520', yeso: '#3a3530', cornisa: '#4a4540',
  alfombra: '#4a3f35',
  // `fierro`: el metal de la luminaria. Neutro y oscuro — el verde `marco` que
  // estaba declarado y nunca se usaba hacía que el perfil se leyera como un
  // objeto flotando en el medio de la sala en vez de como parte del techo.
  fierro: '#5b564c',
  pasillo: '#1a1f33', exterior: '#0d1220', zocalo: '#2a3050', luminaria: '#fff2d8',
};
// El fondo NO es un color plano: es una gradación de pared lejana. Con niebla al
// tono de muro, lo que asoma por encima del edificio se lee como ambiencia de
// sala grande, no como un rectángulo blanco detrás de la oficina.
// El stop claro estaba en #c9beaa y, estirado en el cuadro, formaba UNA franja
// horizontal pálida a un tercio de la altura: el segundo "caño" del metegol. Se
// baja el brillo del centro y se aprieta la niebla para que el horizonte no lave.
const CIELO = ['#0a0e1a', '#1a1f33', '#2a3050', '#1a1f33'];
const NIEBLA = { color: '#0a0e1a', cerca: 30, lejos: 150 };
// Tope de la elevación de cámara. El muro perimetral que cierra el vacío mide
// ALTO_EDIF y la cámara orbita FUERA del edificio: a 1,45 rad el rayo al centro
// cruzaba el muro por debajo de su altura y la sala desaparecía detrás de la
// fachada. Con 1,22 el ojo siempre pasa por arriba del muro de enfrente.
const FASE_MAX = 1.10;

const LUZ = {
  sol: '#ffd9a8', cielo: '#fff3e0', intensidadSol: 2.0,
  // El relleno era `#ffffff` a 0,7: una luz blanca sin sombra que lavaba el piso
  // y las bandas claras. Ahora entra teñida al yeso de la sala y más baja.
  relleno: '#e8d5b7', intensidadRelleno: 0.8,
  hemisferio: 1.6, exposicion: 1.15,
};
const COLOR = { ok: 0x4f9d69, error: 0xd94141, reposo: 0x8a8a8a, sinturno: 0xd9a441,
                 curso: 0x2f7ad1 };

const RUTA = '/oficina3d/';
const MUEBLE = {
  escritorio: 'furniture/pub-workstation-v1.glb',
  silla: 'furniture/office-chair-v1.glb',
  mesa: 'furniture/conference-table-v1.glb',
  impresion: 'furniture/pub-print-bench-v1.glb',
  pizarra: 'furniture/mobile-board-v1.glb',
};
const PERSONAJES = ['characters/office-bomi.glb', 'characters/office-seo.glb',
                    'characters/office-tae.glb'];

let R = null;                             // la escena montada, o null

/* ── estado de un agente → visual ──────────────────────────────────────────── */
function colorDe(a){
  // El azul es el latido: el anillo dice "está corriendo AHORA", algo que antes
  // no se podía saber porque el backend solo informaba el registro del job.
  if(a.en_curso) return 'curso';
  if(a.estado === 'reposo') return 'reposo';
  if(a.estado !== 'activo') return 'sinturno';
  const u = a.ultima;
  if(u && (u.ok === false || u.perdido)) return 'error';
  return 'ok';
}

// El globo SOLO grita lo que hay que mirar: un turno que terminó mal. El tiempo
// ("hace 12 min") se retiró de la escena por pedido del operator — vive en la
// ficha, que es donde se lee. Con globos de tiempos en los 26 puestos la escena
// volvía a ser la Lista pero en 3D.
function globoDe(a){
  const u = a.ultima;
  if(!u) return null;
  if(u.ok === false || u.perdido)
    return { txt: '⚠ ' + String(u.error || 'turno perdido').slice(0, 46), mal: true };
  return null;
}

function grilla(n){
  const cols = Math.max(1, Math.min(MAX_COLS, Math.ceil(Math.sqrt(Math.max(n, 1) * 1.15))));
  return { cols, rows: Math.max(1, Math.ceil(Math.max(n, 1) / cols)) };
}

// La identidad visual depende del id, no del lugar que ocupa en el payload.
function modeloDe(id){
  let h = 0;
  for(const c of String(id)) h = (Math.imul(h, 31) + c.charCodeAt(0)) >>> 0;
  return h % PERSONAJES.length;
}

/* ── las texturas que se generan en canvas, una vez por página ─────────────── */
// Son diminutas (256²) y compartidas entre montajes: por eso `desarmarEscena()`
// dispone los MATERIALES pero nunca sus `map`. Disponer una textura compartida
// dejaría ciego el siguiente montaje.
const TEX = { piso: null, sombra: null, cielo: null };

function texturaPiso(){
  if(TEX.piso) return TEX.piso;
  const c = document.createElement('canvas');
  c.width = c.height = 256;
  const g = c.getContext('2d');
  g.fillStyle = PAL.piso; g.fillRect(0, 0, 256, 256);
  const tablas = 4, alto = 256 / tablas;
  for(let i = 0; i < tablas; i++){
    const y = i * alto;
    // La junta entre tablas es lo que hace que un piso grande no se lea como
    // una mesa lisa: sin ella la losa se ve plastificada.
    // El alterno era `rgba(255,255,255,.06)`, o sea una tabla BLANCA cada 64 px
    // sobre un material con `color:#ffffff` y UV de 2,2 m: una franja clara cada
    // 1,1 m. La veta se marca alternando dos
    // tintes sombra, que es como se ve un parquet de verdad bajo luz rasante.
    g.fillStyle = i % 2 ? 'rgba(0,0,0,.05)' : 'rgba(0,0,0,.016)';
    g.fillRect(0, y, 256, alto);
    for(let j = 0; j < 22; j++){
      g.strokeStyle = 'rgba(94,74,50,' + (0.04 + Math.random() * 0.06) + ')';
      g.lineWidth = 1;
      const yy = y + Math.random() * alto;
      g.beginPath(); g.moveTo(0, yy);
      g.bezierCurveTo(70, yy + (Math.random() * 5 - 2.5), 180, yy + (Math.random() * 5 - 2.5), 256, yy);
      g.stroke();
    }
    g.fillStyle = 'rgba(58,44,28,.5)';
    g.fillRect(0, y + alto - 2, 256, 2);
    g.fillRect((i * 97) % 256, y, 2, alto);       // junta de testa, escalonada
  }
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  TEX.piso = t;
  return t;
}

// Sombra falsa: una elipse suave bajo el personaje. Con `shadowMap.autoUpdate`
// apagado las sombras reales se calculan una vez, y esto es lo que hace que el
// cuerpo pise el piso aunque la escena no se re-sombree en cada cuadro.
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

/* ── la PC de cada agente: UN atlas, UN draw ───────────────────────────────── */
// La pantalla NO es un objeto del GLB: el mueble viene instanciado (11 primitivas
// sin nombre) y una pantalla por agente sería 26 meshes, 26 materiales y 26 draws
// más una textura cada uno. Acá es un canvas compartido en grilla —una celda por
// escritorio— y la geometría de los vidrios es UN solo mesh fusionado: 1 draw y
// 1 subida de textura por repintado, no por agente.
//
// `PANTALLA` está medido sobre `pub-workstation-v1.glb`: la primitiva más alta
// (mesh 8 / node 9) es el monitor, y su caja en coordenadas del mueble es
// x −0.764..−0.477, y 0.89..1.409, z 0.075..0.365. La cara que mira a la cámara
// es la de −Z, o sea la ESPALDA del monitor (el agente está sentado al +Z y mira
// a −Z, hacia el vidrio). Por eso `cara:'camara'`: el panel se mostra como en una
// vista isométrica de oficina, de frente al que mira, aunque el mueble tenga el
// vidrio del otro lado. Con `caja:true` se dibuja el wireframe de la caja real del
// monitor y se puede verificar/ajustar `w/h/x/y/z` desde el arnés.
const PANTALLA = { w:0.26, h:0.47, x:-0.62, y:1.1495, z:0.06, cara:'camara', caja:false };
const CELDA = { w:128, h:232, cols:4 };        // 128/232 ≈ la proporción del vidrio

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
  // La grilla se reusa solo si alcanza: achicar el canvas descartaría las celdas
  // de los montajes anteriores, y agrandarlo deja basura pintada donde no hay vidrio.
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
// Con `cara:'camara'` el plano está girado π para mirar a la cámara, así que se
// espeja `u` — si no, todo el texto saldría al revés.
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

function quadDePantalla(k, at, p){
  const geo = new THREE.PlaneGeometry(PANTALLA.w, PANTALLA.h);
  hornearUVs(geo, k, at);
  const m = new THREE.Matrix4()
    .makeTranslation(p.x + PANTALLA.x, PANTALLA.y, p.z + PANTALLA.z);
  if(PANTALLA.cara === 'camara') m.multiply(new THREE.Matrix4().makeRotationY(Math.PI));
  geo.applyMatrix4(m);
  return geo;
}

/* ── qué se pinta en cada vidrio (solo lo que llegó del backend) ────────────── */
function firmaDePantalla(p){
  const a = p.a;
  // `segundos` se redondeja a 30: sin eso cada refresco reescribiría la celda y
  // subiría el atlas entero por un cronómetro que nadie lee tan rápido.
  const s = a.segundos == null ? '' : Math.round(a.segundos / 30);
  return [a.rol || '', a.estado || '', a.en_curso ? 1 : 0, s, a.faena || '',
          a.hoy == null ? '' : a.hoy, a.hoy_texto || '', p.aviso || '',
          (a.ultima || {}).en || ''].join('|');
}

function envolver(ctx, txt, ancho){
  // Un token que no cabe solo (`laburo_changa_rosario`, una URL en un error) se
  // parte a la fuerza: si no, desborda la celda y el vecino —que se pinta después,
  // con su fondo— lo borra a media palabra.
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
  const apagada = a.estado !== 'activo';
  const borde = css(COLOR[colorDe(a)] ?? COLOR.sinturno);
  // La celda se pinta ENTERA: si no, el texto viejo del refresco anterior se
  // queda encima y la pantalla muestra dos faenas a la vez.
  g.fillStyle = apagada ? '#14161a' : '#0b1016';
  g.fillRect(X, Y, CELDA.w, CELDA.h);
  g.strokeStyle = borde; g.lineWidth = 3;
  g.strokeRect(X + 1.5, Y + 1.5, CELDA.w - 3, CELDA.h - 3);
  g.fillStyle = apagada ? '#4a5157' : borde;
  g.fillRect(X + 3, Y + 3, CELDA.w - 6, 26);
  g.textBaseline = 'top';
  g.fillStyle = apagada ? '#7d858c' : '#08090b';
  g.font = 'bold 12px system-ui, sans-serif';
  const rol = envolver(g, (a.rol || a.nombre || '').toUpperCase(), CELDA.w - 12).slice(0, 2);
  rol.forEach((l, i) => g.fillText(l, X + 6, Y + 8 + i * 11));

  let y = Y + 36;
  g.font = '13px system-ui, sans-serif';
  if(p.aviso){
    // La franja de lo que espera un humano: es HEURÍSTICA del frente (un bloqueo
    // de red no es por agente) y por eso dice "red", nunca "este agente midió X".
    g.fillStyle = css(COLOR.sinturno);
    g.fillRect(X + 3, y, CELDA.w - 6, 20);
    g.fillStyle = '#1a1408'; g.font = 'bold 10.5px system-ui, sans-serif';
    envolver(g, p.aviso, CELDA.w - 12).slice(0, 2)
      .forEach((l, i) => g.fillText(l, X + 6, y + 4 + i * 11));
    y += 26;
    g.font = '13px system-ui, sans-serif';
  }
  if(apagada){
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
    // Dos líneas, no una: "TRABAJANDO ⏱300s" mide ~122px y la celda tiene 116
    // útiles, así que el vecino —que se pinta después con su fondo— se comía los
    // segundos. Sobra lugar vertical (la celda mide 232).
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

/* ── constructores compartidos por las dos escenas ──────────────────────────── */
// Un pool de cajas redondeadas: el edificio entero (losas, paredes, zócalos,
// bandas de pasillo) son INSTANCIAS de una misma geometría escalada, con color
// por instancia. Cien `Mesh` serían cien draws y cien geometrías; esto es uno.
function Pool(padre, material, op){
  const o = op || {};
  // El radio se mide sobre la caja UNITARIA y después se escala a mano: a 21 m de
  // largo el filo redondeado salía de 0,41 m y aplastado a 7 cm de espesor, de
  // 2 mm. O sea lentejas sin arista por todo el edificio. Se baja el radio y las
  // piezas muy alargadas se hacen caja viva con `{roma:true}`.
  const geo = o.roma ? new THREE.BoxGeometry(1, 1, 1)
                     : new RoundedBoxGeometry(1, 1, 1, 2, 0.016);
  const mat = material || new THREE.MeshStandardMaterial({ roughness: 0.92 });
  const ms = [], cs = [], tmp = new THREE.Object3D();
  return {
    caja(w, h, d, x, y, z, color){
      tmp.position.set(x, y, z); tmp.scale.set(w, h, d); tmp.rotation.set(0, 0, 0);
      tmp.updateMatrix();
      ms.push(tmp.matrix.clone()); cs.push(new THREE.Color(color));
    },
    construir(){
      if(!ms.length) return null;
      const im = new THREE.InstancedMesh(geo, mat, ms.length);
      ms.forEach((m, i) => { im.setMatrixAt(i, m); im.setColorAt(i, cs[i]); });
      im.instanceMatrix.needsUpdate = true;
      if(im.instanceColor) im.instanceColor.needsUpdate = true;
      // `sinSombra`: una lámpara colgada a 3,4 m proyectando su propia banda
      // sobre la sala es literalmente la franja clara/flotante que se veía.
      im.castShadow = !o.sinSombra; im.receiveShadow = true;
      padre.add(im);
      return im;
    },
  };
}

// Las luminarias comparten materiales y se agrupan para reducir los draws.
function poolsLuz(g){
  return {
    // Difusor: caja viva (es una pieza alargada, ver `Pool`) y SIN sombra. El
    // `emissive` a 0,22: a 0,85 la tira se autoiluminaba hasta el blanco puro y
    // era indistinguible de una banda de luz sobre la niebla.
    difusor: new Pool(g, new THREE.MeshStandardMaterial({
      roughness: 0.8, emissive: PAL.luminaria, emissiveIntensity: 0.22,
    }), { sinSombra: true, roma: true }),
    // `roma` también acá: el brazo mide el 72 % del ancho del edificio (hasta
    // 21 m) y con RoundedBox escalado el radio sería de 60 cm, o sea una
    // salchicha. Un perfil de luminaria es arista viva.
    marco: new Pool(g, new THREE.MeshStandardMaterial({ roughness: 0.5 }),
      { sinSombra: true, roma: true }),
  };
}

// El piso texturado: un solo plano con las UV multiplicadas por su tamaño, para
// que la tabla conserve su escala en cualquier tamaño de sala.
function pisoPlano(w, d, x, z, tile){
  const geo = new THREE.PlaneGeometry(w, d);
  const uv = geo.attributes.uv;
  for(let i = 0; i < uv.count; i++)
    uv.setXY(i, uv.getX(i) * (w / tile), uv.getY(i) * (d / tile));
  uv.needsUpdate = true;
  const m = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({
    map: texturaPiso(), roughness: 0.88, color: '#ffffff',
  }));
  m.rotation.x = -Math.PI / 2;
  m.position.set(x, 0, z);
  m.receiveShadow = true;
  return m;
}

// El envoltorio: muro perimetral alto, su zócalo y las luminarias que caen sobre
// los pasillos. Es lo que reemplaza al vacío: la cámara, que está a ~13 m de
// altura mirando hacia abajo, siempre encuentra muro o piso antes que el fondo.
function edificio(pool, luz, carcasa, x0, z0, x1, z1){
  const cx = (x0 + x1) / 2, cz = (z0 + z1) / 2, w = x1 - x0, d = z1 - z0;
  pool.caja(w + ESPESOR * 2, ALTO_EDIF, ESPESOR, cx, ALTO_EDIF / 2, z0 - ESPESOR / 2, PAL.exterior);
  pool.caja(w + ESPESOR * 2, ALTO_EDIF, ESPESOR, cx, ALTO_EDIF / 2, z1 + ESPESOR / 2, PAL.exterior);
  pool.caja(ESPESOR, ALTO_EDIF, d, x0 - ESPESOR / 2, ALTO_EDIF / 2, cz, PAL.exterior);
  pool.caja(ESPESOR, ALTO_EDIF, d, x1 + ESPESOR / 2, ALTO_EDIF / 2, cz, PAL.exterior);
  // Zócalo: sin él la pared nace del piso como un papel.
  pool.caja(w, 0.16, 0.07, cx, 0.08, z0 + 0.035, PAL.zocalo);
  pool.caja(w, 0.16, 0.07, cx, 0.08, z1 - 0.035, PAL.zocalo);
  pool.caja(0.07, 0.16, d, x0 + 0.035, 0.08, cz, PAL.zocalo);
  pool.caja(0.07, 0.16, d, x1 - 0.035, 0.08, cz, PAL.zocalo);
  // Cornisa interior del muro: otra línea horizontal que da escala humana.
  pool.caja(w + ESPESOR * 2, 0.1, ESPESOR + 0.08, cx, ALTO_EDIF - 0.05, z0 - ESPESOR / 2, PAL.cornisa);
  pool.caja(w + ESPESOR * 2, 0.1, ESPESOR + 0.08, cx, ALTO_EDIF - 0.05, z1 + ESPESOR / 2, PAL.cornisa);
  // LUMINARIAS. Antes: 5 barras continuas de 14-21 m, de 7 cm de canto, a 3,38 m,
  // paralelas, autoiluminadas (emissive 0,85) y proyectando su propia banda, sin
  // nada donde estar colgadas. Eso es exactamente la "franja blanca flotante" que
  // hacía parecer un metegol. Ahora es un artefacto: perfil de metal de pared a
  // pared (las puntas TOCAN el muro: por eso se lee montado y no flotando) y
  // difusor en TRAMOS cortos con junta, y nada de esto tira sombra.
  // No hay cielo raso: la sala se mira desde arriba. El brazo y la carcasa
  // anclan visualmente las luminarias.
  // Luminarias eliminadas: oficina lux sin luces flotantes.
}

// Agrupa por (geometría, material) para dibujar N puestos en pocos draws: 25
// escritorios de 11 mallas son ~11 draws, no 275.
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
// La caché es POR ARCHIVO, no del conjunto: si un GLB se corta por una conexión
// floja, se re-intenta ese y no se tiran los 7 que ya estaban abajo.
let ASSETS = null;
const BAJADO = new Map();
const TOTAL_GLB = 5 + PERSONAJES.length;
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
  const rutas = [MUEBLE.escritorio, MUEBLE.silla, MUEBLE.mesa, MUEBLE.impresion,
                 MUEBLE.pizarra, ...PERSONAJES];
  let hechos = 0;
  const conProgreso = r => bajar(c, r, 3).then(g => {
    hechos++; if(alProgreso) alProgreso(hechos, TOTAL_GLB, r); return g;
  });
  ASSETS = Promise.all(rutas.map(conProgreso)).then(([esc, silla, mesa, impr, piz, ...cuerpos]) => {
    const propios = { escritorio: esc, silla, mesa, impresion: impr, pizarra: piz, cuerpos };
    // La lista de lo compartido se arma UNA vez, sobre los GLB crudos: así el
    // desarmado de la escena puede disponer todo lo demás sin tocar la caché.
    COMPARTIDO = new Set();
    for(const gltf of [esc, silla, mesa, impr, piz, ...cuerpos]){
      gltf.scene.traverse(o => {
        if(!o.isMesh) return;
        COMPARTIDO.add(o.geometry.uuid);
        for(const m of (Array.isArray(o.material) ? o.material : [o.material])) COMPARTIDO.add(m.uuid);
      });
    }
    return propios;
  }).catch(e => { ASSETS = null; COMPARTIDO = null; throw e; });
  return ASSETS;
}

/* ── API pública ───────────────────────────────────────────────────────────── */
// three r180 NO habla WebGL1: preguntar por cualquier contexto de WebGL mentiría
// "sí" en un teléfono viejo que después revienta al crear el renderer. Se pide
// webgl2 explícitamente y se dice el motivo, para que el fallback a Lista explique
// algo más que "no arrancó".
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
// Cambiar de medio mientras la sala está bajando dispara un segundo `montar` antes
// de que el primero termine: los dos veían el escenario vacío, los dos construían,
// y quedaban dos canvas con dos salas de 25 puestos montadas una encima de la otra
// (50 rótulos, ~1000 draw calls). La cola hace que el montaje nuevo espere al
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

async function montarReal(caja, datos, opciones = {}){
  await destruirReal();
  const raz = motivo();
  if(raz) throw new Error(raz);
  const modo = 'oficina';
  // La caja se mide DESPUÉS de la espera: cambiar de medio mientras la sala está
  // bajando deja el hueco sin layout un instante, y un renderer que nace con el
  // mínimo de 320×240 se queda chico para siempre si nadie lo rectifica.
  await esperarLayout();
  const [ancho, alto] = tamanoDe(caja);
  const movil = window.innerWidth < 720 || Math.min(ancho, alto) < 460;
  const aviso = caja.querySelector('.of-3d-aviso');

  const renderer = new THREE.WebGLRenderer({ antialias: !movil, powerPreference: 'high-performance' });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, movil ? 1.25 : 1.75));
  renderer.setSize(ancho, alto);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.shadowMap.autoUpdate = false;      // la sala es quieta: se sombrea una vez
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

  const camara = new THREE.PerspectiveCamera(46, ancho / alto, 0.1, 240);
  const sol = new THREE.DirectionalLight(LUZ.sol, LUZ.intensidadSol);
  sol.position.set(7, 12, -4);
  sol.castShadow = true;
  sol.shadow.mapSize.set(movil ? 512 : 1024, movil ? 512 : 1024);
  sol.shadow.bias = -0.0006;
  // `normalBias`: con un mapa de 1024 sobre ±18 m el texel mide 3,5 cm y el
  // sesgo solo desplaza la figura de la sombra (peter-panning: los cuerpos
  // flotan). Moviéndolo a lo largo de la normal se recupera el contacto.
  sol.shadow.normalBias = 0.03;
  const relleno = new THREE.DirectionalLight(LUZ.relleno, LUZ.intensidadRelleno);
  relleno.position.set(-6, 5, 9);
  scene.add(sol, new THREE.HemisphereLight(LUZ.cielo, '#b6a68c', LUZ.hemisferio), relleno);

  R = {
    caja, renderer, etiquetas, scene, camara, sol, datos, movil, modo,
    onSeleccion: opciones.onSeleccion || (() => {}),
    mov: !window.matchMedia('(prefers-reduced-motion: reduce)').matches,
    puestos: [], mixers: [], anillos: null, sombras: null, alfombras: null,
    pantallas: null, cajas: null, cajasGeo: null,
    g: null, sala: null,
    previos: {}, caminando: 0, tiempo: 0, muebles: null,
    reloj: new THREE.Clock(), raf: 0, corriendo: false, sel: '',
    al: null, ro: null, ids: '', ancho, alto,
    orbita: { th: -Math.PI / 2, ph: 0.9, r: 20, tr: 20, tx: 0, tz: 0, ttx: 0, ttz: 0 },
    // Recorre la escena buscando instancias con matriz NaN (la GPU las descarta en
    // silencio) y emisivos sobre el umbral (las franjas que se leían blancas).
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
    emisivosAltos(limite = 0.4){
      const fuera = [];
      scene.traverse(o => {
        for(const m of (Array.isArray(o.material) ? o.material : [o.material]))
          if(m && m.emissiveIntensity > limite &&
             m.emissive && m.emissive.getHex() !== 0) fuera.push(m.uuid.slice(0, 8));
      });
      return [...new Set(fuera)];
    },
  };

  // 45 s, no 15: son ~3 MB de mobiliario pasando por el gate del dominio, y un plazo
  // corto mataba descargas que iban por buen camino. El progreso se ve en la barra de
  // aviso, así que "tarda" no se confunde con "se colgó".
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
  encuadrarTodo();
  aplicarCamara();
  enlazar();
  reanudar();
  // El aviso "Armando la oficina…" vive en la plantilla: si no se apaga, queda
  // escrito sobre la escena terminada para siempre.
  caja.querySelector('.of-3d-aviso')?.setAttribute('hidden', '');

  window.__OF3D_LISTO__ = true;
  // El hook de prueba hace lo que un click: encuadra Y abre la ficha. Si solo
  // moviera la cámara, el arnés verificaría un camino que el usuario no recorre.
  window.__OF3D_FOCAR__ = id => {
    focar(id);
    const p = id && R && R.puestos.find(x => x.a.id === id);
    if(p) R.onSeleccion(p.a);
  };
  // El arnés mide el costo real de las pantallas: apagando la malla se ve el delta
  // EXACTO de draws. Dieciséis vidrios fusionados cuestan un draw, no dieciséis.
  window.__OF3D_PC__ = v => { if(R && R.pantallas) R.pantallas.malla.visible = !!v; };
  // Y puede leer el atlas: es literalmente lo que hay en los vidrios, sin depender
  // de que la cámara llegue a tiempo (en swiftshader el lerp necesita decenas de
  // cuadros y esta caja llegó a renderizar a 0,06 fps con un video encima).
  window.__OF3D_ATLAS__ = () => (R && R.pantallas ? R.pantallas.atlas.canvas : null);
  // La invariante que faltaba cuando se fueron los muros laterales: una matriz de
  // instancia con NaN no se dibija y NO da ningún error en consola. Se auditan las
  // dos cosas que pueden romper la escena en silencio.
  window.__OF3D_AUDIT__ = () => ({
    instanciasNaN: [...(R ? R.instanciasRotas() : [])],
    emisivosAltos: [...(R ? R.emisivosAltos() : [])],
  });
  informar();
  return R;
}

/* ── la oficina de un medio ─────────────────────────────────────────────────── */
function armar(){
  const g = new THREE.Group();
  const todos = (R.datos.agentes || []).filter(a => a && a.id);
  // Un medio, una oficina. El piso de escritorios son SUS agentes de producción
  // (redacción, video, placas, edición, medición); cobertura, estrategia y
  // mantenimiento son la retaguardia de la red — una sola mesa de entradas para
  // los diez — y van a la mesa de reuniones. Los que `atiende:false` (el medio no
  // tiene cuenta conectada) no se sientan: en una redacción sin reparto no hay
  // repartidor, y la Lista lo explica con su tarjeta.
  //
  // `ambito` lo manda oficina.py. Si el contenedor que sirve los `.py` todavía no
  // tiene ese campo (static/ y los `.py` se despliegan aparte), todos van al piso:
  // una oficina vacía por un desfasaje de deploy sería peor que la foto vieja.
  const hayRoster = todos.some(a => a.ambito);
  const propios = todos.filter(a => a.atiende !== false &&
    (!hayRoster || a.ambito === 'medio'));
  const red = hayRoster ? todos.filter(a => a.ambito === 'red') : [];
  const { cols, rows } = grilla(propios.length);
  const W = cols * CELDA_X, D = rows * CELDA_Z;
  const sentados = propios.length + red.length;
  R.g = { g, cols, rows, agentes: propios, red };
  R.sala = { W, D };
  R.ids = firmaRoster(todos);   // incluye cambios de ámbito y atención, no solo ids

  const pool = new Pool(g);
  const { difusor, marco } = poolsLuz(g);
  // El piso es del EDIFICIO, no de la sala: la losa se extiende PASILLO más allá
  // de las paredes y el muro perimetral cierra el encuadre.
  const x0 = -PASILLO, z0 = -PASILLO, x1 = W + PASILLO, z1 = D + BANDA + PASILLO;
  g.add(pisoPlano(x1 - x0 + ESPESOR * 2, z1 - z0 + ESPESOR * 2, (x0 + x1) / 2, (z0 + z1) / 2, 2.2));
  edificio(pool, difusor, marco, x0, z0, x1, z1);

  // La pared del fondo va alta y los laterales a media altura: la cámara mira
  // desde el frente y una caja cerrada taparía media redacción.
  pool.caja(W + PARED * 2, ALTO_FONDO, PARED, W / 2, ALTO_FONDO / 2, 0, PAL.yeso);
  pool.caja(W + PARED * 2, 0.09, PARED + 0.06, W / 2, ALTO_FONDO + 0.025, 0, PAL.cornisa);
  pool.caja(W + PARED * 2, 0.14, PARED + 0.045, W / 2, 0.09, 0, PAL.piso);
  // OJO al orden: `caja(w,h,d, x,y,z, color)`. Aquí se pasaba el color en la X,
  // así que `position.set('#e9e1cf', …)` daba NaN en la matriz de instancia (la
  // GPU descartaba la instancia) y `new THREE.Color(7)` negro: los dos muros
  // laterales de la sala NUNCA se dibujaron y la escena quedaba abierta sobre la
  // niebla — media causa del "fondo blanco flotante".
  pool.caja(PARED, ALTO_LATERAL, D + BANDA, 0, ALTO_LATERAL / 2, (D + BANDA) / 2, PAL.yeso);
  pool.caja(PARED, ALTO_LATERAL, D + BANDA, W, ALTO_LATERAL / 2, (D + BANDA) / 2, PAL.yeso);
  // Zócalo de la sala, por dentro.
  pool.caja(W, 0.14, 0.06, W / 2, 0.07, PARED / 2 + 0.03, PAL.zocalo);
  pool.caja(0.06, 0.14, D + BANDA - 0.1, PARED / 2 + 0.03, 0.07, (D + BANDA) / 2, PAL.zocalo);
  pool.caja(0.06, 0.14, D + BANDA - 0.1, W - PARED / 2 - 0.03, 0.07, (D + BANDA) / 2, PAL.zocalo);
  // Banda de pasillo al frente: lo que ve la cámara por debajo de la sala.
  pool.caja(W + PARED * 2, 0.02, 1.1, W / 2, 0.006, D + BANDA + 0.6, PAL.pasillo);

  const inst = new Instanciador(g);
  // Banda de atrás: mesa de reuniones, banco de impresión y pizarra. Es lo que
  // hace que se lea como una redacción y no como un depósito de escritorios.
  const zBanda = D + BANDA / 2;
  const mesaX = W / 2;
  // Los dos destinos del movimiento, en el mismo lugar donde se instanció el
  // mueble: el banco de impresión (se para al costado, no encima) y el extremo de
  // la mesa de reuniones.
  R.muebles = { mesaX, zBanda, impresora: [1.6 + 0.8, zBanda + 1.4],
                mesa: [mesaX - 1.5, zBanda - 1.25] };
  // Las huellas salen de los GLB usados en esta sala, no de tamaños supuestos.
  R.navegacion = { W, D: D + BANDA, obstaculos: [] };
  function obstaculo(modelo, matriz, dueño = null){
    const caja = new THREE.Box3().setFromObject(modelo).applyMatrix4(matriz);
    R.navegacion.obstaculos.push({ minX: caja.min.x, maxX: caja.max.x,
                                   minZ: caja.min.z, maxZ: caja.max.z, dueño });
  }
  const mesaMat = new THREE.Matrix4().makeScale(1.4, 1.4, 1.4).multiply(new THREE.Matrix4().makeTranslation(mesaX, 0, zBanda));
  obstaculo(R.assets.mesa.scene, mesaMat);
  obstaculo(R.assets.impresion.scene, new THREE.Matrix4().makeTranslation(1.6, 0, zBanda + 1.4));
  obstaculo(R.assets.pizarra.scene, new THREE.Matrix4().makeTranslation(W - 1.6, 0, zBanda)
    .multiply(new THREE.Matrix4().makeRotationY(-Math.PI / 2)));
  inst.agregar(R.assets.mesa.scene, mesaMat);
  inst.agregar(R.assets.impresion.scene, new THREE.Matrix4().makeTranslation(1.6, 0, zBanda + 1.4));
  // Premium rug under conference table
  pool.caja(W * 0.9, 0.04, BANDA * 0.9, W / 2, 0.02, zBanda, '#3a2f25');
  inst.agregar(R.assets.pizarra.scene, new THREE.Matrix4().makeTranslation(W - 1.6, 0, zBanda)
    .multiply(new THREE.Matrix4().makeRotationY(-Math.PI / 2)));

  const geoAnillo = new THREE.TorusGeometry(0.44, 0.035, 8, 28);
  geoAnillo.rotateX(-Math.PI / 2);
  R.anillos = new THREE.InstancedMesh(geoAnillo,
    new THREE.MeshStandardMaterial({ roughness: 0.55 }), Math.max(sentados, 1));
  R.anillos.count = sentados;
  R.anillos.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
  g.add(R.anillos);

  const geoSombra = new THREE.CircleGeometry(0.48, 20);
  geoSombra.rotateX(-Math.PI / 2);
  R.sombras = new THREE.InstancedMesh(geoSombra, new THREE.MeshBasicMaterial({
    map: texturaSombra(), transparent: true, depthWrite: false,
  }), Math.max(sentados, 1));
  R.sombras.count = sentados;
  g.add(R.sombras);

  // Alfombra bajo cada puesto: sin ella el escritorio pisa el parquet y la sala
  // parece un showroom; con ella cada agente tiene su tapete de trabajo.
  const geoAlfombra = new THREE.PlaneGeometry(1.9, 1.5);
  geoAlfombra.rotateX(-Math.PI / 2);
  R.alfombras = new THREE.InstancedMesh(geoAlfombra,
    new THREE.MeshStandardMaterial({ color: PAL.alfombra, roughness: 1 }),
    Math.max(propios.length, 1));
  R.alfombras.count = propios.length;
  R.alfombras.receiveShadow = true;
  g.add(R.alfombras);

  const tmp = new THREE.Object3D();
  let puesto = 0;

  // Sentar a un agente: silla + cuerpo + animación + anillo + sombra + rótulo.
  // Sirve igual para el escritorio del medio que para la mesa de la red.
  function sentar(a, x, z, giro, conEscritorio){
    const i = puesto++;
    const modelo = R.assets.cuerpos[modeloDe(a.id)];
    const cuerpo = clonarEsqueleto(modelo.scene);
    cuerpo.position.set(x, 0, z);
    cuerpo.rotation.y = giro;
    cuerpo.traverse(o => { if(o.isMesh){ o.castShadow = true; o.receiveShadow = false; } });
    g.add(cuerpo);

    // Los clips viven en `gltf.animations`, NO en la scene: el clone del
    // esqueleto no se los lleva y buscarlos en el cuerpo devuelve null.
    const clips = modelo.animations;
    const mixer = new THREE.AnimationMixer(cuerpo);
    const acc = nombre => {
      const clip = THREE.AnimationClip.findByName(clips, nombre);
      return clip ? mixer.clipAction(clip) : null;
    };
    // Las TRES acciones se guardan: `walk` estaba bajado y nunca usado, y sin él
    // no hay traslado posible. Se elige la pose por transición real (`irA`), no
    // por un reloj propio.
    const p = { a, i, x, z, giro, cuerpo, etiqueta: null, rotulo: null,
                color: colorDe(a), escritorio: !!conEscritorio,
                sitX: x, sitZ: z, mix: { mixer, sit: acc('sit'), idle: acc('idle'),
                                         walk: acc('walk'), cur: null },
                ruta: null, hasta: 0, aviso: null, celda: -1, enEspera: false,
                pedido: null, enReunion: false, alVuelta: false, salida: 0 };
    const arrancar = p.mix.sit || p.mix.idle;
    if(arrancar){
      arrancar.play();
      p.mix.cur = arrancar;
      // La pose sentada solo se anima mientras el job está realmente corriendo.
      // Los demás conservan una pose fija: estar registrado no significa trabajar.
      arrancar.time = 0.2;
      arrancar.paused = !R.mov || !a.en_curso;
      mixer.update(0);
      R.mixers.push({ mixer, acc: arrancar });
    }

    tmp.position.set(x, 0.02, z); tmp.scale.setScalar(1); tmp.rotation.set(0, 0, 0);
    tmp.updateMatrix();
    R.anillos.setMatrixAt(i, tmp.matrix);
    tmp.position.set(x, 0.014, z); tmp.scale.set(1.1, 1, 1.1); tmp.updateMatrix();
    R.sombras.setMatrixAt(i, tmp.matrix);

    const box = new THREE.Box3().setFromObject(cuerpo);
    box.expandByScalar(0.2);
    p.box = box; p.caja0 = box.clone();
    R.puestos.push(p);
    return p;
  }

  propios.forEach((a, k) => {
    const col = k % cols, fila = Math.floor(k / cols);
    const x = (col + 0.5) * CELDA_X, z = (fila + 0.5) * CELDA_Z;
    // El divisor del puesto mira al −Z: silla y personaje van al costado +Z del
    // escritorio y girados π, si no el agente le da la espalda al monitor.
    const cz = z + 0.62;
    const escritorio = new THREE.Matrix4().makeTranslation(x, 0, z);
    const silla = new THREE.Matrix4().makeTranslation(x, 0, cz)
      .multiply(new THREE.Matrix4().makeRotationY(Math.PI));
    inst.agregar(R.assets.escritorio.scene, escritorio);
    inst.agregar(R.assets.silla.scene, silla);
    obstaculo(R.assets.escritorio.scene, escritorio);
    obstaculo(R.assets.silla.scene, silla, a.id);
    tmp.position.set(x, 0.008, z + 0.3); tmp.scale.setScalar(1); tmp.rotation.set(0, 0, 0);
    tmp.updateMatrix();
    R.alfombras.setMatrixAt(k, tmp.matrix);
    const p = sentar(a, x, cz, Math.PI, true);
    // El escritorio también abre la ficha; la caja del cuerpo sigue al personaje.
    p.boxEscritorio = new THREE.Box3(
      new THREE.Vector3(x - 0.85, 0, z - 0.75),
      new THREE.Vector3(x + 0.85, 1.45, z + 0.48));
  });

  // La mesa de reuniones mide 3,9 × 1,86 m: se reparten los de la red de a dos por
  // fila (un lado mira a −Z, el otro a +Z) y el paso se achica solo si hacen falta.
  const porLado = Math.ceil(red.length / 2) || 1;
  const paso = Math.min(0.95, 3.3 / porLado);
  red.forEach((a, k) => {
    const lado = k % 2 ? 1 : -1;
    const n = Math.floor(k / 2);
    const x = mesaX - (porLado - 1) * paso / 2 + n * paso;
    const z = zBanda + lado * 1.35;
    const silla = new THREE.Matrix4().makeTranslation(x, 0, z)
      .multiply(new THREE.Matrix4().makeRotationY(lado > 0 ? Math.PI : 0));
    inst.agregar(R.assets.silla.scene, silla);
    obstaculo(R.assets.silla.scene, silla, a.id);
    sentar(a, x, z, lado > 0 ? Math.PI : 0, false);
  });

  inst.construir();
  pool.construir();
  difusor.construir();
  marco.construir();
  // Se siembra `p.aviso` y `R.previos` ANTES de pintar las pantallas: si no, el
  // montaje arranca con el cartel de bloqueo afuera del vidrio y hasta el primer
  // refresco no aparece. En el primer pasada nadie camina (`transiciones` salta
  // los puestos que no se vieron nunca), así que esto no mueve nada por sí solo.
  transiciones();
  armarPantallas();
  armarRotulos();
  armarGlobos();
  pintarAnillos();
  R.scene.add(g);

  // El cartel de la pared: qué oficina es esta. Sale del payload (oficina.py pone
  // `medio_nombre`), no de una etiqueta que el frente se invente.
  const d = R.datos, r = d.resumen || {};
  const titulo = d.medio ? (d.medio_nombre || d.medio) : 'La red completa';
  // Si el contenedor desplegado todavía no manda `del_medio`/`de_la_red`, el cartel
  // se queda solo con el nombre: no puede prometer números que el backend no dio.
  const sub = r.del_medio === undefined ? ''
    : d.medio
        ? (d.conectado === false
            ? 'sin cuenta conectada: este medio aún no tiene piso de producción'
            : `${r.del_medio} del medio · ${r.de_la_red || 0} de la red`)
        : `${r.del_medio} de producción + ${r.de_la_red || 0} de la red`;
  R.cartel = new CSS2DObject(cartelDe(titulo, sub));
  R.cartel.position.set(W / 2, ALTO_FONDO - 0.55, 0.3);
  g.add(R.cartel);

  sombrear(g, W, D + BANDA);
}

// La frustum de sombra tiene que cubrir toda la sala traducida, muebles altos
// incluidos; con el default de three los puestos del fondo no se sombrean.
function sombrear(g, W, D){
  const e = Math.hypot(W, D) / 2 + 4;
  Object.assign(R.sol.shadow.camera, { left: -e, right: e, top: e, bottom: -e, near: 0.5, far: e * 4 });
  R.sol.shadow.camera.updateProjectionMatrix();
  R.sol.target.position.set(W / 2, 0, D / 2);
  R.scene.add(R.sol.target);
  R.renderer.shadowMap.needsUpdate = true;
}

// La PC de cada agente. Solo tienen pantalla los que tienen escritorio: los de la
// red se sientan en la mesa de reuniones, y ponerles un monitor que no existe es
// justo lo que la regla del módulo no permite. Los quads se fusionan en UN mesh
// sobre UN atlas: 26 vidrios cuestan un draw, no veintiséis.
function armarPantallas(){
  const conPc = R.puestos.filter(p => p.escritorio);
  if(!conPc.length) return;
  const atlas = asegurarAtlas(conPc.length);
  const partes = [];
  conPc.forEach((p, k) => {
    p.celda = k;
    partes.push(quadDePantalla(k, atlas, p));
    pintarPantalla(atlas, p, true);
  });
  const geo = mergeGeometries(partes, false);
  partes.forEach(gg => gg.dispose());
  const malla = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({
    map: atlas.tex, toneMapped: false,      // una pantalla brilla sola: sin luz, sin sombra
  }));
  malla.castShadow = false; malla.receiveShadow = false;
  R.g.g.add(malla);
  R.pantallas = { malla, atlas, conPc };
  if(PANTALLA.caja){
    // Verificación con el arnés: la caja real del vidrio del GLB en cada puesto,
    // para ajustar `w/h/x/y/z` sobre el mueble y no sobre una corazonada.
    const ga = new THREE.BoxGeometry(PANTALLA.w * 1.1, PANTALLA.h * 1.06, 0.29);
    const aristas = new THREE.EdgesGeometry(ga);
    const ma = new THREE.LineBasicMaterial({ color: 0xff00ff });
    R.cajas = conPc.map(p => {
      const c = new THREE.LineSegments(aristas, ma);
      c.position.set(p.x + PANTALLA.x, PANTALLA.y, p.z + PANTALLA.z + 0.15);
      R.g.g.add(c);
      return c;
    });
    R.cajasGeo = [ga, aristas];              // compartidas: se disponen una sola vez
  }
}

// Rótulo con NOMBRE y ROL del agente: el operator pidió que se lean personas con
// oficio, no tarjetas flotando ni tiempos. Dos líneas porque el nombre es lo que
// se busca con la vista; el rol se cae solo en el celular (oficina.css).
function armarRotulos(){
  for(const p of R.puestos){
    if(!p.rotulo){
      const obj = new CSS2DObject(rotuloDe(p.a));
      obj.position.set(p.x, p.box.max.y + 0.1, p.z);
      R.g.g.add(obj);
      p.rotulo = obj;
    }else{
      // Refresco: mismo puesto, datos nuevos. Se reescribe el texto, no el nodo.
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
    a.estado !== 'activo' ? 'Sin turno' :
    colorDe(a) === 'error' ? 'Última corrida con error' : 'En turno, sin corrida en curso';
}

// El cartel de la entrada: DOM puro con textContent, porque el nombre del medio
// viene de la BD y no hay que darle ninguna oportunidad de ser marcado.
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

// Los globos se rehacen enteros en cada rebuild: son pocos (solo los turnos que
// terminaron mal) y así no hay estados fantasma. Van más arriba que el rótulo.
function armarGlobos(){
  for(const p of R.puestos){
    if(!p.etiqueta) continue;
    R.g.g.remove(p.etiqueta);
    p.etiqueta.element?.remove();
    p.etiqueta = null;
  }
  for(const p of R.puestos){
    // El grito del puesto es el turno perdido; si no lo hay, los de la mesa de la
    // red (que no tienen PC donde leerse) muestran el bloqueo de la red encima de
    // la cabeza. En el escritorio eso ya vive en el vidrio, y repetiría el texto.
    const mal = globoDe(p.a);
    const globo = mal || (p.aviso && !p.escritorio
      ? { txt: '⏳ ' + p.aviso, mal: false, clase: 'reposo' } : null) ||
      (p.a.en_curso && p.a.faena && !p.escritorio
        ? { txt: '● ' + String(p.a.faena).slice(0, 80), mal: false, clase: 'curso' } : null);
    if(!globo) continue;
    const div = document.createElement('div');
    div.className = 'of-globo ' + (globo.clase || (globo.mal ? 'mal' : 'ok'));
    div.textContent = globo.txt;
    const obj = new CSS2DObject(div);
    obj.position.set(p.x, p.box.max.y + 0.72, p.z);
    R.g.g.add(obj);
    p.etiqueta = obj;
  }
}

function pintarAnillos(){
  const c = new THREE.Color();
  for(const p of R.puestos){
    c.setHex(COLOR[p.color] ?? COLOR.sinturno);
    if(R.sel && p.a.id === R.sel) c.multiplyScalar(1.6);   // el seleccionado se ve
    R.anillos.setColorAt(p.i, c);
  }
  if(R.anillos.instanceColor) R.anillos.instanceColor.needsUpdate = true;
}

/* ── el movimiento: ornamento de un evento real, nunca un reloj propio ─────── */
// Nadie camina porque sí. Los traslados se disparan SOLO desde `transiciones()`,
// que compara el payload nuevo contra `R.previos`; `cuadro()` después apenas
// interpola el viaje que ya está pedido. Con `prefers-reduced-motion` no hay
// paseo: el estado se cuenta con el anillo, el globo y la pantalla.
const VELOCIDAD = 1.05;          // m/s, dos pasos por segundo
const MAX_CAMINANDO = 2;         // 26 esqueletos corriendo no son un adorno: son
                                 // 26 mixers moviendo 26 armaduras por frame
const ESTADA_S = 2.5;            // lo que tarda dejar algo en el banco de impresión
const PASO_RUTA = 0.16;          // resolución en metros, menor que el pasillo entre puestos
const MARGEN_RUTA = 0.08;        // espacio adicional alrededor de cada mueble

const SCRATCH = new THREE.Object3D();
const SCRATCH_COLOR = new THREE.Color();
const SCRATCH_VEC = new THREE.Vector3();

// El bloqueo NO es por agente: `bloqueos_humanos()` habla de la red y de los
// medios. Emparejar un bloqueo con un escritorio es HEURÍSTICA de este archivo, y
// por eso el cartel dice "falta un humano (red)" y nunca le atribuye un número.
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

function irA(p, nombre){
  const mix = p && p.mix;
  if(!mix || !R.mov) return;
  let nuevo = mix[nombre];
  if(!nuevo) nuevo = nombre === 'walk' ? mix.idle : mix.sit;   // sin clip de paseo, que se pare
  if(!nuevo || mix.cur === nuevo) return;
  const viejo = mix.cur;
  nuevo.setLoop(THREE.LoopRepeat, Infinity);
  nuevo.reset();
  nuevo.paused = false;
  nuevo.play();
  if(viejo) nuevo.crossFadeFrom(viejo, 0.3, false);
  mix.cur = nuevo;
}

// Mueve al personaje y TODO lo que va pegado a él: el anillo, la sombra falsa
// (InstancedMesh), el rótulo, el globo y la caja con la que se hace click.
function pintarEn(p, x, z, facing){
  p.x = x; p.z = z;
  if(p.cuerpo){
    p.cuerpo.position.set(x, 0, z);
    if(facing != null) p.cuerpo.rotation.y = facing;
  }
  SCRATCH.rotation.set(0, 0, 0);
  SCRATCH.position.set(x, 0.02, z); SCRATCH.scale.setScalar(1); SCRATCH.updateMatrix();
  if(R.anillos) R.anillos.setMatrixAt(p.i, SCRATCH.matrix);
  SCRATCH.position.set(x, 0.014, z); SCRATCH.scale.set(1.1, 1, 1.1); SCRATCH.updateMatrix();
  if(R.sombras) R.sombras.setMatrixAt(p.i, SCRATCH.matrix);
  const arriba = (p.caja0 || p.box).max.y;
  if(p.rotulo) p.rotulo.position.set(x, arriba + 0.1, z);
  if(p.etiqueta) p.etiqueta.position.set(x, arriba + 0.72, z);
  p.box.copy(p.caja0).translate(SCRATCH_VEC.set(x - p.sitX, 0, z - p.sitZ));
}

function sentarse(p){
  // Una ruta cancelada también libera su cupo, no solo una que llega al destino.
  if(p.ruta) R.caminando = Math.max(0, R.caminando - 1);
  p.ruta = null; p.hasta = 0; p.alVuelta = false; p.enEspera = false;
  p.pedido = null; p.enReunion = false; p.salida = 0;
  pintarEn(p, p.sitX, p.sitZ, p.giro);
  if(R.anillos) R.anillos.instanceMatrix.needsUpdate = true;
  if(R.sombras) R.sombras.instanceMatrix.needsUpdate = true;
  irA(p, 'sit');
  if(p.mix.cur) p.mix.cur.paused = !R.mov || !p.a.en_curso;
  reanudarPendientes();
}

// Comprueba el segmento completo, no solo sus extremos: evita cortar esquinas.
function segmentoLibre(a, b, obstaculos){
  for(const o of obstaculos){
    let entrada = 0, salida = 1;
    for(const [v, d, min, max] of [[a[0], b[0] - a[0], o.minX, o.maxX],
                                    [a[1], b[1] - a[1], o.minZ, o.maxZ]]){
      if(Math.abs(d) < 1e-9){
        if(v < min || v > max){ entrada = 2; break; }
      }else{
        const t1 = (min - v) / d, t2 = (max - v) / d;
        entrada = Math.max(entrada, Math.min(t1, t2));
        salida = Math.min(salida, Math.max(t1, t2));
      }
    }
    if(entrada <= salida && entrada <= 1 && salida >= 0) return false;
  }
  return true;
}

// Dijkstra sobre una grilla pequeña de la sala. La silla propia se excluye para
// poder levantarse y volver a sentarse; todas las demás siguen siendo obstáculos.
// Si el destino está dentro de un mueble se elige el punto alcanzable más cercano.
function calcularRuta(nav, inicio, destino, dueño, exigirDestino = false){
  if(!nav) return null;
  const obstaculos = nav.obstaculos.filter(o => o.dueño !== dueño).map(o => ({
    minX: o.minX - MARGEN_RUTA, maxX: o.maxX + MARGEN_RUTA,
    minZ: o.minZ - MARGEN_RUTA, maxZ: o.maxZ + MARGEN_RUTA,
  }));
  const margen = PARED / 2 + MARGEN_RUTA;
  const nx = Math.floor((nav.W - 2 * margen) / PASO_RUTA) + 1;
  const nz = Math.floor((nav.D - 2 * margen) / PASO_RUTA) + 1;
  if(nx < 1 || nz < 1) return null;
  const punto = i => [margen + (i % nx) * PASO_RUTA,
                       margen + Math.floor(i / nx) * PASO_RUTA];
  const total = nx * nz, libres = new Uint8Array(total);
  // Solo los obstáculos cercanos a una celda pueden cortar sus ocho aristas.
  // Sin este índice cada paso revisaría todos los escritorios de la redacción.
  const cercanos = Array.from({ length: total }, () => []);
  for(const o of obstaculos){
    const x0 = Math.max(0, Math.floor((o.minX - margen) / PASO_RUTA) - 1);
    const x1 = Math.min(nx - 1, Math.ceil((o.maxX - margen) / PASO_RUTA) + 1);
    const z0 = Math.max(0, Math.floor((o.minZ - margen) / PASO_RUTA) - 1);
    const z1 = Math.min(nz - 1, Math.ceil((o.maxZ - margen) / PASO_RUTA) + 1);
    for(let z = z0; z <= z1; z++) for(let x = x0; x <= x1; x++) cercanos[z * nx + x].push(o);
  }
  for(let i = 0; i < total; i++) libres[i] = segmentoLibre(punto(i), punto(i), cercanos[i]) ? 1 : 0;
  if(!segmentoLibre(inicio, inicio, obstaculos)) return null;
  const dist = new Float64Array(total); dist.fill(Infinity);
  const prev = new Int32Array(total); prev.fill(-1);
  const cola = [];
  function poner(i, d){
    const item = { i, d }; let k = cola.length; cola.push(item);
    while(k){ const padre = (k - 1) >> 1; if(cola[padre].d <= d) break;
      cola[k] = cola[padre]; k = padre; }
    cola[k] = item;
  }
  function sacar(){
    const primero = cola[0], ultimo = cola.pop();
    if(cola.length){
      let k = 0;
      while(k * 2 + 1 < cola.length){
        let hijo = k * 2 + 1;
        if(hijo + 1 < cola.length && cola[hijo + 1].d < cola[hijo].d) hijo++;
        if(cola[hijo].d >= ultimo.d) break;
        cola[k] = cola[hijo]; k = hijo;
      }
      cola[k] = ultimo;
    }
    return primero;
  }
  for(let i = 0; i < total; i++){
    if(!libres[i]) continue;
    const q = punto(i), d = Math.hypot(q[0] - inicio[0], q[1] - inicio[1]);
    if(d <= PASO_RUTA * 2 && segmentoLibre(inicio, q, obstaculos)){
      dist[i] = d; poner(i, d);
    }
  }
  const destinoLibre = destino[0] >= margen && destino[0] <= nav.W - margen &&
    destino[1] >= margen && destino[1] <= nav.D - margen &&
    segmentoLibre(destino, destino, obstaculos);
  let mejor = -1, distanciaMejor = Infinity, finalExacto = false;
  while(cola.length){
    const actual = sacar(), i = actual.i;
    if(actual.d !== dist[i]) continue;
    const q = punto(i), alDestino = Math.hypot(q[0] - destino[0], q[1] - destino[1]);
    if(alDestino < distanciaMejor){ mejor = i; distanciaMejor = alDestino; }
    if(destinoLibre && alDestino <= PASO_RUTA * 2 && segmentoLibre(q, destino, obstaculos)){
      mejor = i; finalExacto = true; break;
    }
    const x = i % nx, z = Math.floor(i / nx);
    for(let dz = -1; dz <= 1; dz++) for(let dx = -1; dx <= 1; dx++){
      if(!dx && !dz) continue;
      const xx = x + dx, zz = z + dz;
      if(xx < 0 || xx >= nx || zz < 0 || zz >= nz) continue;
      const j = zz * nx + xx;
      if(!libres[j] || !segmentoLibre(q, punto(j), cercanos[i])) continue;
      const d = actual.d + PASO_RUTA * Math.hypot(dx, dz);
      if(d < dist[j]){ dist[j] = d; prev[j] = i; poner(j, d); }
    }
  }
  // Nunca usar un punto inaccesible como si fuera el escritorio o el mueble.
  if(mejor < 0 || (destinoLibre && !finalExacto) ||
     (exigirDestino && !finalExacto) || (!destinoLibre && distanciaMejor > 1.5)) return null;
  const pasos = [];
  for(let i = mejor; i >= 0; i = prev[i]) pasos.push(punto(i));
  pasos.reverse();
  pasos.unshift(inicio);
  if(finalExacto) pasos.push(destino);
  // Simplifica solo cuando el segmento entero está libre de mobiliario.
  const ruta = [pasos[0]];
  for(let i = 0; i < pasos.length - 1;){
    let j = pasos.length - 1;
    while(j > i + 1 && !segmentoLibre(pasos[i], pasos[j], obstaculos)) j--;
    ruta.push(pasos[j]); i = j;
  }
  return ruta;
}

function irDeViaje(p, destino, al){
  if(!p || !p.cuerpo || !R.mov || !p.escritorio || !R.muebles) return false;
  if(Math.hypot(destino[0] - p.x, destino[1] - p.z) < 0.08){
    p.enEspera = false; p.pedido = null; return false;
  }
  if(R.caminando >= MAX_CAMINANDO){ p.enEspera = true; p.pedido = { destino, al }; return false; }
  const pasos = calcularRuta(R.navegacion, [p.x, p.z], destino, p.a.id, al === 'puesto');
  if(!pasos || pasos.length < 2){ p.enEspera = false; p.pedido = null; return false; }
  const tramos = [], t0 = performance.now();
  let largo = 0;
  for(let i = 1; i < pasos.length; i++){
    const d = Math.hypot(pasos[i][0] - pasos[i - 1][0], pasos[i][1] - pasos[i - 1][1]);
    if(d > 1e-6){ tramos.push({ de: pasos[i - 1], a: pasos[i], desde: largo, largo: d }); largo += d; }
  }
  if(!largo){ p.enEspera = false; p.pedido = null; return false; }
  p.ruta = { tramos, largo, dur: largo / VELOCIDAD, al, t0 };
  if(!p.salida) p.salida = t0;
  p.enEspera = false; p.pedido = null;
  R.caminando++;
  irA(p, 'walk');
  return true;
}

function reanudarPendientes(){
  while(R.caminando < MAX_CAMINANDO){
    const esperando = R.puestos.find(p => p.enEspera && p.pedido);
    if(!esperando) return;
    const pedido = esperando.pedido;
    irDeViaje(esperando, pedido.destino, pedido.al);
  }
}

// Interrumpir un viaje no debe atravesar la oficina por teletransporte.
function regresar(p){
  if(p.ruta) R.caminando = Math.max(0, R.caminando - 1);
  p.ruta = null; p.hasta = 0; p.alVuelta = false; p.enReunion = false;
  p.enEspera = false; p.pedido = null;
  if(Math.hypot(p.x - p.sitX, p.z - p.sitZ) < 0.08) sentarse(p);
  else if(!irDeViaje(p, [p.sitX, p.sitZ], 'puesto') && !p.enEspera){
    irA(p, 'idle');
    if(p.mix.cur) p.mix.cur.paused = true;
  }
  reanudarPendientes();
}

function avanzarMovimientos(ahora){
  if(!R || !R.mov) return;
  let movido = false;
  R.tiempo = ahora;
  for(const p of R.puestos){
    if(p.hasta){
      movido = true;
      if(ahora < p.hasta) continue;
      p.hasta = 0;
      if(p.alVuelta){ p.alVuelta = false; regresar(p); }
      else sentarse(p);
      continue;
    }
    if(p.enEspera){
      // El tercero no camina: le parpadea el anillo hasta que se libera un viaje.
      SCRATCH_COLOR.setHex(COLOR[p.color] ?? COLOR.sinturno)
        .multiplyScalar(0.55 + 0.45 * Math.abs(Math.sin(ahora / 333)));
      if(R.anillos) R.anillos.setColorAt(p.i, SCRATCH_COLOR);
      if(R.anillos && R.anillos.instanceColor) R.anillos.instanceColor.needsUpdate = true;
      continue;
    }
    const r = p.ruta;
    if(!r) continue;
    const vivo = ahora - r.t0;
    const f = Math.max(0, Math.min(1, vivo / (r.dur * 1000)));
    // Arranque y frenado suaves, sin alterar la duración medida en pared.
    const paso = f * f * (3 - 2 * f);
    const recorrido = paso * r.largo;
    const tramo = r.tramos.find(t => recorrido <= t.desde + t.largo) || r.tramos[r.tramos.length - 1];
    const u = Math.max(0, Math.min(1, (recorrido - tramo.desde) / tramo.largo));
    const x = tramo.de[0] + (tramo.a[0] - tramo.de[0]) * u;
    const z = tramo.de[1] + (tramo.a[1] - tramo.de[1]) * u;
    // El modelo mira a +Z con rotation.y=0; gira siguiendo cada tramo.
    pintarEn(p, x, z, Math.atan2(tramo.a[0] - tramo.de[0], tramo.a[1] - tramo.de[1]));
    movido = true;
    if(f >= 1){
      p.ruta = null;
      R.caminando = Math.max(0, R.caminando - 1);
      if(r.al === 'impresora'){
        p.hasta = ahora + ESTADA_S * 1000; p.alVuelta = true; irA(p, 'idle');
      }else if(r.al === 'mesa'){
        p.enReunion = true; irA(p, 'idle');     // en la mesa hasta que se despeje
      }else sentarse(p);                        // vuelta o viaje cortado: en su puesto
      reanudarPendientes();
    }
  }
  if(movido){
    if(R.anillos) R.anillos.instanceMatrix.needsUpdate = true;
    if(R.sombras) R.sombras.instanceMatrix.needsUpdate = true;
  }
}

// La única fuente de transiciones es el payload. Se compara contra lo que se vio
// en el refresco anterior (`R.previos`), nunca contra un reloj de la escena.
function transiciones(){
  if(!R || !R.puestos.length) return;
  const nuevos = {}, datos = R.datos || {};
  for(const p of R.puestos){
    const a = p.a;
    if(!a || !a.id) continue;
    const u = a.ultima || {};
    const aviso = avisoDe(p, datos);
    const antes = R.previos[a.id];
    nuevos[a.id] = { en_curso: !!a.en_curso, ok: u.ok, perdido: u.perdido,
                     estado: a.estado, aviso: !!aviso, hoy: a.hoy };
    p.aviso = aviso;
    if(!antes) continue;                     // primer refresco: no hay nada que contar
    if(a.estado !== 'activo'){               // gate apagado: se sienta y no se mueve más
      if((p.ruta && p.ruta.al !== 'puesto') || p.hasta || p.enReunion ||
         (p.enEspera && p.pedido && p.pedido.al !== 'puesto')) regresar(p);
      else if(!p.ruta && !p.enEspera && p.mix.cur) p.mix.cur.paused = true;
      p.enReunion = false;
      continue;
    }
    if(!antes.en_curso && a.en_curso){
      // Se sentó a trabajar: si estaba de reunión o de paseo, vuelve al puesto.
      if((p.ruta && p.ruta.al !== 'puesto') || p.hasta || p.enReunion ||
         (p.enEspera && p.pedido && p.pedido.al !== 'puesto')) regresar(p);
      else if(!p.ruta && !p.enEspera){ irA(p, 'sit'); if(p.mix.cur && R.mov) p.mix.cur.paused = false; }
    }
    if(antes.en_curso && !a.en_curso){
      if(u.ok === false || u.perdido){
        // Turno que terminó mal: el anillo rojo y el globo ya lo dicen. Un
        // personaje "llevando algo a imprimir" que falló sería teatro.
      }else if(!p.ruta && !p.enEspera && aviso && R.muebles){
        irDeViaje(p, R.muebles.mesa, 'mesa');
      }else if(!p.ruta && !p.enEspera && Number.isFinite(a.hoy) && Number.isFinite(antes.hoy) &&
                a.hoy > antes.hoy && R.muebles){
        // Es una representación visual de un aumento observado, no una prueba
        // de que esa corrida haya producido la pieza (los contadores son compartidos).
        irDeViaje(p, R.muebles.impresora, 'impresora');
      }
      if(!p.ruta && !p.enEspera && !p.enReunion && p.mix.cur) p.mix.cur.paused = true;
    }
    if(!antes.aviso && aviso && !a.en_curso && !p.enReunion && !p.ruta && !p.enEspera && R.muebles){
      irDeViaje(p, R.muebles.mesa, 'mesa');
    }else if(antes.aviso && !aviso){
      if(p.enReunion){
        regresar(p);
      }else if((p.ruta && p.ruta.al === 'mesa') ||
               (p.pedido && p.pedido.al === 'mesa')){
        regresar(p);
      }
    }
  }
  R.previos = nuevos;
  repintarPantallas(false);
}

/* ── encuadre ───────────────────────────────────────────────────────────────── */
function encuadrarTodo(){
  const { cols, rows } = R.g;
  const W = cols * CELDA_X, D = rows * CELDA_Z + BANDA;
  const [bx, bz] = [W, D];
  R.orbita.tx = R.orbita.ttx = bx / 2;
  R.orbita.tz = R.orbita.ttz = bz / 2;
  R.orbita.r = R.orbita.tr = distanciaDeEncaje();
}

/* ── cámara orbital a mano ─────────────────────────────────────────────────── */
// Sin OrbitControls: el addon no está vendorizado, y una órbita con dos ejes y
// zoom son ~30 líneas — menos de las que cuesta parcharla para que no pelee con
// el click de selección.
function aplicarCamara(){
  const o = R.orbita;
  o.r += (o.tr - o.r) * 0.16;
  o.tx += (o.ttx - o.tx) * 0.16;
  o.tz += (o.ttz - o.tz) * 0.16;
  const ph = Math.min(FASE_MAX, Math.max(0.22, o.ph));
  R.camara.position.set(
    o.tx + o.r * Math.sin(ph) * Math.cos(o.th),
    o.r * Math.cos(ph) + 1.2,
    o.tz + o.r * Math.sin(ph) * Math.sin(o.th));
  R.camara.lookAt(o.tx, 1.0, o.tz);
}

// Cuánto hay que retroceder para que la sala entre entera. Three mide el campo
// vertical: el ancho útil es fov·tan(fov/2)·aspect, así que en un teléfono vertical
// (aspect ~0,6) la misma sala pide casi el triple de distancia que en un monitor.
// Con la distancia fija del desktop, en el celular se veía una pared de cerca.
function distanciaDeEncaje(){
  const [w, d] = [R.g.cols * CELDA_X, R.g.rows * CELDA_Z + BANDA];
  const mayor = Math.max(w, d);
  const vf = 2 * Math.tan(THREE.MathUtils.degToRad(R.camara.fov / 2));
  const porAlto = mayor / vf;
  const porAncho = mayor / (vf * Math.max(0.35, R.camara.aspect));
  return Math.min(70, Math.max(porAlto, porAncho) * 1.12 + 3);
}

function enlazar(){
  const lienzo = R.renderer.domElement;
  const o = R.orbita;
  // Un AbortController por montaje: los botones de cámara viven en la plantilla,
  // no en la escena, así que sin esto cada re-entrada acumulaba un listener más
  // apuntando a la órbita de una escena que ya no existe (el + terminaba haciendo
  // zoom de a tres).
  const señal = (R.al = new AbortController()).signal;
  let arrastre = null;
  const puntos = new Map();          // puntero activo → para pellizco en el celular
  let pellizco = 0;

  lienzo.addEventListener('pointerdown', e => {
    puntos.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if(puntos.size > 1){ arrastre = null; return; }
    arrastre = { x: e.clientX, y: e.clientY, th: o.th, ph: o.ph, movido: 0 };
    lienzo.setPointerCapture?.(e.pointerId);
  }, { signal: señal });
  lienzo.addEventListener('pointermove', e => {
    if(puntos.has(e.pointerId)) puntos.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if(puntos.size === 2){
      const [a, b] = [...puntos.values()];
      const d = Math.hypot(a.x - b.x, a.y - b.y);
      if(pellizco) o.tr = Math.min(70, Math.max(4, o.tr * (pellizco / Math.max(1, d))));
      pellizco = d;
      return;
    }
    pellizco = 0;
    if(!arrastre) return;
    const dx = e.clientX - arrastre.x, dy = e.clientY - arrastre.y;
    arrastre.movido = Math.max(arrastre.movido, Math.abs(dx) + Math.abs(dy));
    o.th = arrastre.th - dx * 0.006;
    o.ph = Math.min(FASE_MAX, Math.max(0.22, arrastre.ph - dy * 0.005));
  }, { signal: señal });
  lienzo.addEventListener('pointerup', e => {
    puntos.delete(e.pointerId);
    const fueClick = arrastre && arrastre.movido < 6 && puntos.size === 0;
    arrastre = null; pellizco = 0;
    if(fueClick) seleccionar(e, false);
  }, { signal: señal });
  lienzo.addEventListener('pointercancel', e => {
    puntos.delete(e.pointerId); arrastre = null; pellizco = 0;
  }, { signal: señal });
  lienzo.addEventListener('wheel', e => {
    e.preventDefault();
    o.tr = Math.min(70, Math.max(4, o.tr * (1 + (e.deltaY > 0 ? 0.12 : -0.12))));
  }, { passive: false, signal: señal });
  lienzo.addEventListener('dblclick', e => seleccionar(e, true), { signal: señal });

  // Los botones que ya trae la plantilla: +/− y ⤢ (ver toda la redacción).
  R.caja.querySelectorAll('.of-3d-cam [data-cam]').forEach(b => b.addEventListener('click', () => {
    if(!R) return;
    const ob = R.orbita;
    if(b.dataset.cam === 'mas') ob.tr = Math.max(4, ob.tr * 0.78);
    else if(b.dataset.cam === 'menos') ob.tr = Math.min(70, ob.tr * 1.28);
    else focar('');
  }, { signal: señal }));

  document.addEventListener('visibilitychange', () => {
    if(document.hidden) pausar(); else reanudar();
  }, { signal: señal });

  // Girar el teléfono, colapsar un sidebar o cambiar de vista cambia el hueco: la
  // sala tiene que volver a encuadrarse. `ajustar` se llama también al terminar el
  // montaje, porque si la caja todavía no estaba mediible (el cambio de medio llega
  // mientras la sala baja) el renderer nace con el mínimo de 320×240 y sin esta
  // segunda pasada se queda ahí para siempre.
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
  // Si hay un puesto seleccionado se respeta el zoom que eligió la persona.
  if(!R.sel) R.orbita.tr = distanciaDeEncaje();
  R.renderer.shadowMap.needsUpdate = true;
}

function seleccionar(e, enfocar){
  const r = R.renderer.domElement.getBoundingClientRect();
  const ray = new THREE.Raycaster();
  ray.setFromCamera(new THREE.Vector2(
    ((e.clientX - r.left) / r.width) * 2 - 1,
    -((e.clientY - r.top) / r.height) * 2 + 1), R.camara);
  // Se prueba contra la caja propia de cada personaje: poner mallas invisibles
  // de pick serían 25 objetos más en la escena para el mismo resultado.
  const punto = new THREE.Vector3();
  let mejor = null, dmin = Infinity;
  const candidatos = R.puestos;
  for(const p of candidatos){
    for(const box of [p.box, p.boxEscritorio]){
      if(!box || !ray.ray.intersectBox(box, punto)) continue;
      const d = punto.distanceTo(R.camara.position);
      if(d < dmin){ dmin = d; mejor = p; }
    }
  }
  if(!mejor){ if(enfocar) focar(''); return; }
  R.sel = mejor.a.id;
  pintarAnillos();
  if(enfocar) focar(mejor.a.id);
  R.onSeleccion(mejor.a);
}

export function focar(id){
  if(!R || !R.g) return;
  R.sel = id || '';
  pintarAnillos();
  const o = R.orbita;
  if(!id){ encuadrarTodo(); return; }
  const p = R.puestos.find(x => x.a.id === id);
  if(!p) return;
  o.ttx = p.x; o.ttz = p.z; o.tr = 6.5;
}

/* ── el loop ───────────────────────────────────────────────────────────────── */
function cuadro(){
  if(!R) return;
  R.raf = requestAnimationFrame(cuadro);
  // dt con clamp: una pestaña dormida devuelve un delta enorme y el personaje se
  // teletransporta o se queda sin pose.
  const dt = Math.min(0.05, R.reloj.getDelta());
  if(R.mov) for(const m of R.mixers) m.mixer.update(dt);
  // El único reloj de la escena: interpola los viajes que YA pidió `transiciones`.
  // Con tiempo de pared, no con el dt clampeado de los mixers.
  avanzarMovimientos(performance.now());
  aplicarCamara();
  R.renderer.render(R.scene, R.camara);
  R.etiquetas.render(R.scene, R.camara);
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

// Un cambio de ámbito o de atención cambia físicamente la distribución.
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
  }else{
    // Mismos agentes en el mismo orden: cambian los estados, y con eso el color
    // del anillo, el rótulo y qué globos están a la vista. La geometría no se toca.
    const porId = new Map((datos.agentes || []).filter(a => a && a.id).map(a => [a.id, a]));
    R.puestos.forEach(p => {
      const a = porId.get(p.a.id);
      if(!a) return;
      p.a = a; p.color = colorDe(a);
      if(p.rotulo) llenarRotulo(p.rotulo.element, a);
    });
    // Primero se decide quién empezó o terminó (y con eso quién camina y qué dice
    // su pantalla), después se pintan anillos y globos con lo que quedó.
    transiciones();
    pintarAnillos();
    armarGlobos();
  }
  R.renderer.shadowMap.needsUpdate = true;
  informar();
}

function desarmarEscena(){
  if(!R || !R.g) return;
  const { g } = R.g;
  R.scene.remove(g);
  R.scene.remove(R.sol?.target);
  // Se dispone SOLO lo que esta escena creó. La geometría, los materiales y las
  // texturas de los GLB son de la caché compartida (`COMPARTIDO`): disponerlos
  // rompería el próximo montaje, y el parquet o la sombra en canvas viven a nivel
  // módulo desde la primera sala.
  g.traverse(o => {
    if(o.isCSS2DObject) o.element?.remove();
    if(!o.isMesh) return;
    if(o.geometry && COMPARTIDO && COMPARTIDO.has(o.geometry.uuid)) return;
    o.geometry?.dispose?.();
    const mats = Array.isArray(o.material) ? o.material : [o.material];
    // `Material.dispose()` NO toca sus texturas: por eso el map compartido
    // sobrevive y el parquet no hay que regenerarlo en cada montaje.
    for(const m of mats) if(m && !COMPARTIDO?.has(m.uuid)) m.dispose?.();
  });
  R.g = null; R.puestos = []; R.mixers = []; R.anillos = null; R.sombras = null;
  R.alfombras = null; R.cartel = null;
  // Las pantallas se desmontan con la sala, pero el ATLAS es de nivel módulo a
  // propósito: es UNA textura para toda la app y `traverse` nunca dispone un `map`
  // compartido. Los `LineSegments` de la caja de verificación tampoco los recorre
  // el lazo de meshes (no son `isMesh`), así que se disponen acá.
  if(R.cajas) for(const c of R.cajas){ c.parent?.remove(c); c.material?.dispose?.(); }
  (R.cajasGeo || []).forEach(gg => gg.dispose?.());
  R.pantallas = null; R.cajas = null; R.cajasGeo = null;
  // Nadie arrastra el estado del medio anterior: `R.previos` está indexado por id
  // de agente y los mismos ids se repiten de una oficina a otra.
  R.previos = {}; R.caminando = 0; R.tiempo = 0; R.navegacion = null;
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

function informar(){
  if(!R || !R.g) return;
  const i = R.renderer.info;
  const base = {
    modo: R.modo,
    // Con `prefers-reduced-motion` la escena no mueve nada: el arnés tiene que
    // poder comprobar que el estado se comunica igual, por anillo y pantalla.
    mov: R.mov,
    draws: i.render.calls, geometrias: i.memory.geometries, texturas: i.memory.textures,
    cols: R.g.cols, rows: R.g.rows,
    ancho: R.g.cols * CELDA_X,
    alto: R.g.rows * CELDA_Z + BANDA,
  };
  window.__OF3D_INFO__ = { ...base,
        agentes: R.puestos.length,
        propios: R.g.agentes.length, enLaRed: R.g.red.length,
        rotulos: R.puestos.filter(p => p.rotulo).length,
        globos: R.puestos.filter(p => p.etiqueta).length,
        animados: R.mixers.length,
        // Lo que el arnés tiene que ver: los quad de pantalla son UN mesh (un draw
        // más, no veintiséis) y nunca hay más de MAX_CAMINANDO en el piso.
        pantallas: R.pantallas ? R.pantallas.conPc.length : 0,
        caminando: R.caminando,
        // Quién está LEJOS de su puesto (viaje o estada): es la prueba de que el
        // traslado empezó y, sobre todo, de que terminó y se sentó de nuevo.
        afuera: R.puestos.filter(p => Math.hypot(p.x - p.sitX, p.z - p.sitZ) > 0.05)
                         .map(p => p.a.id),
        ejemploRotulo: R.puestos[0]?.rotulo?.element?.textContent || '' };
}
