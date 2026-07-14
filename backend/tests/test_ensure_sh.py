from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def make_repository(tmp_path: Path, *, uv_version: str = "0.11.26") -> tuple[Path, Path]:
    repository = tmp_path / "repository"
    (repository / "scripts").mkdir(parents=True)
    (repository / "backend").mkdir()
    (repository / "frontend").mkdir()
    shutil.copy2(ROOT / "scripts" / "ensure.sh", repository / "scripts" / "ensure.sh")
    (repository / "backend" / "uv.lock").write_text("locked\n", encoding="utf-8")
    (repository / "frontend" / "package-lock.json").write_text("lock-v1\n", encoding="utf-8")

    tools = tmp_path / "tools"
    tools.mkdir()
    log = tmp_path / "commands.log"
    (tools / "uv").write_text(
        f"""#!/usr/bin/env bash
if [[ $1 == --version ]]; then echo 'uv {uv_version}'; exit 0; fi
echo "uv $*" >> "$ARTIGAS_TEST_LOG"
if [[ $1 == sync && $* == *--reinstall* ]]; then mkdir -p .venv/bin; fi
exit 0
""",
        encoding="utf-8",
    )
    (tools / "node").write_text("#!/usr/bin/env bash\necho v24.18.0\n", encoding="utf-8")
    (tools / "npm").write_text(
        """#!/usr/bin/env bash
if [[ $1 == --version ]]; then echo 11.16.0; exit 0; fi
echo "npm $*" >> "$ARTIGAS_TEST_LOG"
if [[ $1 == ci ]]; then mkdir -p node_modules; fi
exit 0
""",
        encoding="utf-8",
    )
    for tool in tools.iterdir():
        tool.chmod(0o755)
    return repository, log


def run_ensure(repository: Path, log: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PATH"] = f"{log.parent / 'tools'}:{environment['PATH']}"
    environment["ARTIGAS_TEST_LOG"] = str(log)
    return subprocess.run(
        [str(repository / "scripts" / "ensure.sh"), *arguments],
        cwd=repository,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def test_ensure_sh_installs_fresh_dependencies_then_uses_fast_path(tmp_path: Path) -> None:
    repository, log = make_repository(tmp_path)

    first = run_ensure(repository, log, "--skip-hook-install")
    assert first.returncode == 0, first.stderr
    first_commands = log.read_text(encoding="utf-8")
    assert "uv sync --locked --dev --reinstall" in first_commands
    assert "npm ci" in first_commands
    assert (repository / "backend/.venv/.artigas-project-path").read_text().strip() == str(
        repository / "backend"
    )
    assert (repository / "frontend/node_modules/.artigas-package-lock.sha256").is_file()

    log.write_text("", encoding="utf-8")
    second = run_ensure(repository, log, "--skip-hook-install")
    assert second.returncode == 0, second.stderr
    second_commands = log.read_text(encoding="utf-8")
    assert "uv sync --locked --dev --check" in second_commands
    assert "npm ls --depth=0" in second_commands
    assert "--reinstall" not in second_commands
    assert "npm ci" not in second_commands


def test_ensure_sh_repairs_dependencies_after_repository_move(tmp_path: Path) -> None:
    repository, log = make_repository(tmp_path)
    assert run_ensure(repository, log, "--skip-hook-install").returncode == 0
    moved = tmp_path / "moved-repository"
    shutil.copytree(repository, moved)
    log.write_text("", encoding="utf-8")

    result = run_ensure(moved, log, "--skip-hook-install")

    assert result.returncode == 0, result.stderr
    assert "uv sync --locked --dev --reinstall" in log.read_text(encoding="utf-8")
    assert (moved / "backend/.venv/.artigas-project-path").read_text().strip() == str(
        moved / "backend"
    )


def test_ensure_sh_reinstalls_frontend_when_lock_changes(tmp_path: Path) -> None:
    repository, log = make_repository(tmp_path)
    assert run_ensure(repository, log, "--skip-hook-install").returncode == 0
    (repository / "frontend/package-lock.json").write_text("lock-v2\n", encoding="utf-8")
    log.write_text("", encoding="utf-8")

    result = run_ensure(repository, log, "--skip-hook-install")

    assert result.returncode == 0, result.stderr
    assert "npm ci" in log.read_text(encoding="utf-8")


def test_ensure_sh_rejects_unsupported_uv(tmp_path: Path) -> None:
    repository, log = make_repository(tmp_path, uv_version="0.11.25")

    result = run_ensure(repository, log, "--skip-hook-install")

    assert result.returncode != 0
    assert "install uv 0.11.26" in result.stderr
