---
marp: true
theme: uba
paginate: true
size: 16:9
---

<!-- _class: lead -->

# De la pregunta al dato

## Un agente SQL mínimo con Ollama, en ~250 líneas de Python

**Mg. Ezequiel Nuske** · Ex Chief Data Officer
Laboratorio interdisciplinario de IA en organizaciones · 28 de Mayo de 2026

---

# Agenda

1. El problema: bases de datos que **solo hablan SQL**
2. La hipótesis: un agente que **traduce, ejecuta y explica**
3. Anatomía de un agente SQL mínimo en 6 pasos
4. Cada componente en código
5. Trade-offs, riesgos y próximos pasos

---

# El problema en una slide

<div class="columns">

<div>

**Qué falla**

- Los datos viven en bases relacionales
- El 90% de la organización **no escribe SQL**
- Hacer un dashboard por cada pregunta no escala
- Cada pregunta nueva = ticket al equipo de datos

</div>

<div>

**Qué intentamos antes**

- BI con filtros: rígido, no responde *lo que no anticipamos*
- “Pasale el CSV a Excel”: sin trazabilidad, sin frescura
- Chatear con un LLM: **no ve la base**, inventa columnas

</div>

</div>

**La pregunta**: ¿cómo le damos a una persona no técnica una **conversación con su base de datos**, sin perder rigor ni control?

> Necesitamos un puente entre **el lenguaje natural** y **el SQL real**.

---

# Un caso concreto

- Una base de propiedades en CABA: **1.651** avisos de venta, **631** de alquiler, geolocalización y features (`bedrooms`, `bathrooms`, `m²`).
- Pregunta típica: *“¿Cuál es el alquiler promedio en USD por cantidad de dormitorios?”*
- Escribir el SQL: requiere conocer joins, el nombre exacto de `rent_price_in_usd` y agrupar.
- Mirar a ojo: **imposible** con miles de filas.
- Dashboard fijo: cubre 3 preguntas, no la cuarta.

**Lo que queremos**: una respuesta en segundos, con la **consulta auditable**, la **tabla** y un **gráfico** cuando ayude.

---

<!-- _class: quote -->

# La hipótesis

> En lugar de enseñarle SQL a la gente,
> le damos al LLM el **schema** de la base
> y lo dejamos **planificar, ejecutar y explicar**.

Eso es un **agente NL2SQL**: *Natural Language to SQL*, con loop de ejecución.

---

# ¿Qué es un agente SQL, en una idea?

<div class="columns">

<div>

**Fase 1 · Contexto** *(barato, una vez)*

- Introspectar las tablas con `PRAGMA`
- Tomar **2 filas de muestra** por tabla
- Armar un *schema prompt* compacto
- Documentar **quirks** del dominio *(ej.: precios como TEXT)*

</div>

<div>

**Fase 2 · Loop** *(por pregunta)*

- El LLM produce **SQL + spec de gráfico**
- Ejecutamos en **modo read-only**
- Si SQLite se queja → **auto-reparación** con el error
- Renderizamos tabla + gráfico
- El LLM **resume** el resultado en español

</div>

</div>

> El modelo no “sabe” la base. Sabe **leer su schema** y **reaccionar a errores**.

---

# ¿Por qué hacerlo local con Ollama?

<div class="columns">

<div>

**Privacidad**

- El **schema y los datos** no salen de tu máquina
- Sin API keys, sin telemetría
- Apto para bases sensibles *(clientes, ventas, RRHH)*

**Costo**

- $0 por consulta
- Sin límites por tokens

</div>

<div>

**Control**

- Elegís el LLM y la temperatura
- Reproducible y versionable
- Funciona **offline**

**Aprendizaje**

- Cada pieza es visible y editable
- Ideal como base didáctica antes de subir a producción

</div>

</div>

---

# Anatomía de un agente SQL mínimo

```text
 pregunta ──► schema_summary ──► plan_query ──► run_sql ──► [ok?]
                                                     │
                                       no ◄──────────┴──────────► sí
                                       │                          │
                                  repair_sql                  make_chart
                                  (con error)                      │
                                       └─────► run_sql ──► summarize ──► respuesta
```

**Seis pasos**, cada uno con una responsabilidad clara:

1. **Introspectar** el schema (tablas, columnas, muestras)
2. **Planificar** SQL + (opcional) especificación de gráfico
3. **Ejecutar** en modo solo-lectura, con whitelist de sentencias
4. **Reparar** el SQL si SQLite devuelve error
5. **Visualizar** con matplotlib cuando el resultado es agregado
6. **Resumir** en lenguaje natural, anclado a la tabla

---

# Stack del proyecto

| Pieza | Tecnología | Por qué |
|---|---|---|
| Base de datos | `sqlite3` *(stdlib)* | Cero infra, modo `?mode=ro` para seguridad |
| LLM | **Ollama** *(HTTP)* | Local, gratis, intercambiable |
| Gráficos | `matplotlib` | Suficiente para bar / line / hist / scatter |
| Parsing de respuesta | `json` + regex | Tolerante a *fences* y texto suelto |
| Glue | `requests` + ~250 líneas | Sin frameworks, todo legible |

**Modelo por defecto**: `llama3.1`. Funciona también con `deepseek-r1` (razonamiento más explícito).

> Sin LangChain, sin agentes ReAct genéricos, sin vector store. **A propósito.**

---

<!-- _class: code-slide -->

# Paso 1 · Introspección del schema

**Le damos al LLM lo que un humano necesitaría**: tablas, tipos de columnas, conteo de filas y **2 filas de ejemplo**. Sin las muestras, el LLM inventa formatos.

```python
def schema_summary(db_path: str) -> str:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    tables = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()]
    parts = []
    for t in tables:
        cols = con.execute(f"PRAGMA table_info('{t}')").fetchall()
        n = con.execute(f"SELECT COUNT(*) FROM '{t}'").fetchone()[0]
        sample = con.execute(f"SELECT * FROM '{t}' LIMIT 2").fetchall()
        parts.append(f"TABLE {t} ({n} filas)\n  cols: "
                     + ", ".join(f"{c[1]} {c[2]}" for c in cols)
                     + "\n  sample:\n"
                     + "\n".join("    " + " | ".join(map(str, r)) for r in sample))
    return "\n\n".join(parts)
```

> Regla: si el schema es ambiguo, **el SQL también lo será**.

---

<!-- _class: code-slide -->

# Paso 2 · Planificación con contrato JSON

**No le pedimos prosa al LLM, le pedimos un JSON.** El contrato fuerza a decidir *en una sola llamada* qué consultar y si dibujar algo.

```python
PLAN_INSTRUCTIONS = """Sos un agente que traduce preguntas en español a SQL de SQLite.
Devolvé EXCLUSIVAMENTE un JSON con esta forma:
{
  "sql": "SELECT ... ;",
  "chart": null | {"kind":"bar"|"line"|"hist"|"scatter",
                   "x":"<col>","y":"<col>","title":"<str>"}
}
Reglas:
- Usá SOLO las tablas y columnas del SCHEMA.
- Los precios en `price` son TEXT ('USD 65.000', '$ 1.000.000').
  Para alquileres usá `real_estate_rent_features.rent_price_in_usd` (REAL).
- "chart" solo si la pregunta lo pide o el resultado es agregado/distribución.
- LIMIT 200 al devolver listas. JSON puro, sin comentarios."""
```

> Las **reglas del dominio** (precios como TEXT) viven en el prompt, no en el código.

---

<!-- _class: code-slide -->

# Paso 3 · Ejecución segura del SQL

**Confianza cero**: abrimos la base en `mode=ro`, exigimos `SELECT`/`WITH`, y rechazamos cualquier sentencia que huela a escritura. Un LLM *jailbreakeado* no puede romper la base.

```python
def run_sql(db_path, sql):
    if not _is_safe_select(sql):
        raise ValueError("Solo se permiten SELECT/CTE de lectura.")
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description] if cur.description else []
    return cols, cur.fetchmany(200)

def _is_safe_select(sql):
    s = sql.strip().rstrip(";").lower()
    if ";" in s: return False                       # una sola sentencia
    if not (s.startswith("select") or s.startswith("with")): return False
    forbidden = (" insert "," update "," delete "," drop ",
                 " alter "," attach "," pragma "," replace ")
    return not any(k in f" {s} " for k in forbidden)
```

> **Defensa en profundidad**: modo read-only + whitelist + cap de filas.

---

<!-- _class: code-slide -->

# Paso 4 · Auto-reparación con el error como contexto

**El LLM falla. SQLite es honesto.** Si la consulta explota, le pasamos el SQL fallido y el mensaje de error: en 1-2 reintentos suele converger.

```python
def repair_sql(question, schema, bad_sql, error):
    prompt = f"""{PLAN_INSTRUCTIONS}
SCHEMA:
{schema}
PREGUNTA: {question}
SQL_PREVIO_FALLIDO:
{bad_sql}
ERROR_SQLITE:
{error}
Corregí el SQL. Devolvé JSON con la misma forma."""
    return _extract_json(_ollama_generate(prompt, temperature=0.0))

# en el orquestador:
for attempt in range(MAX_REPAIRS + 1):
    try:
        cols, rows = run_sql(db_path, plan["sql"]); break
    except Exception as e:
        if attempt == MAX_REPAIRS: raise
        plan = repair_sql(question, schema, plan["sql"], str(e))
```

> Esto convierte al LLM en un agente: **reacciona**, no solo predice.

---

<!-- _class: code-slide -->

# Paso 5 · Visualización condicional

**No todo merece un gráfico.** Si el LLM no lo pidió, no dibujamos. Cuatro tipos cubren el 90% de las preguntas analíticas.

```python
def make_chart(cols, rows, spec, out_path):
    if not spec or not rows: return None
    ix = cols.index(spec["x"]); iy = cols.index(spec["y"]) if "y" in spec else 0
    xs = [r[ix] for r in rows]; ys = [r[iy] for r in rows]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    if spec["kind"] == "bar":      ax.bar([str(x) for x in xs], ys)
    elif spec["kind"] == "line":   ax.plot(xs, ys, marker="o")
    elif spec["kind"] == "hist":   ax.hist([x for x in xs if x is not None], bins=20)
    elif spec["kind"] == "scatter":ax.scatter(xs, ys, s=8, alpha=0.6)
    ax.set_title(spec.get("title", ""))
    plt.tight_layout(); plt.savefig(out_path, dpi=120); plt.close(fig)
    return out_path
```

> El gráfico es una **decisión del agente**, no un default que satura al usuario.

---

<!-- _class: code-slide -->

# Paso 6 · Resumen anclado al resultado

**Segunda llamada al LLM**: ya no inventa, *resume*. Le pasamos la pregunta, el SQL que corrió y la tabla. La temperatura baja para que no “adorne”.

```python
def summarize(question, sql, cols, rows):
    preview = to_markdown_table(cols, rows, max_rows=15)
    prompt = f"""Sos un analista. Respondé en español, en 2-4 frases,
basándote SOLO en los datos. Si el resultado está vacío, decilo. No inventes números.

PREGUNTA: {question}
SQL EJECUTADO: {sql}
RESULTADO ({len(rows)} filas):
{preview}

RESPUESTA:"""
    return _ollama_generate(prompt, temperature=0.2).strip()
```

> El resumen es **derivado** de la tabla. Si la tabla está mal, el resumen lo dirá.

---

# Arquitectura del flujo

```text
                    ┌──── Setup (una vez) ────┐
   real_estate.db ──► schema_summary  ──►  schema string en RAM
                                                          │
   pregunta ──► plan_query ──► {sql, chart}                │
                                  │                       │
                                  ▼                       │
                              run_sql ──── error ─► repair_sql ◄──┘
                                  │                       │
                                  │ ok                    │
                                  ▼                       │
                          ┌───────┴────────┐              │
                          ▼                ▼              │
                     make_chart       summarize ◄─────────┘
                          │                │
                          ▼                ▼
                      chart.png      respuesta NL
```

**Camino caliente** *(segundos)*: plan → ejecutar → resumir.
**Camino frío** *(arranque)*: introspectar schema + samples.

---

# El dato no miente: quirks del dominio

| Columna | Lo que aparenta | Lo que realmente es |
|---|---|---|
| `real_estate.price` | número | TEXT: `'USD 65.000'`, `'$ 1.000.000'`, `'Consultar'` |
| `real_estate_features` | 1 fila por aviso | **~2 filas** por aviso (duplicados) → `DISTINCT` o agregación |
| `real_estate_rent_features.rent_price_in_usd` | igual al anterior | REAL **ya parseado** → preferilo para análisis |
| Múltiples tablas `*_recoleta_*` | extensión del corpus principal | Dataset **separado**, sin features |

> **Estos quirks viven en el prompt**, no en el código. Cambiar de base = editar el prompt, no la lógica.

---

# Trade-offs · planificación

| Decisión | Si va **bajo** | Si va **alto** |
|---|---|---|
| `temperature` del plan | Repite errores idénticos | SQL creativo, pero alucina columnas |
| Filas de muestra en el schema | El LLM no entiende formatos | Prompt enorme, latencia ↑ |
| Reintentos de reparación | Falla por bugs triviales | Bucle largo, costo de tokens |
| Cap de filas (`LIMIT`) | Resúmenes inútiles si el corpus es grande | Resumen demasiado pesado para el LLM |

**Defaults usados**: `temperature=0.1`, `samples=2`, `repairs=2`, `LIMIT=200`.

> No hay valores universales. Hay que **medir** contra preguntas reales del negocio.

---

# Trade-offs · alcance del agente

<div class="columns">

<div>

**Lo que conviene delegar**

- Filtros, agrupaciones, joins explícitos
- Estadísticos básicos *(avg, count, distribuciones)*
- Listados ordenados con cap razonable

**Lo que no**

- KPIs críticos de negocio *(usar vistas curadas)*
- Definiciones ambiguas *(“cliente activo”)*
- Cualquier escritura, schema-change o ETL

</div>

<div>

**Por qué importa**

- Un agente NL2SQL **acelera la exploración**
- No reemplaza el **catálogo de métricas**
- La auditabilidad viene del SQL que devuelve, no del LLM

**Regla práctica**

> Si la respuesta va a un informe oficial, el SQL pasa por revisión humana **antes** de ser canonizado en una vista.

</div>

</div>

---

# Seguridad: defensa en profundidad

<div class="columns">

<div>

**Capa 1 · Conexión**

- `sqlite3.connect("file:...?mode=ro", uri=True)`
- Imposible escribir, incluso si el LLM lo intenta

**Capa 2 · Whitelist sintáctica**

- Solo `SELECT` o `WITH`
- Rechazo de `;` múltiples
- Blacklist de keywords *(INSERT, DROP, PRAGMA, ATTACH…)*

</div>

<div>

**Capa 3 · Cuotas**

- `fetchmany(ROW_LIMIT)` para acotar memoria
- Timeout en la llamada HTTP a Ollama

**Capa 4 · Trazabilidad**

- Loggear **siempre** el SQL ejecutado
- El usuario ve el SQL antes que la prosa
- Auditor reproduce con `sqlite3` directo

</div>

</div>

> En producción agregar: usuario por conexión, rate-limit y *row-level security* vía vistas.

---

# Cuándo NO alcanza este agente mínimo

<div class="columns">

<div>

**Escala**

- Bases con cientos de tablas → necesitás *schema retrieval* (RAG sobre el catálogo)
- Joins multi-tabla complejos → conviene exponer **vistas semánticas**
- Concurrencia → mover SQLite a Postgres + pool de conexiones

**Calidad**

- Ambigüedad de negocio *(“cliente activo”, “revenue”)*: capa de **métricas curadas**
- Resultados sensibles: *human-in-the-loop* antes de publicar

</div>

<div>

**Operación**

- Sin **evaluación** (golden set de preguntas → SQL esperado) no sabés si mejoraste
- Sin **observabilidad** *(latencia, % de repairs, error rate)* es imposible iterar
- Privacidad: si vas a la nube con datos reales, contrato + DPA + redacción de muestras

**Seguridad**

- *Prompt injection* desde campos de texto *(descripciones, comentarios)*
- Filtrado por permisos del usuario sobre tablas

</div>

</div>

---

# Próximos pasos naturales

<div class="columns">

<div>

**Planificación**

- *Few-shot* con preguntas resueltas del dominio
- **Vistas semánticas** (`v_alquileres_usd`) en lugar de joins crudos
- Validación del SQL con `EXPLAIN` antes de ejecutar
- *Dry-run* con `LIMIT 1` para chequear tipos

**Ejecución**

- Cache de `(pregunta → sql → resultado)`
- Streaming de filas para resultados grandes
- Quotas por usuario y por consulta

</div>

<div>

**Evaluación**

- Golden set: pregunta → SQL canónico → tolerancia de resultado
- Métricas: *execution accuracy*, *% repair*, latencia P50/P95
- A/B de prompts y modelos

**Producto**

- UI con tabla, gráfico y “Ver SQL” colapsable
- Compartir resultado como link reproducible
- Pin de preguntas frecuentes como **métricas oficiales**

</div>

</div>

---

<!-- _class: lead -->

# El número que importa

<div class="big-number">~250</div>

**líneas de Python, $0 de infra, 0 vendor lock-in.**
*Un agente honesto, auditable y modificable.*

Suficiente para abrir tu base al resto de la organización antes de comprar una herramienta de BI conversacional.

---

# Lecciones aprendidas

1. **El schema + 2 filas de muestra** ya hace el 80% del trabajo del LLM.
2. **El JSON como contrato** es más confiable que pedir prosa estructurada.
3. **Read-only + whitelist** convierte un riesgo en una herramienta.
4. **La auto-reparación con el error** es lo que vuelve “agente” a un LLM.
5. **Las dos llamadas separadas** *(plan vs. resumen)* aíslan errores: si la tabla está mal, la prosa lo dice.
6. **Sin evaluación, no sabés si mejoraste.** Un golden set de 20 preguntas es el primer paso *después* del MVP.

---

<!-- _class: lead -->

# Para la discusión

¿Qué base de datos tenés hoy donde **abrirla a preguntas en lenguaje natural** cambiaría cómo trabaja tu equipo?

¿Qué **quirks del dominio** *(formatos, joins, definiciones)* habría que poner en el prompt antes de soltar a un agente sobre ella?

---

<!-- _class: closing -->

# ¡Gracias!

**Ezequiel Nuske**

<div class="columns">

<div>

![w:170 h:170](style/qr-email.png)

**Email**
eonuske@mail.austral.edu.ar

</div>

<div>

![w:170 h:170](style/qr-linkedin.png)

**LinkedIn**
https://www.linkedin.com/in/ezequiel-nuske-15137862/

</div>

</div>

*Preguntas y respuestas*
