# ADR-001: Búsqueda semántica — FTS5 + sqlite-vec + fastembed

**Estado:** Aceptado
**Fecha:** 2026-04-07
**Contexto:** Debtector v0.2

---

## Contexto

La búsqueda actual (`LIKE %query%` sobre `name`, `qualified_name` y `signature`) solo
encuentra símbolos cuando se conoce el nombre exacto. Para que una IA pueda navegar un
repositorio desconocido necesita encontrar código por concepto, no por nombre literal.

Identificamos tres capas de búsqueda con utilidad creciente:

| Capa | Ejemplo de query | Estado |
|------|-----------------|--------|
| **Estructural** — SQL exacto | `SELECT … WHERE name = 'AuthService'` | ✅ Implementado |
| **Léxico/ranked** — FTS5 | "autenticación" → encuentra `auth_handler`, `login_user` | 🔜 Fase 1 |
| **Semántico** — embeddings | "rate limiting logic" → código relevante sin keywords exactas | 🔜 Fase 2 |

---

## Decisión

### Fase 1 — FTS5 (SQLite Full Text Search)

Añadir una tabla virtual `nodes_fts` en el mismo `index.db` usando el módulo FTS5
integrado en SQLite. Indexa: `name`, `qualified_name`, `signature`, `docstring`.

**Ventajas:**
- Cero dependencias nuevas (FTS5 está en SQLite stdlib desde 3.9)
- Ranking BM25 nativo, mucho mejor que `LIKE`
- Mismo fichero DB, misma transacción al insertar nodos
- Mejora inmediata y reversible

**Nuevo subcomando / flag:** `debtector --json search "auth middleware"` usará FTS5
automáticamente cuando el término no contiene wildcards.

---

### Fase 2 — Embeddings: sqlite-vec + fastembed

**Almacenamiento de vectores: `sqlite-vec`**

Extensión SQLite de Simon Willison (activamente mantenida). Almacena los vectores
directamente en `index.db` como columna de tipo `float32[N]`. Soporta búsqueda
por coseno, L2 e inner product con índice IVF para ANN (Approximate Nearest Neighbor).

Alternativas descartadas:

| Opción | Motivo de descarte |
|--------|-------------------|
| numpy BLOBs en SQLite | No escala >50k nodos (todo en RAM), sin índice ANN |
| LanceDB | Fichero separado, rompe la filosofía de un solo DB |
| ChromaDB / Qdrant | Necesitan proceso servidor, contra el diseño embedded |
| FAISS | Sin integración SQL, índice separado, más complejo |

**Generación de embeddings: `fastembed`**

Librería de Qdrant que usa ONNX Runtime — no necesita PyTorch. Modelos descargados
automáticamente al primer uso y cacheados en `~/.cache/fastembed/`.

Modelo elegido: **`BAAI/bge-small-en-v1.5`**
- Tamaño: ~24MB
- Dimensiones: 384
- Optimizado para inglés técnico y código
- Benchmark MTEB: top de su clase en el rango <100MB

Alternativas descartadas:

| Opción | Motivo de descarte |
|--------|-------------------|
| `sentence-transformers` | Requiere PyTorch (~1.5GB), demasiado pesado para una CLI |
| APIs cloud (OpenAI, Cohere) | Requieren API key y red, rompen el flujo offline |
| Ollama | Requiere servidor externo instalado |

**Qué se embede por nodo:**
```python
f"{node.kind} {node.name} {node.signature or ''} {node.docstring or ''}"
```

Los embeddings se generan en `index time` (incrementales, solo ficheros cambiados)
y se almacenan en una tabla `node_embeddings(node_id, embedding)` con extensión
`sqlite-vec`.

**Nuevo subcomando:** `debtector --json semantic "authentication middleware"`

---

## Consecuencias

- `pyproject.toml`: añadir `sqlite-vec` y `fastembed` como optional deps en `[mcp]`
  o nuevo grupo `[search]` — la instalación base sigue ligera.
- Primera ejecución con semántica descarga el modelo (~24MB) y lo cachea.
- El `.debtector/.gitignore` ya ignora todo excepto `*.db` — los vectores van al
  mismo `index.db`, se commitean junto con el índice estructural si el equipo lo desea.
- `get_stats()` deberá reportar si hay embeddings disponibles.

---

## Estado de implementación

- [x] FTS5: tabla `nodes_fts`, actualización incremental, flag `--fts` o auto-detect
- [x] sqlite-vec: schema de tabla `node_embeddings`, integración en `store_file`/`remove_file`
- [x] fastembed: `src/debtector/embedder.py` — `embed_text/embed_texts`, lazy import
- [x] `debtector semantic "<query>"` subcomando
- [x] Tests de integración con fixtures conocidos (23 tests, embedder fake determinista)
