# Plattform og selvhosting

Dette dokumentet beskriver hva som faktisk er testet og hva som er forventet
kompatibelt. Det er ikke en garanti for at alle Linux-distribusjoner fungerer.

## Verifisert plattform

| Komponent | Verifisert verdi |
|---|---|
| Verts-OS | Debian GNU/Linux 13 (trixie), testet med kernel 6.12.107+deb13-cloud-amd64 |
| Container-base | `python:3.13.9-slim-bookworm@sha256:b685a4fa58bb19d1814d78a1ec0f0208f351452724f78b20212c984d6e124a34` → Debian 12 (bookworm) |
| Python i containeren | 3.13.9 |
| Docker Engine | 26.1.5+dfsg1 (testet) |
| Docker Compose | 2.26.1-4 (testet) |
| HTTPS/reverse proxy | Caddy 2.11.9-alpine |
| Database | SQLite med WAL |
| Backup | SQLite Backup API via `python -m app backup` |
| Retensjon | `python -m app purge-retention` + systemd-timer |
| Reisedata | Entur Journey Planner/Geocoder |
| SMS | inMobile-adapter (valgfri) |
| Språkmodell | Bineric-adapter (valgfri); andre OpenAI-kompatible leverandører kan konfigureres |

Faktaene over er kontrollert mot den faktiske verten/kjørende container under
denne kandidaten, ikke bare mot eldre rapporter.

## Hvorfor Debian 13?

Debian 13 er valgt som **driftsplattform for den offisielle installasjonen** fordi:

- det er en stabil Debian-utgivelse med sikkerhetsoppdateringer
- det gir systemd, som brukes til den daglige retention-timeren
- det er en minimal, godt dokumentert serverplatform for en liten tjeneste
- erfaringen fra testverten er Debian-basert

Debian 13 er **ikke et krav** for andre installasjoner. Det er ikke dokumentert
testet på andre distribusjoner i denne kandidaten.

## Hvorfor Docker Compose?

Tjenesten består av én liten applikasjon, ett Caddy-containere og SQLite. For
forventet belastning er Docker Compose tilstrekkelig og enklere å drifte enn
Kubernetes. Compose gir:

- én deklarativ tjenestebeskrivelse
- healthcheck, restart-policy og ressursgrenser
- enkel oppgradering og logginnsamling
- ingen egen orkestreringsplattform

Kubernetes, Vault, Redis og ekstern database er ikke nødvendige og er ikke
obligatoriske i standardoppsettet.

## Hvorfor SQLite?

SQLite er egnet fordi:

- tjenesten har én applikasjonsprosess og relativt lav skrivefrekvens
- datamengden er liten
- WAL gir bedre samtidighet mellom lesing og skriving
- database, backup og retensjon kan drives uten en egen databasetjeneste

SQLite er **ikke** egnet uten videre dersom man kjører flere appinstanser mot
samme database, eller får vesentlig skrivebelastning. Skal man skalere horisontalt,
må databasen erstattes eller flyttes bak en felles tjeneste.

## Hvorfor Caddy?

Caddy brukes fordi det gir enkel HTTPS/ACME, reverse proxy, sikkerhetsheadere og
en liten konfigurasjon. Den offentlige Caddy-konfigurasjonen har en eksplisitt
allowlist og eksponerer ikke admin/API.

Bak Caddy må appen sette `TRUST_PROXY=true` for å bruke `X-Forwarded-For` som
klient-IP. Uten dette ser appen Caddy som klient, og rate limits blir felles.
Når `TRUST_PROXY=true`, må `TRUSTED_PROXY_IPS` angi Caddy-peerens CIDR. Tom liste
betyr fail-closed: ingen forwarding-headere stoles på. Dette er en
installasjonsinnstilling; hver operatør må dokumentere sin egen proxy-topologi.

## Vert vs. container

Verten kjører Debian 13. App-containeren kjører Debian 12 bookworm, fordi det
offisielle Python 3.13-imaget bruker bookworm. Dette er normalt:

- vertens kernel og Docker deles
- containerens brukerland, libc og Python følger image
- containerens base kan oppgraderes uavhengig av verten
- appen forutsetter ikke at verten og containeren har samme Debian-versjon

Baseimage er pinnet både med tag og full OCI-manifest-digest
(`python:3.13.9-slim-bookworm@sha256:b685a4fa58bb19d1814d78a1ec0f0208f351452724f78b20212c984d6e124a34`). Caddy-imaget er også
digest-pinnet. Det gir reproduserbare bygg, men krever en plan for bevisst
oppgradering når Python, Debian eller Caddy får sikkerhetsoppdateringer.

## Kompatibilitetsmatrise

| Plattform | Status |
|---|---|
| Debian 13 + Docker 26.1.5 + Compose 2.26.1 | **Testet på eksakt RC12 i ren Debian 13-VM** |
| Debian 12/13 med Docker + Compose, Python 3.13 | **Forventet kompatibelt, ikke testet** |
| Andre Linux-distribusjoner med Docker | **Ikke testet** |
| Rootless Docker/Podman | **Ikke testet** |
| Kubernetes | **Ikke støttet i standardoppsettet** |
| Windows/macOS som produksjonsvert | **Ikke testet** |

## Krav for selvhosting

- Linux-vert med Docker Engine og Compose (`docker compose` eller `docker-compose`)
- Minst 1 vCPU og ca. 2 GB RAM for denne lille tjenesten; mer ved trafikkvekst
- Skrivbar katalog for SQLite (`./state/lib` i standardoppsettet)
- Katalog for backuper (`./state/backups`)
- Katalog for hemmeligheter (`./state/secrets`) med begrensede rettigheter
- App-containeren kjører som uid/gid **10001**. Bind-mount-katalogene må eies av
  denne brukeren, ellers får appen ikke skrevet database eller backup:

  ```bash
  mkdir -p state/lib state/backups state/secrets
  # Generer secret-filene som innlogget bruker FØRST, og lås dem deretter.
  umask 077
  python3 -m app auth-hash > state/secrets/admin_password_hash
  python3 -c "import secrets; print(secrets.token_urlsafe(48))" > state/secrets/pseudonym_salt
  python3 -c "import secrets; print(secrets.token_urlsafe(48))" > state/secrets/session_secret
  chmod 600 state/secrets/*
  chmod 700 state/lib state/backups state/secrets
  sudo chown -R 10001:10001 state/lib state/backups state/secrets
  ```
- HTTPS dersom tjenesten skal eksponeres offentlig

## Installasjon

Se [quickstart.md](quickstart.md). Kort:

```bash
cp .env.example .env
chmod 600 .env
mkdir -p state/lib state/backups state/secrets
umask 077
python3 -m app auth-hash > state/secrets/admin_password_hash
python3 -c "import secrets; print(secrets.token_urlsafe(48))" > state/secrets/pseudonym_salt
python3 -c "import secrets; print(secrets.token_urlsafe(48))" > state/secrets/session_secret
chmod 600 state/secrets/*
chmod 700 state/lib state/backups state/secrets
sudo chown -R 10001:10001 state/lib state/backups state/secrets
docker-compose up --build
```

Standardoppsettet:

- eksponerer appen bare på `127.0.0.1`
- sender ikke SMS
- gjør ikke betalte modellkall
- bruker ikke den offisielle Entur-identiteten
- aktiverer ikke admin offentlig

## Oppgradering

1. Ta en verifisert backup.
2. Hent ny kode.
3. Kjør tester og `docker-compose config`.
4. Bygg og start på nytt.
5. Kontroller `/healthz` og admin-helse.
6. Verifiser at database og backup fortsatt fungerer.

## Begrensninger

- Baseimage og Caddy er digest-pinnet, men må fortsatt oppgraderes bevisst.
- Ren Debian 13 er testet med eksakt RC12-artefakt, syntetiske data og
  Docker/Compose fra Debian-pakker, inkludert Caddy/HTTPS, backup/restore,
  retention og VM-reboot. Det er ikke en langtids produksjonsverifisering.
- Retention-timeren er dokumentert, men ikke kjørt som systemd-timer i denne runden.
- RPO/RTO og kryptert ekstern backup er operatørens ansvar; se [operations.md](operations.md).
