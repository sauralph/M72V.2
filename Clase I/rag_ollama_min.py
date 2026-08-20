import os
import re
import json
import requests
import numpy as np
from pypdf import PdfReader

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
LLM_MODEL = os.environ.get("OLLAMA_LLM_MODEL", "deepseek-r1")
EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text")

# Ajustes simples
CHUNK_SIZE_CHARS = 1200
CHUNK_OVERLAP_CHARS = 200
TOP_K = 5


def extract_text_from_pdf(path: str) -> str:
    reader = PdfReader(path)
    pages = []
    for i, page in enumerate(reader.pages):
        txt = page.extract_text() or ""
        pages.append(txt)
    text = "\n".join(pages)
    # Limpieza mínima
    text = re.sub(r"\s+\n", "\n", text)
    text = re.sub(r"\n\s+", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    if not text:
        return []
    chunks = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + chunk_size, n)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == n:
            break
        start = max(0, end - overlap)
    return chunks


def ollama_embed(text: str, retries: int = 5) -> np.ndarray:
    import time
    url = f"{OLLAMA_BASE_URL}/api/embed"
    payload = {"model": EMBED_MODEL, "input": text}
    for attempt in range(retries):
        try:
            r = requests.post(url, json=payload, timeout=120)
            r.raise_for_status()
            emb = r.json()["embeddings"][0]
            return np.array(emb, dtype=np.float32)
        except (requests.exceptions.HTTPError, requests.exceptions.ConnectionError) as e:
            wait_time = 2 ** attempt  # Exponential backoff: 1, 2, 4, 8, 16 seconds
            if attempt < retries - 1:
                print(f"Retry {attempt + 1}/{retries} after {wait_time}s...")
                time.sleep(wait_time)
                continue
            print(f"Error embedding text (len={len(text)}): {e}")
            if hasattr(r, 'text'):
                print(f"Response: {r.text[:500] if r.text else 'empty'}")
            raise


def cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    denom = (np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def build_index(pdf_paths: list[str]) -> dict:
    docs = []
    vectors = []

    for path in pdf_paths:
        text = extract_text_from_pdf(path)
        chunks = chunk_text(text, CHUNK_SIZE_CHARS, CHUNK_OVERLAP_CHARS)
        for j, ch in enumerate(chunks):
            vec = ollama_embed(ch)
            docs.append({"source": os.path.basename(path), "chunk_id": j, "text": ch})
            vectors.append(vec)

    if not vectors:
        raise ValueError("No se pudo indexar nada. Revisá que los PDFs tengan texto extraíble.")

    mat = np.vstack(vectors)  # shape: (N, D)
    # Normalizamos para cosine similarity rápida con dot
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    mat = mat / norms

    return {"docs": docs, "mat": mat}


def retrieve(index: dict, query: str, top_k: int) -> list[dict]:
    q = ollama_embed(query).astype(np.float32)
    q_norm = np.linalg.norm(q)
    if q_norm == 0:
        q_norm = 1.0
    q = q / q_norm

    scores = index["mat"] @ q  # dot con vectores normalizados == cosine
    top_idx = np.argsort(scores)[::-1][:top_k]

    results = []
    for i in top_idx:
        d = index["docs"][int(i)]
        results.append({
            "score": float(scores[int(i)]),
            "source": d["source"],
            "chunk_id": d["chunk_id"],
            "text": d["text"],
        })
    return results


def ollama_generate(prompt: str) -> str:
    url = f"{OLLAMA_BASE_URL}/api/generate"
    payload = {
        "model": LLM_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.2
        }
    }
    r = requests.post(url, json=payload, timeout=300)
    r.raise_for_status()
    return r.json()["response"]


def build_rag_prompt(question: str, contexts: list[dict]) -> str:
    ctx_lines = []
    for c in contexts:
        header = f"[Fuente: {c['source']} | chunk {c['chunk_id']} | score {c['score']:.3f}]"
        ctx_lines.append(header + "\n" + c["text"])
    ctx = "\n\n".join(ctx_lines)

    return f"""Sos un asistente. Respondé usando SOLO la información del CONTEXTO.
Si el contexto no alcanza, decí claramente "No lo sé con este material".

CONTEXTO:
{ctx}

PREGUNTA:
{question}

RESPUESTA (en español, concisa, con referencias a la fuente y chunk cuando aplique):
"""


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", nargs="+", required=True, help="Rutas a PDFs, ej: a.pdf b.pdf")
    parser.add_argument("--q", required=True, help="Pregunta")
    parser.add_argument("--topk", type=int, default=TOP_K)
    args = parser.parse_args()

    print("Building index...")
    index = build_index(args.pdf)
    print("Retrieving...")
    hits = retrieve(index, args.q, args.topk)
    print("Building prompt...")

    prompt = build_rag_prompt(args.q, hits)
    print("Generating answer...")
    answer = ollama_generate(prompt)

    print("\n=== TOP CONTEXTS ===")
    for h in hits:
        print(f"- {h['source']} chunk {h['chunk_id']} score {h['score']:.3f}")

    print("\n=== ANSWER ===")
    print(answer)


if __name__ == "__main__":
    main()
