"""Page 404 : un navigateur reçoit la page au style de l'app, l'API garde sa 404 JSON."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

BROWSER = {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}


def _is_html_404(r) -> bool:
    return (
        r.status_code == 404
        and r.headers["content-type"].startswith("text/html")
        and "Page introuvable" in r.text
    )


def test_browser_gets_custom_404():
    r = client.get("/cette-page-n-existe-pas", headers=BROWSER)
    assert _is_html_404(r)
    assert '<meta name="robots" content="noindex" />' in r.text
    # Chemin absolu : la feuille de style se charge même sous /a/b/c.
    assert 'href="/static/style.css"' in r.text
    # Aucun détail d'infrastructure dans le texte visible (l'accueil, lui, liste la chaîne).
    for mot in ("GitHub", "Cloudflare", "NPM"):
        assert mot not in r.text, mot
    assert _is_html_404(client.get("/a/b/c", headers=BROWSER))


def test_head_gets_404():
    r = client.head("/a/b/c", headers=BROWSER)
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("text/html")


def test_api_unknown_keeps_json_404():
    for accept in ("application/json", "*/*", BROWSER["Accept"]):
        r = client.get("/api/inconnue", headers={"Accept": accept})
        assert r.status_code == 404
        assert r.json() == {"detail": "Not Found"}
    # 404 levée par une route de l'API : message conservé.
    r = client.get("/api/jobs/inconnu/events", headers=BROWSER)
    assert r.status_code == 404
    assert r.json() == {"detail": "Job inconnu"}


def test_non_browser_clients_keep_json_404():
    for accept in ("application/json", "*/*"):
        r = client.get("/inconnue", headers={"Accept": accept})
        assert r.status_code == 404
        assert r.json() == {"detail": "Not Found"}
    r = client.post("/inconnue", headers=BROWSER)
    assert r.status_code == 404
    assert r.json() == {"detail": "Not Found"}


def test_static_and_health_intact():
    r = client.get("/static/absent.css", headers=BROWSER)
    assert r.status_code == 404
    assert r.json() == {"detail": "Not Found"}
    assert client.get("/static/style.css").status_code == 200
    r = client.get("/api/health", headers=BROWSER)
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    r = client.get("/", headers=BROWSER)
    assert r.status_code == 200
    assert "gotyeah-starter" in r.text
