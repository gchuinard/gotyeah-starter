"""Génération du fichier .github/workflows/deploy.yml selon le type de site.

Hypothèse homelab : un runner self-hosted tourne sur le Pi (label `self-hosted`).
Les conteneurs rejoignent le réseau partagé `nginx-proxy-manager_default` pour que NPM
les résolve par leur nom. Si un backend est défini, un second conteneur est (re)lancé.
"""
from __future__ import annotations

from .models import Endpoint, ProvisionRequest, SiteType

NPM_NETWORK = "nginx-proxy-manager_default"

_INTERNAL_PORT = {SiteType.nextjs: 3000, SiteType.static: 80, SiteType.other: 8080}


def _run_container_step(name: str, ep: Endpoint, internal_port: int, build_dir: str) -> str:
    return f"""      - name: Deploy {name} ({ep.container})
        run: |
          docker build -t {ep.container}:latest {build_dir}
          docker rm -f {ep.container} 2>/dev/null || true
          docker run -d --name {ep.container} --restart unless-stopped \\
            --network {NPM_NETWORK} \\
            -p {ep.port}:{internal_port} {ep.container}:latest
"""


def render_deploy_workflow(req: ProvisionRequest) -> str:
    fe = req.frontend
    internal = _INTERNAL_PORT.get(req.site_type, 8080)
    steps = _run_container_step("frontend", fe, internal, ".")
    if req.backend is not None:
        # Convention : le backend se build depuis ./backend (à adapter au repo).
        steps += "\n" + _run_container_step("backend", req.backend, req.backend.port, "./backend")

    concurrency = fe.container
    return f"""name: Deploy {fe.domain}

on:
  push:
    branches: [main]
  workflow_dispatch:

concurrency:
  group: deploy-{concurrency}
  cancel-in-progress: true

jobs:
  deploy:
    runs-on: self-hosted
    steps:
      - uses: actions/checkout@v4

{steps}
      - name: Prune dangling images
        run: docker image prune -f
"""
