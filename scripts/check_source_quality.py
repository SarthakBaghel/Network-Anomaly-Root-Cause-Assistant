from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCANNED_SUFFIXES = {
    ".env",
    ".js",
    ".json",
    ".mjs",
    ".py",
    ".ts",
    ".tsx",
    ".yaml",
    ".yml",
}
IGNORED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "dist",
    "node_modules",
    "test-results",
}
SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    "Slack token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    "literal credential": re.compile(
        r"(?i)\b(?:api[_-]?key|client[_-]?secret|password|token)\b\s*[:=]\s*"
        r"['\"][^'\"\n]{12,}['\"]"
    ),
}


def _tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    files: list[Path] = []
    for relative in result.stdout.splitlines():
        path = ROOT / relative
        if not path.is_file() or any(part in IGNORED_PARTS for part in path.parts):
            continue
        if path.suffix in SCANNED_SUFFIXES or path.name.startswith(".env"):
            files.append(path)
    return files


def main() -> None:
    findings: list[str] = []
    for path in _tracked_files():
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for label, pattern in SECRET_PATTERNS.items():
            for match in pattern.finditer(content):
                line = content.count("\n", 0, match.start()) + 1
                findings.append(f"{path.relative_to(ROOT)}:{line}: possible {label}")

    production_frontend = ROOT / "frontend" / "src"
    for path in production_frontend.rglob("*"):
        if not path.is_file() or path.suffix not in {".ts", ".tsx"}:
            continue
        content = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(content.splitlines(), start=1):
            if re.search(r"\bas\s+any\b", line):
                findings.append(
                    f"{path.relative_to(ROOT)}:{line_number}: production 'as any' cast"
                )

    generated_types = (
        ROOT / "frontend" / "src" / "contracts" / "openapi.d.ts"
    ).read_text(encoding="utf-8")
    forbidden_empty_business_fields = (
        "raw_payload?: Record<string, never>",
        "payload?: Record<string, never>",
        "raw?: Record<string, never>",
    )
    for marker in forbidden_empty_business_fields:
        if marker in generated_types:
            findings.append(f"frontend/src/contracts/openapi.d.ts: unusable generated {marker}")

    if findings:
        raise SystemExit("source-quality check failed:\n" + "\n".join(findings))
    print("source-quality check passed: no high-confidence secrets or type escapes")


if __name__ == "__main__":
    main()
