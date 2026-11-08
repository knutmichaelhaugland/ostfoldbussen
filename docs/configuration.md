# Konfigurasjon

All konfigurasjon går via miljøvariabler. Se `.env.example` for alle variabler.

## Trygge standardverdier

- `PUBLIC_SMS_ENABLED=false`
- `INMOBILE_OUTBOUND_ENABLED=false`
- `BINERIC_ENABLED=false`
- `LLM_ENABLED=false`
- `PUBLIC_MATOMO_ENABLED=false`

Funksjoner som krever hemmeligheter feiler lukket når de aktiveres uten nødvendige
verdier.

## Viktige grupper

| Gruppe | Variabler |
|---|---|
| App | `APP_ENV`, `HOST`, `PORT`, `DATABASE_PATH`, `PUBLIC_BASE_URL` |
| Entur | `ENTUR_CLIENT_NAME` (sett din egen unike identitet), `ENTUR_*_URL`, `ENTUR_TIMEOUT_S` |
| Reiseterskler | `TRANSFER_SLACK_S`, `MIN_TRANSFER_S`, `MAX_WALK_*`, `SCOPE_POLICY` |
| Offentlig side | `PUBLIC_SMS_ENABLED`, `PUBLIC_SMS_NUMBER`, `PUBLIC_CONTACT_EMAIL` |
| SMS/inMobile | `INMOBILE_*`, `DAILY_SMS_LIMIT`, `RATE_LIMIT_PER_HOUR` |
| Modell | `BINERIC_*`, `LLM_*` |
| SMTP | `SMTP_*`, `CONTACT_TO`, `CONTACT_RATE_LIMIT_PER_HOUR` |
| Admin/personvern | `ADMIN_*`, `SESSION_SECRET`, `PSEUDONYM_SALT`, `SECRETS_DIR` |

## Hemmeligheter

Bruk `*_FILE` eller `SECRETS_DIR` for filbaserte hemmeligheter. Legg dem aldri i repo,
image eller CI. En eksplisitt satt `*_FILE` som mangler eller er tom gir
konfigurasjonsfeil; appen faller ikke stille tilbake til en miljøvariabel.

## Sikkerhet

- Admin må ha autentisering dersom den eksponeres.
- `/api/simulate` bør beskyttes med `SIMULATE_REQUIRE_AUTH=true` utenfor lokal bruk.
- Rate limits og timeout skal være satt for offentlig drift.
- Ingen eksterne API-kall i standard testkjøring.

## Proxy og klient-IP

Sett `TRUST_PROXY=true` bare når appen er bak en betrodd reverse proxy som
setter `X-Forwarded-For`. Ellers brukes TCP-klientadressen. Eksponer aldri appen
direkte samtidig som `TRUST_PROXY=true`.
