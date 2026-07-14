"""Create a new Gemini File Search store and upload one validated PDF."""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from artigas_mvp_backend.config import load_backend_dotenv


class IngestionError(Exception):
    """A safe ingestion failure, optionally associated with a newly created store."""

    def __init__(self, message: str, *, store_name: str | None = None) -> None:
        super().__init__(message)
        self.store_name = store_name


def validate_pdf_path(path: Path) -> Path:
    if not path.exists():
        raise IngestionError("El archivo PDF no existe.")
    if not path.is_file():
        raise IngestionError("La ruta indicada no es un archivo regular.")
    if path.suffix.lower() != ".pdf":
        raise IngestionError("El archivo debe tener extensión .pdf.")
    with path.open("rb") as pdf:
        if pdf.read(5) != b"%PDF-":
            raise IngestionError("El archivo no contiene una cabecera PDF válida.")
    return path


def _value(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _default_client_factory(api_key: str) -> Any:
    from importlib import import_module

    genai = import_module("google.genai")
    return genai.Client(api_key=api_key)


def ingest_pdf(
    pdf_path: Path,
    *,
    client: Any,
    sleep_fn: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> str:
    """Create a store, upload ``pdf_path``, and wait for indexing to complete."""
    path = validate_pdf_path(pdf_path)
    timestamp = now().strftime("%Y%m%dT%H%M%SZ")
    try:
        store = client.file_search_stores.create(
            config={"display_name": f"artigas-mvp-{timestamp}"}
        )
    except Exception:
        raise IngestionError("No fue posible crear el almacén de File Search.") from None
    store_name = _value(store, "name")
    if not isinstance(store_name, str) or not store_name:
        raise IngestionError("Gemini no devolvió el identificador del nuevo almacén.")

    try:
        operation = client.file_search_stores.upload_to_file_search_store(
            file=str(path),
            file_search_store_name=store_name,
            config={
                "display_name": path.name,
                "mime_type": "application/pdf",
                "chunking_config": {
                    "white_space_config": {
                        "max_tokens_per_chunk": 400,
                        "max_overlap_tokens": 60,
                    }
                },
            },
        )
        while not bool(_value(operation, "done")):
            sleep_fn(5)
            operation = client.operations.get(operation)

        if _value(operation, "error"):
            raise IngestionError("Gemini informó un error durante la indexación.")
        indexed_store = client.file_search_stores.get(name=store_name)
        failed_documents = _value(indexed_store, "failed_documents_count") or 0
        if int(failed_documents) > 0:
            raise IngestionError("El documento no pudo indexarse.")
    except IngestionError as exc:
        raise IngestionError(str(exc), store_name=store_name) from None
    except Exception:
        raise IngestionError(
            "No fue posible completar la carga del documento.", store_name=store_name
        ) from None

    return store_name


def main(
    argv: list[str] | None = None,
    *,
    client_factory: Callable[[str], Any] = _default_client_factory,
    sleep_fn: Callable[[float], None] = time.sleep,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    parser = argparse.ArgumentParser(description="Carga un PDF en un nuevo File Search store.")
    parser.add_argument("pdf_path", type=Path)
    args = parser.parse_args(argv)

    load_backend_dotenv()

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        print("Falta configurar GEMINI_API_KEY.", file=stderr)
        return 2

    try:
        path = validate_pdf_path(args.pdf_path)
        client = client_factory(api_key)
        store_name = ingest_pdf(path, client=client, sleep_fn=sleep_fn)
    except IngestionError as exc:
        if exc.store_name:
            print(
                f"La carga falló. Almacén creado para inspección manual: {exc.store_name}",
                file=stderr,
            )
        else:
            print(str(exc), file=stderr)
        return 1
    except Exception:
        print("No fue posible iniciar la carga del documento.", file=stderr)
        return 1

    print(f"GEMINI_FILE_SEARCH_STORE={store_name}", file=stdout)
    print("Copie este valor en su archivo .env y reinicie el backend.", file=stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
