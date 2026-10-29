"""
Agente SQL mínimo (toy-production).

Evolución del agente de Clase II:
- Config por entorno (DB, LLM URL, modelo, timeouts)
- Cliente HTTP OpenAI-compatible (Ollama /v1 o cualquier gateway)
- Misma lógica: schema → plan JSON → SQL ro → repair → summarize
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Optional

import requests

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
# Prefer OpenAI-compatible base; fall back to Ollama native /api/generate.
LLM_BASE_URL = os.environ.get(
    "LLM_BASE_URL",
    f"{OLLAMA_BASE_URL.rstrip('/')}/v1",
)
LLM_MODEL = os.environ.get("OLLAMA_LLM_MODEL") or os.environ.get(
    "LLM_MODEL", "llama3.1"
)
LLM_API_KEY = os.environ.get("LLM_API_KEY", "ollama")  # Ollama ignores key
# Heurística: puerto 11434 o la base derivada de OLLAMA_BASE_URL → hay Ollama.
IS_OLLAMA = ":11434" in LLM_BASE_URL or "LLM_BASE_URL" not in os.environ
LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "120"))

DEFAULT_DB = os.environ.get(
    "REAL_ESTATE_DB",
    str(Path(__file__).resolve().parent.parent / "data" / "real_estate.db"),
)

MAX_REPAIRS = 2
SAMPLE_ROWS = 2
ROW_LIMIT = 50

HIDDEN_TABLES = {
    "real_estate",
    "real_estate_features",
    "real_estate_geolocation",
    "sqlite_sequence",
}
CLEAN_TABLE = "real_estate_clean"


def schema_summary(db_path: str) -> str:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        all_tables = [
            r[0]
            for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]
        tables = [t for t in all_tables if t not in HIDDEN_TABLES]
        parts = []
        for t in tables:
            cols = con.execute(f"PRAGMA table_info('{t}')").fetchall()
            col_defs = ", ".join(f"{c[1]} {c[2]}" for c in cols)
            n = con.execute(f"SELECT COUNT(*) FROM '{t}'").fetchone()[0]
            sample = con.execute(f"SELECT * FROM '{t}' LIMIT {SAMPLE_ROWS}").fetchall()
            rows_preview = "\n".join(
                "    " + " | ".join(_short(str(v)) for v in row) for row in sample
            )
            parts.append(
                f"TABLE {t} ({n} filas)\n  cols: {col_defs}\n  sample:\n{rows_preview}"
            )
        return "\n\n".join(parts)
    finally:
        con.close()


def _short(s: str, n: int = 60) -> str:
    s = s.replace("\n", " ")
    return s if len(s) <= n else s[:n] + "…"


PLAN_SYSTEM = """You are a SQLite query generator for a real-estate analytics app.
You MUST reply with ONLY a single JSON object, no markdown, no prose, no refusal.
Shape: {"sql":"SELECT ...","chart":null}

Rules:
- Read-only SELECT/WITH only. Use ONLY tables/columns from SCHEMA.
- Sales: table real_estate_clean (price_usd, total_m2, bedrooms, ...).
- Rent: real_estate_rent_features (rent_price_in_usd, bedrooms, real_estate_id)
  join real_estate_rent ON real_estate_rent.id = real_estate_rent_features.real_estate_id.
- Prefer GROUP BY for averages. LIMIT 50 for row lists.
- chart is always null.
- Never apologize, never explain, never translate: only JSON."""

PLAN_EXAMPLE = (
    '{"sql":"SELECT bedrooms, AVG(rent_price_in_usd) AS avg_rent '
    'FROM real_estate_rent_features GROUP BY bedrooms ORDER BY bedrooms;",'
    '"chart":null}'
)


def plan_query(question: str, schema: str) -> dict:
    user = f"""SCHEMA:
{schema}

Example valid reply:
{PLAN_EXAMPLE}

Question: {question}

Return the JSON object now."""
    return _extract_json(
        _llm_generate(
            user,
            temperature=0.0,
            system=PLAN_SYSTEM,
            force_json=True,
        )
    )


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
    if ";" in s:
        return False
    if not (s.startswith("select") or s.startswith("with")):
        return False
    forbidden = (
        " insert ",
        " update ",
        " delete ",
        " drop ",
        " alter ",
        " attach ",
        " pragma ",
        " replace ",
    )
    return not any(k in f" {s} " for k in forbidden)


def repair_sql(question: str, schema: str, bad_sql: str, error: str) -> dict:
    user = f"""SCHEMA:
{schema}

Question: {question}

Previous SQL (failed):
{bad_sql}

SQLite error:
{error}

Return corrected JSON only: {{"sql":"SELECT ...","chart":null}}"""
    return _extract_json(
        _llm_generate(
            user,
            temperature=0.0,
            system=PLAN_SYSTEM,
            force_json=True,
        )
    )


def to_markdown_table(cols: list[str], rows: list[tuple], max_rows: int = 15) -> str:
    if not cols:
        return "_(sin columnas)_"
    head = "| " + " | ".join(cols) + " |"
    sep = "|" + "|".join("---" for _ in cols) + "|"
    body = "\n".join(
        "| " + " | ".join(_short(str(v), 40) for v in r) + " |"
        for r in rows[:max_rows]
    )
    return "\n".join([head, sep, body])


def summarize(question: str, sql: str, cols, rows) -> str:
    preview = to_markdown_table(cols, rows, max_rows=12)
    system = (
        "Sos un analista de datos inmobiliarios. "
        "Respondé en español, 2-4 frases, SOLO con los datos del RESULTADO. "
        "Si está vacío, decilo. No inventes números."
    )
    user = f"""PREGUNTA: {question}
SQL: {sql}
RESULTADO ({len(rows)} filas):
{preview}

RESPUESTA:"""
    return _llm_generate(user, temperature=0.2, system=system).strip()


def _llm_generate(
    prompt: str,
    temperature: float = 0.2,
    system: Optional[str] = None,
    force_json: bool = False,
) -> str:
    """OpenAI-compatible chat completions; fallback a Ollama /api/generate."""
    try:
        return _openai_compatible(prompt, temperature, system, force_json)
    except Exception:
        # Sin Ollama detrás (p. ej. DO serverless), mostrar el error real.
        if not IS_OLLAMA:
            raise
        return _ollama_native(prompt, temperature, system, force_json)


def _openai_compatible(
    prompt: str,
    temperature: float,
    system: Optional[str] = None,
    force_json: bool = False,
) -> str:
    url = f"{LLM_BASE_URL.rstrip('/')}/chat/completions"
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    body: dict[str, Any] = {
        "model": LLM_MODEL,
        "temperature": temperature,
        "messages": messages,
    }
    # Ollama accepts both; OpenAI uses response_format.
    if force_json:
        if IS_OLLAMA:
            body["format"] = "json"
        body["response_format"] = {"type": "json_object"}
    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    r = requests.post(url, headers=headers, json=body, timeout=LLM_TIMEOUT)
    if r.status_code in (400, 422) and "response_format" in body:
        # Algunos proveedores no soportan json_object: reintentar sin él
        # (_extract_json igual tolera texto alrededor del JSON).
        body.pop("response_format")
        r = requests.post(url, headers=headers, json=body, timeout=LLM_TIMEOUT)
    if not r.ok:
        raise RuntimeError(f"LLM HTTP {r.status_code}: {r.text[:300]}")
    data = r.json()
    return data["choices"][0]["message"]["content"]


def _ollama_native(
    prompt: str,
    temperature: float,
    system: Optional[str] = None,
    force_json: bool = False,
) -> str:
    full = f"{system}\n\n{prompt}" if system else prompt
    body: dict[str, Any] = {
        "model": LLM_MODEL,
        "prompt": full,
        "stream": False,
        "options": {"temperature": temperature},
    }
    if force_json:
        body["format"] = "json"
    r = requests.post(
        f"{OLLAMA_BASE_URL.rstrip('/')}/api/generate",
        json=body,
        timeout=LLM_TIMEOUT,
    )
    r.raise_for_status()
    return r.json()["response"]


def _extract_json(text: str) -> dict:
    """Parse a JSON object from model output; one retry-friendly error if missing."""
    cleaned = re.sub(r"```(?:json)?", "", text or "").replace("```", "").strip()
    # Prefer first balanced {...} block.
    start = cleaned.find("{")
    if start < 0:
        raise ValueError(f"No se encontró JSON en la respuesta del LLM:\n{text[:500]}")
    depth = 0
    end = -1
    for i, ch in enumerate(cleaned[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end < 0:
        raise ValueError(f"No se encontró JSON en la respuesta del LLM:\n{text[:500]}")
    obj = json.loads(cleaned[start:end])
    if not isinstance(obj, dict) or "sql" not in obj:
        raise ValueError(f"JSON del LLM sin campo sql:\n{obj!r}")
    return obj


def llm_health() -> dict[str, Any]:
    """Chequeo liviano para /health."""
    out: dict[str, Any] = {
        "llm_base_url": LLM_BASE_URL,
        "model": LLM_MODEL,
        "ok": False,
        "detail": "",
    }
    try:
        # Try OpenAI models list, then Ollama tags
        r = requests.get(
            f"{LLM_BASE_URL.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {LLM_API_KEY}"},
            timeout=3,
        )
        if r.ok:
            out["ok"] = True
            out["detail"] = "OpenAI-compatible endpoint reachable"
            return out
    except Exception:
        pass
    try:
        r = requests.get(f"{OLLAMA_BASE_URL.rstrip('/')}/api/tags", timeout=3)
        r.raise_for_status()
        models = [m.get("name", "") for m in r.json().get("models", [])]
        if any(LLM_MODEL in m for m in models):
            out["ok"] = True
            out["detail"] = f"Ollama OK · modelo {LLM_MODEL}"
        else:
            out["detail"] = f"Ollama OK pero falta pull de {LLM_MODEL}"
    except Exception as e:
        out["detail"] = str(e)
    return out


def agent_answer(db_path: str, question: str) -> dict:
    schema = schema_summary(db_path)
    last_err: Optional[Exception] = None
    plan: dict = {}
    for plan_try in range(2):
        try:
            plan = plan_query(question, schema)
            break
        except Exception as e:
            last_err = e
            if plan_try == 1:
                raise
    else:
        raise last_err or ValueError("No se pudo planificar la consulta")

    sql = ""
    cols: list[str] = []
    rows: list[tuple] = []

    for attempt in range(MAX_REPAIRS + 1):
        sql = plan.get("sql", "")
        try:
            cols, rows = run_sql(db_path, sql)
            break
        except Exception as e:
            if attempt == MAX_REPAIRS:
                raise
            plan = repair_sql(question, schema, sql, str(e))

    answer = summarize(question, sql, cols, rows)
    # JSON-serializable rows
    safe_rows = [[_jsonable(v) for v in row] for row in rows]
    return {
        "sql": sql,
        "cols": cols,
        "rows": safe_rows,
        "answer": answer,
        "model": LLM_MODEL,
    }


def _jsonable(v: Any):
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    return str(v)
