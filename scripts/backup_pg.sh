#!/bin/sh
# Backup di PostgreSQL per il servizio «backup» di docker-compose.yml: un pg_dump (formato custom, compresso)
# subito all'avvio e poi ogni $BACKUP_EVERY secondi, in /backups; restano le ultime $BACKUP_KEEP copie.
# Il file si scrive con un nome temporaneo e si rinomina solo a dump riuscito: un backup a metà non sostituisce
# mai uno buono. Ripristino: vedi README («Backup e ripristino»).
set -u
EVERY="${BACKUP_EVERY:-86400}"
KEEP="${BACKUP_KEEP:-14}"
mkdir -p /backups
while true; do
    name="bilancio-$(date -u +%Y%m%d-%H%M%S).dump"
    if pg_dump --format=custom --no-owner --file="/backups/.${name}.tmp"; then
        mv "/backups/.${name}.tmp" "/backups/${name}"
        echo "$(date -u '+%F %T') backup scritto: ${name}"
        ls -1t /backups/bilancio-*.dump 2>/dev/null | tail -n +$((KEEP + 1)) | while read -r old; do
            rm -f "$old" && echo "$(date -u '+%F %T') backup vecchio rimosso: $(basename "$old")"
        done
    else
        rm -f "/backups/.${name}.tmp"
        echo "$(date -u '+%F %T') ERRORE: backup non riuscito" >&2
    fi
    sleep "$EVERY"
done
