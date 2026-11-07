import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import config  # noqa: E402
from pipeline.episode import Episode  # noqa: E402
from pipeline.stages import narracion as N  # noqa: E402

T = ("¿Por qué una persona que gana bien termina debiendo más que nunca? No es el gasto: "
     "es el orden en que la plata entra y sale de su vida.\n\n"
     "Cuando cobró el sueldo, pagó primero la tarjeta. Después vino el alquiler, la cuota "
     "del colegio, la nafta. Quedaron 3.000 pesos y una sensación de derrota que un aumento "
     "no cura. El problema no era la inteligencia de la gente: era la arquitectura de los "
     "incentivos, y nadie la discutía porque había funcionado durante veinte años.\n\n"
     "El informe llegó tarde. Tres mil familias perdieron todo.\n\n"
     "¿Y qué hicieron después de eso?\n")

ep = Episode("prueba-voz-v6")
(ep.dir / "artifacts" / "script.txt").write_text("# Prueba A/B\n\n" + T, encoding="utf-8")
d = ep.dir / "derivados"
d.mkdir(exist_ok=True)
segs = [s.strip() for s in T.split("\n\n") if s.strip()]


def juntar(parts: list[Path], dst: Path) -> None:
    cmd = ["ffmpeg", "-y", "-v", "error"]
    for p in parts:
        cmd += ["-i", str(p)]
    cmd += ["-filter_complex", "".join(f"[{i}:a]" for i in range(len(parts)))
            + f"concat=n={len(parts)}:v=0:a=1[out]", "-map", "[out]", str(dst)]
    subprocess.run(cmd, check=True)


# ANTES: tal como corría _edge hasta hoy (sin --rate, sin --pitch, sin respiración)
tmp = []
for i, s in enumerate(segs):
    mp3 = d / f"b-{i}.mp3"
    wav = d / f"b-{i}.wav"
    subprocess.run([str(config.EDGE_TTS_BIN), "--voice", "es-AR-TomasNeural", "--no-progress",
                    "--text", s, "--write-media", str(mp3)], check=True, timeout=300)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(mp3), "-ar", "22050", "-ac", "1",
                    "-c:a", "pcm_s16le", str(wav)], check=True)
    mp3.unlink()
    tmp.append(wav)
juntar(tmp, d / "voz-ANTES.wav")

# DESPUES: prosodia por rol + respiración de bloque
N.narrar(ep)
subprocess.run(["cp", str(ep.dir / "assets" / "audio" / "narration.wav"),
                str(d / "voz-DESPUES.wav")], check=True)
for w in tmp:
    w.unlink()


def dur(p: Path) -> float:
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                 "-of", "csv=p=0", str(p)], capture_output=True,
                                text=True).stdout)


print(f"ANTES   {dur(d/'voz-ANTES.wav'):6.2f}s   {d/'voz-ANTES.wav'}")
print(f"DESPUES {dur(d/'voz-DESPUES.wav'):6.2f}s   {d/'voz-DESPUES.wav'}")
