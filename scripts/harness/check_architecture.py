"""Enforce the repository's high-level Python dependency boundaries."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RULES = {
    "database": {"agent", "api"},
    "agent": {"api"},
}


def imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def main() -> int:
    findings: list[str] = []
    for layer, forbidden in RULES.items():
        for path in (ROOT / layer).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            try:
                violations = imported_roots(path) & forbidden
            except SyntaxError as error:
                findings.append(f"{path.relative_to(ROOT)}: syntax error: {error.msg}")
                continue
            if violations:
                findings.append(
                    f"{path.relative_to(ROOT)} imports forbidden layer(s): "
                    f"{', '.join(sorted(violations))}"
                )

    api_main = (ROOT / "api" / "main.py").read_text(encoding="utf-8")
    if "asyncpg" in imported_roots(ROOT / "api" / "main.py") or re_sql(api_main):
        findings.append("api/main.py contains direct persistence concerns")

    if findings:
        print("[失败] 架构边界检查")
        print("\n".join(findings))
        return 1
    print("[通过] 架构边界检查")
    return 0


def re_sql(text: str) -> bool:
    # A readiness probe may issue SELECT 1 through the injected pool. Business
    # queries and mutations still belong outside the transport layer.
    sql_tokens = ("INSERT INTO ", "UPDATE ", "DELETE FROM ", "SELECT *", "SELECT ID")
    return any(token in text.upper() for token in sql_tokens)


if __name__ == "__main__":
    raise SystemExit(main())
