# gotyeah-starter

App web qui automatise la mise en route d'un nouveau site sur un homelab
Raspberry Pi 5 (Docker + Nginx Proxy Manager + Cloudflare). Depuis un simple
formulaire, elle enchaîne en cascade :

1. **GitHub** — création du repo (depuis un template selon le type de site, ou vierge)
2. **Cloudflare** — ajout du record DNS `A` pointant vers l'IP du Pi
3. **Nginx Proxy Manager** — certificat Let's Encrypt + proxy host avec SSL forcé
4. **GitHub** — injection de `.github/workflows/deploy.yml` adapté au type de site

Les logs de chaque étape s'affichent **en temps réel** (SSE) dans l'interface.
En cas d'échec, un **rollback** annule les étapes déjà effectuées.

## Stack

- **Backend** : FastAPI (Python 3.12), `httpx` async, dockerisé
- **Frontend** : HTML/CSS/JS vanilla, servi par le même conteneur (un seul déploiement)
- **Temps réel** : Server-Sent Events
- **Zéro dépendance SaaS** : tout tourne sur le Pi ; secrets en `.env`

## Architecture

```
gotyeah-starter/
├── docker-compose.yml         # un seul fichier pour déployer l'ensemble
├── .env.example               # gabarit des secrets (copier en .env)
└── backend/
    ├── Dockerfile
    ├── requirements.txt
    ├── static/                # frontend (index.html, app.js, style.css)
    └── app/
        ├── main.py            # routes FastAPI + endpoint SSE
        ├── config.py          # settings depuis l'environnement
        ├── models.py          # schémas Pydantic + validation
        ├── events.py          # bus d'événements (file par job)
        ├── orchestrator.py    # cascade des 4 étapes + rollback
        ├── workflows.py       # génération du deploy.yml par type de site
        └── services/
            ├── github.py
            ├── cloudflare.py
            └── npm.py
```

## Installation

```bash
cp .env.example .env
# éditez .env avec vos tokens et IPs
nano .env

docker compose up -d --build
```

L'interface est disponible sur `http://<ip-du-pi>:8080`.
Pour l'exposer proprement, ajoutez un proxy host dans NPM vers `pi-ip:8080`.

### Tokens requis

| Service | Permissions |
|---|---|
| GitHub | `repo`, `delete_repo` (pour le rollback) |
| Cloudflare | `Zone.DNS:Edit` + `Zone.Zone:Read` |
| NPM | identifiants d'un compte admin de l'interface NPM |

## Utilisation

1. Ouvrir l'interface, vérifier les badges de configuration (GitHub / Cloudflare / NPM).
2. Renseigner : domaine, type de site, port local cible, nom du repo.
3. Lancer — les logs défilent étape par étape jusqu'au succès (ou au rollback).

## Notes

- Le `deploy.yml` généré suppose un **runner self-hosted** sur le Pi
  (`runs-on: self-hosted`) qui build une image Docker et (re)lance le conteneur
  sur le port cible. Adaptez `backend/app/workflows.py` à votre pipeline réel.
- Le certificat Let's Encrypt via NPM utilise le challenge HTTP : le domaine doit
  résoudre vers le Pi et le port 80 être atteignable (attention au mode `proxied`
  de Cloudflare selon votre configuration).
- L'état des jobs est en mémoire : un redémarrage du conteneur efface l'historique
  des logs (le provisionnement lui-même n'est pas réversible une fois terminé).
