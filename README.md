# Debtector

**Guardarraíl de acoplamiento para CI/PR.** Debtector indexa un repositorio de código como un grafo en SQLite, calcula métricas de acoplamiento estructural (Ca, Ce, inestabilidad, ciclos, god modules) y bloquea el merge cuando las métricas empeoran.

ICP: dev/tech lead que usa agentes de código. Los agentes generan acoplamiento oculto a una velocidad que ningún humano alcanza; Debtector actúa como guardarraíl arquitectónico en el pipeline.

```bash
# Indexar, guardar baseline y comprobar regresiones (típico en CI)
debtector index ./src
debtector baseline save
debtector baseline status   # exit 1 si hay nuevos ciclos o el acoplamiento empeora
```

---

## Instalación

Debtector es una **herramienta de línea de comandos**, no una librería. Instálala globalmente para usarla en cualquier proyecto.

### Con uv (recomendado)

```bash
uv tool install /ruta/a/codeIndex
```

`uv tool install` no soporta modo editable. Para reflejar cambios en el código, reinstala con `--force` (es rápido):

```bash
uv tool install /ruta/a/codeIndex --force
```

### Con pip

```bash
# Instalación normal
pip install /ruta/a/codeIndex

# Editable — los cambios en el código se reflejan inmediatamente sin reinstalar
pip install -e /ruta/a/codeIndex
```

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

# 2. Ver métricas de acoplamiento
debtector metrics

# 3. Guardar baseline (commitear .debtector/baseline.json al repo)
debtector baseline save
git add .debtector/baseline.json && git commit -m "chore: save metrics baseline"

# 4. En CI: comprobar que las métricas no empeoran
debtector baseline status
```

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

### Métricas de acoplamiento

| Comando | Descripción |
|---------|-------------|
| `metrics` | Tabla de Ca, Ce, I por módulo + ciclos + god modules. `--sort fan_in\|fan_out\|instability`, `--limit N`, `--json` |
| `baseline save` | Guarda snapshot de métricas en `.debtector/baseline.json` |
| `baseline status` | Compara métricas actuales con el baseline. Exit 1 si hay regresiones (configurable) |
| `baseline status --reporter github` | Igual pero emite GitHub Actions Annotations (`::error/::warning`) |
| `baseline status --reporter gitlab` | Igual pero emite GitLab CI section markers |

### Configuración y hooks

| Comando | Descripción |
|---------|-------------|
| `install-hook` | Hook git pre-commit para auto-indexado |
| `install-skill` | Skills de Claude Code para uso del grafo en contexto IA |

### Flag global `--json`

Todos los comandos admiten `--json` para emitir JSON compacto en stdout:

```bash
debtector --json metrics
debtector --json baseline status
debtector --json search "AuthService"
```

---

## Métricas disponibles

### Por módulo (`debtector metrics`)

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

### Herencia (`debtector metrics --json`)

Profundidad de jerarquía de herencia y número de hijos directos por clase.

---

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

## Auto-indexado con git hook

```bash
debtector install-hook              # re-indexa en cada pre-commit
debtector install-hook --add-to-stage  # también hace git add del index.db
```

El hook es incremental (solo reparsea ficheros con hash distinto) y nunca bloquea un commit.

---

## Integración con Claude Code

```bash
debtector install-skill --global   # instala en ~/.claude/skills/
debtector install-skill            # instala en .claude/skills/ del proyecto
```

Con los skills instalados, Claude Code reconoce frases como *"analiza el impacto de cambiar AuthService"* o *"¿quién importa flask?"* y llama automáticamente al CLI con `--json`.

---

## Desarrollo

```bash
git clone https://github.com/aitormf/codeIndex
cd codeIndex
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
- [x] **`debtector metrics`** — output tabular con flags
- [x] **Baseline + ratcheting** — CI solo falla si empeoran las métricas
- [x] **Severidad configurable** — `debtector.toml` error/warning/info por tipo
- [x] **CI reporter** — GitHub Annotations + GitLab CI section markers
- [ ] Git history — churn por módulo, hotspot score, temporal coupling
- [ ] Graph diff — delta de métricas entre rama base y PR
- [ ] GitHub Action — comentario automático en PRs
- [ ] Más lenguajes — Go, Rust, Java

## Licencia

MIT
