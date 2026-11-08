# Arkitektur

Østfoldbussen er en liten Python-tjeneste med SQLite, en valgfri SMS-adapter og
en valgfri språkmodell. Dokumentet beskriver den implementerte hovedflyten, ikke
en fremtidig plan. Se [configuration.md](configuration.md) og
[sms-adapters.md](sms-adapters.md) for konfigurasjon og utvidelser.

## Prinsipper

1. **Entur er autoritativ for reisedata.** Språkmodellen tolker spørsmål, men er
   aldri kilde til avganger, steder eller sanntid.
2. **Deterministisk der det er mulig.** Regelbasert tolkning brukes først; LLM er
   valgfri og kan slås av.
3. **Ingen oppdiktede data.** Manglende sanntid merkes som rutetid; ukjent sted
   avklares; API-feil gir et ærlig feil- eller avklaringssvar.
4. **Leverandøruavhengige grensesnitt.** SMS-adapter og LLM-adapter er byttbare.
   En ny leverandør krever adapter eller kompatibel konfigurasjon; det er ikke en
   garanti for at vilkårlige leverandører virker uten tilpasning.
5. **Én liten tjeneste.** SQLite og Docker Compose er standard. Kubernetes,
   ekstern database og mange tjenester er ikke implementert i denne kandidaten.

## Flyt

```text
SMS / HTTP
   │
   ▼
app/server.py ──► app/pipeline.py
                       │
                       ├── app/rules.py             regelbasert tolkning
                       ├── app/llm.py               generisk OpenAI-kompatibel adapter
                       ├── app/bineric_llm.py       separat Bineric-adapter
                       ├── app/place_logic.py       sted, scope og avklaring
                       ├── prototype/entur_client.py Entur GraphQL
                       ├── prototype/departures.py  avganger
                       ├── prototype/journeys.py    reisesøk
                       ├── app/sms_format.py        SMS-tekst og segmenter
                       └── SQLite                    kontekst, driftsdata, idempotens
```

### Ansvar

| Modul | Ansvar |
|---|---|
| `app/server.py` | HTTP, admin, webhooks, sikkerhetsheadere, klient-IP og rate limits |
| `app/pipeline.py` | Orkestrering av tolkning, Entur, svar og feilhåndtering |
| `app/rules.py` | Deterministisk norsk tolkning av vanlige spørsmål |
| `app/llm.py` | Generisk LLM-integrasjon; valgfri |
| `app/bineric_llm.py` | Bineric-spesifikk adapter; valgfri og separat |
| `app/place_logic.py` | Stedsvalidering, scope og tvetydighet |
| `prototype/entur_client.py` | Entur GraphQL, timeout, backoff og svarvalidering |
| `app/sms_adapter.py` | Leverandøruavhengig SMS-grensesnitt |
| `app/inmobile_adapter.py` | inMobile-implementasjon med signatur og idempotens |
| `app/sms_format.py` | GSM-7/UCS-2-segmentering og kort svarformat |
| `app/db.py` | SQLite, WAL, atomisk SMS-kapasitet og retensjon |
| `app/backup.py` | SQLite Backup API, restore og OS-basert lås |
| `app/observability.py` | Strukturerte hendelser uten rå meldingstekst |

## Data og personvern

- Telefonnummer brukes til levering; databasen lagrer en HMAC-basert pseudonym
  der feltet krever det. Pseudonymisering er ikke anonymisering.
- Rå meldingstekst lagres ikke i driftsstatistikken. Meldingshash er valgfri og
  HMAC-basert; uten `MESSAGE_HASH_KEY` lagres ingen hash.
- Kort samtalekontekst har TTL på 30 minutter som standard.
- Logger skal ikke inneholde telefonnummer eller rå meldingstekst.
- Retensjon for driftsdata, leveranser og feilregistreringer er konfigurerbar.
- Se [privacy.md](privacy.md) for detaljer og for forskjellen mellom offisiell
  tjeneste og selvhosting.

## SMS

`app/sms_adapter.py` definerer et lite grensesnitt for innkommende webhook og
utgående SMS. `inmobile_adapter.py` er den eneste adapteren som følger med i
denne kandidaten. Den validerer webhook-signatur, claimer request-ID, eier
idempotens og leveringsstatus, og bruker atomisk kapasitet før utgående sending.
Andre leverandører må implementere samme grensesnitt; se
[sms-adapters.md](sms-adapters.md).

## LLM

LLM er valgfri. `app/llm.py` kan brukes mot OpenAI-kompatible endepunkter;
`app/bineric_llm.py` er en separat adapter for Bineric. Ved feil eller manglende
konfigurasjon faller pipelinen tilbake til regler, ikke til en automatisk
leverandør. Bineric-adapteren har rate limit og budsjettgrense; den generiske adapteren har timeout og eksplisitte input-/outputgrenser. Begge bruker HTTPS i produksjon. Reisedata hentes alltid fra Entur.

## Database, backup og låsing

SQLite kjører med WAL. SMS-reservasjoner og dagens kapasitet oppdateres i samme
transaksjon. Backup tas med SQLite Backup API til en midlertidig fil, verifiseres
med `PRAGMA integrity_check`, settes til `0600` og flyttes atomisk på plass.
Restore mot den aktive databasen krever at appen er stoppet; restore til en ny
testdatabase kan kjøres mens appen lever. Appen holder shared OS-lås, retention
holder shared lås, og restore tar eksklusiv lås. En krasjet prosess frigjør låsen via
kjernen; en gjenværende låsefil er ikke i seg selv en aktiv markør.

## Drift

Standardoppsettet består av app-containeren og Caddy. Appen kjører som uid 10001,
lytter internt på `0.0.0.0:8000` og publiseres bare på vertens loopback i
standard-Compose. Caddy kan brukes med eget testsertifikat lokalt eller offentlig
ACME i produksjon. Admin/API skal ikke eksponeres gjennom den offentlige
allowlisten. Se [setup.md](setup.md) og [operations.md](operations.md).
