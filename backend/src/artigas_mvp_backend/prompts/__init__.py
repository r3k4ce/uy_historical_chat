from importlib.resources import files


def load_artigas_prompt() -> str:
    return files(__package__).joinpath("artigas.txt").read_text(encoding="utf-8")
