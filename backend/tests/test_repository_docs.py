from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_repository_documentation_covers_required_operation_contract() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")

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
        "uv sync --dev --locked",
        "npm ci",
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
        assert '@("run", "pyright")' in script
        assert '@("run", "pytest")' in script

    assert '@("run", "ruff", "format", "--check", ".")' in check
    assert '@("run", "ruff", "check", ".")' in check
    assert '@("run", "ruff", "check", "--fix", ".")' in fix
    assert '@("run", "ruff", "format", ".")' in fix
