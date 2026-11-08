# Drift

## Miljø og hemmeligheter

- Ikke-hemmelig konfigurasjon kan ligge i `.env` lokalt eller egen env-fil.
- Hemmeligheter bør ligge i filer utenfor repoet (`*_FILE` eller `SECRETS_DIR`).
- Rotér nøkler ved mistanke om lekkasje.
- `BINERIC_ENABLED=true` uten nøkkel gir konfigurasjonsfeil ved oppstart; ved runtime-feil faller behandlingen tilbake til regler.

## Helse og overvåking

- `GET /healthz`: 200 = ok, 503 = degraded. Den er intern og skal ikke nødvendigvis
  eksponeres offentlig.
- Admin: `/admin`, `/admin/health`, `/admin/requests`, `/admin/errors`,
  `/admin/deliveries`, `/admin/costs`. Admin er ikke offentlig eksponert.
- Logger er strukturert JSON og skal ikke inneholde telefonnummer eller meldingstekst.

## Personvern og retensjon

- Samtalekontekst: 30 minutter.
- Driftsdata: 30 dager; avsluttede feilgjennomgangsposter: 90 dager.
- Daglig opprydding: `python -m app purge-retention`.
- Telefonnummer pseudonymiseres med HMAC-salt.
- Filbaserte secrets leses fra `SECRETS_DIR/<key.lower()>` eller eksplisitt
  `<KEY>_FILE`; filene skal være `0600` og eies av app-uid 10001 når containeren
  skal lese dem.

## Sikkerhet

- App-containeren kjører som uid 10001, read-only og uten Linux capabilities.
  Caddy-containerne bruker image-default bruker og har bare de capabilities som
  trengs for å binde 80/443; de er ikke samme sikkerhetsprofil som appen.
- Caddy har egen offentlig allowlist; admin/API er ikke offentlig eksponert.
- Ingen automatisk deploy fra CI.

## Backup og restore

Bruk det innebygde, stdlib-baserte verktøyet for en konsistent SQLite-kopi.
Det bruker SQLite Backup API og håndterer WAL; ikke kopier bare `app.db` mens
tjenesten kjører.

```bash
# Konsistent backup (Docker-installasjon; målet må ikke finnes fra før uten --force)
docker-compose exec -T app python -m app backup \
  --database /var/lib/ostfoldbussen/app.db \
  --output /var/backups/app-$(date +%F).db

# Verifiser at backupen kan åpnes og har gyldig integritet
docker-compose exec -T app python -c "import sqlite3; print(sqlite3.connect('/var/backups/app-$(date +%F).db').execute('PRAGMA integrity_check').fetchone()[0])"

# Restore til en NY testdatabase kan gjøres uten å stoppe appen.
docker-compose exec -T app python -m app restore \
  --source /var/backups/app-$(date +%F).db \
  --database /var/lib/ostfoldbussen/restore-test.db

# Reell restore mot aktiv database: stopp appen, håndter sidefiler bevisst,
# og restore i en engangscontainer. Deretter start appen igjen.
docker-compose stop app
docker-compose run --rm app python -m app restore \
  --source /var/backups/app-$(date +%F).db \
  --database /var/lib/ostfoldbussen/app.db --force
docker-compose up -d app
```

`restore` nekter å overskrive en eksisterende database uten `--force`.
Backupfiler ligger i `./state/backups` på verten (montert som `/var/backups`).
Krypter backupen **før** den forlater verten, for eksempel med `age` eller
`openssl enc`; filmontering i Compose krypterer ikke filer på disk. Bruk
`umask 077` eller `chmod 600` slik at også den krypterte filen er beskyttet. Oppbevar
nøkler og backupdestinasjon utenfor repo, image og applikasjonskatalog.

Kjør en restore-prøve med syntetisk database før første ekte gjenoppretting;
appen skal stoppes før en restore mot den aktive databasen.

## Automatisk retention

Utløpt samtalekontekst brukes ikke etter TTL, men fysisk sletting skjer når
purge-jobben kjøres. Installer den medfølgende systemd-timeren på en selvhostet
vert:

```bash
sudo cp deploy/ostfoldbussen-retention.service /etc/systemd/system/
sudo cp deploy/ostfoldbussen-retention.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ostfoldbussen-retention.timer
```

Timeren kjører `docker-compose run --rm app python -m app purge-retention`
daglig kl. 04:15 og forutsetter at prosjektet ligger i `/opt/ostfoldbussen`.
Juster `WorkingDirectory` i service-filen ellers. Verifiser med
`systemctl list-timers ostfoldbussen-retention.timer`, og kjør kommandoen manuelt
én gang etter installasjon. Uten timeren er TTL-en en logisk grense, ikke fysisk
sletting.


## Backupfiler og restore

`python -m app backup` skriver backupen med filrettighet `0600` og oppretter
foreldrekatalogen med `0700`. Krypter backupen før den flyttes ut av verten.
Restore bruker SQLite Backup API; stopp appen og fjern/erstatt WAL/SHM-sidefiler
bevisst før en aktiv database overskrives. Test alltid restore mot en ny
database først.


## Aktiv database og restore

Appprosessen tar en OS-basert `flock` på databasens `.lock`-fil. Restore
sjekker denne låsen og avviser restore mens appen kjører. Låsen frigjøres av
kjernen ved krasj; en gjenværende `.lock`-fil er derfor ikke i seg selv en
aktiv markør. Etter en kontrollert stopp kan operatøren fjerne WAL/SHM-sidefiler
og utføre restore.
