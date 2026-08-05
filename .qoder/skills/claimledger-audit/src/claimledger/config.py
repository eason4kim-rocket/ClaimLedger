from __future__ import annotations

import os
import secrets
import sysconfig
from pathlib import Path


PRIVATE_DIRECTORY_MODE = 0o700
PRIVATE_FILE_MODE = 0o600


def _best_effort_chmod(path: Path, mode: int) -> None:
    """Restrict a local path without making unsupported platforms unusable."""

    try:
        os.chmod(path, mode, follow_symlinks=False)
    except (NotImplementedError, OSError):
        # Windows ACLs and some filesystems do not implement POSIX permission
        # bits. The enclosing private data directory remains the primary
        # boundary there.
        pass


def ensure_private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True, mode=PRIVATE_DIRECTORY_MODE)
    _best_effort_chmod(path, PRIVATE_DIRECTORY_MODE)
    return path


def ensure_private_file(path: Path) -> Path:
    if path.exists():
        _best_effort_chmod(path, PRIVATE_FILE_MODE)
    return path


def data_home() -> Path:
    configured = os.environ.get("CLAIMLEDGER_DATA_DIR")
    root = Path(configured).expanduser() if configured else Path.home() / ".claimledger"
    ensure_private_dir(root)
    resolved = root.resolve()
    ensure_private_dir(resolved)
    return resolved


def jobs_dir() -> Path:
    path = data_home() / "jobs"
    return ensure_private_dir(path)


def models_dir() -> Path:
    path = data_home() / "models"
    return ensure_private_dir(path)


def database_path() -> Path:
    return data_home() / "claimledger.sqlite3"


def api_token() -> str:
    path = data_home() / "api-token"
    if not path.exists():
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, PRIVATE_FILE_MODE)
            try:
                os.write(descriptor, secrets.token_urlsafe(32).encode("utf-8"))
            finally:
                os.close(descriptor)
        except FileExistsError:
            # Another local process won the first-start race.
            pass
    ensure_private_file(path)
    return path.read_text(encoding="utf-8").strip()


def rotate_api_token() -> str:
    """Atomically replace the bootstrap token for a new service process."""

    root = data_home()
    path = root / "api-token"
    token = secrets.token_urlsafe(32)
    temporary = root / f".api-token-{secrets.token_hex(8)}"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, PRIVATE_FILE_MODE)
    try:
        os.write(descriptor, token.encode("utf-8"))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    ensure_private_file(path)
    return token


def model_api_token() -> str:
    path = data_home() / "model-api-token"
    if not path.exists():
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, PRIVATE_FILE_MODE)
        try:
            os.write(descriptor, secrets.token_urlsafe(32).encode("utf-8"))
        finally:
            os.close(descriptor)
    ensure_private_file(path)
    return path.read_text(encoding="utf-8").strip()


def rotate_model_api_token() -> str:
    root = data_home()
    path = root / "model-api-token"
    token = secrets.token_urlsafe(32)
    temporary = root / f".model-api-token-{secrets.token_hex(8)}"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, PRIVATE_FILE_MODE)
    try:
        os.write(descriptor, token.encode("utf-8"))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    ensure_private_file(path)
    return token


def skill_root() -> Path:
    """Return the source Skill root or the installed wheel data root.

    Editable/Qoder installs keep the canonical assets beside ``pyproject.toml``.
    A regular wheel installs the same canonical files under the interpreter's
    data scheme so the console entry point remains self-contained.
    """

    source_root = Path(__file__).resolve().parents[2]
    if (source_root / "assets" / "models.yaml").is_file():
        return source_root
    installed_root = Path(sysconfig.get_path("data")) / "share" / "claimledger"
    if (installed_root / "assets" / "models.yaml").is_file():
        return installed_root
    return source_root
