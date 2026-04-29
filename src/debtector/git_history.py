"""Análisis de comportamiento basado en historial de git.

Extrae métricas como churn, hotspots, acoplamiento temporal y bus factor
a partir de ``git log`` y ``git blame``. Estas señales complementan el
grafo de acoplamiento estructural con evidencia de qué módulos generan
más deuda técnica en la práctica.

Ninguna función de este módulo escribe en la base de datos; todas son
consultas de solo lectura sobre el repositorio git del proyecto.
"""

from __future__ import annotations

import itertools
import re
import subprocess  # nosec B404 — required for git invocation; no user input reaches subprocess
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import structlog

log = structlog.get_logger()

# Patrón para reconocer un hash de commit SHA-1 (40 hex chars)
_HASH_RE = re.compile(r"^[0-9a-f]{40}$")

# Umbral para el cálculo de bus factor: autores mínimos para cubrir X% del código
_BUS_FACTOR_COVERAGE = 0.80


# ──────────────────────────────────────────────
# Dataclasses públicas
# ──────────────────────────────────────────────


@dataclass
class ChurnMetrics:
    """Actividad de un archivo en el historial de git.

    Attributes:
        file_path: Ruta relativa del archivo.
        commits: Número de commits distintos que tocan el archivo.
        lines_added: Total de líneas añadidas en todos los commits.
        lines_deleted: Total de líneas eliminadas en todos los commits.
    """

    file_path: str
    commits: int
    lines_added: int
    lines_deleted: int


@dataclass
class HotspotMetrics:
    """Cruce de churn y acoplamiento estructural.

    Un hotspot es un archivo con alta actividad de cambios *y* alto
    acoplamiento con otros módulos. Es la señal más fiable de deuda
    técnica accionable.

    Attributes:
        file_path: Ruta relativa del archivo.
        churn: Número de commits que tocan el archivo.
        coupling: fan_in + fan_out del módulo en el grafo estructural.
        hotspot_score: churn × coupling — ranking de deuda técnica.
    """

    file_path: str
    churn: int
    coupling: float
    hotspot_score: float


@dataclass
class TemporalCoupling:
    """Par de archivos que co-cambian frecuentemente.

    Detecta dependencias implícitas entre módulos que no tienen un
    import directo pero que el equipo modifica de forma coordinada.

    Attributes:
        file_a: Ruta del primer archivo (lexicográficamente menor).
        file_b: Ruta del segundo archivo.
        shared_commits: Commits donde ambos archivos cambiaron.
        coupling_ratio: shared_commits / min(commits_a, commits_b).
            1.0 significa acoplamiento perfecto.
    """

    file_a: str
    file_b: str
    shared_commits: int
    coupling_ratio: float


@dataclass
class BusFactorMetrics:
    """Riesgo de conocimiento concentrado en un único autor.

    Attributes:
        file_path: Ruta relativa del archivo.
        top_author: Autor con más líneas vigentes según ``git blame``.
        top_author_pct: Porcentaje de líneas del autor dominante.
        bus_factor: Mínimo de autores necesarios para cubrir el 80% del código.
            1 = punto único de fallo.
    """

    file_path: str
    top_author: str
    top_author_pct: float
    bus_factor: int


# ──────────────────────────────────────────────
# Helpers privados
# ──────────────────────────────────────────────


def _run_git(cmd: list[str], cwd: str | Path) -> str:
    """Ejecuta un comando git y devuelve su stdout como texto.

    Args:
        cmd: Partes del comando (e.g. ``["git", "log", "--numstat"]``).
        cwd: Directorio donde ejecutar git.

    Returns:
        Salida estándar decodificada como cadena UTF-8.

    Raises:
        RuntimeError: Si git no está disponible o el directorio no es un repo.
    """
    try:
        result = subprocess.run(  # nosec B603 — cmd is constructed internally, never from user input
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout
    except FileNotFoundError as exc:
        raise RuntimeError(
            "git no está disponible en el PATH. Instala git para usar esta función."
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"Error ejecutando '{' '.join(cmd)}': {exc.stderr.strip()}") from exc


def _is_hash(line: str) -> bool:
    """Devuelve True si la línea es un hash de commit SHA-1."""
    return bool(_HASH_RE.match(line))


# ──────────────────────────────────────────────
# API pública
# ──────────────────────────────────────────────


def parse_churn(
    project_root: str | Path,
    since: str | None = None,
) -> list[ChurnMetrics]:
    """Parsea ``git log --numstat`` para calcular churn por archivo.

    El churn mide cuántas veces se ha modificado cada archivo. Archivos
    binarios (que muestran ``-`` en las columnas de líneas) se incluyen
    con líneas a 0.

    Args:
        project_root: Directorio raíz del repositorio git.
        since: Filtro de fecha opcional (e.g. ``"6 months ago"``).

    Returns:
        Lista de :class:`ChurnMetrics` ordenada por número de commits
        descendente. Vacía si no hay historial.
    """
    cmd = ["git", "log", "--numstat", "--format=%H"]
    if since:
        cmd.append(f"--since={since}")

    output = _run_git(cmd, project_root)

    commits_per_file: dict[str, set[str]] = defaultdict(set)
    lines_added: dict[str, int] = defaultdict(int)
    lines_deleted: dict[str, int] = defaultdict(int)

    current_hash: str | None = None

    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _is_hash(line):
            current_hash = line
        elif current_hash and "\t" in line:
            parts = line.split("\t", 2)
            if len(parts) == 3:
                added_str, deleted_str, file_path = parts
                try:
                    added = int(added_str)
                    deleted = int(deleted_str)
                except ValueError:
                    # Archivos binarios muestran "-"
                    added = deleted = 0
                commits_per_file[file_path].add(current_hash)
                lines_added[file_path] += added
                lines_deleted[file_path] += deleted

    results = [
        ChurnMetrics(
            file_path=fp,
            commits=len(hashes),
            lines_added=lines_added[fp],
            lines_deleted=lines_deleted[fp],
        )
        for fp, hashes in commits_per_file.items()
    ]
    return sorted(results, key=lambda m: m.commits, reverse=True)


def compute_hotspots(
    store: GraphStore,  # type: ignore[name-defined]  # noqa: F821
    project_root: str | Path,
    since: str | None = None,
    limit: int | None = None,
) -> list[HotspotMetrics]:
    """Combina churn con acoplamiento estructural para identificar hotspots.

    La puntuación de hotspot es ``churn × (fan_in + fan_out)``. Solo
    incluye archivos que tienen historial en git *y* están indexados en
    el grafo.

    Args:
        store: :class:`~debtector.graph_store.GraphStore` con el índice.
        project_root: Directorio raíz del repositorio git.
        since: Filtro de fecha opcional para el churn.
        limit: Número máximo de resultados. ``None`` devuelve todos.

    Returns:
        Lista de :class:`HotspotMetrics` ordenada por puntuación descendente.
    """
    from .metrics import compute_metrics

    module_metrics = compute_metrics(store)
    if not module_metrics:
        return []

    churn_list = parse_churn(project_root, since=since)
    churn_map = {c.file_path: c for c in churn_list}

    # Iterate over currently-indexed files so renamed/deleted files from git
    # history don't pollute results with coupling=0.
    coupling_map = {m.file_path: m.fan_in + m.fan_out for m in module_metrics}

    hotspots: list[HotspotMetrics] = []
    for file_path, coupling in coupling_map.items():
        churn_data = churn_map.get(file_path)
        if churn_data is None:
            continue
        score = churn_data.commits * coupling
        hotspots.append(
            HotspotMetrics(
                file_path=file_path,
                churn=churn_data.commits,
                coupling=coupling,
                hotspot_score=score,
            )
        )

    hotspots.sort(key=lambda h: h.hotspot_score, reverse=True)
    if limit is not None:
        hotspots = hotspots[:limit]

    log.debug("hotspots_computed", total=len(hotspots))
    return hotspots


def compute_temporal_coupling(
    project_root: str | Path,
    min_shared: int = 5,
    min_ratio: float = 0.3,
    since: str | None = None,
) -> list[TemporalCoupling]:
    """Encuentra pares de archivos que cambian juntos frecuentemente.

    Detecta dependencias implícitas: módulos que el equipo modifica de
    forma coordinada aunque no tengan un ``import`` directo entre ellos.

    Args:
        project_root: Directorio raíz del repositorio git.
        min_shared: Mínimo de commits compartidos para reportar un par.
        min_ratio: Ratio mínimo ``shared / min(commits_a, commits_b)``.
        since: Filtro de fecha opcional.

    Returns:
        Lista de :class:`TemporalCoupling` ordenada por commits
        compartidos descendente.
    """
    cmd = ["git", "log", "--name-only", "--format=%H"]
    if since:
        cmd.append(f"--since={since}")

    output = _run_git(cmd, project_root)

    # commit_hash → conjunto de archivos modificados
    commit_files: dict[str, list[str]] = {}
    # archivo → conjunto de commits que lo tocan
    file_commits: dict[str, set[str]] = defaultdict(set)

    current_hash: str | None = None
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _is_hash(line):
            current_hash = line
            commit_files[current_hash] = []
        elif current_hash is not None:
            commit_files[current_hash].append(line)
            file_commits[line].add(current_hash)

    # Contar commits compartidos por cada par de archivos
    pair_counts: dict[tuple[str, str], int] = defaultdict(int)
    for files in commit_files.values():
        for a, b in itertools.combinations(sorted(files), 2):
            pair_counts[(a, b)] += 1

    results: list[TemporalCoupling] = []
    for (file_a, file_b), shared in pair_counts.items():
        if shared < min_shared:
            continue
        commits_a = len(file_commits[file_a])
        commits_b = len(file_commits[file_b])
        denom = min(commits_a, commits_b)
        ratio = shared / denom if denom > 0 else 0.0
        if ratio < min_ratio:
            continue
        results.append(
            TemporalCoupling(
                file_a=file_a,
                file_b=file_b,
                shared_commits=shared,
                coupling_ratio=round(ratio, 4),
            )
        )

    results.sort(key=lambda t: t.shared_commits, reverse=True)
    log.debug("temporal_coupling_computed", pairs=len(results))
    return results


def compute_bus_factor(
    store: GraphStore,  # type: ignore[name-defined]  # noqa: F821
    project_root: str | Path,
) -> list[BusFactorMetrics]:
    """Calcula el bus factor por archivo usando ``git blame``.

    Solo procesa archivos presentes en el índice del grafo. Los archivos
    en los que ``git blame`` falla (p.ej. archivos nuevos sin commits)
    se omiten con un aviso en el log.

    Args:
        store: :class:`~debtector.graph_store.GraphStore` con el índice.
        project_root: Directorio raíz del repositorio git.

    Returns:
        Lista de :class:`BusFactorMetrics` ordenada por bus factor
        ascendente (los más en riesgo primero) y luego por porcentaje
        del autor dominante descendente.
    """
    indexed_files = store.get_all_files()
    results: list[BusFactorMetrics] = []

    for file_path in sorted(indexed_files):
        try:
            output = _run_git(
                ["git", "blame", "--line-porcelain", file_path],
                project_root,
            )
        except RuntimeError:
            log.warning("bus_factor_blame_failed", file_path=file_path)
            continue

        author_lines: dict[str, int] = defaultdict(int)
        for line in output.splitlines():
            # "author <name>" lines (not "author-mail", "author-time", etc.)
            if line.startswith("author ") and not line.startswith("author-"):
                author = line[len("author ") :].strip()
                author_lines[author] += 1

        if not author_lines:
            continue

        total = sum(author_lines.values())
        sorted_authors = sorted(author_lines.items(), key=lambda x: x[1], reverse=True)
        top_author, top_count = sorted_authors[0]
        top_pct = top_count / total * 100

        # Bus factor: mínimo de autores para cubrir >= 80% de las líneas
        cumulative = 0
        bus_factor = 0
        for _, count in sorted_authors:
            cumulative += count
            bus_factor += 1
            if cumulative / total >= _BUS_FACTOR_COVERAGE:
                break

        results.append(
            BusFactorMetrics(
                file_path=file_path,
                top_author=top_author,
                top_author_pct=round(top_pct, 1),
                bus_factor=bus_factor,
            )
        )

    results.sort(key=lambda b: (b.bus_factor, -b.top_author_pct))
    log.debug("bus_factor_computed", files=len(results))
    return results
