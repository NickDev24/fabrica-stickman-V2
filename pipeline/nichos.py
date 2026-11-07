"""Canal paraguas Pulso Curioso: historias verificadas de categorías diversas.

El nicho NO es un tema, es una promesa: "hay algo que no sabes y te lo explico con hechos
verificados". Cada CATEGORIA define de donde salen los temas; cada FORMATO define la
estructura repetible que hace que un video se parezca a una serie y no a un documental suelto.

Los pesos (`PESO_INICIAL` / `state/aprendizaje.json`) los ajusta `pipeline.experimentos`
con metricas reales: nunca se inventan.
"""
from __future__ import annotations

import json
import random
import re
import unicodedata

from . import config

CATEGORIAS = {
    "experimentos": {
        "nombre": "Experimentos cientificos y fenomenos que parecen imposibles",
        "descripcion": (
            "Fenomenos reales medidos en un experimento publicado. Nunca se simula un "
            "experimento propio: se narra el experimento que alguien hizo y documento."),
        "semillas": [
            "experimento clasico fisica resultado sorprendente",
            "phenomenon that looks impossible but is measured science",
            "demostracion de laboratorio escala humana",
            "physics demonstration counterintuitive result",
        ],
        "verificable_en": ["physics.nist.gov", "nasa.gov", "arxiv.org", "nature.com",
                           "scientificamerican.com", "phys.org", "reuters.com", "bbc.com"],
    },
    "misterios": {
        "nombre": "Misterios reales y descubrimientos sorprendentes",
        "descripcion": (
            "Casos sin resolver o descubrimientos recientes, siempre con la frontera clara "
            "entre lo medido y lo que todavia no se sabe."),
        "semillas": [
            "caso sin resolver ciencia explicacion actual",
            "unsolved phenomenon scientists still study",
            "descubrimiento reciente arqueologia astronomia",
            "anomaly measurement scientists explained",
        ],
        "verificable_en": ["nasa.gov", "esa.int", "noaa.gov", "usgs.gov", "nature.com",
                           "science.org", "pnas.org", "britannica.com", "bbc.com", "ap.org"],
    },
    "tecnologia": {
        "nombre": "Tecnologia, inteligencia artificial e inventos",
        "descripcion": (
            "Que existe hoy, que se midio y que falta. Prohibido prometer tecnologia que "
            "no esta documentada como real."),
        "semillas": [
            "tecnologia real funcionando hoy limites medidos",
            "invention quietly changed everything history",
            "inteligencia artificial logro benchmark verificado",
            "engineering breakthrough demonstrated tested",
        ],
        "verificable_en": ["ieee.org", "arxiv.org", "nist.gov", "energy.gov", "reuters.com",
                           "bbc.com", "nature.com", "phys.org"],
    },
    "psicologia": {
        "nombre": "Psicologia, cerebro y comportamiento humano",
        "descripcion": (
            "Efectos con estudio y replica. Si un hallazgo no se replico, se dice en el guion."),
        "semillas": [
            "efecto psicologico documentado experimento",
            "cognitive bias original study replication",
            "cerebro respuesta medida fenomeno cotidiano",
            "perception illusion scientific explanation",
        ],
        "verificable_en": ["nih.gov", "apa.org", "nature.com", "science.org", "pnas.org",
                           "britannica.com", "bbc.com"],
    },
}

# Formatos = la formula repetible (los canales que despegan repiten UN patron y cambian el tema).
FORMATOS = {
    "conteo": {
        "nombre": "Cuenta regresiva de un solo lugar",
        "pregunta": "que es lo que casi nadie sabe de {tema}?",
        "estructura": ["gancho con el dato mas fuerte", "5 -> 1", "revelacion final", "CTA"],
        "nota": "Cuenta regresiva numerada sobre UN lugar u objeto por video (5 datos, del "
                "menos al mas impactante). El numero en pantalla es el motor de retencion.",
        "palabras_corto": (140, 210), "palabras_largo": (1500, 2100),
    },
    "paradoja": {
        "nombre": "La paradoja resuelta",
        "pregunta": "como puede ser posible {tema}?",
        "estructura": ["lo que parece imposible", "por que NO puede ser",
                       "la medicion que lo cambia", "el giro", "que significa hoy"],
        "nota": "Abre con el enunciado que suena falso y lo desarma con la medicion que lo prueba.",
        "palabras_corto": (150, 220), "palabras_largo": (1600, 2200),
    },
    "cuerpo": {
        "nombre": "Que le pasa a tu cuerpo",
        "pregunta": "que le pasa a tu cuerpo si {tema}?",
        "estructura": ["escenario", "minuto a minuto", "el limite real", "revelacion", "CTA"],
        "nota": "Escenario hipotetico sostenido solo por fisiologia verificada. Cada bloque "
                "es un salto temporal; formato de alto enganche en divulgacion de ciencia.",
        "palabras_corto": (150, 220), "palabras_largo": (1600, 2300),
    },
    "origen": {
        "nombre": "El origen que nadie pregunta",
        "pregunta": "de donde viene realmente {tema}?",
        "estructura": ["objeto cotidiano", "el problema que resolvio", "el error historico",
                       "giro", "hoy"],
        "nota": "Historia de algo que la gente usa a diario. Viaja entre idiomas y envejece bien.",
        "palabras_corto": (140, 200), "palabras_largo": (1500, 2000),
    },
    "medicion": {
        "nombre": "La medicion que cambio todo",
        "pregunta": "como se midio {tema} por primera vez?",
        "estructura": ["el numero", "quien lo obtuvo", "como sin instrumentos", "el error", "residuo"],
        "nota": "Antes/despues de una medicion concreta. Es el formato mas solido para el pilar largo.",
        "palabras_corto": (150, 210), "palabras_largo": (1700, 2300),
    },
}

# ==== ------------------------------------------------------------------ ====
# Motor editorial por categorías (no canales separados): cada una
# con perfil de audiencia, identidad narrativa, formatos recomendados, duración,
# estrategia visual, frecuencia de publicación, potencial de monetización y KPIs.
# Categorías `ficción` (terror, escenarios apocalípticos, animadas, cine) no exigen fuentes reales
# (gate 1) sino anclas de verosimilitud; las fácticas mantienen el gate completo.

_NUEVA_CATEG = {
    "terror": {
        "nombre": "Relatos de terror y supervivencia",
        "descripcion": "Terror original con amenazas plausible: una situación, unas reglas, una escalada. FICCIÓN propia, jamás basada en IP ajena.",
        "semillas": ["entidad imposible en una casa literal", "costumbre de pueblo que no se debe romper",
                     "salvamento nocturno donde la ayuda no llega"],
        "verificable_en": ["britannica.com", "nih.gov"],
        "ficción": True,
        "público": "18-34 tradicional y noche", "identidad": "primera persona colectiva, miedo realista, detalles de supervivencia",
        "formatos": ["reglas", "expediente"], "duracion_obj_s": (280, 620),
        "estrategia_visual": "interiores nocturnos, silencios largos, texto en pantalla", "frecuencia": "2/semana",
        "monetizacion": "mediano (retención alta, sponsorships limitados)", "kpis": ["retención 30s >60%", "compartidos/1000 vistas"],
        "canal": "Pulso Curioso",
    },
    "apocalipsis": {
        "nombre": "Zombis y escenarios de infección/apocalipsis",
        "descripcion": "Interactive-style survival narrativo: simulaciones con fisicalidad realista (geografía, física, recursos reales). FICCIÓN.",
        "semillas": ["epidemia que se expande en una ciudad argentina", "video diario del superviviente día N",
                     "fortaleza que se defiende con ingenieria doméstica"],
        "verificable_en": ["projects.imperial.ac.uk", "healthdata.org"],
        "ficción": True,
        "público": "18-34 acción" , "identidad": "segunda persona ('vos'), frases cortas, cronología con salto temporal",
        "formatos": ["dia_a_dia", "cuerpo"], "duracion_obj_s": (300, 700),
        "estrategia_visual": "mapas, gráficos de infección, planos urbanos", "frecuencia": "2/semana",
        "monetizacion": "alto en serie", "kpis": ["vistas del siguiente episodio", "retención media >50%"],
        "canal": "Pulso Curioso",
    },
    "animadas": {
        "nombre": "Historias animadas y personajes originales",
        "descripcion": "Pequeños mundos creados: personajes originales que viven situaciones extraordinarias. FICCIÓN con universo reutilizable.",
        "semillas": ["objeto que se convierte en compañero", "regla imposible del mundo cotidiano", "rivalidad creativa entre vecinos"],
        "verificable_en": ["wikipedia"], "ficción": True,
        "público": "familiar 8-40", "identidad": "humor espontáneo, ternura con giro",
        "formatos": ["serie_c", "paradoja"], "duracion_obj_s": (240, 560),
        "estrategia_visual": "avatar 3D + escenas de estudio", "frecuencia": "3/semana",
        "monetizacion": "alto (patrocinio familiar)", "kpis": ["suscriptores por episodio", "recurrentes"],
        "canal": "Pulso Curioso",
    },
    "historia": {
        "nombre": "Documentales históricos",
        "descripcion": "Eventos documentados del pasado con cronología verificada. FÁCTICO: gate 1 completo, recreaciones marcadas.",
        "semillas": ["anecdota olvidada de un evento monumental", "error histórico que se repitió 100 años", "primer registro de algo cotidiano"],
        "verificable_en": ["britannica.com", "loc.gov", "britishlibrary.uk", "unesco.org"],
        "ficción": False,
        "público": "25-54 intelectual", "identidad": "narrador tercera persona, cronología estricta, fuentes visibles",
        "formatos": ["medicion", "origen"], "duracion_obj_s": (420, 900),
        "estrategia_visual": "archivos, mapas de época, cartelas con año", "frecuencia": "1/semana",
        "monetizacion": "medio-alto (alcance), educación", "kpis": ["duración media de vista", "suscriptores"],
        "canal": "Pulso Curioso",
    },
    "mundo": {
        "nombre": "Ciudades, países y culturas",
        "descripcion": "Geografía vivida: cómo se vive algo en un lugar, con datos reales de sus fuentes oficiales. FÁCTICO.",
        "semillas": ["ciudad con dato estadístico asombroso", "oficio típico que desaparece", "vida cotidiana en un lugar extremo"],
        "verificable_en": ["worldbank.org", "who.int", "oecd.org", "un.org"],
        "ficción": False,
        "público": "22-45 viajero", "identidad": "invitación directa al televidente ('mirá'), comparativa entre dos lugares",
        "formatos": ["conteo", "cuerpo"], "duracion_obj_s": (280, 680),
        "estrategia_visual": "mapas, difenias, estaciones", "frecuencia": "2/semana",
        "monetizacion": "alto (sponsorships de viajes)", "kpis": ["retención 30s", "suscriptores"],
        "canal": "Pulso Curioso",
    },
    "finanzas": {
        "nombre": "Finanzas personales y qué hace el dinero en distintos círculos sociales",
        "descripcion": "Patrones verificados de cómo el dinero circula, cambia hábitos y estratos "
                       "— con datos medidos, no con testimonios falsos. FÁCTICO con fuentes.",
        "semillas": [
            "por qué ahorrar cada mes no equivale a ganar más",
            "cómo las deudas de clase media terminan siendo inevitables",
            "por qué una subida salarial no trae felicidad permanente",
        ],
        "verificable_en": ["worldbank.org", "oecd.org", "imf.org", "bls.gov",
                           "ine.es", "reuters.com", "bbc.com"],
        "ficción": False, "sensible": False,
        "formato": "paradoja",
        "público": "22-45 adulto trabajador", "identidad": "narrador testigo, ejemplo cotidiano demostrable",
        "formatos": ["paradoja", "conteo", "medicion"],
        "frecuencia": "1/semana", "monetizacion": "alto",
        "duracion_obj_s": (280, 620),
        "estrategia_visual": "gráficos de proporciones, una persona, una pantalla, una cifra",
        "kpis": ["retención media", "compartidos"], "canal": "Pulso Curioso",
    },
    "empresas": {
        "nombre": "Empresas que crecieron de cero a potencia o quiebre",
        "descripcion": "Emprendimientos reales con documentos públicos: nombre de founder, "
                       "fecha, primera venta real, punto de no retorno. Sin mitos de café.",
        "semillas": [
            "empresa que empezó vendiendo puerta a puerta en un garaje",
            "empresa que sobrevivió una quiebra total cambiando de producto",
            "la primera venta que definió una empresa gigante",
        ],
        "verificable_en": ["sec.gov", "forbes.com", "inc.com", "reuters.com", "bbc.com",
                           "britannica.com", "mit.edu"],
        "ficción": False, "sensible": False,
        "público": "22-50 emprendedor/creativo", "identidad": "narrador protagonista, primera persona",
        "formatos": ["paradoja", "medicion", "origen"], "frecuencia": "1/semana",
        "monetizacion": "alto", "duracion_obj_s": (350, 750),
        "estrategia_visual": "fotos/documentos públicos, diagramas de crecimiento, logos en context",
        "kpis": ["retención media", "compartidos"], "canal": "Pulso Curioso",
    },
    "vidas": {
        "nombre": "Vidas memorables: personas que transformaron su entorno",
        "descripcion": "Biografías de figuras cuyo recorrido real sirve como ejemplo, motivación "
                       "o explicación de un fenómeno. Sin hagiografía; con contradicciones reales.",
        "semillas": [
            "persona anónima que terminó dirigiendo un cambio histórico",
            "vida completa de una figura que nadie con este plan pudo prever",
            "una vida que personifica un fenómeno que millones viven",
        ],
        "verificable_en": ["britannica.com", "smithsonianmag.com", "ap.org", "reuters.com",
                           "bbc.com", "books.google.com"],
        "ficción": False, "sensible": True,
        "público": "20-60 adulto general", "identidad": "narrador testigo, primera persona",
        "formatos": ["origen", "paradoja", "conteo"], "frecuencia": "1/semana",
        "monetizacion": "medio-alto", "duracion_obj_s": (350, 800),
        "estrategia_visual": "retratos en tinta, crónicas de época",
        "kpis": ["retención media", "suscriptores"], "canal": "Pulso Curioso",
    },
    "patrones": {
        "nombre": "Patrones de conducta: cómo funciona tu mente",
        "descripcion": "Sesgos y patrones cognitivos con estudio y réplica. Sin gurú de autoayuda. "
                       "Con fuentes (NIH/APA/Nature) y explicación de costo cognitivo real.",
        "semillas": [
            "por qué la procrastinación no es pereza sino miedo al juicio",
            "por qué ver una tabla de progreso te hace ahorrar más",
            "el sesgo que vuelve a una persona en un saboteador silencioso",
        ],
        "verificable_en": ["nih.gov", "apa.org", "nature.com", "science.org", "britannica.com",
                           "bbc.com"],
        "ficción": False, "sensible": False,
        "público": "22-45 adulto curioso", "identidad": "narrador testigo, primera persona",
        "formatos": ["paradoja", "cuerpo", "conteo"], "frecuencia": "1/semana",
        "monetizacion": "alto", "duracion_obj_s": (280, 600),
        "estrategia_visual": "figura con charts, escena cotidiana, gesto repetido",
        "kpis": ["retención media", "compartidos"], "canal": "Pulso Curioso",
    },
    "crimen": {
        "nombre": "Crímenes reales y misterios no resueltos",
        "descripcion": "Casos documentados, sin culpables por nombrar si no hay condena. FÁCTICO con controles editoriales reforzados.",
        "semillas": ["caso sin resolver con pista clave", "error forense que cerró el caso equivocado",
                     "estafador que usó rutina oficial para pasar desapercibido"],
        "verificable_en": ["fbi.gov", "ojp.gov.uk", "interpoll.int", "reuters.com", "ap.org"],
        "ficción": False, "sensible": True,
        "público": "25-54 true crime", "identidad": "cronología del caso, sin vilificar sospechosos sin condena",
        "formatos": ["expediente", "conteo"], "duracion_obj_s": (320, 700),
        "estrategia_visual": "fichas de expediente, fotos de archivo públicas, redacciones con recorte de privacidad",
        "frecuencia": "1/semana", "monetizacion": "alto pero con riesgo de restricción de anuncios",
        "kpis": ["retención media", "compartidos"], "canal": "Pulso Curioso",
    },
    "mentes_criminales": {
        "nombre": "Crímenes perfectos, fallidos y errores que resolvieron el caso",
        "descripcion": ("Casos reales con sentencia firme o hechos oficiales documentados. El foco es el método, "
                        "la investigación y el error comprobable; nunca se declara culpable a un sospechoso "
                        "sin condena ni se enseña un procedimiento para delinquir."),
        "semillas": ["caso criminal condenado error forense sentencia", "robbery solved by one overlooked clue official case",
                     "forensic mistake overturned conviction official source", "museum theft investigation FBI case"],
        "verificable_en": ["fbi.gov", "justice.gov", "courts.gov", "ojp.gov", "apnews.com", "reuters.com"],
        "ficción": False, "sensible": True,
        "público": "25-54 interesado en historia criminal e investigación",
        "identidad": "cronología precisa, distingue hechos probados, acusaciones y preguntas abiertas",
        "formatos": ["expediente", "paradoja", "conteo"], "duracion_obj_s": (320, 700),
        "estrategia_visual": "expediente ilustrado, mapas y objetos simbólicos; sin gore ni recreaciones que parezcan evidencia",
        "frecuencia": "1/semana", "monetizacion": "medio-alto con cuidado de anunciantes",
        "kpis": ["retención media", "compartidos", "comentarios con fuentes"], "canal": "Pulso Curioso",
    },
    "mentes_brillantes": {
        "nombre": "Mentes brillantes: ideas que cambiaron la historia",
        "descripcion": ("Biografías intelectuales basadas en archivos y fuentes institucionales. Se cuenta el problema, "
                        "el razonamiento documentado y el impacto, evitando mitos de genio solitario."),
        "semillas": ["archivo historia científica idea que cambió el mundo", "mathematician biography breakthrough institution",
                     "inventor patent archive historical biography", "historical figure letters scientific discovery"],
        "verificable_en": ["nobelprize.org", "loc.gov", "si.edu", "royalsocietypublishing.org", "britannica.com", "archives.gov"],
        "ficción": False, "sensible": False,
        "público": "18-54 curioso por ciencia, historia e inventos",
        "identidad": "narrador claro, contexto histórico y límites de lo que se sabe",
        "formatos": ["paradoja", "origen", "medicion"], "duracion_obj_s": (320, 700),
        "estrategia_visual": "retratos estilizados, notas, diagramas de ideas y cronologías",
        "frecuencia": "1/semana", "monetizacion": "alto educativo",
        "kpis": ["retención media", "compartidos", "suscriptores"], "canal": "Pulso Curioso",
    },
    "guerra": {
        "nombre": "Guerras, conflictos y geopolítica",
        "descripcion": "Historias de conflictos con cronología y consecuencias verificadas. FÁCTICO; nada de justificar, nada de fandom.",
        "semillas": ["batalla decidida por un error logístico", "negociación que evitó o aceleró una guerra",
                     "recurso natural que configuró una frontera"],
        "verificable_en": ["isn.ethz.ch", "globalsecurity.org", "britannica.com", "un.org", "reuters.com"],
        "ficción": False, "sensible": True,
        "público": "28-54 interés histórico", "identidad": "narrador neutral, énfasis en consecuencias humanas medibles",
        "formatos": ["medicion", "origen"], "duracion_obj_s": (420, 900),
        "estrategia_visual": "mapas de frentes, cronologías, archivo", "frecuencia": "1/semana",
        "monetizacion": "medio (advertencias de contenido)", "kpis": ["duración de vista", "retención media"],
        "canal": "Pulso Curioso",
    },
    "civilizaciones": {
        "nombre": "Religiones e historia de las civilizaciones",
        "descripcion": "Origen y evolución de creencias y civilizaciones con respeto y fuentes de autores de las propias tradiciones. FÁCTICO", "semillas": ["práctica ritual que cruza siglos", "ciudad que se diseñó alrededor de una creencia", "texto antiguo que cambió de público"],
            "verificable_en": ["britannica.com", "oxfordreference.com", "unesco.org"],
        "ficción": False, "sensible": True,
        "público": "25-60 interesado en historia/cultura", "identidad": "curiosidad respetuosa, sin proselitismo ni sátira",
        "formatos": ["origen", "medicion"], "duracion_obj_s": (380, 850),
        "estrategia_visual": "arte de época, lugares reales, cartelas de contexto", "frecuencia": "1/semana",
        "monetizacion": "medio", "kpis": ["duración de vista", "suscriptores"], "canal": "Pulso Curioso",
    },
    "politica": {
        "nombre": "Política y acontecimientos internacionales",
        "descripcion": "Mecanismo político explicado sin tomar partido. FÁCTICO: cada cifra con fuente fechada; noticias con SOLLO informante oficial.",
        "semillas": ["cómo funciona una institución en la práctica", "regla electoral que cambió el resultado", "tratado con efecto inesperado"],
        "verificable_en": ["un.org", "oecd.org", "worldbank.org", "gov.ar", "reuters.com"],
        "ficción": False, "sensible": True,
        "público": "25-60 actualidad", "identidad": "explicación de mecanismo, no de partido; vigencia limitada",
        "formatos": ["paradoja", "conteo"], "duracion_obj_s": (260, 650),
        "estrategia_visual": "infografías de proceso, cronologías", "frecuencia": "1/semana",
        "monetizacion": "bajo-medio (poca reutilización)", "kpis": ["retención 30s", "CTR"], "canal": "Pulso Curioso",
    },
    "supervivencia": {
        "nombre": "Supervivencia y escenarios hipotéticos",
        "descripcion": "Escenario hipotético sostenido SOLO por datos reales (fisiología, física, geografía). Ficción de premisa, hechos reales.",
        "semillas": ["caer al mar a 100 km de la costa", "quedar sin electricidad en invierno", "escalar-imposible sin equipo"],
        "verificable_en": ["noaa.gov", "who.int", "nih.gov", "armymwr.com"],
        "ficción": False,
        "público": "18-44 aventura", "identidad": "segunda persona, encuadre hipotético explícito, minuto a minuto",
        "formatos": ["cuerpo", "dia_a_dia"], "duracion_obj_s": (260, 640),
        "estrategia_visual": "mapas, gráficos corporales, degradados de tiempo", "frecuencia": "2/semana",
        "monetizacion": "alto", "kpis": ["retención media", "suscriptores"], "canal": "Pulso Curioso",
    },
    "cine": {
        "nombre": "Historias cinematográficas originales",
        "descripcion": "Miniseries y relatos de innegociable producción propia con estructura de tres actos. FICCIÓN original, nada derivado de IP ajena.",
        "semillas": ["dos hermanos rotos por un secreto en una selva", "tramo final de una barrera imposible", "familia reencontrada en un litoral hostil"],
        "verificable_en": ["wikipedia"], "ficción": True,
        "público": "22-45 cine", "identidad": "tres actos, personajes con arco, clima cinemático",
        "formatos": ["serie_c", "expediente"], "duracion_obj_s": (500, 1200),
        "estrategia_visual": "escenas con avatar/actor-principal, luz cinematográfica", "frecuencia": "1/semana",
        "monetizacion": "alto si la serie engancha", "kpis": ["vistas del siguiente episodio", "retención"],
        "canal": "Pulso Curioso",
    },
    # Nichos nomeados por el dueño (2026-11-05) que todavía no existían como configuración:
    # mascotas, salud y fitness, consumibles/deudas diarias y vida silvestre. Sin entrada acá,
    # la fábrica no los elige nunca y el canal no puede probarlos con datos propios.
    "mascotas": {
        "nombre": "Mascotas: comportamiento, razas y cuidados verificables",
        "descripcion": "Por qué un animal doméstico hace lo que hace, con el estudio o la medida "
                       "que lo sostiene. Nada de antropomorfismo vendido como dato; si la ciencia "
                       "aún no lo resolvió, el guion lo dice. FÁCTICO con fuentes.",
        "semillas": ["por qué el perro da vueltas antes de acostarse",
                     "qué ve un gato en la penumbra",
                     "cómo reconoce un perro el olor de una enfermedad",
                     "why dogs respond to human pointing"],
        "verificable_en": ["nih.gov", "nature.com", "sciencedaily.com", "bbc.com", "reuters.com",
                           "frontiersin.org"],
        "ficción": False, "sensible": False,
        "público": "18-54 dueños y amantes de animales",
        "identidad": "narrador que traduce la conducta a mecanismo, sin humanizar de más",
        "formatos": ["paradoja", "origen", "medicion"], "duracion_obj_s": (240, 560),
        "estrategia_visual": "conducta real en primer plano, gráfico del estímulo-respuesta",
        "frecuencia": "2/semana",
        "monetizacion": "medio (alto en Facebook por compartidos, no prometido)",
        "kpis": ["retención 30s", "compartidos"],
        "canal": "Pulso Curioso",
    },
    "salud": {
        "nombre": "Salud y fitness: qué midió el estudio y qué no",
        "descripcion": "Fisiología y entrenamiento con el número y la muestra del estudio delante. "
                       "PROHIBIDO: prometer curas, diagnosticar o reemplazar consejo médico; toda "
                       "recomendación práctica se enuncia como lo que dice la evidencia, no como "
                       "indicación personal. FÁCTICO con fuentes.",
        "semillas": ["qué le pasa al pulso en las primeras cuatro semanas de entrenamiento",
                     "cuánto sleep necesita realmente un adulto según la cohorte",
                     "por qué el dolor de espalda casi nunca es una hernia",
                     "rest between sets strength study"],
        "verificable_en": ["who.int", "nih.gov", "nhs.uk", "mayoclinic.org", "bmj.com",
                           "thelancet.com", "reuters.com"],
        "ficción": False, "sensible": True,
        "público": "25-50 que entrena o cuida su salud",
        "identidad": "tono clínico-cotidiano, cifra con muestra y límite declarado",
        "formatos": ["cuerpo", "medicion", "dia_a_dia"], "duracion_obj_s": (280, 640),
        "estrategia_visual": "gráfico de curva temporal del cuerpo, comparaciones de escala",
        "frecuencia": "2/semana",
        "monetizacion": "medio-alto (YPP exige cuidado extra en claims de salud)",
        "kpis": ["retención media", "guardados"],
        "canal": "Pulso Curioso",
    },
    "consumos": {
        "nombre": "Consumibles y deudas del día a día: a dónde va la plata",
        "descripcion": "El gasto que no se ve porque es chico y repetido: suscripciones, cuotas, "
                       "consumibles del hogar. Todo número sale de una fuente oficial o de un "
                       "precio publicado con fecha; si el precio es de un solo país se dice cuál. "
                       "FÁCTICO con fuentes. No se promete libertad financiera ni un rendimiento.",
        "semillas": ["cuánto cuesta el café que se toma todos los días",
                     "por qué la cuota del celular nunca termina",
                     "qué es un consumible y por qué se come el presupuesto",
                     "cost per month subscription fatigue study"],
        "verificable_en": ["worldbank.org", "oecd.org", "imf.org", "bls.gov", "ine.es",
                           "bcra.gob.ar", "reuters.com", "bbc.com"],
        "ficción": False, "sensible": False,
        "público": "22-45 con ingresos variables y deudas chicas",
        "identidad": "cuenta clara en voz alta, número grande en pantalla, cero venta de cursos",
        "formatos": ["medicion", "conteo", "paradoja"], "duracion_obj_s": (240, 540),
        "estrategia_visual": "billetes/monedas reales, barra acumulada mes a mes",
        "frecuencia": "2/semana",
        "monetizacion": "medio (afín a finanzas, mismo público)",
        "kpis": ["retención 30s", "CTR", "compartidos"],
        "canal": "Pulso Curioso",
    },
    "fauna": {
        "nombre": "Vida silvestre y documentales de naturaleza",
        "descripcion": "Conducta y hábitat de especies reales, con la fuente del estudio de campo "
                       "y el estado de conservación del listado oficial. Sin escenas fabricadas ni "
                       "especies presentadas como peligrosas sin evidencia. FÁCTICO con fuentes.",
        "semillas": ["cómo un pulpo resuelve un frasco sin ver la solución",
                     "por qué un ave migratoria encuentra un punto del mapa",
                     "qué hace un depredador en la sequía",
                     "animal behaviour field study surprising"],
        "verificable_en": ["nationalgeographic.com", "iucnredlist.org", "gbif.org",
                           "smithsonianmag.com", "nature.com", "bbc.com", "noaa.gov"],
        "ficción": False, "sensible": False,
        "público": "18-60 curiosidad por la naturaleza",
        "identidad": "narrador de documental, calma y detalle, cero sensacionalismo de riesgo",
        "formatos": ["origen", "dia_a_dia", "medicion"], "duracion_obj_s": (300, 700),
        "estrategia_visual": "hábitat, mapa de rango y escala corporal; nada de captura falsa",
        "frecuencia": "1/semana",
        "monetizacion": "medio-alto (natural history rinde bien en ambas plataformas)",
        "kpis": ["retención media", "compartidos"],
        "canal": "Pulso Curioso",
    },
}

CATEGORIAS.update(_NUEVA_CATEG)


# Formatos narrativos nuevos (misión §5): reglas, expediente, día-a-día y serie
# animada/cinematográfica se suman a los 5 formatos de curiosidad.
FORMATOS.update({
    "reglas": {
        "nombre": "La historia contada por reglas",
        "pregunta": "qué reglas hay que cumplir para sobrevivir a {tema}?",
        "estructura": ["la regla más extraña", "por qué existe", "cuándo se rompió", "consecuencia", "cierre"],
        "nota": "La narración enumera reglas estrictas y muestra cada una violada o respetada.",
        "palabras_corto": (150, 220), "palabras_largo": (1500, 2100),
    },
    "expediente": {
        "nombre": "Expediente abierto",
        "pregunta": "qué se sabe y qué no de {tema}?",
        "estructura": ["el archivo", "testigos", "evidencia", "lo que no cuadra", "estado actual"],
        "nota": "Presentación documental de un caso organizada por estado de la evidencia; perfecto.",
        "palabras_corto": (160, 230), "palabras_largo": (1600, 2300),
    },
    "dia_a_dia": {
        "nombre": "Día N: sobrevivir mientras",
        "pregunta": "¿qué pasa cada día mientras {tema}?",
        "estructura": ["día 0", "días 1-3", "días 4-10", "el punto de no retorno", "día final"],
        "nota": "Cronología con salto temporal: cada bloque es un día o tramo medido con datos reales.",
        "palabras_corto": (170, 240), "palabras_largo": (1700, 2400),
    },
    "serie_c": {
        "nombre": "Serie con personajes recurrentes",
        "pregunta": "¿qué significaría {tema} para un personaje propio?",
        "estructura": ["protagonista", "mundo", "conflicto", "giro", "cliffhanger"],
        "nota": "Ficción original con continuidad entre episodios: el cliffhanger tira al siguiente vídeo.",
        "palabras_corto": (180, 260), "palabras_largo": (1800, 2600),
    },
})

# Demanda de los nichos nuevos: búsquedas cortas que Wikipedia sí indexa.
_BUSQUEDAS_EXTRA = {
    "terror": ["entidades nocturnas", "pueblo abandonado", "leyenda local"],
    "apocalipsis": ["pandemia simulada", "virus de horizonte", "estudio salto zombie"],
    "animadas": ["storytelling animado", "personaje animado", "cortometraje animado"],
    "historia": ["dinastía Xia", "pan no levado", "tabilla sumerio", "Códice Recuerdos", "viaje Magallanes",
                 "primer ferrocarril", "foto más antigua", "glaciar Moreno"],
    "mundo": ["lago Baikal Isla Olkhon", "Pompeya verano", "ciudad vertical", "aldea rural Mongolia", "suburbio informal", "etnomusica Mongolia"],
    "crimen": ["estafa pirámide", "robo al Banco Río", "contrabando frontera", "_cheque falsificado"],
    "mentes_criminales": ["robo Museo Gardner", "caso criminal resuelto evidencia", "error forense condena anulada", "estafador condenado historia"],
    "mentes_brillantes": ["Ada Lovelace archivo", "Katherine Johnson NASA", "Marie Curie cuadernos", "Alan Turing archivo", "Nikola Tesla patente", "Hedy Lamarr patente"],
    "guerra": ["batalla de Trafalgar", "sitio de Buenos Aires", "Guerra del Paraguay"],
    "civilizaciones": ["civilización Caral", "templo Edfu", "Códice Dresden"],
    "politica": ["reforma constitucional", "bloqueo de puertos", "acuerdo pesquero"],
    "supervivencia": ["hipotermia en río", "Alain Bombard Atlántico", "desierto sin agua"],
    "cine": ["cortometraje español", "miniserie original"],
    # Nichos del dueño (2026-11-05) que estaban registrados como categoría pero sin consultas:
    # sin entrada acá la fábrica no los busca contra Wikipedia y entonces nunca los elige.
    "mascotas": ["comportamiento canino", "gato visión", "perro olfato", "ronroneo",
                 "raza de perro", "dog cognition"],
    "salud": ["fases del sueño", "hipertrofia muscular", "dolor lumbar", "voz máxima de oxígeno",
              "recuperación muscular", "sleep deprivation"],
    "consumos": ["gasto hormiga", "economía doméstica", "tarjeta de crédito", "interés compuesto",
                 "canasta familiar", "suscripción de servicio"],
    "fauna": ["migración de aves", "uso de herramientas animales", "lista roja de especies",
              "comportamiento de depredadores", "comunicación animal", "corredor biológico"],
    "finanzas": ["tasa de interés", "ahorro de hogares", "salario mínimo", "inflación",
                 "deuda pública", "brecha salarial"],
    "empresas": ["historia de una empresa", "quiebra corporativa", "cadena de suministro",
                 "monopolio", "patente", "fundador de empresa"],
    "vidas": ["biografía de científico", "explorador", "pionera", "inventor", "biografía política",
              "autodidacta"],
    "patrones": ["formación de hábitos", "sesgo cognitivo", "ritmo circadiano", "memoria de trabajo",
                "toma de decisiones", "fuerza de voluntad"],
}

# Disparadores léxicos para clasificar un tema a ojo sin LLM.
_DISPARADORES_EXTRA = {
    "terror": ["terror", "fantasma", "espeluznante", "susurro", "fantasmas", "maldito", "entidad", "aparece", "bosque", "casa encantada",
               "horror", "haunted", "ghost", "creepy", "whisper", "cursed"],
    "apocalipsis": ["zombi", "zombie", "apocalipsis", "infección", "infectados", "pandemia", "abandono", "ruinas", "cuarentena", "superviviente",
                     "outbreak", "undead", "quarantine", "ruined"],
    "animadas": ["animado", "animación", "cartoon", "dibujo", "personaje animado", "cortometraje", "estudio",
                 "animation", "cartoon"],
    "historia": ["historia", "época", "siglo", "imperio", "dinastía", "ancient", "empire", "century", "medieval", "cronología"],
    "mundo": ["ciudad", "país", "cultura", "población", "continente", "gentilicio", "tribal", "ciudadanía", "pueblo", "aldea",
              "city", "country", "culture", "population", "continent", "village"],
    "crimen": ["crimen", "caso", "homicidio", "secuestro", "estafado", "falsificador", "forense", "juzgado", "whole", "caso abierto",
               "crime", "murder", "kidnapping"],
    "mentes_criminales": ["crimen", "crimenes", "criminal", "criminales", "robo", "atraco", "estafador", "forense", "sentencia", "condena", "evidencia", "misterio", "heist", "fraud"],
    "mentes_brillantes": ["genio", "genios", "brillante", "brillantes", "inventor", "inventora", "cientifico", "cientifica", "matematico", "matematica", "descubrimiento", "patente", "nobel"],
    "guerra": ["guerra", "batalla", "frente", "asedio", "conflicto", "armisticio", "tratado", "flota", "regimiento",
               "war", "battle", "siege", "front"],
    "civilizaciones": ["civilización", "religión", "ritual", "templo", "diós", "río sagrado", "sagrada", "creencia",
                       "civilization", "religion", "temple", "ritual"],
    "politica": ["política", "elecciones", "congreso", "parlamento", "sanción", "tratado", "referéndum", "partido",
                  "politics", "election", "sanction", "treaty"],
    "supervivencia": ["supervivencia", "hipotermia", "ajeno", "derramado", "sequía", "huracán", "avalancha", "desierto",
                      "survival", "hypothermia", "avalancha", "desierto"],
    "cine": ["cine", "film", "pelicula", "thriller", "miniserie", "dramático", "actor", "guionista",
              "cinema", "film", "thriller", "miniseries"],
    # Los cuatro nichos del dueño que no existían + los cuatro que ya estaban en CATEGORIAS
    # pero sin disparadores: sin entrada acá, categoria_de() los clasifica como None y la
    # fábrica los deja fuera del ranking aunque sean nichos nombrados por el dueño.
    # Una sola palabra por disparador: categoria_de() compara TOKENES y "casa encantada" no matchea.
    "mascotas": ["mascota", "perro", "perros", "canino", "canina", "ladrido", "gato", "gatos",
                 "felino", "ronroneo", "caballo", "loro", "tutor", "raza", "obediencia",
                 "dog", "cats", "pet", "puppy", "feline"],
    "salud": ["salud", "entrenamiento", "musculo", "musculos", "ejercicio", "cardio", "pulso",
              "proteina", "dieta", "lesion", "fractura", "dormir", "insomnio", "recuperacion",
              "fisiologia", "glucosa", "colesterol", "vo2", "hipertrofia",
              "fitness", "sleep", "workout", "muscle", "recovery"],
    "consumos": ["gasto", "gastos", "consumible", "consumibles", "suscripcion", "cuota", "cuotas",
                 "tarjeta", "presupuesto", "precio", "precios", "supermercado", "recibo", "plata",
                 "compra", "compras", "monedero", "wallet", "subscription", "spending", "budget"],
    "fauna": ["fauna", "especie", "especies", "habitat", "depredador", "depredadores", "migracion",
              "manada", "nido", "ave", "aves", "ballena", "tiburon", "lobo", "zorro", "elefante",
              "pulpo", "coral", "silvestre", "naturaleza", "wildlife", "species", "predator",
              "migration", "safari"],
    "finanzas": ["finanza", "finanzas", "dinero", "inversion", "inversiones", "tasa", "inflacion",
                 "salario", "salarios", "banco", "bancos", "economia", "impuesto", "riqueza",
                 "pobreza", "credito", "finance", "money", "interest", "inflation", "wage"],
    "empresas": ["empresa", "empresas", "compania", "companias", "negocio", "fundador", "fundadora",
                 "quiebra", "monopolio", "fabrica", "mercado", "rival", "patente", "concurso",
                 "company", "business", "startup", "bankruptcy", "monopoly", "factory"],
    "vidas": ["biografia", "protagonista", "pionero", "pionera", "autodidacta", "exilio", "legado",
              "infancia", "retrato", "memorias", "diario", "biography", "pioneer"],
    "patrones": ["habito", "habitos", "patron", "patrones", "motivacion", "disciplina", "voluntad",
                 "circadiano", "decision", "decisiones", "autocontrol", "rutina", "procrastinacion",
                 "habit", "habits", "willpower", "routine", "selfcontrol"],
}

PESO_INICIAL = {c: 1.0 for c in CATEGORIAS}
APRENDIZAJE = config.STATE / "aprendizaje.json"


# Perfil de canal por nicho: identidad narrativa unificada para prompts.
def canal_de(categoria: str) -> dict:
    """Perfil completo del nicho con defaults; canal = marca/voz/estilo por categoría."""
    perfil = dict(CATEGORIAS.get(categoria) or {})  # defensive: nicho sin registrar
    perfil["canal"] = "Pulso Curioso"
    # guion.py (FixKeyError): siempre proveer nombre/categoría — un nicho desconocido no
    # debe reventar con KeyError en medio de la cadena de producción
    perfil["nombre"] = str(perfil.get("nombre") or categoria or "general")
    perfil["promesa"] = ("Una curiosidad sorprendente, con hechos verificables, contexto y una "
                          "explicación propia que deje algo útil al espectador.")
    perfil.setdefault("ficción", False)
    perfil.setdefault("identidad", "narrador curioso, tercera persona, frases cortas")
    perfil.setdefault("público", "adulto general")
    perfil.setdefault("formatos", list(FORMATOS))
    perfil.setdefault("duracion_obj_s", (280, 620))
    perfil.setdefault("estrategia_visual", "planos con Ken Burns y cartelas")
    perfil.setdefault("frecuencia", "2/semana")
    perfil.setdefault("monetizacion", "medio")
    perfil.setdefault("kpis", ["retención media", "suscriptores"])
    perfil.setdefault("sensible", False)
    return perfil


def es_ficcion(categoria: str) -> bool:
    return bool(canal_de(categoria)["ficción"])


def resumen_multinicho() -> list[dict]:
    """Resumen de todas las categorías activas (sa panel/dashboard y calendario)."""
    out = []
    for cat, defn in CATEGORIAS.items():
        out.append({
            "id": cat, "canal": defn.get("canal", "Pulso Curioso"),
            "nombre": defn.get("nombre"), "descripcion": defn.get("descripcion"),
            "ficción": bool(defn.get("ficción")), "sensible": bool(defn.get("sensible")),
            "público": defn.get("público"), "estrategia_visual": defn.get("estrategia_visual"),
            "frecuencia": defn.get("frecuencia"), "monetizacion": defn.get("monetizacion"),
            "kpis": defn.get("kpis"), "duracion_obj_s": defn.get("duracion_obj_s"),
            "peso": pesos().get(cat, 1.0),
        })
    return out

# Consultas CORTAS para medir demanda: srsearch de Wikipedia trata todo el texto como AND,
# las semillas descriptivas (frases largas) devuelven 0 resultados.
BUSQUEDAS = {
    "experimentos": ["experimento de Milgram", "efecto Mpemba", "doble rendija",
                     "experimento Stern-Gerlach", "resonancia", "caída libre"],
    "misterios": ["señal Wow", "triángulo de las Bermudas", "faro Flannan Isles",
                  "colonia perdida Roanoke", "luz de Hessdalen", "ciudad perdida"],
    "tecnologia": ["computación cuántica", "fusión nuclear", "batería de estado sólido",
                   "impresión 3D de órganos", "interfaz cerebro-computadora", "manipulación genética"],
    "psicologia": ["sesgo cognitivo", "memoria falsa", "efecto Mandela", "parálisis del sueño",
                   "plasticidad cerebral", "ceguera por inatención"],
}

# Lexikon de disparadores: detectar a què familia pertenece un tema sin gastar llamadas al LLM.
DISPARADORES = {
    "experimentos": [
        "experimento", "medido", "medicion", "laboratorio", "efecto demostrado", "escala",
        "caida libre", "vacío", "presion", "temperatura", "imposible", "contraintuitivo",
        "experiment", "measured", "laboratory", "demonstration", "vacuum", "pressure",
    ],
    "misterios": [
        "misterio", "sin resolver", "desconocido", "anomalia", "incidente", "desaparicion",
        "evento", "explosion", "crater", "senal", "no se sabe", "sin explicacion",
        "mystery", "unsolved", "anomaly", "unexplained", "signal", "disappearance", "tunguska",
    ],
    "tecnologia": [
        "tecnologia", "invento", "máquina", "motor", "chip", "inteligencia artificial",
        "modelo", "robot", "red", "satelite", "bateria", "reactor", "invencion",
        "technology", "invention", "engine", "chip", "robot", "network", "reactor", "battery",
    ],
    "psicologia": [
        "cerebro", "mente", "memoria", "percepcion", "sesgo", "conducta", "comportamiento",
        "emocion", "sueno", "atencion", "ilusion", "optico", "humano", "psicologia",
        "brain", "memory", "bias", "behavior", "perception", "illusion", "sleep", "psychology",
    ],
}

BUSQUEDAS.update(_BUSQUEDAS_EXTRA)
DISPARADORES.update(_DISPARADORES_EXTRA)


def pesos() -> dict:
    """Pesos de categoria aprendidos de metricas reales (vacio = arrancamos parejos)."""
    if not APRENDIZAJE.exists():
        return dict(PESO_INICIAL)
    datos = json.loads(APRENDIZAJE.read_text(encoding="utf-8"))
    return {**PESO_INICIAL, **datos.get("pesos", {})}


def _norm(texto: str) -> str:
    """Minúsculas, sin acentos y sin símbolos: 'Máquina' y 'maquina' tienen que coincidir."""
    sin_acentos = "".join(c for c in unicodedata.normalize("NFKD", texto.lower())
                          if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]+", " ", sin_acentos)


def categoria_de(texto: str) -> str | None:
    """Clasifica un tema en una categoría editorial contando disparadores léxicos.

    Coincidencia por PALABRA COMPLETA: con substring, "Alfredo" activaba "red" y el top
    diario de Wikipedia se llenaba de futbolistas clasificados como tecnologia.
    """
    tokens = set(_norm(texto).split())
    puntos = {cat: sum(1 for k in palabras if _norm(k) in tokens)
              for cat, palabras in DISPARADORES.items()}
    # Si un nicho específico empata con uno paraguas (p. ej. historia/crimen o psicología),
    # gana la serie editorial específica que la persona pidió.
    prioridad = {"mentes_criminales": 2, "mentes_brillantes": 2}
    mejor = max(puntos, key=lambda c: (puntos[c], prioridad.get(c, 0)))
    return mejor if puntos[mejor] > 0 else None


def elegir_formato(rng: random.Random | None = None) -> tuple[str, dict]:
    """Un formato al azar: la serie alterna formulas, no rellena la misma plantilla."""
    rng = rng or random.Random()
    clave = rng.choice(list(FORMATOS))
    return clave, FORMATOS[clave]


def potencial(idea: dict, senales: list[dict] | None = None) -> tuple[float, str]:
    """Potencial EDITORIAL (no promete vistas): demanda observada + verificabilidad + formato."""
    puntos, why = 0.0, []
    senal = max((float(s.get("score", 0) or 0) for s in (senales or [])), default=0.0)
    if senal >= 0.66:
        puntos += 30
        why.append(f"demanda real observada ({senal:.2f})")
    elif senal > 0:
        puntos += 15
        why.append(f"demanda baja pero medida ({senal:.2f})")
    else:
        why.append("sin senal de demanda medida")

    n_fuentes = int(idea.get("fuentes", 0) or 0)
    if n_fuentes >= 4:
        puntos += 25
        why.append(f"{n_fuentes} fuentes independientes")
    elif n_fuentes >= 2:
        puntos += 15
        why.append(f"{n_fuentes} fuentes (minimo del gate 1)")
    else:
        puntos -= 20
        why.append("sin fuentes confirmadas: no pasa el gate 1")

    if idea.get("formato") in FORMATOS:
        puntos += 20
        why.append(f"formato serie: {FORMATOS[idea['formato']]['nombre']}")
    if idea.get("giro"):
        puntos += 15
        why.append("tiene giro verificable")
    if idea.get("gancho"):
        puntos += 10
        why.append("gancho de 1-3 s escrito")

    peso = pesos().get(idea.get("categoria"), 1.0)
    puntos *= peso
    why.append(f"peso aprendido de la categoria {peso:.2f}")
    return round(max(0.0, min(puntos, 100.0)), 1), " | ".join(why)
