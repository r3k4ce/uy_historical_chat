from artigas_mvp_backend.main import health


def test_health() -> None:
    assert health() == {"status": "ok", "project": "artigas-mvp"}
