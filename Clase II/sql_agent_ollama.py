import os
import re
import json
import sqlite3
import argparse
from typing import Optional

import requests
import matplotlib

matplotlib.use("Agg")  # backend sin display
import matplotlib.pyplot as plt

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
LLM_MODEL = os.environ.get("OLLAMA_LLM_MODEL", "deepseek-r1")

MAX_REPAIRS = 2          # reintentos si el SQL falla
SAMPLE_ROWS = 2          # filas de ejemplo por tabla para el prompt
ROW_LIMIT = 200          # cota dura al resultado para no inflar el contexto

# Tablas crudas que el agente NO debería ver: están reemplazadas por
# `real_estate_clean` (precios numéricos, m² y geo en una sola tabla).
# Ocultarlas evita que el LLM caiga en CAST(REPLACE(price,...)).
HIDDEN_TABLES = {
    "real_estate",                 # reemplazada por real_estate_clean
    "real_estate_features",        # joineada dentro de real_estate_clean
    "real_estate_geolocation",     # joineada dentro de real_estate_clean
    "sqlite_sequence",             # interna de SQLite
}
CLEAN_TABLE = "real_estate_clean"


# ─────────────────────────────────────────────────────────────────────
# 1) Esquema: introspección + filas de muestra
# ─────────────────────────────────────────────────────────────────────
def schema_summary(db_path: str) -> str:
    """Devuelve un resumen compacto del schema + ejemplos por tabla.

    Filtra `HIDDEN_TABLES` para que el agente solo vea las tablas curadas.
    """
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    cur = con.cursor()
    all_tables = [r[0] for r in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()]
    tables = [t for t in all_tables if t not in HIDDEN_TABLES]

    parts = []
    for t in tables:
        cols = cur.execute(f"PRAGMA table_info('{t}')").fetchall()
        col_defs = ", ".join(f"{c[1]} {c[2]}" for c in cols)
        n = cur.execute(f"SELECT COUNT(*) FROM '{t}'").fetchone()[0]

        sample = cur.execute(
            f"SELECT * FROM '{t}' LIMIT {SAMPLE_ROWS}"
        ).fetchall()
        col_names = [c[1] for c in cols]
        rows_preview = "\n".join(
            "    " + " | ".join(_short(str(v)) for v in row) for row in sample
        )
        parts.append(
            f"TABLE {t} ({n} filas)\n  cols: {col_defs}\n  sample:\n{rows_preview}"
        )
    con.close()
    return "\n\n".join(parts)


def _short(s: str, n: int = 60) -> str:
    s = s.replace("\n", " ")
    return s if len(s) <= n else s[:n] + "…"


# ─────────────────────────────────────────────────────────────────────
# 2) Plan: el LLM produce SQL + (opcional) especificación de gráfico
# ─────────────────────────────────────────────────────────────────────
PLAN_INSTRUCTIONS = """Sos un agente que traduce preguntas en español a SQL de SQLite (read-only).
Devolvé EXCLUSIVAMENTE un JSON con esta forma:

{
  "sql": "SELECT ... ;",
  "chart": null
   | {"kind": "bar"|"line"|"hist"|"scatter", "x": "<col>", "y": "<col>", "title": "<str>"}
}

Reglas:
- Usá SOLO las tablas y columnas del SCHEMA (las tablas crudas ya no están expuestas).
- Para VENTA: usá `real_estate_clean`. Todos sus campos numéricos están parseados
  (`price_usd`, `total_m2`, `bedrooms`, `bathrooms`, `rooms`, `parking`,
  `price_per_m2`, `latitude`, `longitude`). Filtrá `WHERE price_usd IS NOT NULL`
  cuando hagas estadísticos o ordenes por precio.
- Para ALQUILER: usá `real_estate_rent_features.rent_price_in_usd` (REAL) y
  joinealo con `real_estate_rent` por `real_estate_id` si necesitás dirección/descripción.
- Limitá listas con `LIMIT 200`.
- `chart` SOLO si la pregunta pide visualización o si el resultado es claramente
  agregado/distribución. Para `hist` usá solo `x` (sin `y`).
- Salida: JSON puro, sin comentarios ni texto extra."""


def plan_query(question: str, schema: str) -> dict:
    prompt = f"""{PLAN_INSTRUCTIONS}

SCHEMA:
{schema}

PREGUNTA:
{question}

JSON:"""
    raw = _ollama_generate(prompt, temperature=0.1)
    return _extract_json(raw)


# ─────────────────────────────────────────────────────────────────────
# 3) Ejecución segura del SQL
# ─────────────────────────────────────────────────────────────────────
def run_sql(db_path: str, sql: str) -> tuple[list[str], list[tuple]]:
    if not _is_safe_select(sql):
        raise ValueError("Solo se permiten consultas SELECT/CTE de lectura.")
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cur = con.execute(sql)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchmany(ROW_LIMIT)
    finally:
        con.close()
    return cols, rows


def _is_safe_select(sql: str) -> bool:
    s = sql.strip().rstrip(";").lower()
    if ";" in s:                       # una sola sentencia
        return False
    if not (s.startswith("select") or s.startswith("with")):
        return False
    forbidden = (" insert ", " update ", " delete ", " drop ",
                 " alter ", " attach ", " pragma ", " replace ")
    return not any(k in f" {s} " for k in forbidden)


# ─────────────────────────────────────────────────────────────────────
# 4) Auto-reparación: si SQLite explota, le devolvemos el error al LLM
# ─────────────────────────────────────────────────────────────────────
def repair_sql(question: str, schema: str, bad_sql: str, error: str) -> dict:
    prompt = f"""{PLAN_INSTRUCTIONS}

SCHEMA:
{schema}

PREGUNTA:
{question}

SQL_PREVIO_FALLIDO:
{bad_sql}

ERROR_SQLITE:
{error}

Corregí el SQL. Devolvé JSON con la misma forma.
JSON:"""
    return _extract_json(_ollama_generate(prompt, temperature=0.0))


# ─────────────────────────────────────────────────────────────────────
# 5) Renderizado: tabla markdown + gráfico opcional
# ─────────────────────────────────────────────────────────────────────
def to_markdown_table(cols: list[str], rows: list[tuple], max_rows: int = 20) -> str:
    if not cols:
        return "_(sin columnas)_"
    head = "| " + " | ".join(cols) + " |"
    sep = "|" + "|".join("---" for _ in cols) + "|"
    body = "\n".join(
        "| " + " | ".join(_short(str(v), 40) for v in r) + " |"
        for r in rows[:max_rows]
    )
    extra = f"\n_({len(rows)} filas, mostrando {min(max_rows, len(rows))})_" \
        if len(rows) > max_rows else ""
    return "\n".join([head, sep, body]) + extra


def make_chart(cols, rows, spec: dict, out_path: str) -> Optional[str]:
    if not spec or not rows:
        return None
    kind = spec.get("kind")
    title = spec.get("title", "")
    try:
        ix = cols.index(spec["x"]) if spec.get("x") in cols else 0
        iy = cols.index(spec["y"]) if spec.get("y") in cols else (1 if len(cols) > 1 else 0)
        xs = [r[ix] for r in rows]
        ys = [r[iy] for r in rows]
        fig, ax = plt.subplots(figsize=(8, 4.5))
        if kind == "bar":
            ax.bar([str(x) for x in xs], ys)
            plt.xticks(rotation=45, ha="right")
        elif kind == "line":
            ax.plot(xs, ys, marker="o")
        elif kind == "hist":
            ax.hist([x for x in xs if x is not None], bins=20)
        elif kind == "scatter":
            ax.scatter(xs, ys, s=8, alpha=0.6)
        else:
            return None
        ax.set_title(title or kind)
        ax.set_xlabel(spec.get("x", ""))
        ax.set_ylabel(spec.get("y", "") if kind != "hist" else "frecuencia")
        plt.tight_layout()
        plt.savefig(out_path, dpi=120)
        plt.close(fig)
        return out_path
    except Exception as e:
        print(f"[chart] omitido: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────
# 6) Respuesta en lenguaje natural anclada al resultado
# ─────────────────────────────────────────────────────────────────────
def summarize(question: str, sql: str, cols, rows) -> str:
    preview = to_markdown_table(cols, rows, max_rows=15)
    prompt = f"""Sos un analista. Respondé en español, en 2-4 frases, basándote SOLO en los datos.
Si el resultado está vacío, decilo. No inventes números.

PREGUNTA:
{question}

SQL EJECUTADO:
{sql}

RESULTADO ({len(rows)} filas):
{preview}

RESPUESTA:"""
    return _ollama_generate(prompt, temperature=0.2).strip()


# ─────────────────────────────────────────────────────────────────────
# Helpers LLM
# ─────────────────────────────────────────────────────────────────────
def _ollama_generate(prompt: str, temperature: float = 0.2) -> str:
    try:
        r = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={"model": LLM_MODEL, "prompt": prompt, "stream": False,
                  "options": {"temperature": temperature}},
            timeout=300,
        )
    except requests.exceptions.ConnectionError as e:
        raise RuntimeError(
            f"No se pudo conectar a Ollama en {OLLAMA_BASE_URL}. "
            f"¿Está corriendo? (`ollama serve`)"
        ) from e
    if r.status_code == 404:
        raise RuntimeError(
            f"Ollama respondió 404 para el modelo '{LLM_MODEL}'. "
            f"Probablemente no esté descargado. Soluciones:\n"
            f"  1) ollama pull {LLM_MODEL}\n"
            f"  2) OLLAMA_LLM_MODEL=<otro_modelo> python sql_agent_ollama.py ...\n"
            f"Modelos disponibles: `ollama list`"
        )
    r.raise_for_status()
    return r.json()["response"]


def _extract_json(text: str) -> dict:
    """Tolerante a ```json fences``` y a texto antes/después."""
    text = re.sub(r"```(?:json)?", "", text).replace("```", "")
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError(f"No se encontró JSON en la respuesta del LLM:\n{text}")
    return json.loads(m.group(0))


# ─────────────────────────────────────────────────────────────────────
# 7) Orquestación
# ─────────────────────────────────────────────────────────────────────
def ensure_clean_table(db_path: str) -> None:
    """Garantiza que `real_estate_clean` exista. Si no, la construye on-the-fly."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        exists = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (CLEAN_TABLE,),
        ).fetchone() is not None
    finally:
        con.close()
    if exists:
        return
    print(f"[setup] '{CLEAN_TABLE}' no existe; construyéndola desde las tablas crudas...")
    try:
        from clean_real_estate import build_clean
    except ImportError as e:
        raise RuntimeError(
            f"Falta {CLEAN_TABLE} y no encuentro `clean_real_estate.py`. "
            f"Corré primero: python clean_real_estate.py --db {db_path}"
        ) from e
    stats = build_clean(db_path, CLEAN_TABLE)
    print(f"[setup] listo: {stats}")


def agent_answer(db_path: str, question: str, chart_path: str = "chart.png") -> dict:
    ensure_clean_table(db_path)
    schema = schema_summary(db_path)
    plan = plan_query(question, schema)

    for attempt in range(MAX_REPAIRS + 1):
        sql = plan.get("sql", "")
        try:
            cols, rows = run_sql(db_path, sql)
            break
        except Exception as e:
            if attempt == MAX_REPAIRS:
                raise
            print(f"[repair {attempt + 1}/{MAX_REPAIRS}] {e}")
            plan = repair_sql(question, schema, sql, str(e))

    chart = make_chart(cols, rows, plan.get("chart"), chart_path)
    answer = summarize(question, sql, cols, rows)
    return {"sql": sql, "cols": cols, "rows": rows, "chart": chart, "answer": answer}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="real_estate.db", help="Ruta a la SQLite")
    parser.add_argument("--q", required=True, help="Pregunta en lenguaje natural")
    parser.add_argument("--chart-out", default="chart.png")
    args = parser.parse_args()

    res = agent_answer(args.db, args.q, args.chart_out)

    print("\n=== SQL ===")
    print(res["sql"])
    print("\n=== TABLA ===")
    print(to_markdown_table(res["cols"], res["rows"]))
    if res["chart"]:
        print(f"\n=== GRÁFICO ===\nGuardado en: {res['chart']}")
    print("\n=== RESPUESTA ===")
    print(res["answer"])


if __name__ == "__main__":
    main()
