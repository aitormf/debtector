---
status: done
issue: null
---

# Diff de arquitectura por PR: `debtector diff` y la Action

**Problema:** hoy debtector solo compara contra un `baseline.json` commiteado (`baseline status`). Esa comparación tiene tres límites:
- Necesita que alguien guarde y commitee el baseline. Si está viejo, una PR hereda las regresiones de otras.
- No incluye la complejidad de las funciones ni los hotspots.
- Su salida son anotaciones o texto en el log de CI, no algo que lea quien revisa la PR.

Quien revisa una PR, persona o agente, quiere ver qué empeora *esta* PR respecto a su rama base: ciclos nuevos, god modules nuevos, funciones que se vuelven complejas o ficheros que pasan a ser hotspot. Es la pieza más diferencial del roadmap (fase 4 de `TODO.md`).

**Plazo máximo:** 2-3 días.

**Fuera de alcance:**
- Integración con GitLab (merge requests).
- Salida SARIF y Code Scanning.
- Publicar la Action en el GitHub Marketplace. Se usa como `aitormf/debtector@vX`.
- Cambiar `baseline status`: sigue como está y convive con `diff`.

## Mapa de ejemplos

Rule R1: `debtector diff <db_base> <db_pr>` compara dos índices y lista los ciclos, god modules y violaciones SDP nuevos y resueltos, y las regresiones de inestabilidad. Usa las mismas reglas que `baseline status`. → D-0008
  E1: el ciclo `a.py → b.py` está en el índice de la PR y no en el de la base → aparece en `new_cycles`.
  E2: un ciclo de la base que ya no está en la PR → aparece en `resolved_cycles`, no en `new_cycles`.
  E3: el mismo ciclo, con los módulos en otro orden (`b.py → a.py`) → no es nuevo.
  E4: módulo que solo existe en la PR, con inestabilidad 1.0 → no es una regresión de inestabilidad.
  E5: inestabilidad 0.40 → 0.45 (justo la tolerancia de 0.05) → no es regresión; 0.40 → 0.46 → sí.
  E6: god module nuevo en la PR → `new_god_modules`; uno que deja de serlo → `resolved_god_modules`.
  E7: dos índices iguales → diff vacío, exit 0 y el texto `No architectural changes`.

Rule R2: las entradas se validan y el código de salida sigue a las severidades de `debtector.toml`, como en `baseline status`. → D-0008
  E8: los dos índices tienen distinto `parser_version` → exit 2 y un mensaje que pide reindexar.
  E9: una ruta que no existe o que no es un índice de debtector → exit 2 con la ruta en el mensaje.
  E10: un ciclo nuevo con `cycles = "error"` → exit 1; con `"warning"` → se muestra y exit 0.

Rule R3: con `--base <ref>`, debtector indexa la ref en un worktree temporal y la compara con el índice actual del proyecto. El worktree se borra siempre, también si falla.
  E11: `debtector diff --base main` en un repo donde la rama actual añade un ciclo → aparece en `new_cycles` y no queda ningún worktree (`git worktree list`).
  E12: `--base no-existe` → exit 2 con un mensaje que nombra la ref.
  E13: `--base` junto con dos rutas de índice → error de uso (exit 2).

Rule R4: una función entra en el diff si en la PR tiene complejidad ≥ `complexity_medium` y es nueva o su complejidad ha subido. Entra como mejora si baja de `complexity_medium` o desaparece estando por encima. La identidad es el `qualified_name`. → D-0010
  E14: función nueva con complejidad 21 → `worsened_functions`, `before: null`, `after: 21`, `severity: medium`.
  E15: función que pasa de 18 a 22 → `worsened_functions`.
  E16: función que pasa de 25 a 28 → `worsened_functions` (ya era `medium` pero empeora).
  E17: función que pasa de 10 a 20 → no aparece (sigue por debajo del umbral).
  E18: función que pasa de 32 a 15 → `improved_functions`.
  E19: función de un fichero de tests con complejidad 40 → no aparece.

Rule R5: un fichero entra en el diff de hotspots si en la PR es un hotspot accionable y en la base no lo era, o si su severidad sube de `medium` a `high`. El churn es el del repo de la PR en los dos lados; solo cambia la complejidad.
  E20: fichero que en la base está por debajo del corte y en la PR lo supera → `new_hotspots`.
  E21: fichero accionable `medium` en la base y `high` en la PR → `worsened_hotspots`.
  E22: clon superficial (`--depth 1`) → la sección de hotspots sale como `skipped` con el motivo y el resto del diff funciona.
  Question: ¿el churn de cada lado debería salir de su propio historial? → No: entre la base y la PR solo difieren los commits de la PR, y con el mismo churn el cambio refleja solo lo que la PR hace con la complejidad. Además `diff <db> <db>` funciona sin dos checkouts. (Recomendado: churn del repo de la PR en los dos lados).

Rule R6: `--format markdown` produce un comentario de PR legible y acotado.
  E23: diff vacío → una línea: `✅ debtector: no architectural changes`.
  E24: el markdown empieza por el marcador oculto `<!-- debtector-diff -->`.
  E25: 60 funciones empeoradas → se muestran 20 y una línea `…and 40 more`.
  E26: un `qualified_name` con `|`, `<` o backticks → se escapa y no rompe la tabla ni inyecta HTML.

Rule R7: la Action compuesta (`action.yml` en la raíz del repo) indexa la base y la PR de una `pull_request`, publica el diff en un único comentario que se actualiza en cada push y lo escribe siempre en el job summary. → D-0009
  E27: primer push de una PR → se crea un comentario con el marcador.
  E28: segundo push → se actualiza el mismo comentario y no aparece otro.
  E29: PR desde un fork (token de solo lectura) → no hay comentario, el diff está en el job summary y el job no falla por eso.
  E30: un ciclo nuevo con `cycles = "error"` y `fail-on-error: true` (por defecto) → el job falla después de publicar el comentario.

## Supuestos

- Las severidades (`[metrics.severity]`) y los umbrales (`[metrics.thresholds]`, `[audit.thresholds]`) se leen del `debtector.toml` del proyecto de la PR, igual en los dos lados.
- La complejidad (R4) y los hotspots (R5) no bloquean CI en este cambio: son informativos y no tienen severidad configurable. Si hace falta, se añade después con su propia clave.
- Una función que cambia de nombre o de fichero sale como nueva: no se intenta detectar renombrados.
- El JSON de `diff` tiene una clave por sección (`new_cycles`, `resolved_cycles`, `new_god_modules`, `resolved_god_modules`, `new_sdp_violations`, `instability_regressions`, `worsened_functions`, `improved_functions`, `new_hotspots`, `worsened_hotspots`) y se documenta en `docs/diff-schema.md`.
- La lógica de comparación va en un módulo nuevo (`src/debtector/diff.py`), no en `cli.py`. `baseline status` no se toca.
- Los ejemplos de la Action (E27–E30) se comprueban con un workflow del propio repo (`.github/workflows/debtector.yml`) que usa la Action local (`uses: ./`) en sus PRs, empezando por la PR de la tarea que la crea. La parte que se puede probar en local, buscar el comentario por el marcador, va en un script con tests.
- La Action instala debtector con uv desde PyPI en la versión del tag, o desde el propio checkout cuando se usa como `./`.
- README (los dos idiomas) y `TODO.md` (fase 4) se actualizan en la tarea que cambia lo que documentan.

## Tareas

Un fichero por tarea en `tasks/`, cada una con su rama y su PR. Las que están listas se ven en el tablero de `task-done` (`scripts/board.py`). No se listan aquí: los ficheros de tarea son la única fuente.
