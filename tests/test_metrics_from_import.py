"""`from X import a` depends on the submodule `X.a` when it exists (D-0018)."""

from __future__ import annotations

from debtector.graph_store import GraphStore
from debtector.metrics import compute_metrics, find_cycles, sdp_violations
from debtector.models import EdgeInfo, EdgeKind, NodeInfo, NodeKind


def _add(store: GraphStore, path: str, *imports: tuple[str, list[str] | None]) -> None:
    """Index *path* with hand-written IMPORTS_FROM edges (target, names)."""
    node = NodeInfo(
        kind=NodeKind.FILE,
        name=path.split("/")[-1],
        qualified_name=path,
        file_path=path,
        language="python",
    )
    edges = [
        EdgeInfo(
            kind=EdgeKind.IMPORTS_FROM,
            source=path,
            target=target,
            file_path=path,
            line=1,
            extra={"names": names} if names is not None else {},
        )
        for target, names in imports
    ]
    store.store_file(path, [node], edges)


def _by_file(store: GraphStore) -> dict[str, tuple[float, float]]:
    return {m.file_path: (m.fan_in, m.fan_out) for m in compute_metrics(store)}


def test_E5_relative_from_import_of_submodule(tmp_db: GraphStore) -> None:  # D-0018
    _add(tmp_db, "src/blib2to3/__init__.py")
    _add(tmp_db, "src/blib2to3/pgen2/__init__.py")
    _add(tmp_db, "src/blib2to3/pgen2/driver.py")
    _add(tmp_db, "src/blib2to3/pygram.py", (".pgen2", ["driver"]))
    got = _by_file(tmp_db)
    assert got["src/blib2to3/pgen2/driver.py"][0] == 1
    assert got["src/blib2to3/pgen2/__init__.py"][0] == 0
    assert got["src/blib2to3/pygram.py"][1] == 1


def test_E6_absolute_from_import_of_two_submodules(tmp_db: GraphStore) -> None:
    _add(tmp_db, "pydantic/__init__.py")
    _add(tmp_db, "pydantic/_internal/__init__.py")
    _add(tmp_db, "pydantic/_internal/_repr.py")
    _add(tmp_db, "pydantic/_internal/_fields.py")
    _add(tmp_db, "pydantic/main.py", ("pydantic._internal", ["_repr", "_fields"]))
    got = _by_file(tmp_db)
    assert got["pydantic/main.py"][1] == 2
    assert got["pydantic/_internal/__init__.py"][0] == 0
    assert got["pydantic/_internal/_repr.py"][0] == 1
    assert got["pydantic/_internal/_fields.py"][0] == 1


def test_E7_imported_class_depends_on_its_module(tmp_db: GraphStore) -> None:
    _add(tmp_db, "app/__init__.py")
    _add(tmp_db, "app/models.py")
    _add(tmp_db, "app/views.py", ("app.models", ["User"]))
    got = _by_file(tmp_db)
    assert got["app/models.py"][0] == 1
    assert got["app/views.py"][1] == 1


def test_E8_imported_function_depends_on_init(tmp_db: GraphStore) -> None:
    _add(tmp_db, "app/__init__.py")
    _add(tmp_db, "app/models.py")
    _add(tmp_db, "main.py", ("app", ["create_app"]))
    got = _by_file(tmp_db)
    assert got["app/__init__.py"][0] == 1
    assert got["app/models.py"][0] == 0


def test_E9_submodule_and_function_in_one_import(tmp_db: GraphStore) -> None:
    _add(tmp_db, "app/__init__.py")
    _add(tmp_db, "app/models.py")
    _add(tmp_db, "main.py", ("app", ["models", "create_app"]))
    got = _by_file(tmp_db)
    assert got["main.py"][1] == 2
    assert got["app/models.py"][0] == 1
    assert got["app/__init__.py"][0] == 1


def test_E10_from_dot_import_function_of_init(tmp_db: GraphStore) -> None:
    _add(tmp_db, "pkg/__init__.py")
    _add(tmp_db, "pkg/mod.py", (".", ["helper"]))
    got = _by_file(tmp_db)
    assert got["pkg/__init__.py"][0] == 1
    assert got["pkg/mod.py"][1] == 1


def test_E11_subpackage_resolves_to_its_init(tmp_db: GraphStore) -> None:
    _add(tmp_db, "pkg/__init__.py")
    _add(tmp_db, "pkg/sub/__init__.py")
    _add(tmp_db, "main.py", ("pkg", ["sub"]))
    got = _by_file(tmp_db)
    assert got["pkg/sub/__init__.py"][0] == 1
    assert got["pkg/__init__.py"][0] == 0


def test_E12_star_import_depends_on_init(tmp_db: GraphStore) -> None:
    _add(tmp_db, "pkg/__init__.py")
    _add(tmp_db, "pkg/sub.py")
    _add(tmp_db, "main.py", ("pkg", None))
    got = _by_file(tmp_db)
    assert got["pkg/__init__.py"][0] == 1
    assert got["pkg/sub.py"][0] == 0


def test_E13_stdlib_import_has_no_internal_dependency(tmp_db: GraphStore) -> None:
    _add(tmp_db, "pkg/__init__.py")
    _add(tmp_db, "pkg/path.py")
    _add(tmp_db, "main.py", ("os", ["path"]))
    got = _by_file(tmp_db)
    assert got["main.py"][1] == 0
    assert got["pkg/path.py"][0] == 0


def test_cycles_and_sdp_use_imported_names(tmp_db: GraphStore) -> None:
    # a -> pkg.b (submodule) and b -> a close a cycle only if the name resolves
    _add(tmp_db, "pkg/__init__.py")
    _add(tmp_db, "pkg/b.py", ("pkg.a", ["x"]))
    _add(tmp_db, "pkg/a.py", ("pkg", ["b"]))
    assert [sorted(c) for c in find_cycles(tmp_db)] == [["pkg/a.py", "pkg/b.py"]]
    assert isinstance(sdp_violations(tmp_db), list)
