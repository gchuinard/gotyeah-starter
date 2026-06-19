"""Tests de fumée — aucun appel réseau réel, gate du job CI avant déploiement."""
from fastapi.testclient import TestClient

from app.main import app
from app.models import Endpoint, ProvisionRequest, SiteType
from app.workflows import render_deploy_workflow

client = TestClient(app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert "config" in r.json()


def test_index_served():
    r = client.get("/")
    assert r.status_code == 200
    assert "gotyeah-starter" in r.text


def test_provision_rejects_invalid_domain():
    r = client.post(
        "/api/provision",
        json={"repo_name": "x", "site_type": "nextjs",
              "frontend": {"domain": "pas-un-domaine", "container": "x", "port": 3000}},
    )
    assert r.status_code == 422


def test_workflow_frontend_only():
    req = ProvisionRequest(
        repo_name="s", site_type=SiteType.nextjs,
        frontend=Endpoint(domain="s.exemple.com", container="s", port=3000),
    )
    y = render_deploy_workflow(req)
    assert "runs-on: self-hosted" in y
    assert "s:latest" in y
    assert "nginx-proxy-manager_default" in y


def test_workflow_with_backend():
    req = ProvisionRequest(
        repo_name="s", site_type=SiteType.other,
        frontend=Endpoint(domain="s.exemple.com", container="s", port=3000),
        backend=Endpoint(domain="api-s.exemple.com", container="s-api", port=8000),
    )
    y = render_deploy_workflow(req)
    assert "s-api:latest" in y
    assert "./backend" in y
