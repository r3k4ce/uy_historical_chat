import pytest
from pydantic import ValidationError

from artigas_mvp_backend.models import (
    ChatRequest,
    Citation,
    CompleteEventData,
    EducationalAction,
    ErrorPayload,
    LearningState,
    UsagePayload,
)


def test_chat_request_accepts_completed_alternating_history() -> None:
    request = ChatRequest.model_validate(
        {
            "message": "¿Y después?",
            "history": [
                {"role": "user", "content": "¿Qué ocurrió?"},
                {"role": "assistant", "content": "Ocurrió esto."},
            ],
            "turn_number": 2,
        }
    )

    assert [message.role for message in request.history] == ["user", "assistant"]


@pytest.mark.parametrize(
    ("history", "turn_number"),
    [
        ([], 2),
        ([{"role": "assistant", "content": "Respuesta"}], 1),
        ([{"role": "user", "content": "Pregunta"}], 2),
        (
            [
                {"role": "user", "content": "Uno"},
                {"role": "assistant", "content": "Respuesta"},
                {"role": "assistant", "content": "Otra"},
            ],
            2,
        ),
    ],
)
def test_chat_request_rejects_incomplete_or_mismatched_history(
    history: list[dict[str, str]], turn_number: int
) -> None:
    with pytest.raises(ValidationError):
        ChatRequest.model_validate(
            {"message": "Pregunta", "history": history, "turn_number": turn_number}
        )


def test_chat_request_trims_outer_whitespace() -> None:
    request = ChatRequest(message="  ¿Qué defendía?  ", turn_number=1)

    assert request.message == "¿Qué defendía?"
    assert request.history == []


@pytest.mark.parametrize("message", ["", " \n\t "])
def test_chat_request_rejects_empty_content(message: str) -> None:
    with pytest.raises(ValidationError):
        ChatRequest(message=message, turn_number=1)


def test_chat_request_accepts_exact_character_limit() -> None:
    assert len(ChatRequest(message="á" * 2000, turn_number=1).message) == 2000


def test_chat_request_rejects_over_character_limit() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(message="á" * 2001, turn_number=1)


@pytest.mark.parametrize("turn_number", [0, -1, 13])
def test_chat_request_rejects_invalid_turns(turn_number: int) -> None:
    with pytest.raises(ValidationError):
        ChatRequest(message="Pregunta", turn_number=turn_number)


def test_chat_request_accepts_turn_twelve() -> None:
    history = [
        item
        for number in range(11)
        for item in (
            {"role": "user", "content": f"Pregunta {number}"},
            {"role": "assistant", "content": f"Respuesta {number}"},
        )
    ]
    assert (
        ChatRequest.model_validate(
            {"message": "Pregunta", "history": history, "turn_number": 12}
        ).turn_number
        == 12
    )


def test_error_payload_has_stable_public_schema() -> None:
    payload = ErrorPayload(
        code="invalid_request",
        message="La pregunta no es válida.",
        retryable=False,
    )

    assert payload.model_dump(mode="json") == {
        "code": "invalid_request",
        "message": "La pregunta no es válida.",
        "retryable": False,
    }


def test_complete_payload_has_stable_public_schema() -> None:
    payload = CompleteEventData(
        final_text="Defendí la soberanía.",
        citations=[
            Citation(
                number=1,
                title="artigas.pdf",
                page=None,
                supported_text="la soberanía",
                start_index=8,
                end_index=20,
            )
        ],
        answer_status="documented",
        sources=[],
        educational_actions=[
            EducationalAction(
                type="deepen",
                label="Profundizar",
                action_id="federalismo-intro-1",
                question="¿Cómo se organizaba la autonomía provincial?",
                url=None,
            )
        ],
        learning_state=LearningState(shown_action_ids=["federalismo-intro-1"]),
        usage=UsagePayload(
            input_tokens=100,
            cached_input_tokens=10,
            output_tokens=20,
            thought_tokens=5,
            total_tokens=125,
            estimated_cost_usd=0.00036,
        ),
    )

    assert payload.model_dump(mode="json") == {
        "final_text": "Defendí la soberanía.",
        "citations": [
            {
                "number": 1,
                "title": "artigas.pdf",
                "page": None,
                "supported_text": "la soberanía",
                "start_index": 8,
                "end_index": 20,
            }
        ],
        "answer_status": "documented",
        "sources": [],
        "educational_actions": [
            {
                "type": "deepen",
                "label": "Profundizar",
                "action_id": "federalismo-intro-1",
                "question": "¿Cómo se organizaba la autonomía provincial?",
                "url": None,
            }
        ],
        "learning_state": {
            "shown_action_ids": ["federalismo-intro-1"],
            "selected_action_ids": [],
            "submitted_action_id": None,
            "topic_depths": {},
        },
        "usage": {
            "input_tokens": 100,
            "cached_input_tokens": 10,
            "output_tokens": 20,
            "thought_tokens": 5,
            "total_tokens": 125,
            "estimated_cost_usd": 0.00036,
        },
    }


def test_educational_actions_enforce_fixed_slot_shapes() -> None:
    question = EducationalAction(
        type="compare",
        label="Contrastar",
        action_id="compare-1",
        question="¿Qué tensión puede contrastarse?",
    )
    source = EducationalAction(
        type="source",
        label="Examinar la fuente",
        url="/api/corpus/artigas#page=26",
    )

    assert question.url is None
    assert source.action_id is None
    assert source.question is None

    with pytest.raises(ValidationError):
        EducationalAction(
            type="source",
            label="Examinar la fuente",
            action_id="not-allowed",
            url="/api/corpus/artigas#page=26",
        )
