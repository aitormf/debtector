---
status: open
issue: null
---

# Partir `cli.py` en un paquete con un módulo por responsabilidad

**Problema:** `src/debtector/cli.py` tiene 2226 líneas y mezcla siete responsabilidades: los helpers compartidos (store, índice, rutas de tests), los comandos de consulta del grafo, la calidad (complejidad, untested, audit), el diff de PR, el baseline y el ratcheting, los reporters de CI (anotaciones de GitHub, informe de GitLab), las métricas de acoplamiento, el historial de git, el informe combinado y el cableado de argparse. Cada cambio en un comando obliga a navegar el fichero entero y las PRs de agentes tocan siempre el mismo fichero. Es justo el god module que debtector detecta en otros repos.

**Plazo máximo:** un día. Es un refactor puro: se mueve código tal cual, sin cambiar comportamiento, salida ni flags.

**Fuera de alcance:**
- Cambiar el comportamiento, la salida o los argumentos de ningún comando.
- Renombrar helpers (p. ej. quitar el `_` de `_get_store`) o refactorizar su lógica.
- Cambiar de argparse a otra librería (typer, click).
- Partir `graph_store.py`, `python_parser.py` o `js_parser.py`.
- Cambiar el entry point `debtector = "debtector.cli:main"` de `pyproject.toml`.

## Mapa de ejemplos

Es un refactor: en vez de reglas, pasos. Cada paso deja el proyecto en verde y se comprueba con `uv run pytest -q && uv run ruff check .`. La forma del paquete está en D-0011.

```
S1: cli.py pasa a ser el paquete debtector/cli/ y los helpers compartidos van a cli/common.py
    (_INDEX_ROOT_KEY, _debtector_dir, _auto_index, _get_store, _open_store, _test_dirs,
    _test_prefixes, _index_root, _json_out, _configured_god_modules, _configured_sdp_violations,
    _sdp_dict, _blocks, _warns, _print_section). El resto sigue en cli/__init__.py.
S2: comandos del grafo → cli/graph.py (index, search, summary, impact, imports, status, callers).
S3: calidad → cli/quality.py (complexity, untested, audit y sus helpers).
S4: reporters de CI → cli/reporters.py (_emit_github_annotations, _emit_gitlab_report,
    _annotation_level, _safe_annotation_path, _sdp_text).
S5: baseline → cli/baseline.py (cmd_baseline, _baseline_save, _baseline_status, _baseline_path,
    _BASELINE_FILE).
S6: diff de PR → cli/pr_diff.py (cmd_diff, _DIFF_SECTIONS, _diff_item, _git_out,
    _current_index_root, _refresh_index, _index_base_ref).
S7: acoplamiento → cli/coupling.py (cmd_coupling y su alias cmd_metrics).
S8: historial de git → cli/git.py (hotspots, temporal-coupling, bus-factor, git-coupling).
S9: informe combinado → cli/report.py (cmd_report).
S10: argparse → cli/app.py (main); cli/__init__.py queda solo con `from .app import main`.
     CLAUDE.md y las filas Affects de docs/decisions/README.md apuntan a las rutas nuevas.

Question: ¿qué exporta cli/__init__.py y dónde importan y parchean los tests? → D-0011
  (recomendado: solo `main`; los tests importan del submódulo y parchean donde se busca el nombre)
```

## Supuestos

- Los nombres de los helpers no cambian (`_get_store` sigue con `_`), aunque se importen entre módulos del paquete. Renombrarlos es otro cambio.
- El paquete `cli/pr_diff.py` se llama así, no `diff.py`, para no confundirlo con `debtector.diff`.
- Cada paso mueve el código tal cual. Los tests de los comandos que se mueven cambian solo la ruta del import y de los `patch(...)`; ninguna aserción cambia.
- Los diffs de mover código superan las 200 líneas de D-0044 al contar añadidas + borradas (S3 mueve ~330 líneas). Son movimientos literales: se revisan con `git diff -M --color-moved=zebra`, y el tamaño es una señal, no un bloqueo (D-0037). Partirlos más (un comando por PR) no hace la revisión más fácil.
- Las tareas van en cadena (cada una toca `cli/__init__.py`), para no tener conflictos entre PRs.

## Tareas

Un fichero por tarea en `tasks/`, cada una con su rama y su PR. Cuáles están listas: el board de `task-done` (`scripts/board.py`). No se listan aquí: los ficheros de tarea son la única fuente.
