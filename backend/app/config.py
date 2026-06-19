"""Configuration centralisée — tout vient des variables d'environnement (.env)."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- GitHub ---
    github_token: str = ""
    github_owner: str = ""  # user ou organisation propriétaire des repos créés
    # Repos template par type de site : "owner/repo". Vides => repo vierge.
    github_template_nextjs: str = ""
    github_template_static: str = ""
    github_template_other: str = ""

    # --- Cloudflare ---
    cloudflare_token: str = ""
    cloudflare_zone_id: str = ""  # optionnel : si vide, la zone est résolue depuis le domaine
    pi_public_ip: str = ""        # IP cible du record A
    # État proxied FINAL souhaité (orange cloud) une fois tout en place.
    cloudflare_proxied: bool = True
    # Crée le record en DNS-only puis rebascule en proxied après l'émission du
    # cert NPM — reproduit le flux "DNS-only -> NPM OK -> repasse en proxy".
    cloudflare_dns_only_during_ssl: bool = True

    # --- Nginx Proxy Manager ---
    npm_base_url: str = "http://nginx-proxy-manager:81"
    npm_email: str = ""
    npm_password: str = ""
    # Hôte vers lequel NPM redirige le trafic (le Pi / un conteneur). Défaut = IP du Pi.
    npm_forward_host: str = ""
    npm_forward_scheme: str = "http"
    letsencrypt_email: str = ""

    @property
    def template_for(self) -> dict[str, str]:
        return {
            "nextjs": self.github_template_nextjs,
            "static": self.github_template_static,
            "other": self.github_template_other,
        }

    @property
    def forward_host(self) -> str:
        return self.npm_forward_host or self.pi_public_ip


settings = Settings()
