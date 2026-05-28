# Bonus · GUI Streamlit para el agente SQL

Interfaz web mínima sobre `sql_agent_ollama.py`. Conserva exactamente la misma lógica del agente CLI (mismo módulo, no se duplica nada): la GUI sólo orquesta inputs y render.

## Captura conceptual

```
┌─ Sidebar ──────────────────┐ ┌─ Main ─────────────────────────────┐
│ DB path                    │ │ 🏠 Agente SQL · Real Estate         │
│ Estado Ollama              │ │ [chips de preguntas de ejemplo]    │
│ Tablas expuestas/ocultas   │ │ ┌─────────────────────────────────┐│
└────────────────────────────┘ │ │ Tu pregunta...                  ││
                               │ └─────────────────────────────────┘│
                               │ [Preguntar]                        │
                               │ ──────                              │
                               │ Respuesta NL                       │
                               │ ⏱ 4.3s · 8 filas                   │
                               │ [📊 Datos][🛠 SQL][📈 Gráfico]      │
                               └────────────────────────────────────┘
```

## Instalación

Desde `Clase 10/`:

```bash
source .venv/bin/activate          # el mismo venv del agente CLI
pip install -r bonus/requirements.txt
```

## Uso

Desde `Clase 10/`:

```bash
streamlit run bonus/streamlit_app.py
```

Abre `http://localhost:8501` en el navegador.

## Variables de entorno

| Variable           | Default                  | Descripción                                  |
| ------------------ | ------------------------ | -------------------------------------------- |
| `OLLAMA_BASE_URL`  | `http://localhost:11434` | URL del servidor Ollama                      |
| `OLLAMA_LLM_MODEL` | `deepseek-r1`            | Modelo para planificar y resumir             |
| `REAL_ESTATE_DB`   | `../real_estate.db`      | Ruta a la SQLite (relativa a `bonus/`)       |

## Qué hace

1. **Setup auto**: al cargar, verifica que Ollama responda y construye `real_estate_clean` si no existe (vía `ensure_clean_table`).
2. **Schema curado**: la sidebar muestra qué tablas ve el agente y cuáles se ocultaron (las crudas, reemplazadas por la limpia).
3. **Ejemplos**: 6 preguntas de un click para arrancar.
4. **Pregunta libre**: textarea + botón.
5. **Resultado en 3 pestañas**:
   - **Datos**: DataFrame paginado + descarga CSV.
   - **SQL**: el SQL exacto que se ejecutó, copiable.
   - **Gráfico**: el PNG generado si el agente decidió dibujar.

## Diseño

- **No reimplementa nada**: importa `agent_answer`, `ensure_clean_table`, `HIDDEN_TABLES` y `CLEAN_TABLE` desde el módulo del agente.
- **`@st.cache_data` sobre `db_stats`**: evita golpear SQLite en cada rerun.
- **No reescribe el `chart.png`** dentro de `Clase 10/`: lo guarda en `bonus/chart.png`.
- **Falla con mensajes claros** si Ollama no responde o el modelo no está pulled.
