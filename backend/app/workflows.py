"""Génération du fichier .github/workflows/deploy.yml selon le type de site.

Hypothèse homelab : un runner self-hosted tourne sur le Pi (label `self-hosted`).
Le déploiement build une image Docker et (re)lance un conteneur sur le port cible.
"""
from __future__ import annotations

from .models import SiteType


def _nextjs(domain: str, port: int, container: str) -> str:
    return f"""name: Deploy {domain}

on:
  push:
    branches: [main]
  workflow_dispatch:

concurrency:
  group: deploy-{container}
  cancel-in-progress: true

jobs:
  deploy:
    runs-on: self-hosted
    steps:
      - uses: actions/checkout@v4

      - name: Build image
        run: docker build -t {container}:latest .

      - name: Restart container
        run: |
          docker rm -f {container} 2>/dev/null || true
          docker run -d --name {container} --restart unless-stopped \\
            -p {port}:3000 {container}:latest

      - name: Prune dangling images
        run: docker image prune -f
"""


def _static(domain: str, port: int, container: str) -> str:
    return f"""name: Deploy {domain}

on:
  push:
    branches: [main]
  workflow_dispatch:

concurrency:
  group: deploy-{container}
  cancel-in-progress: true

jobs:
  deploy:
    runs-on: self-hosted
    steps:
      - uses: actions/checkout@v4

      # Adaptez la build si le site statique nécessite un bundler.
      # - run: npm ci && npm run build

      - name: Serve static files via nginx
        run: |
          docker rm -f {container} 2>/dev/null || true
          docker run -d --name {container} --restart unless-stopped \\
            -p {port}:80 \\
            -v "$GITHUB_WORKSPACE/public:/usr/share/nginx/html:ro" \\
            nginx:alpine
"""


def _other(domain: str, port: int, container: str) -> str:
    return f"""name: Deploy {domain}

on:
  push:
    branches: [main]
  workflow_dispatch:

concurrency:
  group: deploy-{container}
  cancel-in-progress: true

jobs:
  deploy:
    runs-on: self-hosted
    steps:
      - uses: actions/checkout@v4

      # Type "autre" : pipeline générique via docker compose.
      # Exposez votre service sur le port {port} dans le compose.
      - name: Deploy with docker compose
        run: |
          docker compose pull || true
          docker compose up -d --build
        env:
          TARGET_PORT: "{port}"
"""


_GENERATORS = {
    SiteType.nextjs: _nextjs,
    SiteType.static: _static,
    SiteType.other: _other,
}


def render_deploy_workflow(site_type: SiteType, domain: str, port: int, repo_name: str) -> str:
    container = repo_name.lower().replace("_", "-")
    return _GENERATORS[site_type](domain, port, container)
