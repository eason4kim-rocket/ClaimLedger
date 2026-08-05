#!/usr/bin/env python3
"""Build and verify the public ClaimLedger Skill archive.

The archive is intentionally allow-listed. Competition documents and reconstructed
demos live in the repository, but only files required to install, run, and test the
Skill may enter the ModelScope ZIP.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".qoder" / "skills" / "claimledger-audit"
DIST = ROOT / "dist"

ALLOWED_ROOT_FILES = {"SKILL.md", "LICENSE", "pyproject.toml"}
ALLOWED_ROOT_DIRS = {"agents", "assets", "references", "scripts", "src", "tests"}
ALLOWED_SUFFIXES_BY_ROOT = {
    "agents": {".yaml", ".yml"},
    "assets": {".html", ".png", ".svg", ".yaml", ".yml"},
    "references": {".md"},
    "scripts": {".py", ".sh"},
    "src": {".css", ".html", ".js", ".py"},
    "tests": {".json", ".py", ".yaml", ".yml"},
}
REQUIRED_MEMBERS = {
    "SKILL.md",
    "LICENSE",
    "pyproject.toml",
    "agents/openai.yaml",
    "assets/claimledger-icon-1024.png",
    "assets/models.yaml",
    "assets/rules/generic-zh.yaml",
    "assets/ui/claimledger-brief.html",
    "references/statuses.md",
    "scripts/claimledger.py",
    "src/claimledger/__init__.py",
    "tests/test_end_to_end.py",
    "tests/test_packaging.py",
}
EXCLUDED_PARTS = {
    ".git",
    ".venv",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "__pycache__",
    "artifacts",
    "cache",
    "customer-data",
    "data",
    "evidence",
    "jobs",
    "logs",
    "model-cache",
    "models",
    "outputs",
    "private",
    "tmp",
    "user-documents",
}
EXCLUDED_NAMES = {
    ".DS_Store",
    ".env",
    "api-token",
}
EXCLUDED_SUFFIXES = {
    ".bin",
    ".blob",
    ".db",
    ".gguf",
    ".log",
    ".onnx",
    ".pdmodel",
    ".pdparams",
    ".pyc",
    ".pyo",
    ".safetensors",
    ".sqlite",
    ".sqlite3",
    ".tmp",
}
SOURCE_DATE = (2026, 1, 1, 0, 0, 0)
MAX_FILE_BYTES = 5_000_000
MAX_ARCHIVE_BYTES = 50_000_000
TEXT_SUFFIXES = {
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".py",
    ".sh",
    ".svg",
    ".toml",
    ".yaml",
    ".yml",
}
FORBIDDEN_TEXT_PATTERNS = {
    "macOS absolute user path": re.compile(r"/Users/[^/\s]+/"),
    "Windows absolute user path": re.compile(r"[A-Za-z]:\\Users\\[^\\\s]+\\"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "OpenAI-style secret": re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    "bearer token": re.compile(r"\bAuthorization\s*:\s*Bearer\s+\S+", re.IGNORECASE),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build and verify the ClaimLedger Skill ZIP")
    parser.add_argument(
        "--output",
        type=Path,
        default=DIST / "claimledger-audit.zip",
        help="archive destination (default: dist/claimledger-audit.zip)",
    )
    parser.add_argument(
        "--verify-only",
        type=Path,
        help="verify an existing archive without rebuilding it",
    )
    parser.add_argument(
        "--upload-dir",
        type=Path,
        default=DIST / "modelscope-upload",
        help="同时生成可直接上传的展开目录",
    )
    return parser.parse_args()


def archive_name(path: Path) -> str:
    return path.relative_to(SKILL).as_posix()


def include(path: Path) -> bool:
    relative = path.relative_to(SKILL)
    if not relative.parts:
        return False
    top = relative.parts[0]
    if len(relative.parts) == 1:
        if top not in ALLOWED_ROOT_FILES:
            return False
    elif top not in ALLOWED_ROOT_DIRS:
        return False
    elif path.suffix.lower() not in ALLOWED_SUFFIXES_BY_ROOT[top]:
        return False
    if any(part in EXCLUDED_PARTS or part.endswith(".egg-info") for part in relative.parts):
        return False
    if path.name in EXCLUDED_NAMES or path.suffix.lower() in EXCLUDED_SUFFIXES:
        return False
    if path.is_symlink():
        raise SystemExit(f"refusing to package symlink: {relative}")
    if not path.is_file():
        return False
    if path.stat().st_size > MAX_FILE_BYTES:
        raise SystemExit(f"refusing to package file larger than {MAX_FILE_BYTES} bytes: {relative}")
    return True


def selected_files() -> list[Path]:
    if not SKILL.is_dir():
        raise SystemExit(f"Skill directory not found: {SKILL}")
    files = [path for path in SKILL.rglob("*") if include(path)]
    names = {archive_name(path) for path in files}
    missing = REQUIRED_MEMBERS - names
    if missing:
        raise SystemExit("required package members are missing: " + ", ".join(sorted(missing)))
    return sorted(files, key=archive_name)


def zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, SOURCE_DATE)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    return info


def build(destination: Path) -> None:
    files = selected_files()
    destination = destination.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()

    manifest_files: list[dict[str, str | int]] = []
    with zipfile.ZipFile(destination, "w") as archive:
        for path in files:
            data = path.read_bytes()
            name = archive_name(path)
            archive.writestr(zip_info(name), data)
            manifest_files.append(
                {
                    "path": name,
                    "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
        manifest = {
            "format": "claimledger-skill-package-v1",
            "skill": "claimledger-audit",
            "files": manifest_files,
        }
        archive.writestr(
            zip_info("PACKAGE_MANIFEST.json"),
            (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )


def materialize_upload_dir(archive_path: Path, destination: Path) -> None:
    archive_path = archive_path.expanduser().resolve()
    destination = destination.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="claimledger-upload-",
        dir=destination.parent,
    ) as temporary:
        staging = Path(temporary) / "payload"
        staging.mkdir()
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(staging)
        root_skill_files = list(staging.glob("SKILL.md"))
        nested_skill_files = [
            path for path in staging.rglob("SKILL.md") if path.parent != staging
        ]
        if len(root_skill_files) != 1 or nested_skill_files:
            raise SystemExit("upload directory must contain exactly one root-level SKILL.md")
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(staging, destination)


def verify_text_content(name: str, data: bytes) -> None:
    if PurePosixPath(name).suffix.lower() not in TEXT_SUFFIXES:
        return
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SystemExit(f"text file is not valid UTF-8: {name}") from exc
    for label, pattern in FORBIDDEN_TEXT_PATTERNS.items():
        if pattern.search(text):
            raise SystemExit(f"forbidden {label} found in package content: {name}")


def verify_skill_frontmatter(data: bytes) -> None:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SystemExit("SKILL.md is not valid UTF-8") from exc
    match = re.match(r"\A---\r?\n(?P<header>.*?)\r?\n---(?:\r?\n|\Z)", text, re.DOTALL)
    if not match:
        raise SystemExit("invalid SKILL.md: YAML frontmatter is missing")
    header = match.group("header")
    name = re.search(r"(?m)^name:\s*(?P<value>[^\r\n]+?)\s*$", header)
    description = re.search(r"(?m)^description:\s*(?P<value>[^\r\n]+?)\s*$", header)
    if not name or name.group("value").strip("\"'") != "claimledger-audit":
        raise SystemExit("invalid SKILL.md: name must be claimledger-audit")
    if not description:
        raise SystemExit("invalid SKILL.md: a single-line description is required")
    description_value = description.group("value").strip("\"'")
    if not description_value or len(description_value) > 1024:
        raise SystemExit("invalid SKILL.md: description must contain 1-1024 characters")


def verify(destination: Path) -> dict[str, str | int]:
    destination = destination.expanduser().resolve()
    if not destination.is_file():
        raise SystemExit(f"archive not found: {destination}")
    with zipfile.ZipFile(destination) as archive:
        bad_member = archive.testzip()
        if bad_member:
            raise SystemExit(f"CRC verification failed: {bad_member}")
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise SystemExit("invalid package: duplicate archive members")
        if "SKILL.md" not in names:
            raise SystemExit("invalid package: SKILL.md is not at the archive root")
        missing = REQUIRED_MEMBERS - set(names)
        if missing:
            raise SystemExit("invalid package: missing " + ", ".join(sorted(missing)))
        if "PACKAGE_MANIFEST.json" not in names:
            raise SystemExit("invalid package: PACKAGE_MANIFEST.json is missing")
        verify_skill_frontmatter(archive.read("SKILL.md"))
        total_uncompressed = 0
        for name in names:
            member = PurePosixPath(name)
            if member.is_absolute() or ".." in member.parts or not member.parts:
                raise SystemExit(f"invalid package path: {name}")
            info = archive.getinfo(name)
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise SystemExit(f"invalid package: symlink member found: {name}")
            if info.file_size > MAX_FILE_BYTES:
                raise SystemExit(f"invalid package: oversized member found: {name}")
            total_uncompressed += info.file_size
            if len(member.parts) > 1 and member.parts[0] not in ALLOWED_ROOT_DIRS:
                raise SystemExit(f"unexpected top-level directory: {name}")
            if len(member.parts) == 1 and name not in ALLOWED_ROOT_FILES | {"PACKAGE_MANIFEST.json"}:
                raise SystemExit(f"unexpected root member: {name}")
            if (
                len(member.parts) > 1
                and member.suffix.lower() not in ALLOWED_SUFFIXES_BY_ROOT[member.parts[0]]
            ):
                raise SystemExit(f"unexpected file type: {name}")
            if any(part in EXCLUDED_PARTS or part.endswith(".egg-info") for part in member.parts):
                raise SystemExit(f"excluded content found: {name}")
            if member.name in EXCLUDED_NAMES or member.suffix.lower() in EXCLUDED_SUFFIXES:
                raise SystemExit(f"unsafe file found: {name}")
            verify_text_content(name, archive.read(name))
        if total_uncompressed > MAX_ARCHIVE_BYTES:
            raise SystemExit(
                f"invalid package: uncompressed payload exceeds {MAX_ARCHIVE_BYTES} bytes"
            )

        manifest = json.loads(archive.read("PACKAGE_MANIFEST.json"))
        if (
            manifest.get("format") != "claimledger-skill-package-v1"
            or manifest.get("skill") != "claimledger-audit"
            or not isinstance(manifest.get("files"), list)
        ):
            raise SystemExit("invalid package manifest metadata")
        manifest_files = manifest["files"]
        for item in manifest_files:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("path"), str)
                or not isinstance(item.get("bytes"), int)
                or not isinstance(item.get("sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
            ):
                raise SystemExit("invalid package manifest file record")
        recorded = {item["path"]: item for item in manifest_files}
        if len(recorded) != len(manifest_files):
            raise SystemExit("invalid package manifest: duplicate file record")
        payload_names = set(names) - {"PACKAGE_MANIFEST.json"}
        if set(recorded) != payload_names:
            raise SystemExit("package manifest does not match archive members")
        for name in sorted(payload_names):
            data = archive.read(name)
            item = recorded[name]
            if item["bytes"] != len(data) or item["sha256"] != hashlib.sha256(data).hexdigest():
                raise SystemExit(f"package manifest checksum mismatch: {name}")

    return {
        "archive": str(destination),
        "bytes": destination.stat().st_size,
        "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        "members": len(names),
        "skill_md_at_root": "yes",
        "package_policy": "allowlist and checksums verified",
    }


def main() -> None:
    args = parse_args()
    destination = args.verify_only or args.output
    if args.verify_only is None:
        build(destination)
        materialize_upload_dir(destination, args.upload_dir)
    result = verify(destination)
    if args.verify_only is None:
        result["upload_dir"] = str(args.upload_dir.expanduser().resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
