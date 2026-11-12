# Decisiones

Por qué el sistema es como es: decisiones de arquitectura, reglas de negocio y enfoques que se probaron y se descartaron. El código y los tests dicen **qué** hace; este directorio dice **por qué**.

**Antes de cambiar código,** busca las filas cuya columna *Affects* cubre las rutas que vas a tocar y lee esas decisiones. No las leas todas.

**Para contradecir una decisión aceptada,** no la cambies en silencio: escribe una nueva que la sustituya. Las decisiones aceptadas no se editan.

**Para añadir una,** usa la skill `record-decision`, o copia la plantilla con el siguiente número libre y añade aquí su fila. Comprueba con `check_decisions.py docs/decisions`.

| ID | Title | Type | Status | Affects |
|---|---|---|---|---|
| [D-0001](0001-semantic-search.md) | Búsqueda semántica: FTS5 + sqlite-vec + fastembed | architecture | obsolete | src/debtector/graph_store.py, src/debtector/indexer.py |
| [D-0002](0002-pivot-ci-coupling.md) | Pivote: de navegación para IA a análisis de acoplamiento para CI/PR | architecture | accepted | . |
| [D-0003](0003-audit-as-second-surface.md) | Audit como segunda superficie de presentación | architecture | accepted | src/debtector/cli.py, src/debtector/audit/, docs/audit-schema.md |
| [D-0004](0004-own-cyclomatic-complexity.md) | Complejidad ciclomática propia con tree-sitter, sin radon ni lizard | architecture | accepted | src/debtector/parser/ |
| [D-0005](0005-hotspot-churn-x-complexity.md) | El hotspot es churn × complejidad del fichero | rule | accepted | src/debtector/git_history.py, src/debtector/audit/health_score.py, docs/audit-schema.md |
| [D-0006](0006-function-complexity-scores.md) | Las funciones con complejidad alta puntúan en el health score | rule | accepted | src/debtector/cli.py, src/debtector/audit/, src/debtector/config.py, docs/audit-schema.md |
| [D-0007](0007-hotspot-severity-by-magnitude.md) | La severidad del hotspot depende de su magnitud respecto al corte | rule | accepted | src/debtector/audit/health_score.py, src/debtector/git_history.py, src/debtector/config.py, docs/audit-schema.md |
| [D-0008](0008-diff-reuses-baseline-rules.md) | debtector diff compara dos índices con las reglas de baseline status | rule | accepted | src/debtector/diff.py, src/debtector/cli.py, docs/diff-schema.md |
| [D-0009](0009-github-action-in-repo.md) | La GitHub Action vive en este repo y publica un comentario único | architecture | accepted | action.yml, .github/workflows/, scripts/ |
| [D-0010](0010-function-complexity-in-diff.md) | Qué funciones entran en el diff por complejidad | rule | accepted | src/debtector/diff.py, docs/diff-schema.md |
