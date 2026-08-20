"""
Limpia la tabla `real_estate` (y sus auxiliares) hacia `real_estate_clean`
con tipos correctos, precio numérico, m² y geolocalización.

Hallazgos previos al diseño:
- `real_estate.price`: 1651/1651 con prefijo 'USD '. Miles con '.', sin decimales.
  Ej: 'USD 65.000' -> 65000.0
- `main_features`: multi-línea, sólo trae 'X m² tot.' (no 'cub.'). Pueden faltar
  'amb.', 'dorm.', 'baño', 'coch.'.
- `real_estate_features`: ~2 filas por listing, pero son DUPLICADOS EXACTOS:
  resolvemos con GROUP BY id y MAX(...).
- `real_estate_geolocation`: 1-a-1 con `real_estate` (no hay dups).

Uso:
    python clean_real_estate.py
    python clean_real_estate.py --db real_estate.db --table real_estate_clean
"""
import argparse
import re
import sqlite3
from typing import Optional


PRICE_RE = re.compile(r"USD\s+([\d\.]+)", re.IGNORECASE)
INT_TOKEN_RE = {
    "rooms":     re.compile(r"(\d+)\s*amb\.",  re.IGNORECASE),
    "bedrooms":  re.compile(r"(\d+)\s*dorm\.", re.IGNORECASE),
    "bathrooms": re.compile(r"(\d+)\s*baño",   re.IGNORECASE),
    "parking":   re.compile(r"(\d+)\s*coch\.", re.IGNORECASE),
}
M2_RE = re.compile(r"(\d+(?:[\.,]\d+)?)\s*m²\s*tot", re.IGNORECASE)


def parse_price_usd(raw: Optional[str]) -> Optional[float]:
    """'USD 65.000' -> 65000.0. Devuelve None si no matchea."""
    if not raw:
        return None
    m = PRICE_RE.search(raw)
    if not m:
        return None
    try:
        return float(m.group(1).replace(".", ""))
    except ValueError:
        return None


def parse_int(raw: Optional[str], key: str) -> Optional[int]:
    if not raw:
        return None
    m = INT_TOKEN_RE[key].search(raw)
    if not m:
        return None
    try:
        v = int(m.group(1))
        # filtro de outliers obvios (vimos '40 coch.')
        if key == "parking" and v > 20:
            return None
        return v
    except ValueError:
        return None


def parse_total_m2(raw: Optional[str]) -> Optional[float]:
    if not raw:
        return None
    m = M2_RE.search(raw)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


CREATE_SQL = """
CREATE TABLE {table} (
    id            TEXT PRIMARY KEY,
    price_raw     TEXT,
    currency      TEXT,
    price_usd     REAL,
    address       TEXT,
    rooms         INTEGER,
    bedrooms      INTEGER,
    bathrooms     INTEGER,
    parking       INTEGER,
    total_m2      REAL,
    price_per_m2  REAL,
    latitude      REAL,
    longitude     REAL,
    description   TEXT,
    link          TEXT
);
"""

# Trae features deduplicadas + geolocalización, todo en un solo SELECT.
SOURCE_SQL = """
SELECT
    r.id,
    r.price,
    r.address,
    r.main_features,
    r.description,
    r.link,
    f.bedrooms_db,
    f.bathrooms_db,
    f.square_meters_db,
    g.latitude,
    g.longitude
FROM real_estate r
LEFT JOIN (
    SELECT real_estate_id,
           MAX(bedrooms)       AS bedrooms_db,
           MAX(bathrooms)      AS bathrooms_db,
           MAX(square_meters)  AS square_meters_db
    FROM real_estate_features
    GROUP BY real_estate_id
) f ON f.real_estate_id = r.id
LEFT JOIN real_estate_geolocation g ON g.real_estate_id = r.id;
"""

INSERT_SQL_TPL = """
INSERT OR REPLACE INTO {table}
(id, price_raw, currency, price_usd, address, rooms, bedrooms, bathrooms,
 parking, total_m2, price_per_m2, latitude, longitude, description, link)
VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
"""


def build_clean(db_path: str, table: str) -> dict:
    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        cur.execute(f"DROP TABLE IF EXISTS {table}")
        cur.execute(CREATE_SQL.format(table=table))

        stats = {"total": 0, "price_ok": 0, "m2_ok": 0,
                 "geo_ok": 0, "bedrooms_ok": 0}
        rows = cur.execute(SOURCE_SQL).fetchall()
        out = []
        for (rid, price_raw, address, mf, desc, link,
             bed_db, bath_db, m2_db, lat, lon) in rows:
            price_usd = parse_price_usd(price_raw)
            currency = "USD" if price_usd is not None else None

            # Prioridad: tabla features (más confiable) -> parse de main_features
            bedrooms = bed_db if bed_db not in (None, 0) else parse_int(mf, "bedrooms")
            bathrooms = bath_db if bath_db not in (None, 0) else parse_int(mf, "bathrooms")
            rooms = parse_int(mf, "rooms")
            parking = parse_int(mf, "parking")

            m2 = m2_db if m2_db not in (None, 0) else parse_total_m2(mf)
            price_per_m2 = (price_usd / m2) if (price_usd and m2) else None

            out.append((
                rid, price_raw, currency, price_usd, address,
                rooms, bedrooms, bathrooms, parking,
                m2, price_per_m2, lat, lon, desc, link,
            ))

            stats["total"] += 1
            stats["price_ok"]    += price_usd is not None
            stats["m2_ok"]       += m2 is not None
            stats["geo_ok"]      += (lat is not None and lon is not None)
            stats["bedrooms_ok"] += bedrooms is not None

        cur.executemany(INSERT_SQL_TPL.format(table=table), out)

        # Índices útiles para el agente
        cur.executescript(f"""
        CREATE INDEX IF NOT EXISTS idx_{table}_price    ON {table}(price_usd);
        CREATE INDEX IF NOT EXISTS idx_{table}_m2       ON {table}(total_m2);
        CREATE INDEX IF NOT EXISTS idx_{table}_bedrooms ON {table}(bedrooms);
        CREATE INDEX IF NOT EXISTS idx_{table}_geo      ON {table}(latitude, longitude);
        """)
        con.commit()
        return stats
    finally:
        con.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="real_estate.db")
    parser.add_argument("--table", default="real_estate_clean")
    args = parser.parse_args()

    print(f"Limpiando {args.db} -> {args.table}")
    stats = build_clean(args.db, args.table)
    n = stats["total"] or 1
    print("\n=== ESTADÍSTICAS ===")
    for k, v in stats.items():
        pct = f"{v / n * 100:5.1f}%" if k != "total" else ""
        print(f"  {k:<14} {v:>6}  {pct}")
    print("\nListo. Probá:")
    print(f"  sqlite3 {args.db} 'SELECT bedrooms, ROUND(AVG(price_usd)) AS avg_usd, "
          f"COUNT(*) FROM {args.table} WHERE price_usd IS NOT NULL "
          f"GROUP BY bedrooms ORDER BY bedrooms;'")


if __name__ == "__main__":
    main()
