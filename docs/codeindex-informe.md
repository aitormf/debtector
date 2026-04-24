# codeIndex — Informe completo

> Fecha: 2026-04-24
> Revisado con feedback de CTO externo.

---

## 1. Qué era codeIndex (objetivo original)

codeIndex indexa repositorios de código fuente y almacena su estructura
(clases, funciones, métodos, imports, llamadas) como un grafo en SQLite.
El objetivo inicial era que **una IA consultara el grafo en lugar de leer
archivos enteros**, reduciendo el consumo de tokens.

### Por qué ese objetivo falla

- El grafo tiene utilidad marginal para la IA: cuando Claude necesita *hacer
  algo*, igual necesita leer el código fuente para entender el contexto
- Las herramientas nativas de Claude Code (Glob, Grep, Read) ya resuelven
  bien el 90% de los casos de navegación
- El valor real requeriría proyectos de cientos de miles de líneas
- El MCP server era el único multiplicador real, pero no salva el producto
- Conclusión original: **parar**

---

## 2. El pivote — nuevo objetivo

**Cambiar el usuario objetivo: ya no es la IA, es el desarrollador.**

El nuevo problema a resolver: **detectar acoplamiento de código en pipelines
de CI y PR reviews**, dando al desarrollador contexto arquitectónico antes
de mergear.

El grafo que ya existe (nodos + aristas IMPORTS_FROM, CALLS, INHERITS) es
exactamente la estructura necesaria para computar métricas de acoplamiento.
No hay que reescribir nada — solo añadir capas de análisis encima.

Conclusión tras pivote: **continuar**.

### El ángulo que abre la era de los agentes

Pivotamos *desde* la IA como usuario, pero hay un nuevo ángulo de IA que
ningún competidor está usando: **los agentes de código generan acoplamiento
oculto a una velocidad que ningún humano alcanza**.

Claude Code, Copilot, Codex y similares producen código funcional, pero no
tienen incentivo para respetar la arquitectura existente. Un agente puede
introducir en minutos el mismo nivel de deuda técnica que un equipo humano
acumula en meses.

codeIndex puede posicionarse como **el primer fitness function diseñado para
la era de los agentes**: una herramienta que actúa como guardarraíl
arquitectónico en los pipelines donde los agentes generan código.

**Karajan como primer consumidor:** Karajan orquesta agentes de código. Si
codeIndex se integra como gate en el pipeline de Karajan, resuelve el
problema clásico del open-source sin usuarios iniciales — el primer usuario
es el propio workflow del desarrollador.

---

## 3. Perfil de cliente ideal (ICP) — pregunta abierta

**Advertencia:** sin ICP definido, el roadmap es una lista de cosas
construibles, no de cosas necesarias. Cada perfil pide features distintas:

| Perfil | Qué le duele | Qué pediría primero |
|---|---|---|
| **Tech lead** (equipo 5-15 devs) | PRs que degradan la arquitectura sin que nadie lo vea | Gate en CI, comentario automático en PR |
| **Staff engineer** | Visibilidad de deuda técnica acumulada, argumentar refactors | Tendencias históricas, hotspots, informe ejecutable |
| **CTO de startup** | Velocidad sin acumular deuda que paralice en 6 meses | Dashboard simple, semáforo de salud arquitectónica |
| **Dev usando agentes (Karajan, Copilot)** | Los agentes rompen la arquitectura sin saberlo | Integración nativa en pipeline de agente, zero-config |

La hipótesis de trabajo es que el ICP más viable en la fase inicial es
**el dev o tech lead que ya usa agentes de código** — es el perfil con el
problema más agudo y sin solución actual. Pero es una hipótesis, no un
hecho. Hay que validarlo antes de comprometer el roadmap.

---

## 4. Análisis competitivo — qué existe ya

| Herramienta | Lenguajes | Tipo análisis | Estado | Limitación clave |
|---|---|---|---|---|
| py_coupling_metrics | Solo Python | Estructural (AST) | ~6 commits, estancado | Trata módulos como clases, sin JS/TS |
| module_coupling_metrics | Solo Python | Estructural | Activo, básico | Solo Python, sin CI integration |
| codemetrix | Solo TypeScript | Estructural | Activo | Un solo lenguaje |
| code-maat | Cualquier repo | Behavioral (git log) | Última release 2023, requiere Clojure | No analiza AST, problemas de memoria |
| CodeScene | Multi-lenguaje | Estructural + behavioral | Activo, líder | Comercial/SaaS, caro |
| SonarQube CE | Multi-lenguaje | Estructural | Activo | Requiere servidor, coupling básico |
| RefactorFirst | Solo Java | Estructural | Activo | Java únicamente |

### El hueco real

No existe ninguna herramienta open-source, ligera, multi-lenguaje
(Python + JS/TS), que combine análisis estructural + behavioral con CI
integration sin servidor. CodeScene lo resuelve bien pero es comercial.
El resto son mono-lenguaje o están estancados.

---

## 5. Métricas y features — clasificadas por viabilidad y valor

### Tier 1 — Fáciles de implementar, alto valor
*El grafo ya tiene los datos necesarios.*

#### Ca / Ce / Inestabilidad (Robert C. Martin)

| Métrica | Fórmula | Significado |
|---|---|---|
| Fan-in (Ca) | aristas IMPORTS_FROM entrantes al módulo | cuántos dependen de este módulo |
| Fan-out (Ce) | aristas IMPORTS_FROM salientes del módulo | de cuántos depende este módulo |
| Inestabilidad (I) | Ce / (Ca + Ce) | 0 = estable, 1 = inestable |

Un módulo estable (I ≈ 0) no debería cambiar frecuentemente porque muchos
dependen de él. Si cambia mucho (churn alto), es una señal de riesgo.

#### Detección de ciclos

- DFS sobre aristas IMPORTS_FROM + CALLS
- Binario para CI gate: "este PR introduce un ciclo nuevo, falla build"
- Los ciclos impiden la sustitución independiente de módulos y dificultan
  el testing aislado
- py_coupling_metrics no los detecta; code-maat solo los ve en cambios de
  commit, no en el AST

#### God modules

- Outliers estadísticos en Ca: módulos con fan-in muy superior a la media
- Útil en PR review: "este cambio toca un módulo del que dependen 14 otros"
- Métricas relativas (percentil 90 del proyecto) más útiles que umbrales
  absolutos — en proyectos pequeños casi todo parece God module con valores fijos

#### Profundidad de herencia / número de hijos

- Traverse INHERITS edges (ya en el grafo)
- Herencia profunda > 3-4 niveles: diseño frágil (cambio en base = cascada)
- Número de hijos alto: clase base con alta responsabilidad

#### Arista USES_TYPE

`def f(x: User) -> Response` genera aristas hacia `User` y `Response`.

Acoplamiento real aunque no haya llamada directa: si `User` cambia su
interfaz, `f` puede romperse. Enriquece Ca/Ce sin nueva fuente de datos —
todo sale del AST que ya se parsea.

#### Impact radius en PR

- Ya funciona en el CLI (`codeindex impact`)
- Pendiente: formatearlo como CI reporter para GitHub/GitLab

---

### Tier 2 — Requieren trabajo nuevo, valor alto

#### Graph diff entre ramas

El feature más diferencial técnicamente. Ninguna herramienta ligera lo hace:

```
main branch  ->  index A (SQLite)
PR branch    ->  index B (SQLite)
diff A vs B  ->  nuevas aristas de acoplamiento introducidas
             ->  módulos que aumentaron inestabilidad
             ->  ciclos nuevos detectados
             ->  god modules nuevos o empeorados
```

Ejemplo de output en comentario de PR:
```
WARNING  auth.py: fan-in 3 -> 8  (+5 nuevas dependencias entrantes)
ERROR    CICLO DETECTADO: user.py -> order.py -> user.py  (nuevo en este PR)
OK       Inestabilidad media del proyecto: 0.42 -> 0.41
```

Técnicamente: indexar la rama base + la rama del PR, comparar los dos `.db`.

#### Abstractness + Distancia a la secuencia principal

- Abstractness (A): ratio de clases abstractas/interfaces sobre total del módulo
- Distancia = |A + I - 1|, donde 0 es ideal (en la secuencia principal)
- "Zona del dolor" (D aprox 1, I aprox 0, A aprox 0): concreto + estable,
  difícil de cambiar y difícil de extender
- "Zona inútil" (D aprox 1, I aprox 1, A aprox 1): abstracto + inestable,
  nadie lo usa

**Limitación honesta:** Python y JS tienen poca cultura de clases abstractas
formales. La métrica pierde precisión frente a Java o C#. Reportar con
cautela.

#### Architectural layer violations

- El usuario define capas en `codeindex.toml`:
  `web -> service -> repository -> model`
- El analizador detecta imports que violan el sentido:
  hay IMPORTS_FROM desde `repository` hacia `web`?
- Muy útil en proyectos con arquitectura hexagonal o clean architecture
- **Requiere configuración manual por proyecto** — no funciona out of the box

#### CI reporter con GitHub Annotations

- GitHub acepta anotaciones de línea en PRs vía Actions:
  `::warning file=auth.py,line=14::fan-in aumentó de 3 a 8`
- Señalar la línea exacta donde se introduce el acoplamiento problemático
- Formato JSON compatible con el workflow de GitHub Actions / GitLab CI

---

### Tier 3 — Requieren nueva fuente de datos (git history)
*Alto valor. CodeScene basa aquí su ventaja. Parsear git log es más barato
de lo que parece y hotspots los entiende cualquier senior en 10 segundos.*

#### Hotspots

`hotspot = acoplamiento_estructural x churn_de_git`

Los archivos con más acoplamiento Y más commits son los más peligrosos:
prioridad real de deuda técnica. Para implementarlo: parsear
`git log --numstat` y cruzarlo con el grafo. El resultado es un ranking
de "archivos que más duelen tocar".

#### Temporal coupling (acoplamiento behavioral)

Archivos que se modifican juntos en los mismos commits aunque no tengan
dependencia estructural en el AST.

Ejemplo: `auth.py` y `session.py` cambian juntos en el 80% de commits,
están acoplados aunque no haya ningún import entre ellos.

Esta es **la métrica más valiosa y más ignorada** del análisis de código.
Ningún analizador de AST la detecta. code-maat la calcula pero requiere
Clojure y tiene problemas de memoria en repos grandes.

#### Knowledge / bus factor

- Qué porcentaje del código fue escrito por una sola persona por módulo
- Módulos con un único autor = riesgo si esa persona no está disponible
- Requiere parsear `git blame` por módulo

---

### Tier 4 — No merece la pena
*Terreno ya ocupado mejor por otras herramientas.*

| Métrica | Por qué no implementar |
|---|---|
| Complejidad ciclomática | Radon (Python) y ESLint (JS) lo hacen mejor y más rápido |
| Líneas de código / ratio comentarios | Cualquier linter básico |
| Detección de duplicados | PMD, SonarQube tienen años de ventaja |
| Connascence | Requiere análisis semántico profundo; falsos positivos masivos en Python/JS |
| LCOM (falta de cohesión) | Complejo y poco preciso con duck typing; radon lo aproxima |

---

## 6. Gestión de ruido — condición de supervivencia

**SonarQube se desinstala por esto.** La primera ejecución sobre un codebase
real genera cientos de warnings sobre deuda existente. El equipo no puede
arreglarlo todo de golpe, el CI empieza a fallar, y la herramienta se
desactiva a la semana.

Baseline + ratcheting no es una feature opcional — es una condición para
que codeIndex no muera en la primera demo. Debe estar en Fase 1.

### Mecanismos obligatorios desde el día uno

**Baseline**

Snapshot del estado actual del proyecto en el momento de activar codeIndex.
Todos los problemas existentes quedan registrados y no generan error en CI.
Solo fallan los problemas *nuevos* introducidos a partir de ese momento.

```bash
codeindex baseline save   # guarda estado actual como referencia
codeindex baseline status # muestra delta respecto al baseline
```

**Ratcheting**

El CI solo falla si las métricas empeoran respecto al baseline.
Si el proyecto tiene hoy 5 ciclos, los 5 ciclos no bloquean. El ciclo
número 6, introducido en un PR, sí bloquea.

**Severidad configurable** en `codeindex.toml`:

```toml
[thresholds]
new_cycle       = "error"    # bloquea CI
fan_in_increase = "warning"  # comenta en PR, no bloquea
instability     = "info"     # solo reporta
```

**Modo silencioso por defecto**

La primera ejecución sin baseline configurado no falla — solo reporta.
El desarrollador decide qué umbrales activar y cuándo.

---

## 7. Roadmap propuesto

*Orden revisado tras feedback de CTO: git history sube a Fase 2 porque
hotspots se venden en 10 segundos a cualquier senior; graph diff baja a
Fase 3 como feature premium que requiere más contexto para entender.*

### Fase 1 — Fundación estructural + gestión de ruido
*Todo construible sobre el grafo existente. Sin esto no hay producto.*

- [ ] Módulo `metrics.py`: Ca, Ce, inestabilidad por módulo
- [ ] Detección de ciclos (DFS sobre el grafo)
- [ ] God module detection (outliers estadísticos en Ca)
- [ ] Profundidad de herencia y número de hijos
- [ ] Arista `USES_TYPE` para anotaciones de tipo en funciones y métodos
- [ ] Comando CLI `codeindex metrics` con output tabular
- [ ] **Baseline + ratcheting**: snapshot del estado actual, solo fallan
      problemas nuevos respecto a la referencia
- [ ] **Severidad configurable** en `codeindex.toml`
- [ ] CI reporter: salida compatible con GitHub Annotations / GitLab

### Fase 2 — Análisis behavioral (git history)
*Parsear `git log` es barato. Hotspots los entiende cualquier senior en
10 segundos. Esta fase da ventaja real sobre herramientas estructurales puras.*

- [ ] Parser de `git log --numstat` para churn por módulo
- [ ] Hotspot score: churn x acoplamiento estructural, ranking de deuda real
- [ ] Temporal coupling: archivos que cambian juntos con frecuencia > umbral
- [ ] Bus factor por módulo (`git blame`)
- [ ] Integración Karajan: gate en pipeline de agente que bloquea si se
      introducen hotspots nuevos

### Fase 3 — Graph diff para PRs (feature premium)
*El más diferencial técnicamente, pero necesita más contexto para venderse.
Construir cuando Fase 1+2 tengan tracción y haya ICP validado.*

- [ ] Comando `codeindex diff <db_base> <db_pr>`
- [ ] Delta de métricas por PR: qué empeoró, qué mejoró
- [ ] Detección de ciclos nuevos en el PR
- [ ] GitHub Action `codeindex-action` que indexa ambas ramas y comenta

### Fase 4 — Features avanzadas
*Solo si las fases anteriores demuestran tracción.*

- [ ] Architectural layer violations con config declarativa
- [ ] Abstractness + distancia a la secuencia principal
- [ ] Tendencias históricas de acoplamiento a lo largo del tiempo

---

## 8. Código a eliminar — búsqueda semántica y embeddings

El ADR-001 declara explícitamente el objetivo de esta capa:

> *"Para que una IA pueda navegar un repositorio desconocido necesita
> encontrar código por concepto, no por nombre literal."*

Ese objetivo ya no existe en el nuevo codeIndex. Todo lo construido para
búsqueda semántica es dead weight para el objetivo CI/PR.

### Inventario

| Componente | Qué hace | Util para CI/PR |
|---|---|---|
| `embedder.py` + `fastembed` | Genera vectores semánticos por nodo | No |
| `node_embeddings` (sqlite-vec) | Almacena vectores, búsqueda por coseno | No |
| `codeindex semantic "..."` | Busca código por concepto | No |
| FTS5 (`nodes_fts`) | Búsqueda textual nombre/firma/docstring | Marginal |
| Grafo estructural (nodes + edges) | Ca, Ce, ciclos, impacto | Es la base |

Para calcular métricas de acoplamiento, diff de grafos y CI gates nunca se
necesita búsqueda por concepto semántico. Las consultas son SQL puro sobre
el grafo.

### Peso que añade sin valor

- `fastembed` arrastra ONNX Runtime como dependencia — pesado para una CLI de CI
- Modelo `BAAI/bge-small-en-v1.5`: ~24 MB descargados en el primer uso
- `sqlite-vec`: extensión SQLite adicional con su propio ciclo de mantenimiento
- 23 tests de embeddings que seguirán pasando pero no cubren el nuevo objetivo

### Decisión

No eliminar de golpe — hay código funcional y tests — pero **congelar**:
no desarrollar más, marcar como opcional en las dependencias (grupo `[semantic]`
en `pyproject.toml`), y eliminar limpiamente cuando el roadmap de CI esté
avanzado.

---

## 9. Riesgos y limitaciones honestas

**ICP sin validar:** el roadmap actual asume que el dev/tech lead que usa
agentes es el ICP correcto. Es una hipótesis razonable pero no probada.
Si el ICP real es el staff engineer, las prioridades del roadmap cambian.

**Sin Fase 2, CodeScene sigue ganando:** las métricas estructurales solas
(Fase 1) no superan a CodeScene. La ventaja real llega con git history
(hotspots, temporal coupling). Fase 1 es fundación, no producto completo.

**Limitación de lenguajes en Abstractness:** Python y JS tienen poca
cultura de clases abstractas formales. La métrica pierde precisión frente
a Java o C#.

**Falsos positivos en God modules:** en proyectos pequeños, los umbrales
absolutos distorsionan. Usar métricas relativas (percentil 90 del proyecto).

**Mantenimiento de parsers:** tree-sitter evoluciona; los parsers de Python
y JS/TS necesitan mantenimiento cuando cambia la gramática del lenguaje.

---

## 10. Conclusión

| Dimensión | Evaluación |
|---|---|
| Hueco en el mercado | Real: no existe herramienta ligera multi-lenguaje open-source con behavioral + CI |
| Viabilidad técnica | Alta en Fase 1 (grafo existe); media en Fases 2-3 (nuevas fuentes de datos) |
| Diferencial real | Hotspots multi-lenguaje + graph diff + integración con pipelines de agentes |
| Competencia directa | CodeScene (comercial), py_coupling_metrics (mono-lenguaje, estancado) |
| Riesgo principal | ICP no validado; sin Fase 2 la herramienta es útil pero no líder |
| Deuda a eliminar | embeddings + sqlite-vec + fastembed: funcionales pero sin valor en el nuevo objetivo |
| Condición de supervivencia | Baseline + ratcheting en Fase 1, o la herramienta muere en la primera demo |

El pivote es sólido. La Fase 1 entrega fundación estructural con gestión de
ruido desde el día uno. La Fase 2 (git history + hotspots) es donde codeIndex
se diferencia de verdad. La integración con Karajan resuelve el bootstrap.
El ángulo de agentes es el hook de posicionamiento que ningún competidor usa.
