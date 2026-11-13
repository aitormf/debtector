# Debtector

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Python](https://img.shields.io/badge/Python-%E2%89%A53.12-blue)](https://www.python.org/)

[Read in English](README.md)

**Guardarraíl de acoplamiento para CI/PR.** Debtector indexa un repositorio de código como un grafo en SQLite, calcula métricas de acoplamiento estructural (Ca, Ce, inestabilidad, ciclos, god modules) y behavioral (churn, hotspots, temporal coupling, bus factor), y bloquea el merge cuando las métricas empeoran.

ICP: dev/tech lead que usa agentes de código. Los agentes generan acoplamiento oculto a una velocidad que ningún humano alcanza; Debtector actúa como guardarraíl arquitectónico en el pipeline.

```bash
# Informe completo: acoplamiento estructural + histórico git
debtector report

# Flujo típico en CI: indexar, guardar baseline, comprobar regresiones
debtector index ./src
debtector baseline save
debtector baseline status   # exit 1 si hay nuevos ciclos o el acoplamiento empeora
```

---

## Instalación

Debtector es una **herramienta de línea de comandos**, no una librería. Instálala globalmente para usarla en cualquier proyecto.

### Con uv (recomendado)

```bash
uv tool install debtector
uv tool upgrade debtector   # más adelante, para actualizar
```

### Con pip

```bash
pip install debtector
```

Para trabajar en el propio debtector, ver [Desarrollo](#desarrollo).

Verificar que está disponible globalmente:

```bash
debtector --help
which debtector
```

**Requisitos:** Python ≥ 3.12

---

## Inicio rápido

```bash
# 1. Indexar el proyecto (incremental: solo reparsea ficheros cambiados)
debtector index ./src

# 2. Ver acoplamiento estructural
debtector coupling

# 3. Ver métricas de historial git (hotspots, temporal coupling, bus factor)
debtector git-coupling

# 4. Informe completo (estructural + behavioral)
debtector report

# 5. Guardar baseline (commitear .debtector/baseline.json al repo)
debtector baseline save
git add .debtector/baseline.json && git commit -m "chore: save metrics baseline"

# 6. En CI: comprobar que las métricas no empeoran
debtector baseline status
```

> **Nota:** los comandos de análisis (`coupling`, `git-coupling`, `report`, `impact`, etc.) auto-indexan silenciosamente si hay ficheros modificados. No hace falta ejecutar `index` manualmente en el flujo habitual.

El índice vive en `.debtector/index.db`. El baseline en `.debtector/baseline.json`. Los logs en `.debtector/debtector.log`.

---

## Comandos

### Indexación

| Comando | Descripción |
|---------|-------------|
| `index <dir>` | Indexa el directorio (incremental por hash SHA-256) |
| `status` | Estadísticas del grafo (ficheros, nodos, aristas por tipo) |

### Análisis de código

| Comando | Descripción |
|---------|-------------|
| `search <query>` | Busca símbolos por nombre (FTS5 + BM25). `--kind Class\|Function\|Method` para filtrar |
| `summary <file>` | Todos los símbolos e imports de un fichero |
| `impact <files...>` | Qué ficheros y nodos se ven afectados por un cambio. `--depth N` |
| `imports <module>` | Qué ficheros importan un módulo o librería |
| `callers <qname>` | Qué funciones/métodos llaman a un símbolo concreto |
| `untested [path]` | Símbolos de producción sin ningún test que los cubra |

### Acoplamiento estructural

| Comando | Descripción |
|---------|-------------|
| `complexity` | Funciones y métodos ordenados por complejidad ciclomática. `--limit N`, `--min N`, `--json` |
| `coupling` | Tabla de Ca, Ce, I por módulo + ciclos + god modules. `--sort fan_in\|fan_out\|instability`, `--limit N`, `--json` |
| `baseline save` | Guarda snapshot de métricas en `.debtector/baseline.json` |
| `baseline status` | Compara métricas actuales con el baseline. Exit 1 si hay regresiones (configurable) |
| `baseline status --reporter github` | Igual pero emite GitHub Actions Annotations (`::error/::warning`) |
| `baseline status --reporter gitlab` | Igual pero emite GitLab CI section markers |

### Acoplamiento behavioral (git history)

| Comando | Descripción |
|---------|-------------|
| `hotspots` | Ranking de deuda técnica: churn × complejidad ciclomática (el acoplamiento se muestra como contexto). `--limit N`, `--since DATE` |
| `temporal-coupling` | Pares de archivos que cambian juntos sin import directo. `--min-shared N`, `--min-ratio F`, `--since DATE` |
| `bus-factor` | Riesgo de concentración de conocimiento: % de líneas por autor dominante. `--limit N` |
| `git-coupling` | Vista agregada de los tres anteriores. `--json` combina las tres secciones |
| `report` | Informe completo: acoplamiento estructural + behavioral. `--json` para consumo por IA/CI |

### Flag global `--json`

Todos los comandos admiten `--json` para emitir JSON compacto en stdout, apto para consumo directo por agentes de IA o pipelines:

```bash
debtector --json coupling
debtector --json report
debtector --json hotspots --limit 10
debtector --json baseline status
debtector --json search "AuthService"
```

---

## Métricas disponibles

### Acoplamiento estructural (`debtector coupling`)

| Métrica | Descripción |
|---------|-------------|
| **Ca (fan-in)** | Cuántos módulos dependen de éste. Peso 1.0 por `IMPORTS_FROM` y `USES_TYPE` |
| **Ce (fan-out)** | Cuántos módulos importa éste. Mismo esquema de pesos |
| **I (inestabilidad)** | `Ce / (Ca + Ce)`. 0 = muy estable, 1 = muy inestable |

Ejemplo de salida:

```
Módulo                      Ca      Ce       I    Flags
──────────────────────────────────────────────────────
src/graph_store.py        12.0     3.0   0.200
src/cli.py                 0.0    14.5   1.000  ⚠ inestable
src/models.py              9.5     0.0   0.000  ● god
──────────────────────────────────────────────────────
Total: 8 módulos

✓  Sin ciclos
● God modules (Ca > p90): src/models.py
```

### Ciclos

Detección de ciclos de importación con el algoritmo de Tarjan (SCCs). Considera aristas `IMPORTS_FROM` y `CALLS`.

### God modules

Módulos cuyo fan-in supera el percentil 90 del proyecto. Umbral relativo, no absoluto.

### Herencia (`debtector coupling --json`)

Profundidad de jerarquía de herencia y número de hijos directos por clase.

### Acoplamiento behavioral (`debtector git-coupling`)

| Métrica | Descripción |
|---------|-------------|
| **Hotspot score** | `churn × complejidad`, donde la complejidad es la suma de la complejidad ciclomática (McCabe) de las funciones del archivo. Los archivos más cambiados y más complejos son el mayor riesgo de deuda técnica |
| **Temporal coupling** | Pares de archivos que aparecen juntos en commits con frecuencia > umbral configurable, aunque no tengan `import` directo entre ellos |
| **Bus factor** | Mínimo de autores necesarios para cubrir el 80% de las líneas de un archivo. 1 = punto único de fallo |

Ejemplo de salida de `debtector hotspots`:

```
Módulo                            Churn  Complexity   Coupling     Score
───────────────────────────────────────────────────────────────────────
src/cli.py                           31         290      14.50   8990.00
src/graph_store.py                   47         138      15.00   6486.00
src/parser/python_parser.py          28         130       3.00   3640.00
───────────────────────────────────────────────────────────────────────
Total: 8 hotspots
```

---

## Identificar archivos afectados por una tarea

Cuando partes de una descripción en lenguaje natural ("añade rate limiting", "refactoriza el módulo de pagos") y necesitas saber qué archivos del repo están implicados, debtector ofrece datos deterministas que acotan la búsqueda. El flujo recomendado es:

1. **Buscar candidatos por keywords.** `debtector search` (FTS5 + BM25) devuelve los símbolos lexicalmente relacionados con la tarea, ordenados por relevancia:

   ```bash
   debtector --json search "rate limit"
   debtector --json search "AuthService" --kind Class
   ```

2. **Expandir el radio de impacto.** Una vez identificadas las semillas, `debtector impact` hace BFS sobre el grafo y devuelve todos los archivos y nodos que dependen de ellas directa o transitivamente:

   ```bash
   debtector --json impact src/auth/service.py
   debtector --json impact src/auth/service.py src/auth/middleware.py --depth 3
   ```

3. **Enriquecer con riesgo y cobertura.** Cruzar el conjunto resultante con métricas y tests aporta contexto arquitectónico para priorizar la lectura:

   ```bash
   debtector --json coupling             # qué módulos del impact set son god / inestables
   debtector --json untested src/auth/   # qué partes carecen de tests
   debtector --json hotspots             # qué módulos del impact set acumulan deuda
   ```

Cada paso emite JSON estable y se compone fácilmente desde scripts, IDEs, CI o agentes. El paso 1 es lexical: si la tarea usa sinónimos que no aparecen en el código (p. ej. "rate limiting" cuando el módulo se llama `throttle`), el consumidor decide qué candidatos son relevantes — debtector no inventa.

---

## Diff arquitectónico en pull requests

`debtector diff --base <ref> --format markdown` compara el proyecto con una ref de git y escribe un comentario de PR. La GitHub Action lo ejecuta en cada pull request, publica el resultado en un único comentario que se actualiza en cada push (ciclos nuevos, god modules nuevos, violaciones SDP nuevas, complejidad y hotspots que empeoran) y lo escribe siempre en el job summary.

### Cómo añadir la GitHub Action a tu repositorio

1. **Crea el workflow** `.github/workflows/debtector.yml`:

   ```yaml
   name: debtector

   # Usa pull_request, nunca pull_request_target: ejecutaría el código de la PR con un token de escritura.
   on:
     pull_request:
       branches: [main]

   # Una ejecución por PR: un push nuevo cancela la anterior y nunca compiten por el comentario.
   concurrency:
     group: debtector-${{ github.event.pull_request.number }}
     cancel-in-progress: true

   permissions:
     contents: read
     pull-requests: write   # para crear y actualizar el comentario

   jobs:
     diff:
       name: Architectural diff
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v6
           with:
             fetch-depth: 0   # el commit base y el historial tienen que estar disponibles
         - uses: aitormf/debtector@v0.30.0   # fija un tag de release
           # with:
           #   fail-on-error: false   # por defecto true: falla tras comentar si el diff tiene severidad `error`
           #   version: 0.30.0        # versión de debtector en PyPI; por defecto, la de la Action
           #   github-token: ${{ secrets.MI_TOKEN }}   # por defecto, el GITHUB_TOKEN del job
   ```

2. **Revisa los permisos del token.** El job pide `pull-requests: write`. Si tu organización o repositorio restringe los permisos de los workflows (*Settings → Actions → General → Workflow permissions*), permite también ese alcance allí; si no, la Action no podrá comentar.

3. **Fija la versión.** Usa un tag de release (`@vX.Y.Z`, ver [releases](https://github.com/aitormf/debtector/releases)) en vez de `@main`. La Action instala el debtector de ese mismo tag salvo que pases `version`.

4. **Decide qué bloquea la PR.** Por defecto el job falla, después de comentar, si el diff tiene algo con severidad `error`. Las severidades salen de `debtector.toml` (ver [Configuración de severidad](#configuración-de-severidad-debtectortoml)); por ejemplo, `cycles = "error"` bloquea los ciclos nuevos y `god_modules = "warning"` solo los informa. Con `fail-on-error: false` comenta sin fallar nunca.

5. **Opcional: ajusta qué se mide.**
   - `.debtectorignore` en la raíz del repo excluye rutas (código generado, `scripts/`, benchmarks, ejemplos de docs).
   - `test_paths` en `debtector.toml` si tus tests no siguen las convenciones habituales; los ficheros de test nunca cuentan como módulos.

6. **Opcional: hazlo obligatorio.** En la regla de protección de `main`, añade *Architectural diff* (el `name` del job) como status check requerido.

Notas:

- `fetch-depth: 0` importa. Con el clon superficial por defecto el historial tiene un commit: el diff funciona, pero los hotspots se omiten (el comentario lo dice).
- Las PRs desde forks tienen un token de solo lectura: no hay comentario, el diff está en el job summary y el job no falla por eso. No cambies a `pull_request_target` para evitarlo.
- La Action se usa en `ubuntu-latest`. Necesita `bash` y `python3` en el runner (los de GitHub tienen los dos) e instala `uv` y debtector por su cuenta.
- La Action complementa el [ratcheting con baseline](#ratcheting-en-ci): el diff compara la PR con su rama base; el ratchet compara las métricas actuales con el `baseline.json` commiteado.

## Ratcheting en CI

El flujo típico en CI es:

```yaml
# .github/workflows/ci.yml
- name: Check coupling ratchet
  run: |
    debtector index ./src
    debtector baseline status --reporter github
```

- Si no existe `baseline.json` → exit 0 (modo silencioso, no bloquea)
- Si existe y las métricas mejoran o son iguales → exit 0
- Si hay nuevos ciclos, nuevos god modules o la inestabilidad empeora → exit 1

### Configuración de severidad (`debtector.toml`)

```toml
[metrics.thresholds]
god_module_percentile = 90    # percentil para considerar god module
instability_threshold = 0.8   # I >= umbral → aviso en tabla

[metrics.severity]
cycles      = "error"    # bloquea CI
god_modules = "warning"  # avisa pero no bloquea
complexity  = "warning"  # "error" bloquea funciones nuevas o empeoradas con complejidad >= complexity_medium
instability = "warning"  # avisa pero no bloquea
inheritance = "info"     # solo informa
```

Severidades: `error` (exit 1) · `warning` (imprime, exit 0) · `info` (silencioso, exit 0).

---

## Lenguajes soportados

| Lenguaje | Extensiones |
|----------|------------|
| Python | `.py` |
| JavaScript | `.js`, `.jsx` |
| TypeScript | `.ts`, `.tsx` |

---

## Tipos de aristas del grafo

| Tipo | Descripción |
|------|-------------|
| `CONTAINS` | Fichero → clase/función |
| `HAS_METHOD` | Clase → método |
| `IMPORTS_FROM` | Fichero → módulo importado (peso 1.0 en Ca/Ce) |
| `INHERITS` | Clase → clase base |
| `CALLS` | Función/método → función/método llamado |
| `COVERS` | Función de test → símbolo de producción que ejercita |
| `USES_TYPE` | Función → tipo referenciado en type hints (peso 1.0 en Ca/Ce) |

---

## Directorio `.debtector/`

```
.debtector/
  index.db        # grafo SQLite (commiteable si se quiere compartir)
  baseline.json   # snapshot de métricas (committear al repo)
  debtector.log   # logs estructurados (ignorado por git)
  .gitignore      # generado automáticamente
```

El `.gitignore` de `.debtector/` está gestionado por Debtector: ignora todo excepto `baseline.json` y el propio `.gitignore`.

---

## Desarrollo

```bash
git clone https://github.com/aitormf/debtector
cd debtector
uv sync --dev

uv run pytest                     # tests
uv run ruff check .               # linter
uv run ruff format .              # formatter
uv run bandit -r src/             # seguridad

# Instalar hooks pre-commit (tres stages necesarios)
uv run pre-commit install
uv run pre-commit install --hook-type commit-msg
uv run pre-commit install --hook-type pre-push
```

---

## Logging

```bash
DEBTECTOR_LOG_JSON=false debtector index ./src   # coloreado (default)
DEBTECTOR_LOG_JSON=true  debtector index ./src   # JSON lines (prod/observabilidad)
```

Los logs siempre van a `.debtector/debtector.log`, nunca a stdout.

---

## Roadmap

- [x] FTS5 — búsqueda léxica/ranked
- [x] CALLS — aristas de llamadas intra-fichero
- [x] COVERS + `debtector untested` — cobertura de tests
- [x] `.debtectorignore` — rutas adicionales ignoradas
- [x] **Ca, Ce, inestabilidad** — métricas de acoplamiento por módulo
- [x] **Ciclos** — detección con algoritmo de Tarjan
- [x] **God modules** — outliers de fan-in (percentil 90)
- [x] **Herencia** — profundidad y número de hijos
- [x] **USES_TYPE** — acoplamiento por type hints (peso 1.0)
- [x] **`debtector coupling`** — output tabular con flags (antes `metrics`)
- [x] **Baseline + ratcheting** — CI solo falla si empeoran las métricas
- [x] **Severidad configurable** — `debtector.toml` error/warning/info por tipo
- [x] **CI reporter** — GitHub Annotations + GitLab CI section markers
- [x] **Auto-index silencioso** — los comandos de análisis indexan antes de ejecutarse
- [x] **Hotspots** — churn × acoplamiento estructural; ranking de deuda técnica real
- [x] **Temporal coupling** — archivos que co-cambian sin import directo
- [x] **Bus factor** — riesgo de concentración de conocimiento por archivo
- [x] **`debtector git-coupling` / `report`** — vistas agregadas behavioral y completa
- [x] **`debtector audit`** — vista para tech lead: health score, cohesión (LCOM4), testRisk, prioridad de ciclos ([schema](docs/audit-schema.md))
- [x] **Complejidad ciclomática por función** (`debtector complexity`) — hotspots churn × complejidad
- [ ] Complejidad cognitiva por función
- [x] Graph diff — delta de métricas entre rama base y PR (GitHub Action)
- [x] **Resolución de imports** — layout `src/` de Python y `from paquete import submódulo`, ESM `.js` → `.ts`, `require()` de CommonJS en cualquier sitio, reexports `export ... from`, barrels JS/TS como fachadas
- [x] **Tests fuera de las métricas de acoplamiento** — los ficheros de test (`tests/`, `test/`, `__tests__/`, `*.test.*`, `*.spec.*`, `test_paths`) no son módulos
- [x] **GitHub Action** — comentario automático en PRs, actualizado en cada push ([cómo añadirla](#cómo-añadir-la-github-action-a-tu-repositorio))
- [ ] Más lenguajes — Go, Rust, Java

## Licencia

AGPL-3.0 — ver [LICENSE](LICENSE).
