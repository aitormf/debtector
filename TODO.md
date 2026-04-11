# TODO — CodeIndex

Tareas pendientes ordenadas por prioridad.

---

## Prioridad alta

- [x] **Tests unitarios** — parsers (Python, JS/TS), GraphStore, indexer (TDD obligatorio)
- [x] **Fixture JS/TS** — archivo de test equivalente a `tests/fixtures/sample.py` para el JS parser
- [x] **Verificar parsers** — ejecutar contra los fixtures existentes y confirmar conteo de nodos/aristas
- [x] **`.codeindexignore`** — soporte para ignorar rutas adicionales en la indexación (como `.gitignore`)

## Prioridad media

- [x] **Arista `COVERS`** — arista que une un test (Function/Method en archivo test) con el símbolo de producción que ejercita:
  - Parsers emiten CALLS no resueltos (`extra={"unresolved": true}`) desde archivos test hacia nombres externos
  - `GraphStore.update_covers_edges()` deriva aristas COVERS por resolución de nombres tras cada indexación
  - `GraphStore.get_uncovered_symbols()` devuelve símbolos de producción sin ninguna arista COVERS entrante
  - Nuevo subcomando `codeindex untested [path]` que lista símbolos sin cobertura
  - `is_test_file()` en `utils.py` como utilidad compartida (Python + JS/TS)

- [ ] **Schema migrations** — tabla `metadata` con `schema_version` + script de migración automática al abrir una DB antigua

- [ ] **`codeindex init` + filtros git** — comandar que configura el repo para compartir la BD entre desarrolladores:
  - Entry points `codeindex-clean` (SQLite → SQL dump) y `codeindex-smudge` (SQL dump → SQLite) para usar como filtros git
  - `codeindex init` escribe/parchea `.gitattributes`, configura `filter.codeindex` y `diff.codeindex` en git local, e instala los hooks `post-checkout`, `post-merge` y `post-rewrite`
  - **Depende de Schema migrations**: la BD compartida necesita migraciones automáticas para que un desarrollador con una versión anterior del esquema pueda hacer pull sin romper su índice
  - Pendiente de diseño: política de resolución de conflictos cuando dos ramas modifican el índice de forma incompatible

- [x] **Búsqueda semántica** — `sqlite-vec` + `fastembed` para embeddings sin cambiar de base de datos (ver `docs/decisions/001-semantic-search.md`)


- [ ] **Más lenguajes** — Go, Rust, Java (Tree-sitter los soporta; solo falta escribir el parser siguiendo `base.py`)

## Prioridad baja

- [ ] **Benchmark de ahorro de tokens** — comando `codeindex benchmark` que mide el ahorro estimado frente a leer los archivos directamente:
  - Para cada query de un conjunto estándar, calcular `tokens(archivos que habría que leer)` vs `tokens(respuesta del grafo)` usando `tiktoken`
  - `codeindex stats` ampliar para mostrar: tamaño total del source en tokens, promedio de tokens por query al grafo, ahorro estimado en porcentaje
  - Opcional: modo `--trace` para registrar en cada consulta CLI los tokens reales consumidos y acumularlos en `metadata`

- [ ] **Soporte monorepo** — permitir indexar múltiples paquetes/apps dentro de un mismo repositorio como unidades independientes pero consultables de forma conjunta:
  - Detección automática de raíces de paquete (`package.json`, `pyproject.toml`, `Cargo.toml`…)
  - Opción `--workspace` para indexar todo el monorepo y etiquetar cada nodo con su paquete de origen (`package` en `extra`)
  - Filtrado por paquete en los comandos existentes: `codeindex search "Service" --package api`
  - Aristas `CROSS_PACKAGE` para imports entre paquetes del mismo workspace

- [ ] **Exportación del grafo** — formatos DOT / JSON para visualización externa (D3.js, Graphviz)

- [ ] **MCP server** — exponer el GraphStore como herramienta MCP para que Claude Code consulte el índice sin invocar la CLI

- [ ] **Detección de API pública** — distinguir funciones/clases internas (`_prefijo`) de las exportadas; marcarlas en el nodo o con arista `EXPORTS`

- [ ] **Type hints como aristas** — `def f(x: User) -> Response` → aristas `USES_TYPE` hacia `User` y `Response`

---

## Hecho recientemente

- [x] FTS5 con BM25 y camelCase splitting para `codeindex search`
- [x] Aristas `CALLS` en parsers Python y JS/TS
- [x] Git pre-commit hook (`codeindex install-hook`)
- [x] Skills para Claude Code (`codeindex install-skill`) con triggers ampliados
