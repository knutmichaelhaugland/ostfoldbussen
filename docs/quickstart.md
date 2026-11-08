# Quick start

## Plattform

Se [setup.md](setup.md) for verifisert vert/container, støttematrise og
plattformvalg.

## Krav

- Python 3.13+
- eller Docker Engine + Compose
- Ingen tredjepartspakker for appen

På Debian 13 kan Docker og Compose installeres slik:

```bash
sudo apt-get update
sudo apt-get install -y docker.io docker-compose
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"   # logg inn på nytt etterpå
```

Debian-pakken gir `docker-compose`; hvis du har Docker Compose v2-plugin kan
kommandoen `docker compose` brukes i stedet. Begge er testet mot denne koden.

## Lokalt uten Docker

```bash
cp .env.example .env
chmod 600 .env
mkdir -p state/lib state/backups state/secrets
umask 077
python3 -m app auth-hash > state/secrets/admin_password_hash
python3 -c "import secrets; print(secrets.token_urlsafe(48))" > state/secrets/pseudonym_salt
python3 -c "import secrets; print(secrets.token_urlsafe(48))" > state/secrets/session_secret
chmod 600 state/secrets/*
python3 -m app --env-file .env
```

Åpne <http://127.0.0.1:8000/>. Helse: `/healthz`.
Testflate uten SMS: `POST /api/simulate` med JSON `{"message": "..."}`.
Som standard krever testflaten admin-innlogging (`SIMULATE_REQUIRE_AUTH=true`).
For lokal, isolert testing kan du sette `SIMULATE_REQUIRE_AUTH=false` bevisst i
`.env`; ikke gjør det på en offentlig eksponert instans.

## Docker

```bash
cp .env.example .env
chmod 600 .env
mkdir -p state/lib state/backups state/secrets
# Generer som innlogget bruker før katalogen overføres til uid 10001.
umask 077
python3 -m app auth-hash > state/secrets/admin_password_hash
python3 -c "import secrets; print(secrets.token_urlsafe(48))" > state/secrets/pseudonym_salt
python3 -c "import secrets; print(secrets.token_urlsafe(48))" > state/secrets/session_secret
chmod 600 state/secrets/*
# Lås katalogene og overfør dem til app-uid 10001 etter generering.
chmod 700 state/lib state/backups state/secrets
sudo chown -R 10001:10001 state/lib state/backups state/secrets
docker-compose up --build
```

Nettsiden ligger på <http://127.0.0.1:8080>. Databasen ligger i `./state/lib`.
Debian-pakken gir `docker-compose`; Compose v2-plugin kan bruke `docker compose`.

Secrets bør ikke limes inn i et delt skall eller havne i shell-historikk. Generer
dem lokalt og legg dem i `.env`, eller bruk `state/secrets` med filrettighet `0600`.
Se [operations.md](operations.md) for backup og restore; restore krever at appen
er stoppet og at WAL/SHM-sidefiler er håndtert.

## Hva som må fylles ut

| Variabel | Krav |
|---|---|
| `ADMIN_PASSWORD_HASH` | Genereres med `python3 -m app auth-hash` |
| `PSEUDONYM_SALT` | Minst 16 tegn, tilfeldig |
| `SESSION_SECRET` | Minst 32 tegn, tilfeldig |
| `PUBLIC_BASE_URL` | Valgfri offentlig URL for operatørens lenker; ikke nødvendig lokalt |
| `ENTUR_CLIENT_NAME` | Sett din egen unike identitet; standard er `ostfoldbussen-selfhosted` |

SMS, e-post, Matomo og språkmodell er valgfrie og av som standard.

## Hva som ikke skjer automatisk

- Ingen SMS sendes.
- Ingen betalt modell-API kalles.
- Ingen produksjonslegitimasjon brukes.
- Ingen eksterne sideeffekter fra testene.


## Periodisk retention (påkrevd for personvern)

TTL-en hindrer at utløpt samtalekontekst brukes, men **fysisk sletting** skjer
bare når `purge-retention` kjøres. Standard Docker-oppsett leverer ikke en
automatisk timer. En selvhostet instans må derfor aktivere en egen jobb.

Manuell verifisering:

```bash
docker-compose run --rm app python -m app purge-retention
```

Eksempel med systemd-timeren som følger med i `deploy/`:

```bash
sudo cp deploy/ostfoldbussen-retention.service /etc/systemd/system/
sudo cp deploy/ostfoldbussen-retention.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ostfoldbussen-retention.timer
systemctl list-timers ostfoldbussen-retention.timer
```

Juster `WorkingDirectory` i service-filen hvis prosjektet ikke ligger i
`/opt/ostfoldbussen`. Uten denne jobben kan utløpte rader bli liggende fysisk
til tross for at de ikke lenger brukes; det skal dokumenteres i operatørens
personvernrutine. Se [operations.md](operations.md) for detaljer.
