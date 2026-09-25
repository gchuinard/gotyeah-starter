#!/bin/bash
# Déploiement de gotyeah-starter sur le Pi. Ce script ne se lance pas à la main : il est
# exécuté par /usr/local/sbin/gotyeah-deploy (commande forcée de la clé
# SSH_KEY dans authorized_keys), depuis /home/pi/deploiement/gotyeah-starter (copie git de ce
# dépôt public), après un git fetch.
# Variables reçues : CIBLE (commit à déployer), AVANT (commit en place).
# Le script est lu dans le commit CIBLE : le modifier sur main suffit.
#
# Jusqu'au 25/09/2026, ces étapes vivaient dans .github/workflows/deploy.yml : le runner
# envoyait son checkout par rsync, puis lançait docker compose en SSH. Elles sont reprises
# telles quelles, seul l'envoi du code change : il part de la copie git du Pi.
set -euo pipefail

# La copie git tient le rôle du checkout du runner : exactement le commit à déployer.
git reset --hard "$CIBLE"

# Dossier du service (l'ancien REMOTE_DIR du workflow), créé au besoin comme le faisait
# --rsync-path="mkdir -p ...". Mêmes exclusions que l'ancien rsync : le .env du Pi (secrets)
# n'est ni écrasé ni supprimé par --delete.
# --chmod : le checkout du runner ne donnait aucun droit d'écriture au groupe ni aux autres,
# et rsync -a recopiait ces droits ; on garde ce résultat quel que soit le umask du Pi.
REMOTE_DIR=/home/pi/sites/gotyeah-starter
mkdir -p "$REMOTE_DIR"
rsync -a --delete --chmod=Dgo-w,Fgo-w \
  --exclude='.git' \
  --exclude='.env' \
  --exclude='__pycache__' \
  ./ "$REMOTE_DIR/"

# Construire et relancer le conteneur. --wait : la commande échoue (et le job de CI avec) si
# le conteneur ne devient pas sain en 120 s. Pas de retour arrière, comme avant.
cd "$REMOTE_DIR"
docker compose up -d --build --wait --wait-timeout 120
docker image prune -f
