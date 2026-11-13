from pathlib import Path
import os
from typing import Literal
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=os.environ.get("METRO_ENV_FILE", ROOT / ".env"), extra="ignore", hide_input_in_errors=True)
    database_url: str = f"sqlite:///{(ROOT / 'data' / 'metro-app.db').as_posix()}"
    migration_database_url: str = ""
    app_env: Literal["local", "software", "test", "production"] = "local"
    auth_secret: str = ""
    network_file: str = ""
    secure_cookies: bool = False
    allowed_hosts: str = "localhost,127.0.0.1,testserver"
    trusted_proxy_cidrs: str = ""
    session_hours: int = 12
    max_request_bytes: int = 131072
    max_ws_connections: int = 200
    retention_days: int = 30
    sensor_api_key: str = ""
    admin_api_key: str = ""
    crowd_tokens: str = ""
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    simulation_enabled: bool = False
    prediction_model_file: str = ""
    mqtt_enabled: bool = False
    mqtt_host: str = "localhost"
    mqtt_port: int = 8883
    mqtt_user: str = "metro-ingestor"
    mqtt_password: str = ""
    mqtt_ca_file: str = ""
    transition_seconds: int = 60
    crowd_max_age_seconds: int = 300
    # Passenger service reports have a separate, short live-evidence lifetime.
    service_report_max_age_seconds: int = 30
    service_consensus_window_seconds: int = 120
    service_consensus_users: int = 3
    reroute_delay_seconds: int = 180
    reroute_min_saving_seconds: int = 120
    cell_map_file: str = ""
    hardware_enabled: bool = False
    sensor_max_age_seconds: int = 30
    min_source_trust: float = 0.60
    switch_margin: float = 0.15
    switch_confirmations: int = 3
    switch_hold_seconds: int = 30

    @model_validator(mode="after")
    def validate_profile(self):
        if self.app_env != "test" and len(self.auth_secret) < 48:
            raise ValueError("AUTH_SECRET must contain at least 48 characters; run scripts/start.ps1 for local setup")
        if self.app_env not in {"test", "software"} and self.simulation_enabled:
            raise ValueError("Simulation is restricted to isolated tests")
        if self.app_env == "software" and (not self.simulation_enabled or not self.network_file):
            raise ValueError("Software validation requires an explicit test feed and separate configured network")
        if self.app_env == "software":
            from sqlalchemy.engine import make_url
            if make_url(self.database_url).database != "metro_software":
                raise ValueError("Software inputs require the dedicated metro_software database")
        if self.app_env == "production":
            if not self.database_url.startswith("postgresql+psycopg://"):
                raise ValueError("Production requires PostgreSQL")
            if not self.secure_cookies or any(not x.strip().startswith("https://") for x in self.cors_origins.split(",")):
                raise ValueError("Production requires secure cookies and explicit HTTPS origins")
            hosts = [x.strip() for x in self.allowed_hosts.split(",")]
            if any(x in {"*", "testserver"} for x in hosts) or not any(x not in {"localhost", "127.0.0.1"} for x in hosts):
                raise ValueError("Production requires explicit application hosts")
            if self.mqtt_enabled and (not self.mqtt_ca_file or not self.mqtt_password or self.mqtt_port == 1883):
                raise ValueError("Production MQTT requires TLS and authenticated broker access")
        return self

    def contributors(self):
        return dict(item.split(":", 1) for item in self.crowd_tokens.split(",") if ":" in item) if self.app_env == "test" else {}

    @property
    def synthetic_data(self):
        return self.app_env in {"test", "software"}


settings = Settings()
