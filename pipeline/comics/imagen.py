"""Adaptador de imágenes de paneles: reusa la maquinaria de pipeline.imagen.

El cómic no inventa un motor nuevo: llama a `imagen.generar` (cascada flux ->
pollinations -> hf-space -> gemini opt-in), que trae caché por huella, imagenoteca,
cuota diaria local y fallbacks. El prompt del panel NUNCA pide texto dibujado
(regla del diseño): el texto lo compone `componer.py` en postproducción.

v2 — variedad real de escenas (orden del dueño: nada de 15 viñetas gemelas):
  - plano por rotación determinista ((b*2+1) % len(PLANOS)),
  - LUZ según el rol rítmico: gancho = contraste duro, escala = luz fría,
    silencio = NO se genera imagen (panel negro en componer, cero cuota),
    remate = acento rojo en la oscuridad,
  - encuadre/composición rota por pool para que dos viñetas seguidas no
    compartan composición,
  - contexto narrativo = ancla_guion LITERAL del storyboard (nada inventado).
"""
from __future__ import annotations

from pathlib import Path

from .. import imagen
from ..episode import Episode

PLANOS_EN = {
    "establecido": "establishing wide shot, full environment visible",
    "general": "wide shot",
    "medio": "medium shot",
    "primer_plano": "close-up",
    "detalle": "extreme close-up",
    "contrapicado": "dramatic low angle shot",
}

# luz según rol rítmico — el clima acompaña el ritmo del capítulo
LUZ_ROL = {
    "gancho": "hard noir contrast, deep black shadows, single harsh light source",
    "cliffhanger": "low-key tension lighting, heavy shadows closing in",
    "remate": "darkness with a single red accent light",
    "escala": "cold clinical light, museum stillness",
    "contexto": "overcast daylight, muted tones",
    "giro": "flashbulb instant, stark one-frame exposure",
}

# variedad de composición (rotación determinista — dos viñetas seguidas nunca
# comparten encuadre)
COMPOSICION = (
    "centered symmetrical composition",
    "rule of thirds, subject off-center",
    "dutch angle composition",
    "deep one-point perspective corridor",
    "over-the-shoulder framing",
    "high horizon line, oppressive sky",
    "low horizon line, tight doorway framing",
)

NEGATIVOS = ("comic panel, thick ink border, black ink, warm white paper, red accent, "
             "absolutely no text, no letters, no speech bubbles, no captions, no numbers, "
             "no watermark, no typography")


def prompt_panel(panel: dict, ficha: dict | None, idx: int = 0) -> str:
    """IDENTIDAD(personaje) + luz de rol + escena del beat + plano + composición + negativos."""
    guia = (ficha or {}).get("guia", "silueta negra con contorno blanco grueso")
    plano_en = PLANOS_EN.get(str(panel.get("plano", "medio")), "medium shot")
    rol = str(panel.get("rol_ritmico", "contexto"))
    luz = LUZ_ROL.get(rol, LUZ_ROL["contexto"])
    # escena del beat: ancla LITERAL del guion (contexto), narración (acción visible)
    escena = (str(panel.get("ancla_guion", "")).strip()
              or str(panel.get("narracion", "")).strip())
    composit = COMPOSICION[idx % len(COMPOSICION)]
    partes = [guia, "stickman noir style, thick expressive ink linework, graphic novel art",
              f"lighting: {luz}",
              plano_en,
              f"scene: {_recorta(escena, 180)}",
              composit,
              "single panel illustration",
              NEGATIVOS]
    return ", ".join(p for p in partes if p)


def _recorta(texto: str, limite: int) -> str:
    texto = " ".join((texto or "").split())
    return texto if len(texto) <= limite else texto[:limite].rsplit(" ", 1)[0] + "…"


def generar(ep: Episode, datos_comic: dict, fichas_map: dict, *,
            modelo: str = "flux", forzar: bool = False,
            renovar: set[int] | None = None) -> list[Path]:
    """Renderiza las viñetas con imagen (la de silencio NO: panel negro)."""
    renovar = renovar or set()
    carpeta = ep.dir / "comics" / "paneles"
    carpeta.mkdir(parents=True, exist_ok=True)
    ext = imagen.extension(modelo)
    rutas = []
    for p in sorted(datos_comic.get("paneles", []), key=lambda x: int(x.get("i", 0))):
        i = int(p.get("i", 0))
        out = carpeta / f"p-{i:03d}.{ext}"
        # viñeta de silencio: panel negro en componer.py — no quema cuota
        if str(p.get("accion", "")) == "silencio":
            p["procedencia_imagen"] = "panel_negro (sin cuota)"
            rutas.append(out)
            if out.exists():
                out.unlink()
            continue
        ficha = fichas_map.get(str(p.get("actor", ""))) or fichas_map.get("narrador_canal")
        prompt = prompt_panel(p, ficha, idx=i)
        if out.exists() and i not in renovar and not forzar:
            rutas.append(out)
            p["procedencia_imagen"] = "cache"
            continue
        imagen.generar(prompt, out, modelo=modelo, forzar=i in renovar,
                       w=1024, h=1024,
                       escena=str(p.get("ancla_guion", ""))[:180],
                       accion=str(p.get("accion", "")),
                       plano=str(p.get("plano", "")))
        p["procedencia_imagen"] = "generada"
        rutas.append(out)
    # imágenes de paneles que ya no existen en la adaptación vigente: huérfanos
    # de una corrida anterior; se sacan para no confundir al QC ni al lector
    vigentes = {r.name for r in rutas if r.exists()}
    for hu in carpeta.glob("p-*.*"):
        if hu.name not in vigentes:
            hu.unlink()
    return rutas
