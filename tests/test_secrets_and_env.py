"""Verifies no secret values are hardcoded anywhere in tracked source, and
that .env is properly git-ignored.
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Patterns that look like real key material, not env-var *names*.
SECRET_PATTERNS = [
    re.compile(r"sk-or-v1-[a-zA-Z0-9]{20,}"),
    re.compile(r"sk-proj-[a-zA-Z0-9_-]{20,}"),
    re.compile(r"github_pat_[a-zA-Z0-9_]{20,}"),
    re.compile(r"ghp_[a-zA-Z0-9]{20,}"),
    re.compile(r"AIza[a-zA-Z0-9_-]{20,}"),
]

SCAN_EXTENSIONS = {".py", ".md", ".txt", ".json", ".toml", ".cfg", ".ini", ".yml", ".yaml"}
SKIP_DIRS = {".venv", "venv", ".git", "__pycache__", "node_modules"}


def _tracked_files_to_scan():
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in SCAN_EXTENSIONS:
            continue
        if path.name == ".env":
            continue
        yield path


def test_no_hardcoded_secret_values_in_source():
    offenders = []
    for path in _tracked_files_to_scan():
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, f"Possible hardcoded secret found in: {offenders}"


def test_env_file_is_gitignored():
    result = subprocess.run(
        ["git", "check-ignore", ".env"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, ".env is NOT git-ignored!"


def test_env_file_is_not_tracked_by_git():
    result = subprocess.run(
        ["git", "ls-files", ".env"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "", ".env must never be committed"
