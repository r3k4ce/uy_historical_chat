import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_repository_documentation_covers_required_operation_contract() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    maintenance = (ROOT / "docs" / "corpus-maintenance.md").read_text(encoding="utf-8")
    agent_guidance = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    env_example = (ROOT / "backend" / ".env.example").read_text(encoding="utf-8")
    assert not (ROOT / ".env.example").exists()

    environment_names = (
        "CHAT_MODEL",
        "GROQ_API_KEY",
        "VOYAGE_API_KEY",
        "EMBEDDING_MODEL",
        "EMBEDDING_DIMENSIONS",
        "CHROMA_PERSIST_DIRECTORY",
        "CHAT_MAX_OUTPUT_TOKENS",
        "CHAT_TEMPERATURE",
        "CHAT_REASONING_EFFORT",
        "MAX_USER_MESSAGE_CHARS",
        "MAX_CONVERSATION_TURNS",
        "CHAT_REQUEST_TIMEOUT_SECONDS",
        "CHAT_MAX_RETRIES",
        "CHAT_INPUT_PRICE_USD_PER_MILLION",
        "CHAT_OUTPUT_PRICE_USD_PER_MILLION",
        "COST_WARNING_USD_PER_REQUEST",
    )
    for name in environment_names:
        assert name in readme
        assert name in env_example
    for removed_name in ("CHAT_PROVIDER", "OPENAI_API_KEY"):
        assert removed_name not in readme
        assert removed_name not in env_example

    required_readme_text = (
        "Python 3.12",
        ".\\scripts\\ensure.ps1",
        "./scripts/ensure.sh",
        "data/artigas-corpus.pdf",
        "artigas_mvp_backend.corpus prepare",
        "artigas_mvp_backend.corpus validate --production",
        "artigas_mvp_backend.index_corpus",
        "artigas_mvp_backend.main:app",
        "artigas_mvp_backend.evaluate run --all --confirm-cost",
        "artigas_mvp_backend.evaluate review",
        "artigas_mvp_backend.evaluate compare",
        "artigas_mvp_backend.evaluate promote",
        ".\\scripts\\check.ps1",
        "./scripts/check.sh",
        "/api/corpus/artigas#page=26",
        "Documento primario",
        "Contexto editorial",
        "Reconstrucción contemporánea",
        "Límite documental",
        "Profundizar",
        "Contrastar",
        "Examinar la fuente",
        "React",
        "no se muestra un número de página inventado",
        "desaparecen al recargar",
        "guardarraíl de experiencia de usuario",
        "historial explícito",
        "backend/.env",
        "Groq model identifier",
        "Inicio rápido",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8000/api/health",
        "Ctrl+C",
        "configuration_error",
        "corpus_unavailable",
        "--replace",
        "Solución de problemas",
        "primera persona",
        "cadencia oriental sutil",
        "0.4` a `0.8",
        "reinicie el backend",
        "terminal nueva",
        "guardan después de cada caso",
        "no entrenan ni modifican el modelo",
    )
    for text in required_readme_text:
        assert text in readme

    forbidden_readme_text = (
        "artigas-dev-corpus.pdf",
        "artigas_mvp_backend.dev_corpus",
        "segundo personaje",
    )
    for text in forbidden_readme_text:
        assert text not in readme

    required_maintenance_text = (
        "data/artigas-corpus.pdf",
        "data/artigas-pages.json",
        "data/source-manifest.yaml",
        "data/learning-map.yaml",
        "Codex",
        "corpus prepare",
        "corpus validate --production",
        "PowerShell",
        "Linux",
        "Índice Chroma",
        "artigas-corpus-v1",
        "SHA-256",
        "400",
        "60",
        "19 casos live",
        "20 turnos live",
        "20 consultas a Voyage",
        "solicitud adicional a Groq",
        "3,25",
        "90 %",
        "15 %",
        "4.096",
        "baseline.json",
        "promote",
        "category_notes",
        "terminal nueva",
        "no entrenan ni modifican el modelo",
        "--replace",
    )
    for text in required_maintenance_text:
        assert text in maintenance

    for obsolete in ("GEMINI_", "Gemini", "File Search", "artigas_mvp_backend.ingest"):
        assert obsolete not in readme
        assert obsolete not in maintenance

    assert "Agents, hooks, CI, and ordinary repository checks" in agent_guidance
    assert "explicit user approval for that specific run" in agent_guidance


def test_personality_rubrics_cover_character_specificity_and_conversational_presence() -> None:
    rubric = (ROOT / "evals" / "rubric.yaml").read_text(encoding="utf-8")

    highest_score = rubric.split("character_fidelity:", maxsplit=1)[1].split("4:", maxsplit=1)[1]
    assert "primera persona" in highest_score
    assert "sabor de época sobrio" in highest_score
    assert "maquinaria de recuperación" in highest_score
    assert "no exige escribir `yo`" in highest_score
    assert "otros actores" in highest_score
    fidelity = rubric.split("character_fidelity:", maxsplit=1)[1].split(
        "conversational_presence:", maxsplit=1
    )[0]
    assert "narración externa" in fidelity
    assert "asistente genérico" in fidelity
    assert "no puede superar 2" in fidelity
    assert "de principio a fin" in fidelity
    presence = rubric.split("conversational_presence:", maxsplit=1)[1]
    assert "presencia conversacional" in presence.casefold()
    assert "apertura" in presence.casefold()
    assert "asistente genérico" in presence.casefold()
    assert "entrada directa" in presence.casefold()
    assert "brevedad" in presence.casefold()
    assert "cierre orgánico" in presence.casefold()
    assert "tesis" in presence.casefold()
    assert "recapitul" in presence.casefold()
    assert "estructura" in presence.casefold()


def test_character_authoring_guide_defines_required_profile_and_manual_gate() -> None:
    guide = (ROOT / "docs" / "character-authoring.md").read_text(encoding="utf-8")

    for field in (
        "convictions",
        "temperament",
        "visitor_relationship",
        "address_form",
        "linguistic_register",
        "rhetorical_habits",
        "conversational_rules",
        "forbidden_inventions",
        "examples",
    ):
        assert f"`{field}`" in guide
    for scenario in (
        "Buenas tardes.",
        "Dígame algo sin discurso",
        "concentrar el poder",
        "¿Y qué cambiaba eso en la relación con Buenos Aires?",
        "una simulación?",
        "Explíqueme aquello.",
    ):
        assert scenario in guide
    assert "3/4" in guide
    assert "3,5" in guide
    assert "una sola pregunta" in guide
    for setting in ("CHAT_TEMPERATURE", "CHAT_REASONING_EFFORT"):
        assert setting in guide
    for value in ("`0.4`", "`0.6`", "`0.8`", "`low`", "`medium`", "`high`"):
        assert value in guide
    assert "reinicie el backend" in guide
    assert "0.6 + medium" in guide


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
    assert not any(item.startswith("google-genai") for item in runtime)
    for dependency in (
        "chromadb",
        "langchain-chroma",
        "langchain-core",
        "langchain-groq",
        "voyageai",
        "langchain-text-splitters",
        "tiktoken",
    ):
        assert any(item.startswith(dependency) for item in runtime)
    assert not any(item.startswith("langchain-openai") for item in runtime)
    assert "pypdf==6.14.2" in runtime
    assert "pyyaml==6.0.3" in runtime
    assert not any(item.startswith("pyyaml") for item in dev)
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
