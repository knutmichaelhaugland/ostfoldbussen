# Østfoldbussen

Østfoldbussen er et uavhengig, ikke-kommersielt prosjekt som gjør
kollektivinformasjon tilgjengelig med SMS og en enkel nettside. Målet er at
mennesker som ikke bruker smarttelefon eller app skal kunne spørre «når går
bussen?» og få et kort, ærlig svar med reisedata fra Entur.

Prosjektet er åpen kildekode under MIT. Den offisielle tjenesten på
[ostfoldbussen.no](https://ostfoldbussen.no/) beskriver sine egne leverandører og
sin egen behandling av personopplysninger. Andre kan installere og drifte
Østfoldbussen selv, men er da selv ansvarlige for leverandørvalg, personvern,
sikkerhet og drift.

> **Status: offentlig forhåndsutgave av kildekoden.** Kandidaten er
> release-kvalifisert med tester, sikkerhetsskanning og en isolert
> Debian 13-installasjon med backup/restore. Dette er **ikke** en erklæring om at
> selvhosting eller den offisielle SMS-tjenesten er produksjonsklar. Se
> [setup.md](docs/setup.md) og [security.md](docs/security.md) for begrensninger.

## Hva som er implementert

- SMS inn/ut gjennom et leverandøruavhengig adaptergrensesnitt. inMobile-adapteren
  følger med; andre SMS-leverandører krever egen adapter eller konfigurert
  integrasjon.
- Regelbasert tolkning av vanlige norske reisespørsmål. En språkmodell er valgfri
  og brukes bare til å tolke fritekst, aldri som kilde til transportfakta.
- Generisk OpenAI-kompatibel LLM-adapter og en separat Bineric-adapter. Den
  offisielle tjenesten kan velge Bineric; andre operatører kan bruke en annen
  kompatibel leverandør eller ingen LLM.
- Entur Journey Planner v3 og Geocoder v3 som autoritativ kilde til reiser,
  avganger og steder.
- Korte SMS-svar med GSM-7/UCS-2-segmentering, sanntid der det finnes, og tydelig
  merking når bare rutetider er tilgjengelige.
- Adminflate og webhooks med autentisering, signaturverifisering, idempotens,
  atomisk SMS-kapasitet og fail-closed feilhåndtering.
- SQLite med WAL, backup via SQLite Backup API, retention og OS-basert låsing ved
  restore.

## Arkitektur

```text
SMS / HTTP
   │
   ▼
app/server.py ──► app/pipeline.py
                       │
                       ├── app/rules.py             regelbasert tolkning
                       ├── app/llm.py               generisk LLM-adapter (valgfri)
                       ├── app/bineric_llm.py       Bineric-adapter (valgfri)
                       ├── app/place_logic.py       stedsvalidering og scope
                       ├── prototype/entur_client.py Entur GraphQL
                       ├── app/sms_format.py        SMS-format og segmenter
                       └── SQLite                    kontekst, driftsdata, revisjon
```

Applikasjonen bruker bare Python-standardbiblioteket. Entur er en åpen tjeneste
uten API-nøkkel for denne bruken. SMS, e-post, Matomo og språkmodell er valgfrie.
En leverandør kan byttes bare når det finnes en adapter eller en kompatibel
konfigurasjon; prosjektet lover ikke at vilkårlige leverandører virker uten slik
tilpasning.

## Kom i gang

### Docker på Debian 13

```bash
sudo apt-get update
sudo apt-get install -y docker.io docker-compose
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"   # logg inn på nytt
git clone https://github.com/knutmichaelhaugland/ostfoldbussen.git
cd ostfoldbussen
cp .env.example .env
chmod 600 .env
mkdir -p state/lib state/backups state/secrets
# Generer hemmelighetene som den innloggede brukeren FØRST. Katalogen må
# fortsatt være skrivbar for denne brukeren; derfor chown nedenfor.
umask 077
python3 -m app auth-hash > state/secrets/admin_password_hash
python3 -c "import secrets; print(secrets.token_urlsafe(48))" > state/secrets/pseudonym_salt
python3 -c "import secrets; print(secrets.token_urlsafe(48))" > state/secrets/session_secret
chmod 600 state/secrets/*
# Først etter at filene er skrevet: lås katalogene og gi dem til app-uid 10001.
chmod 700 state/lib state/backups state/secrets
sudo chown -R 10001:10001 state/lib state/backups state/secrets
docker-compose up --build
```

Nettsiden ligger på <http://127.0.0.1:8080>. Databasen ligger i `./state/lib`.
På Debian kan `docker.io` og `docker-compose` installeres med apt; kommandoen
`docker compose` kan brukes dersom Compose v2-pluginen er installert; Debian-pakken bruker `docker-compose`. Se
[quickstart.md](docs/quickstart.md) for lokal Python-kjøring og flere detaljer.

### Lokalt uten Docker

```bash
python3 -m venv .venv && . .venv/bin/activate
cp .env.example .env
mkdir -p state/lib state/secrets
python3 -m app auth-hash
python3 -m app --env-file .env
```

`.env.example` bruker en relativ databasebane for lokal kjøring. Docker-oppsettet
overstyrer databasebanen til containervolumet.

## Tester

```bash
python3 -m unittest discover -s tests -t .
python3 -m unittest discover -s prototype/tests -t .
```

Testene er hermetiske og bruker syntetiske Entur-data; de krever ikke nettverk,
API-nøkler eller SMS. CI kjører begge testsuitene, Docker-bygg,
hemmelighetsskanning og Markdown-lenkkontroll.

## Sikkerhet og personvern

- Ingen konto og ingen sporingscookies i standardoppsettet.
- Telefonnummer brukes til levering; i applikasjonens database lagres en
  HMAC-basert pseudonymisert verdi, ikke nummeret i klartekst.
- Den opprinnelige SMS-teksten lagres ikke i driftsstatistikken. Dersom
  `MESSAGE_HASH_KEY` er satt, lagres en HMAC-SHA256 av meldingen; uten nøkkel
  lagres ingen meldingshash. Kort samtalekontekst kan inneholde tekst i inntil
  30 minutter, og SMS-leverandøren behandler meldingsinnhold for levering.
- Admin/API skal ikke eksponeres offentlig; se [security.md](docs/security.md) og
  [privacy.md](docs/privacy.md).
- Rapporter sårbarheter privat som beskrevet i [SECURITY.md](SECURITY.md), ikke i
  et offentlig issue.

## Begrensninger og releasegrenser

| Nivå | Status |
|---|---|
| Offentlig MIT-kildekode | Forhåndsutgave av kildekoden; publiseres etter eierens endelige godkjenning |
| Produksjonsklar selvhosting | **Ikke erklært.** Offentlig DNS/ACME, live leverandørflyter og langtidsdrift er ikke fullt verifisert |
| Offisiell SMS-produksjon | **Ikke produksjonsverifisert.** Ingen ekte SMS/webhook er testet i release-kvalifiseringen |

SQLite forutsetter én appinstans. Kryptert backup er operatørens ansvar. En
selvhostet instans må lage egen personvernerklæring og egne databehandleravtaler.

## Dokumentasjon

- [Arkitektur](docs/architecture.md)
- [Konfigurasjon](docs/configuration.md)
- [Quickstart](docs/quickstart.md)
- [Plattform og selvhosting](docs/setup.md)
- [Drift og backup](docs/operations.md)
- [Sikkerhet](docs/security.md)
- [Personvern](docs/privacy.md)
- [SMS-adaptere](docs/sms-adapters.md)
- [Språkmodell](docs/llm-live.md)
- [Leverandørvurdering](docs/providers.md)
- [Lisensiering](docs/licensing.md)
- [Bidra](CONTRIBUTING.md)
- [Code of Conduct](CODE_OF_CONDUCT.md)

## Lisens og data

- **Kode:** MIT, se [LICENSE](LICENSE).
- **Entur-data:** NLOD 2.0, ikke omfattet av MIT. Se [NOTICE](NOTICE).
- Navn på tredjepartsleverandører innebærer ikke godkjenning eller varemerkerett.
