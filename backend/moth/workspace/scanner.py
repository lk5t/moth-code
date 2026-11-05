"""Project scanning: file tree, languages, build systems, ignore rules."""

from __future__ import annotations

import fnmatch
import os
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_IGNORES = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env", "dist", "build", "target",
    ".next", ".nuxt", ".cache", ".pytest_cache", ".mypy_cache", ".idea", ".vscode", "coverage",
    ".tox", ".gradle", "bin", "obj", ".moth",
}

LANGUAGES = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript",
    ".rs": "Rust", ".go": "Go", ".java": "Java", ".kt": "Kotlin", ".c": "C", ".h": "C", ".cpp": "C++",
    ".cc": "C++", ".hpp": "C++", ".cs": "C#", ".rb": "Ruby", ".php": "PHP", ".swift": "Swift",
    ".html": "HTML", ".css": "CSS", ".scss": "SCSS", ".json": "JSON", ".toml": "TOML", ".yaml": "YAML",
    ".yml": "YAML", ".md": "Markdown", ".sh": "Shell", ".ps1": "PowerShell", ".sql": "SQL", ".lua": "Lua",
    ".vue": "Vue", ".svelte": "Svelte", ".dart": "Dart", ".zig": "Zig",
}

BUILD_MARKERS = {
    "package.json": "npm", "pyproject.toml": "python", "setup.py": "python", "requirements.txt": "python",
    "Cargo.toml": "cargo", "go.mod": "go", "pom.xml": "maven", "build.gradle": "gradle",
    "build.gradle.kts": "gradle", "CMakeLists.txt": "cmake", "Makefile": "make", "*.sln": "dotnet",
    "*.csproj": "dotnet", "Gemfile": "ruby", "composer.json": "php",
}

TEST_COMMANDS = {
    "npm": "npm test", "python": "python -m pytest", "cargo": "cargo test", "go": "go test ./...",
    "maven": "mvn test", "gradle": "gradle test", "dotnet": "dotnet test", "make": "make test",
}
BUILD_COMMANDS = {
    "npm": "npm run build", "cargo": "cargo build", "go": "go build ./...", "maven": "mvn package",
    "gradle": "gradle build", "dotnet": "dotnet build", "make": "make", "cmake": "cmake --build build",
}


def load_gitignore(root: Path) -> list[str]:
    gi = root / ".gitignore"
    if not gi.exists():
        return []
    pats = []
    for line in gi.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and not line.startswith("!"):
            pats.append(line.rstrip("/"))
    return pats


def ignored(rel: str, name: str, patterns: list[str]) -> bool:
    if name in DEFAULT_IGNORES:
        return True
    for pat in patterns:
        p = pat.lstrip("/")
        if fnmatch.fnmatch(name, p) or fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(rel, p + "/*"):
            return True
    return False


def iter_files(root: Path, max_files: int = 20000):
    """Yield (relative posix path, absolute Path) for non-ignored files."""
    root = Path(root).resolve()
    patterns = load_gitignore(root)
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        rel_dir = "" if rel_dir == "." else rel_dir
        dirnames[:] = sorted(
            d for d in dirnames
            if not ignored(f"{rel_dir}/{d}".lstrip("/"), d, patterns) and not os.path.islink(os.path.join(dirpath, d))
        )
        for fn in sorted(filenames):
            rel = f"{rel_dir}/{fn}".lstrip("/")
            if ignored(rel, fn, patterns):
                continue
            yield rel, Path(dirpath) / fn
            count += 1
            if count >= max_files:
                return


@dataclass
class ProjectSummary:
    root: str
    file_count: int = 0
    total_bytes: int = 0
    languages: dict[str, int] = field(default_factory=dict)
    build_systems: list[str] = field(default_factory=list)
    test_command: str | None = None
    build_command: str | None = None
    entry_points: list[str] = field(default_factory=list)
    has_git: bool = False
    readme: str | None = None

    def describe(self) -> str:
        langs = ", ".join(f"{k} ({v})" for k, v in sorted(self.languages.items(), key=lambda kv: -kv[1])[:6])
        lines = [
            f"Project root: {self.root}",
            f"Files: {self.file_count} ({self.total_bytes // 1024} KiB)",
            f"Languages: {langs or 'unknown'}",
            f"Build systems: {', '.join(self.build_systems) or 'none detected'}",
        ]
        if self.test_command:
            lines.append(f"Test command: {self.test_command}")
        if self.build_command:
            lines.append(f"Build command: {self.build_command}")
        if self.entry_points:
            lines.append(f"Entry points: {', '.join(self.entry_points)}")
        return "\n".join(lines)


ENTRY_NAMES = {"main.py", "app.py", "__main__.py", "index.ts", "index.tsx", "index.js", "main.ts", "main.tsx",
               "main.rs", "lib.rs", "main.go", "Program.cs", "manage.py", "server.py", "cli.py"}


def scan_project(root: Path | str) -> ProjectSummary:
    root = Path(root).resolve()
    summary = ProjectSummary(root=str(root), has_git=(root / ".git").exists())
    langs: Counter[str] = Counter()
    builds: list[str] = []
    for rel, path in iter_files(root):
        summary.file_count += 1
        try:
            summary.total_bytes += path.stat().st_size
        except OSError:
            pass
        lang = LANGUAGES.get(path.suffix.lower())
        if lang:
            langs[lang] += 1
        if "/" not in rel:
            for marker, system in BUILD_MARKERS.items():
                if fnmatch.fnmatch(path.name, marker) and system not in builds:
                    builds.append(system)
            if path.name.lower().startswith("readme") and summary.readme is None:
                summary.readme = rel
        if path.name in ENTRY_NAMES and rel.count("/") <= 2:
            summary.entry_points.append(rel)
    summary.languages = dict(langs)
    summary.build_systems = builds
    for b in builds:
        summary.test_command = summary.test_command or TEST_COMMANDS.get(b)
        summary.build_command = summary.build_command or BUILD_COMMANDS.get(b)
    summary.entry_points = summary.entry_points[:10]
    return summary


def file_tree(root: Path | str, max_entries: int = 5000) -> list[dict]:
    """Flat list of non-ignored files and directories for the explorer."""
    root = Path(root).resolve()
    dirs: set[str] = set()
    files: list[dict] = []
    for rel, path in iter_files(root, max_files=max_entries):
        parts = rel.split("/")
        for i in range(1, len(parts)):
            dirs.add("/".join(parts[:i]))
        files.append({"path": rel, "dir": False})
    return sorted([{"path": d, "dir": True} for d in dirs] + files, key=lambda e: e["path"].lower())
