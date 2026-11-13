---
status: done
issue: null
---

# La complejidad puede bloquear, en `diff` y en el baseline

**Problema:** una función nueva con complejidad 40 sale en el comentario de la PR, pero nunca falla nada: en `diff` la complejidad es informativa (nunca cambia el código de salida) y el baseline no la guarda, así que `baseline status` no la ve. Quien quiere un guardarraíl de complejidad (código generado por agentes, sobre todo) no puede tenerlo, y fuera de la GitHub Action (GitLab, `pre-push` local, CI sin historial completo) no la ve ni como aviso.

**Plazo máximo:** dos días.

**Fuera de alcance:**
- Hotspots en el baseline: dependen del churn, que cambia en cada commit; no son ratcheables así.
- Complejidad cognitiva (otro punto del roadmap).
- Umbrales de complejidad por fichero o por función, o excepciones en línea (`# debtector: ignore`).
- Recalibrar `complexity_medium` / `complexity_high`.

## Mapa de ejemplos

```
Rule R1: `[metrics.severity] complexity` decide si una función empeorada (D-0010) bloquea;
         por defecto `warning`, así que nada cambia sin configurarlo. → D-0019
  E1: sin `complexity` en debtector.toml; la PR añade `def f` con complejidad 40
      → `diff` la lista en worsened_functions y sale con 0 (como hoy).
  E2: `complexity = "error"`; misma PR → `diff` sale con 1.
  E3: `complexity = "error"`; la PR solo baja una función de 35 a 10 (improved) → sale con 0.
  E4: `complexity = "error"`; una función pasa de 12 a 18 (< complexity_medium 21) → sale con 0.
  E5: `complexity = "info"` → `diff` sigue listando la función (la sección es informativa),
      sale con 0.
  E6: `complexity = "bogus"` → error de configuración como el resto de severidades.

Rule R2: `baseline save` guarda la complejidad de las funciones de producción con complejidad
         >= complexity_medium, y el umbral usado. → D-0019
  E7: `def g` con complejidad 25 y `def h` con 5 → baseline.json tiene
      "complexity": {"medium": 21, "functions": {"src/a.py::g": 25}}.
  E8: una función en tests/ con complejidad 40 → no está en el baseline.

Rule R3: `baseline status` informa las funciones nuevas o empeoradas respecto del baseline con
         la regla de D-0010 y bloquea según `complexity`. → D-0019
  E9: baseline con g=25; ahora g=30 → regresión de complejidad g 25 → 30.
  E10: baseline con g=25; ahora g=25 → sin cambios.
  E11: función nueva k=22 que no estaba en el baseline → regresión (antes: ninguna).
  E12: función m que no estaba en el baseline porque tenía 15, ahora 24 → regresión
       (antes: ninguna; no se guardó por estar bajo el umbral).
  E13: `complexity = "error"` y E9 → exit 1; con `warning` → se imprime y exit 0.
  E14: baseline antiguo sin "complexity" → no se compara la complejidad y se avisa de que hay
       que volver a guardar el baseline; el resto se compara como hoy.
  E15: baseline guardado con medium 21 y ahora complexity_medium = 15 → no se compara la
       complejidad y se avisa de volver a guardar (las funciones entre 15 y 21 no están).
  E16: `--json` incluye `complexity_regressions`; `--reporter github` y `gitlab` las emiten
       con su severidad.
```

## Supuestos

- La severidad nueva vive en `[metrics.severity]` junto a las demás (`cycles`, `god_modules`...), aunque los umbrales estén en `[audit.thresholds]`: es donde está todo lo que decide el código de salida.
- Guardar solo las funciones `>= complexity_medium` es equivalente a guardarlas todas para la regla de D-0010: una función que no está y ahora supera el umbral ha crecido seguro. Así el baseline no crece con cada función trivial.
- `baseline status` no lista las funciones que mejoran (como no lista los god modules resueltos); `diff` sí, como hoy.
- La complejidad viene del parser: si cambia `PARSER_VERSION`, las cifras pueden no ser comparables. Se trata como el resto: el aviso de versión de D-0014 y volver a guardar. No se añade otra versión.
- Se actualizan `docs/diff-schema.md` (la complejidad deja de ser "siempre informativa"), la sección de severidad de los README y el punto del TODO.

## Tareas

Un fichero por tarea en `tasks/`, cada una con su rama y su PR. Cuáles están listas: el board de `task-done` (`scripts/board.py`). No se listan aquí: los ficheros de tarea son la única fuente.
