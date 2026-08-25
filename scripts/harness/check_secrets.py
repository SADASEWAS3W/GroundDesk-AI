"""Fail when commit candidates contain likely credentials or private key material."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKIP_PARTS = {".git", "node_modules", ".next", ".venv", "__pycache__"}
SKIP_FILES = {".env", ".env.local"}
TEXT_SUFFIXES = {
    "", ".cfg", ".css", ".env", ".html", ".ini", ".js", ".json", ".jsx",
    ".md", ".mjs", ".ps1", ".py", ".sh", ".sql", ".toml", ".ts", ".tsx",
    ".txt", ".yaml", ".yml",
}

SECRET_PATTERNS = [
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("OpenAI-style key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")),
    ("GitHub token", re.compile(r"\bgh[opusr]_[A-Za-z0-9]{20,}\b")),
    (
        "credential assignment",
        re.compile(
            r"(?im)^\s*(?:OPENAI|DASHSCOPE|DEEPSEEK|ANTHROPIC|GEMINI|GOOGLE|"
            r"OPENROUTER)?_?(?:API_KEY|TOKEN|SECRET|PASSWORD)[ \t]*[:=][ \t]*[\"']?([^\s\"']+)"
        ),
    ),
]

SAFE_VALUE_MARKERS = (
    "your-", "example", "placeholder", "changeme", "redacted", "dummy",
    "test-", "env-", "os.", "${", "$(", "<", "***", "...",
)


def candidate_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    files: list[Path] = []
    for name in result.stdout.splitlines():
        path = ROOT / name
        if not path.is_file() or path.name in SKIP_FILES:
            continue
        if any(part in SKIP_PARTS for part in path.parts):
            continue
        if path.suffix.lower() in TEXT_SUFFIXES and path.stat().st_size <= 2_000_000:
            files.append(path)
    return files


def main() -> int:
    findings: list[str] = []
    for path in candidate_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for label, pattern in SECRET_PATTERNS:
            for match in pattern.finditer(text):
                value = match.group(1) if match.lastindex else match.group(0)
                normalized = value.strip().lower()
                if (
                    not normalized
                    or normalized in {"none", "str", "str|none", "str | none"}
                    or normalized.endswith("_api_key")
                    or any(marker in normalized for marker in SAFE_VALUE_MARKERS)
                ):
                    continue
                line = text.count("\n", 0, match.start()) + 1
                findings.append(f"{path.relative_to(ROOT)}:{line}: possible {label}")

    if findings:
        print("[失败] 密钥扫描")
        print("\n".join(findings))
        return 1
    print("[通过] 密钥扫描")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
