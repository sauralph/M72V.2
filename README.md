# M72V.2 13 - 7027 - Laboratorio interdisciplinario de inteligencia artificial en organizaciones - PARTE I

Para generar la presentación en PDF, ejecutá el siguiente comando:

```bash
npx @marp-team/marp-cli "Clase 9.md" -o "Clase 9.pdf" --theme ./style/uba.css --allow-local-files
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
