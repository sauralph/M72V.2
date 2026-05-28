"""
GUI Streamlit del agente SQL.

Ejecutar desde `Clase 10/`:
    streamlit run bonus/streamlit_app.py

Variables de entorno opcionales:
    OLLAMA_BASE_URL   (default http://localhost:11434)
    OLLAMA_LLM_MODEL  (default deepseek-r1)
    REAL_ESTATE_DB    (default ../real_estate.db relativo a esta carpeta)
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time
from pathlib import Path

import pandas as pd
import streamlit as st

# Importar el agente que vive un directorio arriba.
HERE = Path(__file__).resolve().parent
PARENT = HERE.parent
sys.path.insert(0, str(PARENT))

from sql_agent_ollama import (  # noqa: E402
    CLEAN_TABLE,
    HIDDEN_TABLES,
    LLM_MODEL,
    OLLAMA_BASE_URL,
    agent_answer,
    ensure_clean_table,
)

DEFAULT_DB = Path(os.environ.get("REAL_ESTATE_DB", PARENT / "real_estate.db"))

EXAMPLES = [
    "¿Cuál es el precio promedio por cantidad de dormitorios?",
    "Top 10 propiedades más caras en USD con su dirección",
    "Distribución de precios por m² (histograma)",
    "Mostrame la ubicación geográfica de las propiedades de menos de 80.000 USD",
    "¿Cuál es el alquiler promedio en USD por cantidad de dormitorios?",
    "¿Qué barrios (primeras palabras de address) concentran más avisos? Top 15",
]


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def db_stats(db_path: str) -> dict:
    """Cuenta filas de las tablas visibles para el agente."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        tables = [
            r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]
        return {
            t: con.execute(f"SELECT COUNT(*) FROM '{t}'").fetchone()[0]
            for t in tables if t not in HIDDEN_TABLES
        }
    finally:
        con.close()


def ollama_ok() -> tuple[bool, str]:
    import requests
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=2)
        r.raise_for_status()
        models = [m["name"] for m in r.json().get("models", [])]
        if any(LLM_MODEL in m for m in models):
            return True, f"OK · modelo `{LLM_MODEL}` disponible"
        return False, (
            f"Ollama corre pero `{LLM_MODEL}` no está descargado. "
            f"Probá `ollama pull {LLM_MODEL}` o cambiá `OLLAMA_LLM_MODEL`."
        )
    except Exception as e:
        return False, f"No se pudo contactar Ollama en {OLLAMA_BASE_URL}: {e}"


# ─────────────────────────────────────────────────────────────────────
# UI
# ─────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Agente SQL · Real Estate",
    page_icon="🏠",
    layout="wide",
)

st.title("🏠 Agente SQL · Real Estate")
st.caption(
    "Preguntá en español. El agente traduce a SQL, ejecuta sobre la base limpia, "
    "te muestra la tabla y un gráfico si corresponde."
)

# ── Sidebar ──────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Configuración")

    db_path = st.text_input("DB path", value=str(DEFAULT_DB))
    if not Path(db_path).exists():
        st.error(f"No existe: {db_path}")
        st.stop()

    st.markdown("**Modelo**")
    st.code(f"{OLLAMA_BASE_URL}\n{LLM_MODEL}", language="text")
    ok, msg = ollama_ok()
    (st.success if ok else st.error)(msg)

    with st.spinner("Verificando tabla limpia..."):
        try:
            ensure_clean_table(db_path)
        except Exception as e:
            st.error(f"Fallo construyendo `{CLEAN_TABLE}`: {e}")
            st.stop()

    st.markdown("**Tablas expuestas al agente**")
    for t, n in db_stats(db_path).items():
        st.markdown(f"- `{t}` — {n:,} filas")

    st.markdown("**Tablas ocultas** _(crudas, reemplazadas por la limpia)_")
    st.markdown("\n".join(f"- `{t}`" for t in sorted(HIDDEN_TABLES)))


# ── Estado de la sesión ──────────────────────────────────────────────
if "question" not in st.session_state:
    st.session_state.question = ""
if "result" not in st.session_state:
    st.session_state.result = None

# ── Ejemplos como chips ──────────────────────────────────────────────
st.markdown("**Ejemplos** _(click para cargar)_")
cols = st.columns(3)
for i, ex in enumerate(EXAMPLES):
    if cols[i % 3].button(ex, key=f"ex_{i}", use_container_width=True):
        st.session_state.question = ex

# ── Input + botón ────────────────────────────────────────────────────
question = st.text_area(
    "Tu pregunta",
    value=st.session_state.question,
    height=80,
    placeholder="Ej: ¿Cuál es el precio promedio por m² en Recoleta?",
)
go = st.button("Preguntar", type="primary", disabled=not question.strip())

# ── Ejecución ────────────────────────────────────────────────────────
if go and ok:
    chart_path = str(HERE / "chart.png")
    t0 = time.time()
    with st.spinner("Planificando SQL, ejecutando y resumiendo..."):
        try:
            res = agent_answer(db_path, question.strip(), chart_path)
            res["elapsed"] = time.time() - t0
            st.session_state.result = res
            st.session_state.question = question
        except Exception as e:
            st.error(f"❌ {type(e).__name__}: {e}")
            st.session_state.result = None
elif go and not ok:
    st.warning("Resolvé primero el problema con Ollama (ver sidebar).")

# ── Render del resultado ─────────────────────────────────────────────
res = st.session_state.result
if res:
    st.divider()
    st.subheader("Respuesta")
    st.write(res["answer"])
    st.caption(f"⏱ {res.get('elapsed', 0):.1f}s · {len(res['rows'])} filas")

    tab_table, tab_sql, tab_chart = st.tabs(["📊 Datos", "🛠 SQL", "📈 Gráfico"])

    with tab_table:
        if res["rows"]:
            df = pd.DataFrame(res["rows"], columns=res["cols"])
            st.dataframe(df, use_container_width=True, height=420)
            st.download_button(
                "⬇ Descargar CSV",
                df.to_csv(index=False).encode("utf-8"),
                file_name="resultado.csv",
                mime="text/csv",
            )
        else:
            st.info("La consulta no devolvió filas.")

    with tab_sql:
        st.code(res["sql"], language="sql")

    with tab_chart:
        if res["chart"] and Path(res["chart"]).exists():
            st.image(res["chart"], use_container_width=True)
        else:
            st.info(
                "Para esta pregunta el agente decidió que un gráfico no aportaba. "
                "Pedile explícitamente un histograma / distribución / mapa para forzarlo."
            )
else:
    st.info("Cargá una pregunta de los ejemplos o escribí la tuya y apretá **Preguntar**.")
