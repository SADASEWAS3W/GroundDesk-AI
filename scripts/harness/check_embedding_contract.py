"""Verify that code, schema, and configuration agree on 1536 dimensions."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def require(path: str, pattern: str, description: str, findings: list[str]) -> None:
    text = (ROOT / path).read_text(encoding="utf-8")
    if not re.search(pattern, text, flags=re.MULTILINE):
        findings.append(f"{path}: missing {description}")


def main() -> int:
    findings: list[str] = []
    require(
        "database/migrations/001_initial_schema.sql",
        r"embedding\s+VECTOR\s*\(\s*1536\s*\)",
        "VECTOR(1536) schema contract",
        findings,
    )
    require(
        ".env.example",
        r"^EMBEDDING_DIMENSIONS=1536$",
        "1536-dimensional example configuration",
        findings,
    )
    require(
        "agent/tools/knowledge.py",
        r'EMBEDDING_DIMENSIONS[^\n]*"1536"',
        "runtime 1536-dimensional default",
        findings,
    )
    require(
        "agent/tools/knowledge.py",
        r"len\(query_embedding\)\s*!=\s*_EMBEDDING_DIMENSIONS",
        "runtime embedding length validation",
        findings,
    )
    require(
        "database/migrations/002_seed_knowledge_base.py",
        r"len\(embedding\)\s*!=\s*dimensions",
        "seed embedding length validation",
        findings,
    )
    require(
        "docker-compose.yml",
        r"EMBEDDING_DIMENSIONS:\s*\$\{EMBEDDING_DIMENSIONS:-1536\}",
        "Compose 1536-dimensional default",
        findings,
    )

    if findings:
        print("[失败] Embedding 契约检查")
        print("\n".join(findings))
        return 1
    print("[通过] Embedding 契约：1536 维")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
