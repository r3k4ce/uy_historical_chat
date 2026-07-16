"""Generate the deterministic synthetic PDF used for local retrieval development."""

from __future__ import annotations

import argparse
import textwrap
from pathlib import Path
from typing import Final

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas

SECTION_IDS: Final = (
    "DEV-INTRO-01",
    "DEV-FED-01",
    "DEV-INS-01",
    "DEV-CEN-01",
    "DEV-TIE-01",
    "DEV-PRI-01",
    "DEV-MOD-01",
)

_PAGES: Final = (
    (
        "DEV-INTRO-01 | CORPUS SINTÉTICO DE DESARROLLO",
        (
            "ESTADO: SINTETICO. Este documento es una fuente sintética creada exclusivamente "
            "para probar la "
            "recuperación documental de la aplicación Artigas MVP. No es una edición crítica, "
            "una fuente primaria ni una investigación histórica.",
            "Su contenido resume temas generales sin incluir citas literales. Solo permite "
            "comprobar el flujo técnico de búsqueda, respuesta y referencias; no constituye "
            "evidencia suficiente para una publicación educativa.",
            "ADVERTENCIA DE REEMPLAZO: antes de cualquier lanzamiento publico, sustituya este "
            "archivo por un corpus seleccionado y revisado por especialistas, vuelva a crear el "
            "índice de recuperación y valide cada respuesta.",
        ),
    ),
    (
        "DEV-FED-01 | FEDERALISMO Y SOBERANÍA",
        (
            "El proyecto federal asociado a Artigas sostenía que los pueblos y las provincias "
            "conservaban su soberanía y debían vincularse por medio de acuerdos libres.",
            "La autoridad común no debía anular las competencias locales. La unión política se "
            "entendia como una liga de comunidades con representacion y capacidad de decidir "
            "sobre sus propios asuntos.",
            "Esta formulación permite relacionar libertad política, autonomía provincial y "
            "cooperación federal sin atribuir frases literales que este corpus no reproduce.",
        ),
    ),
    (
        "DEV-INS-01 | INSTRUCCIONES DEL AÑO XIII",
        (
            "Las Instrucciones del Año XIII expresaron orientaciones políticas de los delegados "
            "orientales para la organización de las Provincias Unidas.",
            "Entre sus propósitos figuraban afirmar la independencia, establecer una forma "
            "republicana y federal, proteger libertades civiles y asegurar que la autoridad "
            "general respetara la autonomia de las provincias.",
            "El documento debe interpretarse en el contexto de las disputas por la representación "
            "y por la distribución territorial del poder durante el proceso revolucionario.",
        ),
    ),
    (
        "DEV-CEN-01 | CONFLICTO CON EL CENTRALISMO PORTEÑO",
        (
            "La oposición artiguista al gobierno central de Buenos Aires surgió de diferencias "
            "sobre representación, soberanía provincial y control de decisiones comunes.",
            "El centralismo concentraba autoridad política y recursos en una sola ciudad. La "
            "alternativa federal reclamaba que las provincias participaran como integrantes con "
            "derechos propios y no como dependencias subordinadas.",
            "El conflicto fue político y territorial: discutía quién podía gobernar, con qué "
            "mandato y bajo qué relación entre los pueblos de la región.",
        ),
    ),
    (
        "DEV-TIE-01 | REGLAMENTO DE TIERRAS",
        (
            "El Reglamento de Tierras de 1815 organizó la distribución de terrenos disponibles "
            "en un contexto de guerra, desplazamiento y reconstrucción productiva.",
            "Sus criterios priorizaban a sectores vulnerables y buscaban poblar, trabajar y "
            "defender el territorio. La asignacion de tierras combinaba una finalidad social con "
            "necesidades económicas y de seguridad propias del momento.",
            "Este resumen explica principios de distribución y protección sin inventar una cita "
            "textual ni sustituir la consulta de una edicion documental completa.",
        ),
    ),
    (
        "DEV-PRI-01 | PRINCIPIOS POLÍTICOS DOCUMENTADOS",
        (
            "Los materiales sintetizados conectan libertad, federación, representación y "
            "protección social. La libertad exige límites al poder concentrado; la federación "
            "articula comunidades con autonomía; la representación vincula autoridad y mandato.",
            "La atención a quienes se encontraban en situación desventajosa aparece en la política "
            "de tierras. Estos principios no forman una formula atemporal: deben comprenderse en "
            "sus circunstancias históricas y justificarse mediante documentos.",
            "Una explicación rigurosa debe distinguir entre hechos respaldados, interpretaciones "
            "y reconstrucciones contemporáneas.",
        ),
    ),
    (
        "DEV-MOD-01 | MÉTODO SINTÉTICO PARA RECONSTRUCCIONES MODERNAS",
        (
            "Para abordar un asunto posterior a la vida de Artigas, la simulación debe declarar "
            "que ofrece una reconstrucción y no una opinión histórica registrada.",
            "La reconstrucción solo puede aplicar principios respaldados en estas secciones: "
            "límites al poder concentrado, soberanía de los pueblos, representación, cooperación "
            "federal y protección de grupos desfavorecidos.",
            "No debe atribuir al personaje conocimiento personal del asunto posterior, inventar "
            "hechos o presentar la extrapolación como testimonio. Si el corpus no ofrece base "
            "suficiente, corresponde reconocer la limitación documental.",
        ),
    ),
)


def generate_dev_corpus(output_path: Path) -> None:
    """Write the fixed seven-page development corpus to ``output_path``."""
    canvas = Canvas(
        str(output_path),
        pagesize=A4,
        invariant=1,
        pageCompression=0,
    )
    canvas.setAuthor("Artigas MVP")
    canvas.setCreator("artigas_mvp_backend.dev_corpus")
    canvas.setTitle("Corpus sintético de desarrollo de Artigas MVP")
    canvas.setSubject("Fixture sintético para pruebas de recuperación documental")

    width, height = A4
    for title, paragraphs in _PAGES:
        canvas.setFont("Helvetica-Bold", 15)
        canvas.drawString(54, height - 64, title)
        canvas.setFont("Helvetica", 10)
        canvas.drawRightString(width - 54, height - 64, "NO USAR COMO FUENTE HISTÓRICA")

        text = canvas.beginText(54, height - 105)
        text.setFont("Helvetica", 11)
        text.setLeading(16)
        for paragraph in paragraphs:
            for line in textwrap.wrap(paragraph, width=86, break_long_words=False):
                text.textLine(line)
            text.textLine("")
        canvas.drawText(text)
        canvas.showPage()

    canvas.save()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Genera el corpus PDF sintético de desarrollo.")
    parser.add_argument("output_path", type=Path)
    args = parser.parse_args(argv)
    generate_dev_corpus(args.output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
