from workflow_engine.core.config import DEV_SECRET, Settings


def test_development_defaults_are_refused_in_production() -> None:
    problems = " ".join(Settings(app_env="production").production_problems())
    for expected in ("SESSION_SECRET", "API_KEY_PEPPER", "COOKIE_SECURE", "VAULT_PROVIDER"):
        assert expected in problems


def test_a_real_production_configuration_passes() -> None:
    settings = Settings(
        app_env="production",
        session_secret="s" * 48,
        api_key_pepper="p" * 48,
        cookie_secure=True,
        cors_origins="https://automate.example.com",
        vault_provider="kms",
        kms_key_id="alias/wfe-prod",
        http_allowed_hosts="crm.internal.example.com, erp.internal.example.com",
    )
    assert settings.production_problems() == []
    assert settings.cors_origins == ["https://automate.example.com"]
    assert settings.http_allowed_hosts == ["crm.internal.example.com", "erp.internal.example.com"]


def test_emulators_and_open_networks_are_refused_in_production() -> None:
    settings = Settings(
        session_secret="x" * 40,
        api_key_pepper="x" * 40,
        aws_endpoint_url="http://floci:4566",
        http_allow_private_networks=True,
    )
    problems = " ".join(settings.production_problems())
    assert "must differ" in problems
    assert "AWS_ENDPOINT_URL" in problems
    assert "HTTP_ALLOW_PRIVATE_NETWORKS" in problems
    assert Settings().session_secret.get_secret_value() == DEV_SECRET


def test_hook_urls_default_to_the_api_url() -> None:
    assert Settings(api_url="http://localhost:8130/").hooks_base_url == "http://localhost:8130"
    public = Settings(public_hooks_url="https://hooks.example.com")
    assert public.hooks_base_url == "https://hooks.example.com"
    assert Settings(max_payload_kb=64).max_payload_bytes == 65536
