from openroboops.config import Settings


def test_allowed_origins_accepts_a_single_url(monkeypatch) -> None:
    monkeypatch.setenv("OPENROBOOPS_ALLOWED_ORIGINS", "https://robot-console.example")

    settings = Settings(_env_file=None)

    assert settings.allowed_origins == ["https://robot-console.example"]


def test_allowed_origins_accepts_comma_separated_urls(monkeypatch) -> None:
    monkeypatch.setenv(
        "OPENROBOOPS_ALLOWED_ORIGINS",
        "https://one.example, https://two.example",
    )

    settings = Settings(_env_file=None)

    assert settings.allowed_origins == ["https://one.example", "https://two.example"]
