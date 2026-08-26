from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _route_functions() -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    tree = ast.parse((ROOT / "app/main.py").read_text(encoding="utf-8"))
    routes = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if any(
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and isinstance(decorator.func.value, ast.Name)
            and decorator.func.value.id == "app"
            for decorator in node.decorator_list
        ):
            routes.append(node)
    return routes


def test_http_routes_do_not_execute_sql_or_open_transactions() -> None:
    violations: list[str] = []
    for route in _route_functions():
        for node in ast.walk(route):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr in {"execute", "connect", "transaction"}:
                violations.append(f"{route.name}:{node.lineno}:{node.func.attr}")
    assert violations == []


def test_services_do_not_execute_sql() -> None:
    violations = []
    for path in (ROOT / "app/services").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "execute":
                violations.append(f"{path.name}:{node.lineno}")
    assert violations == []
