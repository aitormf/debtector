---
id: D-0011
title: "La CLI es un paquete con un módulo por grupo de comandos"
type: architecture
status: accepted
date: 2026-11-13
affects: [src/debtector/cli/, tests/]
supersedes: null
superseded_by: null
issue: null
---

# D-0011: La CLI es un paquete con un módulo por grupo de comandos

## Contexto

`src/debtector/cli.py` llegó a 2226 líneas con siete responsabilidades (consulta del grafo, calidad, diff de PR, baseline, reporters de CI, acoplamiento, historial de git, informe combinado y argparse). Los tests importan los `cmd_*` y helpers de `debtector.cli` y parchean nombres como `debtector.cli.compute_hotspots` o `debtector.cli._auto_index`. Al partir el fichero, un `patch` solo funciona si apunta al módulo donde el código busca el nombre.

## Decisión

- La CLI es el paquete `debtector/cli/`, con un módulo por grupo de comandos (`graph`, `quality`, `pr_diff`, `baseline`, `coupling`, `git`, `report`), `common` para los helpers compartidos, `reporters` para las salidas de CI y `app` para argparse (`main`).
- `cli/__init__.py` solo expone `main` (el entry point `debtector.cli:main` no cambia). No reexporta los `cmd_*` ni los helpers.
- Los tests importan cada comando de su submódulo (`from debtector.cli.git import cmd_hotspots`) y parchean el nombre en el módulo que lo usa (`patch("debtector.cli.git.compute_hotspots")`).
- Un comando nuevo va en el módulo de su grupo; solo se crea un módulo nuevo si no encaja en ninguno.

## Alternativas descartadas

- Reexportar todo desde `cli/__init__.py` para no tocar los imports de los tests: `patch("debtector.cli.compute_hotspots")` seguiría resolviendo pero ya no tendría efecto, y los tests pasarían por motivos equivocados o fallarían de forma confusa.
- Un módulo por comando: 18 ficheros, muchos de 25 líneas, y los helpers de un grupo (p. ej. el diff) quedarían repartidos.
- Dejar `cli.py` como está: es el god module que debtector señala en otros repos.

## Cómo se hace cumplir

La estructura la dejan las tareas de `docs/changes/split-cli/`. `code-reviewer` señala un `cmd_*` nuevo fuera de su módulo o un `patch("debtector.cli.<nombre>")` que no apunta a un submódulo.
