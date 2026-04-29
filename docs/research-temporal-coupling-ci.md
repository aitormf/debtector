# Investigación: Temporal Coupling en CI/PR guardarraíles

Fecha: 2026-04-29
Contexto: evaluar cómo añadir temporal coupling al ratcheting de `debtector baseline status`.

---

## El problema

`compute_temporal_coupling` analiza todo el historial git por defecto (sin `--since`).
Esto hace que el baseline sea inconsistente: dos repos con el mismo código pero diferente
antigüedad de historial producen resultados distintos. Una ventana fija en el baseline
tampoco es trivial porque los pares acumulan commits con el tiempo.

---

## Cómo lo resuelven otras herramientas

### Code-maat (Adam Tornhill, "Your Code as a Crime Scene")

- No gestiona la ventana internamente. El usuario acota el historial **antes** de llamar
  a la herramienta: `git log --after="2024-01-01" | code-maat ...`
- Tiene `--temporal-period` para agrupar commits del mismo día como un único commit lógico,
  pero la ventana temporal es responsabilidad del llamador.
- Para CI recomiendan fijar la ventana en el script de CI explícitamente.

### CodeScene (herramienta comercial)

Da la vuelta al problema: **no detecta acoplamiento nuevo, detecta acoplamiento roto**.

Su alerta "Absence of Expected Change Pattern" avisa cuando:
- Dos archivos *históricamente siempre cambian juntos* (ratio >= umbral, default 80%)
- Pero en el PR actual solo cambió uno de ellos

Esto es lo que tiene sentido en CI: no "apareció un nuevo par", sino
"rompiste un patrón establecido — ¿olvidaste cambiar X cuando cambiaste Y?".

El algoritmo es *self-correcting*: si el equipo ignora el aviso repetidamente,
el ratio baja orgánicamente y el aviso desaparece solo.

El umbral es configurable vía API (`coupling_threshold_percent`, default 80%).

---

## Implicaciones para debtector

### Opción A — ventana fija en baseline (simple)

Guardar en `baseline.json` los pares con `coupling_ratio >= umbral` usando
una ventana temporal fija (e.g. `--since "6 months ago"`). La ventana queda
registrada en el baseline junto con los datos para que las comparaciones
sean consistentes.

Limitación: no detecta patrones rotos, solo pares nuevos.

### Opción B — enfoque CodeScene (más potente, requiere diff del PR)

1. `baseline save` guarda los pares con ratio alto (e.g. >= 0.5)
2. `baseline status` recibe los archivos modificados en el PR
   (`git diff --name-only origin/main...HEAD`)
3. Para cada archivo modificado, comprueba si tiene parejas en el baseline
   con ratio alto — y si esa pareja **no** aparece en los archivos del PR,
   emite aviso: "cambiaste A pero no B, y suelen cambiar juntos"

Esto requiere que `baseline status` conozca el diff del PR, lo que conecta
con el item **"Graph diff"** del roadmap.

### Recomendación

Implementar Opción B cuando se aborde el Graph diff. Es el enfoque correcto
semánticamente y es cómo lo hace la herramienta más madura del sector.
Opción A es un parche que produce más ruido que señal.

---

## Referencias

- [code-maat — GitHub](https://github.com/adamtornhill/code-maat)
- [CodeScene — Temporal Coupling docs](https://docs.enterprise.codescene.io/versions/3.4.0/guides/technical/temporal-coupling.html)
- [CodeScene — CI/CD Delta Analysis](https://docs.enterprise.codescene.io/versions/4.5.0/guides/delta/automated-delta-analyses.html)
