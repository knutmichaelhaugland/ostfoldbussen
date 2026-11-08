# Sikkerhetsmodell for admin og webhooks

## Session-cookie

Session-cookien er en HMAC-signert base64url-payload med bruker, utstedt tid og
utløp. Appen bruker `hmac.compare_digest` og avviser ugyldig base64, ugyldig
JSON, ikke-ASCII payload, manglende/feil exp og utløpte tokens. En malformet
cookie skal gi `401`, ikke `500`.

## CSRF

Admin-skjemaene bruker HMAC-signert double-submit:

- en `HttpOnly`, `SameSite=Lax` cookie
- et skjult skjemafelt med samme signerte token
- serveren krever at begge finnes, har gyldig HMAC og er like

Tokenet er **ikke bundet til en innlogget sesjon**. Det er en bevisst begrensning,
ikke en påstått bypass: en angriper som ikke kan lese cookien eller skjemafeltet
kan ikke lage et gyldig token. Session-binding ville beskytte mot gjenbruk av et
token på tvers av sesjoner, men login skjer før en sesjon finnes, og én-admin-
oppsettet gir liten praktisk gevinst. Dersom tokenet først er kompromittert
(f.eks. via XSS), er CSRF-binding alene ikke tilstrekkelig.

## Login-POST-ressursgrense

Alle `POST /admin/login` telles i et kort 60-sekunders vindu, også ugyldig eller
utløpt CSRF. Grensen er en ressursbeskyttelse (30 POST-er per IP per minutt), ikke
en permanent kontolås. Feil passord har i tillegg en egen lockout. Dette gjør at
et utløpt skjema eller en kort feilserie ikke permanent stenger en legitim bruker.

## Webhooks

- Leverandøradapteren validerer webhook-signaturen før noe annet; ugyldige
  signaturer gir fail-closed.
- inMobile: ECDSA-signatur over request-ID + timestamp + body valideres før
  request-ID claim. Manglende/endrede signaturfelt gir 403.
- Adapteren eier idempotens og leveringsstatus; kjernen eier inbound/outbound-policy,
  atomisk kapasitet og konservativ `unknown`-håndtering.

## Meldingsfingeravtrykk

Den opprinnelige SMS-teksten lagres ikke i driftsstatistikken. Dersom
`MESSAGE_HASH_KEY` er satt (minst 32 tegn), lagres en HMAC-SHA256 av normalisert
meldingstekst beregnet med denne separate nøkkelen. Uten nøkkelen lagres **ingen
meldingshash**; det finnes ingen usaltet SHA-256-fallback.

Nøkkelen er separat fra `SESSION_SECRET` og `PSEUDONYM_SALT`, skal ligge i
secrets-filen og ikke i repo eller image. Ved nøkkelrotasjon endres nye hasher;
eksisterende historiske hasher er ikke konverterbare, men brukes heller ikke som
oppslag for å gjenopprette meldinger.

Dette gjelder driftsstatistikken. Kortvarig samtalekontekst kan inneholde
meldingstekst i inntil 30 minutter, og SMS-leverandøren behandler meldingen for å
levere den. Se [privacy.md](privacy.md).

## Proxy og klient-IP

`TRUST_PROXY=true` aktiverer XFF bare fra peers som matcher
`TRUSTED_PROXY_IPS` (kommaseparerte IP-er/CIDR). Uten treff brukes TCP-peer.
Produksjon skal ikke eksponere app-containeren direkte.


## Avviste og aksepterte risikoområder

- Usaltet SHA-256 av meldingstekst brukes ikke; uten `MESSAGE_HASH_KEY` lagres
  ingen meldingshash i driftsstatistikken.
- Samtalekontekst lagrer stedsnavn og intent i maks 30 minutter for oppfølging;
  steds-ID-er er fjernet fra konteksten. Error-review kan fortsatt ha pseudonym og
  steds-ID-er for operativ feiloppfølging.
- SQLite er ikke kryptert i seg selv; diskkryptering, filrettigheter og krypterte
  backuper er separate driftskontroller.
