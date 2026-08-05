# Datos

- `real_estate.db` — copia de `Clase 10/real_estate.db` (default del agente y Docker).
- `toy_real_estate.db` — seed chico (8 ventas + 3 alquileres) para demos livianas:

  ```bash
  REAL_ESTATE_DB=./data/toy_real_estate.db uvicorn app.api:app --port 8000
  ```
