from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    rossoctl_api_url: str = (
        "http://rossoctl-backend.rossoctl-system.svc.cluster.local:8000"
    )

    enable_auth: bool = True
    keycloak_url: str = "http://keycloak.keycloak.svc.cluster.local:8080"
    keycloak_public_url: str = "http://keycloak.localtest.me:8080"
    keycloak_realm: str = "rossoctl"
    client_id: str = "app-demo"

    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://app-demo.localtest.me:8080",
    ]

    domain_name: str = "localtest.me"

    token_broker_url: str = ""


settings = Settings()
