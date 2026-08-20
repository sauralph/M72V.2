"""
API HTTP mínima del agente SQL (toy-production).

Reemplaza la GUI Streamlit de Clase II/bonus por:
- FastAPI (contrato JSON estable)
- static/index.html (UI mínima sin framework)
- /health para orquestadores y load balancers
"""
from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.agent import DEFAULT_DB, HIDDEN_TABLES, agent_answer, llm_health

STATIC = Path(__file__).resolve().parent / "static"
DB_PATH = os.environ.get("REAL_ESTATE_DB", DEFAULT_DB)

app = FastAPI(
    title="Agente SQL · Toy Production",
    description="Versión mínima desplegable del bonus de Clase II",
    version="0.1.0",
)

EXAMPLES = [
    "¿Cuál es el precio promedio por cantidad de dormitorios?",
    "Top 5 propiedades más caras en USD con su dirección",
    "¿Cuál es el alquiler promedio en USD por dormitorios?",
    "¿Cuántas propiedades hay por barrio aproximado (primer token de address)?",
]


class AskRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=500)


class AskResponse(BaseModel):
    answer: str
    sql: str
    cols: list[str]
    rows: list[list]
    model: str
    elapsed_s: float


@app.get("/health")
def health():
    db_ok = Path(DB_PATH).exists()
    llm = llm_health()
    status = "ok" if db_ok and llm.get("ok") else "degraded"
    return {
        "status": status,
        "db_path": DB_PATH,
        "db_ok": db_ok,
        "llm": llm,
    }


@app.get("/meta")
def meta():
    if not Path(DB_PATH).exists():
        raise HTTPException(404, f"DB no encontrada: {DB_PATH}")
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        tables = [
            r[0]
            for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]
        stats = {}
        for t in tables:
            if t in HIDDEN_TABLES:
                continue
            stats[t] = con.execute(f"SELECT COUNT(*) FROM '{t}'").fetchone()[0]
    finally:
        con.close()
    return {"db_path": DB_PATH, "tables": stats, "examples": EXAMPLES}


@app.post("/ask", response_model=AskResponse)
def ask(body: AskRequest):
    if not Path(DB_PATH).exists():
        raise HTTPException(503, f"DB no encontrada: {DB_PATH}")
    t0 = time.time()
    try:
        res = agent_answer(DB_PATH, body.question.strip())
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}") from e
    return AskResponse(
        answer=res["answer"],
        sql=res["sql"],
        cols=res["cols"],
        rows=res["rows"],
        model=res["model"],
        elapsed_s=round(time.time() - t0, 2),
    )


@app.get("/")
def index():
    index_path = STATIC / "index.html"
    if not index_path.exists():
        raise HTTPException(404, "static/index.html missing")
    return FileResponse(index_path)


if STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
