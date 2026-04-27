# Investigación: Métricas de Detección de Acoplamiento y Problemas Arquitectónicos

> Referencia para el roadmap de codeIndex. Complementa y contextualiza la métrica de inestabilidad de Martin ya implementada en Fase 1.
>
> Fecha: 2026-04-26

---

## 1. Punto de partida: qué hace (y no hace) la inestabilidad de Martin

La métrica de Martin (`I = Ce / Ca + Ce`) es **estructural y estática**: mide cuánto depende un módulo de otros vs cuánto dependen otros de él. Ya implementada en `metrics.py` con pesos diferenciados (`IMPORTS_FROM` = 1.0, `USES_TYPE` = 0.5).

**Lo que Martin detecta bien:**
- Módulos que deberían ser estables (muchos dependientes) pero son frágiles (muchas dependencias)
- El principio de dependencias estables (SDP) de manera cuantitativa
- Regresiones de inestabilidad a lo largo del tiempo (ratcheting)

**Lo que Martin no detecta:**
- Acoplamiento implícito no capturado por imports (lógica de negocio distribuida)
- Módulos que cambian juntos sin tener aristas entre ellos
- Cohesión interna de un módulo (puede ser estable y estar mal diseñado por dentro)
- Dónde conviene invertir el esfuerzo de refactor (qué es urgente vs qué es teórico)
- Clases con radio de explosión alto aunque tengan pocos imports directos

---

## 2. Suite Chidamber & Kemerer (CK) — métricas OO clásicas

### Descripción

Conjunto de 6 métricas diseñadas en 1994 para código orientado a objetos. Empíricamente validadas durante 30 años; correlación probada con defect density y coste de mantenimiento.

| Métrica | Qué mide | Datos necesarios en codeIndex |
|---|---|---|
| **CBO** — Coupling Between Objects | Nº de clases con las que una clase está acoplada (bidireccional, sin pesos) | CALLS + IMPORTS_FROM ya indexados |
| **RFC** — Response For a Class | Métodos locales + métodos remotos invocables. Radio de explosión de una clase | CALLS ya indexado |
| **LCOM** — Lack of Cohesion in Methods | % de métodos que no comparten atributos de instancia. Detecta clases que deberían dividirse | Requiere análisis de atributos (no disponible actualmente) |
| **WMC** — Weighted Methods per Class | Suma de complejidades ciclomáticas por clase. God class detector | Requiere complejidad ciclomática por método |
| **DIT** — Depth of Inheritance Tree | Profundidad máxima en la jerarquía de herencia | **Ya implementado** — aristas INHERITS |
| **NOC** — Number of Children | Hijos directos de una clase en la jerarquía | **Ya implementado** — aristas INHERITS |

### Pros

- Las métricas con mayor respaldo empírico de la literatura — estudios desde los 90 hasta hoy
- CBO es directamente computable desde el grafo existente (suma de CALLS + IMPORTS_FROM bidireccional)
- RFC con CALLS ya indexado: contar métodos externos que puede invocar una clase es trivial
- DIT y NOC ya están implementados en codeIndex
- LCOM detecta un problema completamente distinto al de Martin: módulos que *parecen* cohesivos pero no lo son internamente

### Contras

- Diseñadas para OO clásico (Java, C++) — en Python/JS la herencia es menos prominente y los objetos son más dinámicos
- LCOM tiene varias variantes (LCOM1, LCOM2, LCOM4, LCOM96) con resultados inconsistentes entre sí; requiere elegir una definición
- RFC puede dispararse con duck typing, callbacks o patrones funcionales
- WMC y LCOM requieren datos no presentes actualmente en el índice (atributos de instancia, complejidad ciclomática)

### Integración con Martin

RFC + CBO juntos completan la imagen que fan-in/fan-out dejan incompleta. Ejemplo: un módulo puede tener inestabilidad baja (pocos Ce directos) pero RFC muy alto (llama a decenas de métodos externos). Martin no lo captura; RFC sí.

**CBO es el candidato más fácil de implementar**: calcular Ca+Ce sin pesos sobre CALLS e IMPORTS_FROM y compararlo con la inestabilidad ponderada revela módulos donde el tipo de acoplamiento importa.

### Referencias

- [Virtual Machinery — CK Metrics Suite (WMC, CBO, RFC, LCOM, DIT, NOC)](http://www.virtualmachinery.com/sidebar3.htm)
- [Aivosto — Project Metrics Help: CK Suite](https://www.aivosto.com/project/help/pm-oo-ck.html)
- [ACM DL — Coupling and Cohesion Metrics for OO Software](https://dl.acm.org/doi/pdf/10.1145/3172871.3172878)

---

## 3. Acoplamiento lógico / temporal (Change Coupling)

### Descripción

Dos archivos que cambian juntos frecuentemente en el historial git tienen **acoplamiento lógico**, aunque no tengan ninguna arista estática entre ellos. Es el tipo de acoplamiento más difícil de detectar con análisis estático y el más frecuente en sistemas con lógica de negocio distribuida.

**Fórmula base (coeficiente de Jaccard sobre commits):**

```
change_coupling(A, B) = |commits_con_A_y_B| / |commits_con_A_o_B|
```

Variante con ventana temporal (más precisa para repos activos):

```
change_coupling_windowed(A, B, W) = |commits_en_ventana_W_con_A_y_B| / |commits_en_W_con_A_o_B|
```

**Fuente de datos:** `git log --numstat --format="%H"` — parseable en Python sin dependencias externas.

### Pros

- Detecta acoplamiento *implícito* invisible al análisis estático: lógica de negocio distribuida, configuraciones sincronizadas, tests que siempre rompen juntos
- Completamente lenguaje-agnóstico: funciona igual para Python, JS, YAML, SQL, Dockerfiles
- Alta precisión en code review: si A cambió en este PR y B siempre acompaña a A, el reviewer debería revisar B también
- Correlación empírica fuerte con densidad de defectos (IEEE WCRE 2009, Kagdi et al.)
- Herramienta de referencia en producción: [CodeScene](https://codescene.com) lo usa como feature core

### Contras

- Requiere historial git con suficiente profundidad (señal útil a partir de ~100 commits)
- Proyectos nuevos o con historial corto no generan señal fiable
- Commits bien atómicos (todo lo relacionado junto) generan muchos pares con coupling = 1.0 — ruido alto
- Refactors masivos o commits de linting crean picos de falsos positivos — necesita filtrado por ventana temporal o umbral de frecuencia mínima
- La señal decae con el tiempo en codebases que evolucionan rápido

### Integración con Martin

Ortogonal a la inestabilidad: un módulo puede ser perfectamente estable estructuralmente (bajo fan-in, bajo fan-out) pero tener fuerte acoplamiento temporal con un módulo de otra capa. Esto señala arquitecturas "rotas silenciosamente" que los imports no revelan.

**Combinación potente:** módulos con inestabilidad alta *y* change coupling alto son los más urgentes de refactorizar — doble señal de riesgo.

**Ya en el roadmap:** Fase 2, ítem "temporal coupling" del TODO.md.

### Referencias

- [CodeScene — Change Coupling documentation](https://docs.enterprise.codescene.io/versions/4.5.0/guides/technical/change-coupling.html)
- [IEEE — On the Relationship Between Change Coupling and Software Defects](https://ieeexplore.ieee.org/document/5328803/)
- [IEEE — Logical Coupling Based on Fine-Grained Change Information](https://ieeexplore.ieee.org/document/4656392/)
- [Fine-Grained Analysis of Change Couplings — Fluri et al. (PDF)](https://pinzger.github.io/papers/Fluri2005-couplings.pdf)
- Libro: *Your Code as a Crime Scene* — Adam Tornhill (Pragmatic Programmers)
- Libro: *Software Design X-Rays* — Adam Tornhill

---

## 4. Hotspot Analysis (Behavioral Code Analysis)

### Descripción

Combina **frecuencia de cambio** (historial git) con **complejidad del código** para identificar hotspots: archivos que cambian mucho *y* son complejos. Son los de mayor riesgo y coste de mantenimiento real — no el módulo más acoplado teóricamente, sino el que más se toca y más cuesta cambiar.

```
hotspot_score(file) = change_frequency(file) × complexity(file)
```

Donde:
- `change_frequency`: nº de commits que tocaron el archivo (o frecuencia en ventana temporal)
- `complexity`: líneas de código, complejidad ciclomática, o número de funciones/métodos

### Pros

- La correlación hotspot → densidad de defectos es la más fuerte en la literatura empírica reciente
- Prioriza *dónde invertir el refactor*: no el módulo más acoplado en abstracto, sino el más acoplado **y** el que más se toca en la realidad
- Interpretable por cualquier desarrollador o tech lead sin conocimientos de métricas
- Metodología validada por CodeScene y respaldada por dos libros de Adam Tornhill
- Los datos de frecuencia de cambio (git log) ya son necesarios para change coupling — reutilización directa

### Contras

- Requiere historial git (misma limitación que change coupling)
- Complejidad es un proxy — nº de LOC o nº de métodos son más fáciles de calcular que complejidad ciclomática
- En monorepos, frecuencia alta puede ser legítima (ficheros de configuración central, schemas compartidos)
- CodeScene es SaaS cerrado — reimplementarlo es trabajo adicional no trivial
- Riesgo de metric creep: otro número que el usuario debe interpretar y ponderar

### Integración con Martin

La inestabilidad responde "¿qué tan frágil es este módulo estructuralmente?". Hotspot responde "¿dónde debería mirar primero en la práctica?". Combinación:

```
risk_score(file) = instability(file) × hotspot_score(file)
```

Esto daría un ranking accionable ordenado por urgencia real, no solo por arquitectura teórica.

**Ya en el roadmap:** Fase 2, ítem "hotspot score = churn × acoplamiento estructural" del TODO.md.

### Referencias

- [CodeScene — Code Health](https://codescene.com/product/code-health)
- [CodeScene — Hotspots documentation](https://codescene.io/docs/guides/technical/hotspots.html)
- Libro: *Your Code as a Crime Scene* — Adam Tornhill
- Libro: *Software Design X-Rays* — Adam Tornhill

---

## 5. Dependency Structure Matrix (DSM)

### Descripción

Representación matricial N×N del grafo de dependencias. La celda `(i,j) = 1` si el módulo `i` depende del módulo `j`. Sobre esta matriz se pueden detectar:

- **Ciclos**: si hay 1s en ambos lados de la diagonal → dependencia bidireccional (ya detectado con Tarjan)
- **Violaciones de capas**: dependencias que van en sentido contrario al esperado según la arquitectura
- **Clusters**: bloques densos = módulos muy acoplados que deberían ser un subsistema natural
- **Módulos "hub"**: filas o columnas con muchos 1s → equivalente visual al god module

La DSM es directamente computable desde el grafo NetworkX que ya existe en memoria.

### Pros

- Visual e intuitivo — excelente para comunicar problemas arquitectónicos a stakeholders no técnicos
- Los algoritmos de clustering sobre DSM (ej. basados en particionamiento espectral) pueden sugerir refactors concretos: "estos 3 módulos forman un cluster natural, conviértelos en paquete"
- Reordenamiento de la matriz (algoritmo de Warfield o similar) revela estructura latente
- Directamente computable desde el grafo NetworkX existente sin datos adicionales
- Utilizado en sistemas embebidos, aerospace y software de alta criticidad como método estándar de gestión de dependencias

### Contras

- No es una métrica numérica sino una representación — necesita interpretación o algoritmos adicionales para ser útil en CI
- En proyectos grandes (>500 nodos a nivel de archivo) la matriz se vuelve ilegible
- Los algoritmos de clustering son O(N²) o peor — puede ser lento en proyectos muy grandes
- Para CI necesita traducirse a métricas derivadas (% de violaciones, nº de clusters anómalos)
- Valor principalmente en análisis exploratorio y reporting, no en guardarraíles automatizados

### Integración con Martin

La DSM es la mejor forma de *visualizar* por qué ciertos módulos tienen inestabilidad alta. Un módulo con I=0.9 en la DSM aparecerá con su fila llena de 1s y su columna vacía — la causa es inmediatamente visible.

**Encaja en Fase 4** (Architectural layer violations): el usuario define capas en `debtector.toml`, la DSM muestra visualmente las violaciones.

### Referencias

- [Wikipedia — Design Structure Matrix](https://en.wikipedia.org/wiki/Design_structure_matrix)
- [DSM Web — Introduction to DSM](https://dsmweb.org/introduction-to-dsm/)
- [DZone — DSM for Software Architecture](https://dzone.com/articles/dependency-structure-matrix-for-software-architect)
- [Medium — Managing Architecture Debt with DSM](https://azeynalli1990.medium.com/managing-architecture-debt-with-dependency-structure-matrix-51f63b6efb4c)
- [DSM Suite — open source tooling](https://dsmsuite.github.io/dsm_overview.html)

---

## 6. Architecture Fitness Functions

### Descripción

Concepto de *Building Evolutionary Architectures* (Ford, Parsons, Kua, O'Reilly 2017, 2ª ed. 2022). Una fitness function es cualquier mecanismo que evalúa una característica arquitectónica de forma automática y ejecutable en CI. No son métricas nuevas — son *wrappers ejecutables* sobre métricas existentes.

Tipos:
- **Atómica**: evalúa una sola característica (ej. "ningún ciclo entre módulos de negocio")
- **Holística**: evalúa combinaciones (ej. "inestabilidad del core < 0.2 Y sin god modules en domain/")
- **Triggered**: se activa en CI, no en cada commit (ej. solo en PRs a main)

Ejemplos directamente implementables sobre el grafo de codeIndex:

```toml
# debtector.toml (propuesta)
[rules]
no_cycles_in         = ["src/domain/", "src/core/"]
max_instability      = { "src/core/" = 0.2, "src/adapters/" = 0.8 }
no_imports_from      = [["src/domain/", "src/infrastructure/"]]
max_fan_in           = 20
```

### Pros

- Convierte cualquier métrica ya calculada en un guardarraíl CI ejecutable — máximo valor con mínimo coste adicional
- Documenta la intención arquitectónica de forma ejecutable y versionable (mejor que diagramas o ADRs sueltos)
- "Shift left" en detección: los problemas se detectan antes de llegar a revisión humana
- Estado del arte recomendado en 2025 para governance arquitectónico
- codeIndex ya implementa esto parcialmente con el ratcheting de baseline

### Contras

- No detectan nada que las métricas subyacentes no detecten — son infrastructure, no signal
- Requieren que el equipo decida umbrales iniciales — sin criterio base los thresholds son arbitrarios
- Demasiadas fitness functions = friction en el pipeline; la recomendación de la literatura es 3-6 máximo
- Las reglas declarativas en TOML requieren un parser de reglas adicional en `config.py`

### Integración con Martin

codeIndex ya implementa fitness functions implícitas (ratcheting de inestabilidad, ciclos como error, god modules como warning). La extensión natural es hacerlas **declarativas y configurables** en `debtector.toml`, permitiendo al equipo definir sus propias reglas sin tocar código.

**Encaja en Fase 4** (Architectural layer violations) y en mejoras de Fase 1 (severidad configurable).

### Referencias

- [Gaurav Notes — Architectural Fitness Functions: A Practical Guide (2025)](https://gauravnotes.com/2025/06/15/fitness-functions/)
- [Trailhead — Fitness Functions: Unit Tests for Architecture](https://trailheadtechnology.com/fitness-functions-unit-tests-for-your-architecture/)
- [Continuous Architecture — Fitness Functions practice](https://continuous-architecture.org/practices/fitness-functions/)
- [Code4IT — Fitness Functions in Software Architecture](https://www.code4it.dev/architecture-notes/fitness-functions/)
- [Developers Voice — Fitness Functions in .NET (2024)](https://developersvoice.com/blog/architecture/architectural-fitness-functions-automating-governance/)

---

## 7. Complejidad cognitiva vs ciclomática

### Descripción

La complejidad ciclomática (McCabe, 1976) cuenta caminos independientes en el flujo de control. La complejidad cognitiva (Campbell/SonarSource, 2017) penaliza adicionalmente el anidamiento y las rupturas del flujo lineal, correlacionando mejor con "dificultad real de entender el código".

```
# Ciclomática: cada if/for/while/case suma 1
# Cognitiva:   cada if suma 1 + penalización por nivel de anidamiento
```

Aunque no mide acoplamiento *entre* módulos, es un proxy de acoplamiento *interno* (estado compartido, lógica anidada, callbacks profundos) y de god functions.

### Pros

- Mejor predictor de bugs que la complejidad ciclomática en estudios recientes (SonarSource)
- Tree-sitter ya parsea la estructura de control — calculable sin dependencias nuevas
- Combinado con hotspot score: `hotspot_score × complejidad_cognitiva` = signal de deuda técnica más preciso
- Umbral típico de alerta: complejidad cognitiva > 15 por función

### Contras

- No mide acoplamiento entre módulos, solo dentro de una función — señal diferente a todo lo anterior
- Requiere traversal del AST con conteo de anidamiento: más complejo de implementar que métricas sobre el grafo
- No hay consenso internacional sobre umbrales por lenguaje
- Riesgo de metric creep si se añade sin una historia clara de usuario que lo justifique

### Integración con Martin

Proxy de calidad interna del módulo. Un módulo con inestabilidad baja (bien posicionado en la arquitectura) pero complejidad cognitiva alta en sus funciones tiene deuda técnica interna que Martin no revela. Útil como tercer eje en el ranking de riesgo.

### Referencias

- [SonarSource — Cognitive Complexity: A New Way of Measuring Understandability (PDF)](https://www.sonarsource.com/docs/CognitiveComplexity.pdf)
- [TechTarget — Software coupling metrics basics](https://www.techtarget.com/searchapparchitecture/tip/The-basics-of-software-coupling-metrics-and-concepts)

---

## 8. Resumen ejecutivo y priorización para codeIndex

### Mapa de cobertura

| Problema | Métrica | Estado en codeIndex |
|---|---|---|
| Módulos frágiles por exceso de dependencias salientes | Inestabilidad (Martin) | ✅ Fase 1 |
| Ciclos de importación | Tarjan SCC | ✅ Fase 1 |
| Módulos con demasiados dependientes | God module (Ca p90) | ✅ Fase 1 |
| Jerarquías de herencia patológicas | DIT / NOC | ✅ Fase 1 |
| Módulos con radio de explosión alto | RFC | 🔶 Calculable desde CALLS ya indexado |
| Acoplamiento bidireccional sin ponderar | CBO | 🔶 Trivial desde grafo existente |
| Módulos que cambian juntos sin imports | Change coupling | ⭐ Fase 2 — alta prioridad |
| Deuda técnica priorizada por actividad real | Hotspot score | ⭐ Fase 2 — alta prioridad |
| Cohesión interna de clases | LCOM | 🔵 Requiere datos no disponibles |
| Violaciones de capas arquitectónicas | DSM / Fitness functions | 🔵 Fase 4 |
| Complejidad interna de funciones | Complejidad cognitiva | 🔵 Requiere traversal AST adicional |

### Recomendación de implementación por coste/valor

#### Corto plazo (sobre el grafo existente, sin datos nuevos)

**RFC (Response For a Class)** — calcular para cada clase el número de métodos externos a los que puede llamar. Directamente desde las aristas CALLS ya indexadas. Complementa la inestabilidad de Martin identificando clases con radio de explosión alto aunque tengan pocos imports directos.

**CBO (Coupling Between Objects)** — suma de Ca+Ce sin ponderación sobre CALLS + IMPORTS_FROM. Validación cruzada con la inestabilidad: si CBO y I divergen, hay acoplamiento de tipo diferente que merece atención.

#### Medio plazo (requieren `git log`, ya en roadmap Fase 2)

**Change coupling** — el de mayor valor diferencial. Detecta lo que ninguna métrica estática puede detectar. Implementación: parsear `git log --numstat`, calcular coeficiente de Jaccard por par de archivos, filtrar por umbral de frecuencia mínima y ventana temporal configurable. Output directo al PR reviewer: "estos archivos siempre cambian con el que modificaste".

**Hotspot score** — una vez se tiene la frecuencia de cambio del change coupling, combinarla con fan-in ya calculado para obtener un ranking de deuda técnica accionable. El módulo más urgente no es el más inestable en abstracto sino el más inestable **y** el más activo.

#### Largo plazo (Fase 4)

**Fitness functions declarativas** en `debtector.toml` — convertir las métricas en reglas de arquitectura configurables por el equipo. Encaja con el ítem "Architectural layer violations" ya en el roadmap.

**DSM** — útil principalmente para reporting y comunicación, no para guardarraíles CI automáticos.

### Señal combinada de riesgo (propuesta)

Para un ranking final accionable que combine lo mejor de cada dimensión:

```
risk_score(module) = instability(module)           # ¿qué tan frágil es?
                   × change_frequency(module)       # ¿con qué frecuencia se toca?
                   × log(1 + fan_in(module))        # ¿cuántos se verían afectados?
```

Un módulo con las tres señales altas simultáneamente es el candidato más urgente de refactorizar, independientemente de cualquier umbral arbitrario.

---

## 9. Herramientas de referencia del mercado

| Herramienta | Enfoque | Open Source |
|---|---|---|
| [CodeScene](https://codescene.com) | Behavioral: hotspots + change coupling + code health | No (SaaS) |
| [SonarQube](https://www.sonarsource.com) | Estático: complejidad, duplicación, smells | Parcial (Community Edition) |
| [ArchUnit](https://www.archunit.org) | Fitness functions para JVM — reglas de arquitectura como tests | Sí |
| [Lattix](https://dsmweb.org/lattix/) | DSM commercial para análisis de dependencias | No |
| [DSM Suite](https://dsmsuite.github.io) | DSM open source | Sí |
| [module-coupling-metrics](https://pypi.org/project/module-coupling-metrics/) | Fan-in/fan-out Python puro, sin grafo | Sí |
| [Understand](https://scitools.com) | Análisis estático con métricas CK completas | No |

codeIndex tiene ventaja diferencial sobre todos los open source al combinar **grafo estructural** (nodes/edges) con **métricas en CI** y en el futuro con **git history** — ninguna herramienta open source hace las tres de forma integrada.
