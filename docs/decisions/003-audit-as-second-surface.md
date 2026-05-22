# ADR-003: Audit como segunda superficie de presentación

**Estado:** Aceptado
**Fecha:** 2026-05-22
**Contexto:** Debtector v0.4

---

## Contexto

Tras Fase 1 (acoplamiento estructural) y Fase 2 (behavioral vía git history),
debtector tiene en el grafo todos los datos necesarios para dos perfiles de uso
distintos, pero sólo presenta uno:

- **Dev en PR**: necesita señal terse, accionable, machine-readable. Cubierto
  por `coupling`, `baseline status`, `report`, `--reporter github|gitlab`.
- **Tech lead en revisión profunda**: necesita snapshot completo, agregado,
  con priorización opinada. **No cubierto.** Hoy hay que componer manualmente
  varios comandos y el output crudo no jerarquiza el riesgo.

Existe además un caso paralelo: orquestadores externos de IA (p. ej. agentes
que producen informes de salud de codebase) invocan a un LLM para descubrir
acoplamiento, ciclos cross-language, hotspots o gaps de cobertura. Todo eso
es información que el grafo ya tiene de forma determinista — el LLM trabaja
en territorio donde una consulta SQL daría una respuesta exacta y más barata.
Falta exponerla como JSON estable y agregado.

---

## Decisión

Añadir un **segundo presenter** sobre el mismo backend de métricas: el comando
`debtector audit`. Mismo grafo, presentación distinta.

### Características

- 8 secciones: `summary`, `coupling`, `cycles`, `cohesion`, `testRisk`,
  `hotspots`, `busFactor`, `inheritance`.
- Top-N por dimensión por defecto (output opinado, no listado plano).
- `--full` para volcado completo, `--json` para consumo programático.
- `schema_version: 1` en la raíz del JSON: contrato público que consumidores
  externos pueden depender de sin acoplarse al detalle interno del grafo.

### Métricas y cruces nuevos que habilita

| Cruce | Datos requeridos | Procedencia |
|---|---|---|
| **LCOM4 por clase** | aristas CALLS entre métodos de la misma clase | ya en grafo (Fase 1) |
| **Priorización de ciclos** | fan-in de cada nodo del ciclo | composición |
| **untested × Ce alto** | `COVERS` + Ca/Ce | composición |
| **untested × churn alto** | `COVERS` + git churn | composición |
| **bus factor 1 × Ca alto** | bus factor + Ca | composición |
| **Health score agregado** | suma ponderada de lo anterior | composición |

Sin nueva fuente de datos. Todo es agregación y joins sobre el grafo existente.

---

## Consecuencias

### División clara entre CI/CD y auditoría

- **CI/CD (existente)**: `coupling`, `baseline status`, `report`. Deltas,
  ratcheting, presentación terse, ideal para PR.
- **Auditoría (nuevo)**: `audit`. Snapshot completo, top-N opinado, salida
  estructurada para consumo profundo.

Mismo backend, dos presenters. Sin diluir el ICP original — ambos perfiles
son dev/tech lead con agentes; sólo cambia el momento del ciclo.

### Posicionamiento

El producto cubre ahora dos momentos del ciclo de vida del código:

1. **PR/CI**: guardarraíl preventivo (actual)
2. **Revisión periódica**: auditoría retrospectiva (nuevo)

El mensaje de la herramienta no cambia (detector de acoplamiento); se amplía
el momento en que se usa.

### Schema estable como contrato público

`audit --json` con `schema_version` se vuelve API pública. Cualquier
consumidor externo (IDE plugins, orquestadores de IA, scripts internos,
dashboards) puede depender del schema. Evolución por versión, no por cambio
silencioso.

---

## Decisiones explícitas no tomadas

Estas decisiones se evaluaron durante el diseño de Fase 3 y se rechazaron de
forma consciente. Documentarlas evita que vuelvan a discutirse sin nuevo
contexto.

### Embeddings — siguen congelados

`embedder.py`, `sqlite-vec` y `fastembed` siguen en el grupo opcional
`[semantic]` y `debtector semantic` sigue devolviendo error de deprecación
(continúa lo decidido en [ADR-002](002-pivot-ci-coupling.md)).

**Por qué no descongelarlos ahora:** descongelarlos resolvería el salto de
lenguaje natural a archivos semilla (caso típico de un agente de IA
investigando un repo), pero ampliaría el alcance del producto a "buscador
semántico + guardrail" — diluyendo el ICP justo cuando audit está
consolidando la propuesta.

**Consecuencia aceptada:** el descubrimiento NL→archivos sigue siendo trabajo
del llamador. Debtector cubre el ~70% de los casos (todo lo que ocurre
*después* de tener semillas: impact, riesgos, cobertura); el 30% restante
(sinonimia fuerte sin keywords compartidos, p. ej. "rate limiting" cuando el
módulo se llama `throttle`) queda fuera y se asume.

### No se crea un comando paraguas `debtector hint`

Se evaluó añadir `debtector hint <task>` que combinara `search` + `impact` +
métricas en una única invocación para reducir spawns de proceso desde
consumidores externos.

**Descartado por:**

- **Viola el principio de composición** del propio `CLAUDE.md` ("Decoupled:
  parsers, store y CLI son intercambiables sin dependencias circulares"). Un
  comando-paraguas crea dependencias entre comandos hermanos.
- **Se acoplaría a un consumidor concreto**. La forma del JSON estaría
  diseñada para el caso de uso del momento. Cuando un IDE plugin, otro
  orquestador o un humano quiera otra composición, aparece `hint2`,
  `hint-quick`, `hint-for-X`.
- **YAGNI**. Los `--json` ya están en `search`, `impact`, `coupling`,
  `untested`. El consumidor compone con coste cero.
- **No añade información**, sólo composición. Y la composición es trabajo
  del consumidor, no de debtector.

**Solución adoptada:** documentar **la receta** en el README ("Identificar
archivos afectados por una tarea") en lugar de exponerla como comando.
Receta como documentación, no como código.

**Si la latencia de spawn se mide y es un problema real**, la solución
correcta sería un modo daemon (`debtector serve`) o una API Python directa
— no un comando-paraguas.

---

## Alternativas descartadas

**Hacer Graph diff (antes Fase 3) antes que Audit**
Descartado: graph diff sigue siendo el feature más diferencial técnicamente,
pero necesita tracción para venderse (mantenido en [ADR-002](002-pivot-ci-coupling.md)).
Audit consolida valor ya construido y abre la segunda superficie sin
inversión nueva en infraestructura. El orden importa: primero usar lo que
ya hay, después construir lo que falta.

**Audit como subset de `report --full`**
Descartado: confunde dos presenters en uno. `report` está optimizado para CI
(terse + JSON estable orientado a ratcheting); audit lo está para revisión
humana (top-N + secciones priorizadas). Hacerlos el mismo comando obliga a
heurísticas frágiles para decidir el modo.

**Crear superficie específica para un consumidor (p. ej. orquestadores de IA)**
Descartado: audit es para humanos primero. Los consumidores externos usan
`audit --json` (contrato estable) o componen comandos atómicos. No se crea
superficie específica por consumidor — eso fragmenta el producto.
