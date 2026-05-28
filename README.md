# M72V.2 13 - 7027 - Laboratorio interdisciplinario de inteligencia artificial en organizaciones - PARTE I

Para generar las presentaciones en PDF, ejecutá:

```bash
npx @marp-team/marp-cli "Clase 9.md"  -o "Clase 9.pdf"  --theme ./style/uba.css --allow-local-files
npx @marp-team/marp-cli "Clase 10.md" -o "Clase 10.pdf" --theme ./style/uba.css --allow-local-files
```

---

## RAG con Ollama - Sistema de Preguntas sobre PDFs

Sistema minimalista de Retrieval-Augmented Generation (RAG) que permite hacer preguntas sobre documentos PDF usando modelos locales con Ollama.

### Requisitos

- Python 3.10+
- Ollama instalado y corriendo

### Instalación

1. Crear entorno virtual e instalar dependencias:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install requests numpy pypdf
   ```

2. Descargar los modelos necesarios en Ollama:

   ```bash
   # Modelo de embeddings (obligatorio)
   ollama pull nomic-embed-text

   # Modelo LLM (elegir uno)
   ollama pull llama3.1      # Por defecto
   ollama pull deepseek-r1   # Alternativa con razonamiento
   ```

### Uso

**Comando básico:**

```bash
python rag_ollama_min.py --pdf documento.pdf --q "Tu pregunta aquí"
```

**Con múltiples PDFs:**

```bash
python rag_ollama_min.py --pdf tesis1.pdf tesis2.pdf --q "¿Cuál es el tema principal?"
```

**Cambiar modelo LLM:**

```bash
OLLAMA_LLM_MODEL=deepseek-r1 python rag_ollama_min.py --pdf documento.pdf --q "Tu pregunta"
```

### Opciones

| Argumento | Descripción |
|---|---|
| `--pdf` | Rutas a uno o más archivos PDF (requerido) |
| `--q` | Pregunta a realizar (requerido) |
| `--topk` | Cantidad de fragmentos de contexto a usar (default: 5) |

### Variables de entorno

| Variable | Default | Descripción |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | URL del servidor Ollama |
| `OLLAMA_LLM_MODEL` | `llama3.1` | Modelo para generar respuestas |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Modelo para embeddings |

### Ejemplo completo

```bash
source .venv/bin/activate
OLLAMA_LLM_MODEL=deepseek-r1 python rag_ollama_min.py \
  --pdf tesis1.pdf tesis2.pdf \
  --q "¿Cuáles son las principales conclusiones?" \
  --topk 5
```

### Cómo funciona

1. **Extracción**: Lee el texto de los PDFs.
2. **Chunking**: Divide el texto en fragmentos de ~1200 caracteres con overlap de 200.
3. **Embeddings**: Genera vectores semánticos de cada fragmento usando `nomic-embed-text`.
4. **Búsqueda**: Ante una pregunta, busca los fragmentos más similares (cosine similarity).
5. **Generación**: El LLM responde usando solo el contexto recuperado.

### Solución de problemas

- **Error 500 / EOF**: Reiniciar Ollama y volver a intentar.

  ```bash
  pkill ollama && ollama serve
  ```

- **"Ignoring wrong pointing object"**: Son warnings de `pypdf` sobre PDFs mal formados, se pueden ignorar.

---

## Agente SQL con Ollama - Consultas en lenguaje natural sobre SQLite

Agente mínimo que traduce preguntas en español a SQL, las ejecuta sobre `Clase 10/real_estate.db` (sólo lectura) y devuelve una **respuesta en lenguaje natural**, una **tabla** y un **gráfico** cuando aplica.

### Requisitos

- Python 3.9+
- Ollama instalado y corriendo

### Instalación

```bash
cd "Clase 10"
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

ollama pull deepseek-r1   # default del script. También sirve llama3.1
```

### Preparación de datos (recomendado, una sola vez)

La tabla `real_estate` original guarda precios como TEXT (`'USD 65.000'`) y reparte features en varias tablas con duplicados. El script `clean_real_estate.py` consolida todo en `real_estate_clean` con tipos numéricos correctos:

```bash
python clean_real_estate.py
```

Crea/refresca la tabla `real_estate_clean(id, price_raw, currency, price_usd,
address, rooms, bedrooms, bathrooms, parking, total_m2, price_per_m2,
latitude, longitude, description, link)` e índices sobre `price_usd`,
`total_m2`, `bedrooms` y `(latitude, longitude)`. El agente la prefiere
automáticamente para consultas de venta.

### Uso

```bash
python sql_agent_ollama.py \
  --db real_estate.db \
  --q "¿Cuál es el alquiler promedio en USD por cantidad de dormitorios?"
```

### Opciones

| Argumento | Descripción |
|---|---|
| `--db` | Ruta al archivo SQLite (default: `real_estate.db`) |
| `--q` | Pregunta en lenguaje natural (requerido) |
| `--chart-out` | Ruta para guardar el gráfico, si el agente decide dibujarlo (default: `chart.png`) |

### Variables de entorno

| Variable | Default | Descripción |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | URL del servidor Ollama |
| `OLLAMA_LLM_MODEL` | `deepseek-r1` | Modelo para planificar SQL y resumir resultados |

### Ejemplos de preguntas

```bash
python sql_agent_ollama.py --q "Mostrame los 10 alquileres más caros en USD"
python sql_agent_ollama.py --q "Distribución de propiedades en venta por cantidad de dormitorios"
python sql_agent_ollama.py --q "Precio promedio de venta en USD por barrio aproximado (los primeros 15)"
python sql_agent_ollama.py --q "¿Cuántas propiedades tienen geolocalización registrada?"
```

### Cómo funciona

1. **Introspección**: lee `sqlite_master` + `PRAGMA table_info` + 2 filas de muestra por tabla.
2. **Planificación**: el LLM devuelve un JSON `{"sql": ..., "chart": null | {...}}`.
3. **Ejecución segura**: conexión `?mode=ro` + whitelist de `SELECT`/`WITH` + cap de filas.
4. **Auto-reparación**: si SQLite falla, se reenvía el SQL fallido + el error al LLM (hasta 2 reintentos).
5. **Visualización**: `matplotlib` (`bar`/`line`/`hist`/`scatter`) sólo si el plan lo pidió.
6. **Resumen**: una segunda llamada al LLM produce la respuesta en español, anclada a la tabla.

### Bonus · GUI con Streamlit

Hay una interfaz web mínima sobre el mismo agente en `Clase 10/bonus/`:

```bash
cd "Clase 10"
pip install -r bonus/requirements.txt
streamlit run bonus/streamlit_app.py
```

Abre `http://localhost:8501` con: ejemplos de preguntas, textarea libre, tabla con descarga CSV, SQL ejecutado y gráfico en pestañas separadas. Más detalles en `Clase 10/bonus/README.md`.
