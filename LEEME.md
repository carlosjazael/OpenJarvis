# Mi asistente personal (voz de mujer, en español)

Esta es mi copia personal de [OpenJarvis](https://github.com/open-jarvis/OpenJarvis)
(licencia Apache 2.0, ver `LICENSE`). Funciona igual que el original, con estos cambios:

- **Voz femenina en español por defecto**: Kokoro `ef_dora` (local, gratis, sin internet).
  Si se usa un servicio en la nube, también cae en voces de mujer: OpenAI `nova`,
  ElevenLabs `Sarah`.
- **Escucha en español**: el reconocimiento de voz usa `language = "es"`.
- **Habla en femenino y responde en español de México.**
- **Preset listo**: `voz-mujer-es` (archivo `configs/openjarvis/examples/voz-mujer-es.toml`).

Todo lo demás (agentes, herramientas, interfaz gráfica, resumen matutino) es del
proyecto original. Este no es un producto oficial de OpenJarvis.

## Instalación (Windows, macOS o Linux)

Necesitas [Python 3.11+](https://www.python.org/downloads/), [Git](https://git-scm.com/downloads),
[uv](https://docs.astral.sh/uv/getting-started/installation/) y [Ollama](https://ollama.com/download).

```bash
git clone https://github.com/carlosjazael/OpenJarvis.git
cd OpenJarvis
uv sync --extra speech --extra voice     # incluye Whisper (oído) y Kokoro (voz)
ollama pull qwen3.5:4b                   # el "cerebro" local
uv run jarvis init --preset voz-mujer-es --force
```

La primera vez que hable, Kokoro descarga su modelo (~330 MB) y Whisper el suyo.

## Uso

```bash
uv run jarvis chat --voice    # le hablas por el micrófono y te contesta en voz alta
uv run jarvis chat            # chat escrito
uv run jarvis gui             # interfaz gráfica en el navegador (requiere Node.js 22+)
```

## Personalizar

Edita `~/.openjarvis/config.toml` (en Windows: `C:\Users\<tú>\.openjarvis\config.toml`):

| Quiero… | Cambia |
|---|---|
| Que hable más lento o más rápido | `[speech] voice_speed = 0.9` (o `1.1`) |
| Otra voz de mujer (en inglés) | `voice_id = "af_heart"`, `"bf_emma"`… |
| Voz más natural (de pago) | `tts_backend = "elevenlabs"` y `voice_id = "EXAVITQu4vr4xnSDxMaL"` |
| Darle un nombre o personalidad | `[agent] system_prompt = """Te llamas …"""` |
| Un modelo más listo | `[intelligence] default_model = "qwen3.5:9b"` |

## Mantenerla al día con el original

```bash
git remote add upstream https://github.com/open-jarvis/OpenJarvis.git
git fetch upstream
git merge upstream/main
```
