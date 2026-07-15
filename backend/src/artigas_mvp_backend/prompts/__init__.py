from importlib.resources import files

DOCUMENTARY_LIMIT_RESPONSE = (
    "Los documentos disponibles no me permiten responder esa pregunta con suficiente rigor."
)
RECONSTRUCTION_OPENING = (
    "No conocí ese asunto en mi tiempo. Lo que sigue es una reconstrucción basada en los "
    "principios documentados en las fuentes disponibles."
)


def load_artigas_prompt() -> str:
    template = files(__package__).joinpath("artigas.txt").read_text(encoding="utf-8")
    return template.replace("{{DOCUMENTARY_LIMIT_RESPONSE}}", DOCUMENTARY_LIMIT_RESPONSE).replace(
        "{{RECONSTRUCTION_OPENING}}", RECONSTRUCTION_OPENING
    )
