# Kasandra (Kasi): mi asistente personal con voz de mujer

Esta es mi copia personal de [OpenJarvis](https://github.com/open-jarvis/OpenJarvis)
(licencia Apache 2.0, ver `LICENSE`). Funciona igual que el original, con estos cambios:

- **Voz de Thalita** (`pt-BR-ThalitaMultilingualNeural`), voz neuronal de Microsoft vía edge-tts: gratis y muy
  natural, pero necesita internet. El preset `kasandra-inteligente` usa **Dalia**
  (`es-MX-DaliaNeural`): mexicana y unas 3 veces más rápida, ideal para hablar frase por frase. Sin internet usa Kokoro `ef_dora` (local).
  Si se usa un servicio en la nube, también cae en voces de mujer: OpenAI `nova`,
  ElevenLabs `Sarah`.
- **Escucha en español**: el reconocimiento de voz usa `language = "es"`.
- **Se llama Kasandra (Kasi de cariño)**, habla en femenino y responde en español de México.
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

## Reloj holográfico

Un núcleo holográfico flotante para el escritorio: una esfera de partículas que
florece con la voz de Kasandra, anillos orbitales en 3D (uno es el segundero),
rayos de luz y una onda expansiva cada vez que empieza a hablar.

```bash
uv sync --extra speech --extra voice --extra reloj
uv run kasandra-reloj          # en Windows abre sin ventana de consola
uv run kasandra-reloj --demo   # simula una voz para verlo en acción
```

- Arrástralo con el botón izquierdo; recuerda dónde lo dejaste.
- Clic derecho: "Siempre visible" o "Cerrar reloj".
- Para que aparezca al encender Windows, pon un acceso directo a
  `.venv\Scripts\kasandra-reloj.exe` en la carpeta `shell:startup`.
- **Escribirle sin micrófono:** usa la caja de texto bajo el núcleo (o empieza a
  teclear con el reloj seleccionado). Ella contesta con subtítulos y en voz alta,
  con las mismas herramientas y memoria del chat de voz.
- Para no enviar las ondas: variable de entorno `OPENJARVIS_VISUALIZER=0`.

## Velocidad (tarjetas de video chicas)

Con 4 GB de VRAM el modelo corre casi todo en el procesador. Ayuda mucho:

```powershell
setx OLLAMA_KEEP_ALIVE -1      # el modelo se queda cargado, sin recargas
setx JARVIS_NUM_CTX 8192       # contexto más corto: más capas caben en la GPU
```

Luego reinicia Ollama. El reloj además enciende el servidor al iniciar Windows.

Otros trucos que ya trae el preset `kasandra-inteligente`:

- `[agent] smart_tools = true`: en una charla normal Kasandra contesta en una sola
  llamada, sin cargar las herramientas. Solo las usa cuando pides buscar, calcular,
  leer un archivo o recordar algo. Pon `false` si quieres que siempre las tenga.
- El reloj solo le manda los últimos 6 mensajes de la conversación.
- En la charla normal la respuesta llega palabra por palabra: el reloj empieza a
  hablar en cuanto Kasandra termina la primera frase, y prepara la voz de la
  siguiente mientras dice la anterior.
- Cierra programas que usan la tarjeta de video (AutoCAD, Photoshop, LM Studio)
  mientras hablas con ella: así el modelo cabe más en la GPU.
- `qwen3.5:2b` responde 2-3 veces más rápido, pero es menos lista.

## Personalizar

Edita `~/.openjarvis/config.toml` (en Windows: `C:\Users\<tú>\.openjarvis\config.toml`):

| Quiero… | Cambia |
|---|---|
| Ver también el texto de sus respuestas en el reloj | `setx OPENJARVIS_RELOJ_SUBTITULOS 1` (por defecto solo se escuchan) |
| Voz más grave o más aguda | `voice_id = "es-MX-DaliaNeural;pitch=-8Hz"` (negativo = más grave) |
| Que hable más lento o más rápido | `[speech] voice_speed = 0.9` (o `1.1`) |
| Otra voz de mujer | `voice_id = "es-MX-DaliaNeural"`, `"es-US-PalomaNeural"`, `"es-CO-SalomeNeural"` |
| Voz sin internet | `tts_backend = "kokoro"` y `voice_id = "ef_dora"` |
| Voz más natural (de pago) | `tts_backend = "elevenlabs"` y `voice_id = "EXAVITQu4vr4xnSDxMaL"` |
| Cambiarle el nombre o la personalidad | `[agent] system_prompt = """Te llamas …"""` |
| Un modelo más listo | `[intelligence] default_model = "qwen3.5:9b"` |

## Mantenerla al día con el original

```bash
git remote add upstream https://github.com/open-jarvis/OpenJarvis.git
git fetch upstream
git merge upstream/main
```
