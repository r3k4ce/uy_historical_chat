import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_repository_documentation_covers_required_operation_contract() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    env_example = (ROOT / "backend" / ".env.example").read_text(encoding="utf-8")
    assert not (ROOT / ".env.example").exists()

    environment_names = (
        "GEMINI_API_KEY",
        "GEMINI_FILE_SEARCH_STORE",
        "GEMINI_MODEL",
        "GEMINI_THINKING_LEVEL",
        "GEMINI_MAX_OUTPUT_TOKENS",
        "GEMINI_TEMPERATURE",
        "MAX_USER_MESSAGE_CHARS",
        "MAX_CONVERSATION_TURNS",
        "GEMINI_REQUEST_TIMEOUT_SECONDS",
        "GEMINI_MAX_RETRIES",
        "COST_WARNING_USD_PER_REQUEST",
    )
    for name in environment_names:
        assert name in readme
        assert name in env_example

    required_readme_text = (
        "Python 3.12",
        ".\\scripts\\ensure.ps1",
        "./scripts/ensure.sh",
        "artigas_mvp_backend.dev_corpus",
        "artigas_mvp_backend.ingest",
        "artigas_mvp_backend.main:app",
        "artigas_mvp_backend.evaluate --case instructions-xiii --confirm-cost",
        ".\\scripts\\check.ps1",
        "./scripts/check.sh",
        "sintético",
        "reemplaz",
        "no se muestra un número de página inventado",
        "desaparecen al recargar",
        "guardarraíl de experiencia de usuario",
        "retención predeterminada del proveedor",
        "backend/.env",
    )
    for text in required_readme_text:
        assert text in readme


def test_native_powershell_scripts_exist_and_cover_full_repository_checks() -> None:
    check_path = ROOT / "scripts" / "check.ps1"
    fix_path = ROOT / "scripts" / "fix.ps1"
    assert check_path.is_file()
    assert fix_path.is_file()

    check = check_path.read_text(encoding="utf-8")
    fix = fix_path.read_text(encoding="utf-8")
    for script in (check, fix):
        assert "ensure.ps1" in script
        assert '$ErrorActionPreference = "Stop"' in script
        assert "try" in script
        assert "finally" in script
        assert "$LASTEXITCODE" in script
        assert "npm.cmd" in script
        for command in (
            '@("run", "test")',
            '@("run", "typecheck")',
            '@("run", "lint")',
            '@("run", "build")',
        ):
            assert command in script
        assert '@("run", "--locked", "python", "-m", "pyright")' in script
        assert '@("run", "--locked", "python", "-m", "pytest")' in script

    assert '@("run", "--locked", "python", "-m", "ruff", "format", "--check", ".")' in check
    assert '@("run", "--locked", "python", "-m", "ruff", "check", ".")' in check
    assert '@("run", "--locked", "python", "-m", "ruff", "check", "--fix", ".")' in fix
    assert '@("run", "--locked", "python", "-m", "ruff", "format", ".")' in fix


def test_dependency_and_tool_versions_are_declared_at_their_project_roots() -> None:
    assert not (ROOT / ".python-version").exists()
    backend = tomllib.loads((ROOT / "backend" / "pyproject.toml").read_text(encoding="utf-8"))
    runtime = backend["project"]["dependencies"]
    dev = backend["dependency-groups"]["dev"]

    assert backend["tool"]["uv"]["required-version"] == "==0.11.26"
    assert any(item.startswith("pydantic") for item in runtime)
    assert any(item.startswith("google-genai") for item in runtime)
    assert not any(item.startswith(("reportlab", "pytest", "ruff", "pyright")) for item in runtime)
    assert any(item.startswith("reportlab") for item in dev)
    assert any(item.startswith("pyright[nodejs]") for item in dev)

    package = __import__("json").loads(
        (ROOT / "frontend" / "package.json").read_text(encoding="utf-8")
    )
    assert package["engines"] == {"node": ">=24 <25", "npm": ">=11 <12"}
    package_lock = __import__("json").loads(
        (ROOT / "frontend" / "package-lock.json").read_text(encoding="utf-8")
    )
    assert package_lock["packages"][""]["engines"] == package["engines"]


def test_ensure_scripts_define_move_safe_dependency_and_hook_contracts() -> None:
    bash = (ROOT / "scripts" / "ensure.sh").read_text(encoding="utf-8")
    powershell = (ROOT / "scripts" / "ensure.ps1").read_text(encoding="utf-8")

    for script in (bash, powershell):
        assert ".artigas-project-path" in script
        assert ".artigas-package-lock.sha256" in script
        assert "0.11.26" in script
        assert "--locked" in script
        assert "--dev" in script
        assert "--reinstall" in script
        assert "npm" in script
        assert "ci" in script
        assert "ls" in script
        assert "pre_commit" in script
        assert "ARTIGAS_SKIP_HOOK_INSTALL" in script

    assert "--skip-hook-install" in bash
    assert "SkipHookInstall" in powershell
    assert "sha256sum" in bash or "shasum" in bash


def test_root_scripts_hook_and_ci_share_the_orchestration_contract() -> None:
    check_sh = (ROOT / "scripts" / "check.sh").read_text(encoding="utf-8")
    fix_sh = (ROOT / "scripts" / "fix.sh").read_text(encoding="utf-8")
    run_sh = (ROOT / "scripts" / "run.sh").read_text(encoding="utf-8")
    pre_commit = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    for script in (check_sh, fix_sh, run_sh):
        assert '"$root/scripts/ensure.sh"' in script
    for script in (check_sh, fix_sh):
        assert "python -m pytest" in script
    assert "python -m uvicorn" in run_sh
    assert "wait -n" in run_sh
    assert "pre-commit" in pre_commit
    assert "pre-push" not in pre_commit
    assert "ARTIGAS_SKIP_HOOK_INSTALL" in pre_commit
    assert "scripts/check.sh" in pre_commit
    assert "version: 0.11.26" in ci
    assert "node-version: 24" in ci
    assert "ARTIGAS_SKIP_HOOK_INSTALL" in ci
    assert "./scripts/check.sh" in ci
