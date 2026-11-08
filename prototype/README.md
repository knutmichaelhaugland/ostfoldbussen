# Prototype — minimal lokal Entur-kjerne

Isolert, **lokal** prototype for Østfoldbussen. Ingen SMS sendes, ingen deploy,
ingen betalte tjenester, ingen hemmeligheter. Kun **Python 3 stdlib**
(`urllib`, `json`) — ingen installasjoner.

Alle Entur-kall sender `ET-Client-Name: ostfoldbussen-sms`.

## Krav

- Python 3.10+ (bruker `X | None`-syntaks)
- Nettverkstilgang til `api.entur.io`

## Kjøring

```bash
# fra repo-roten ostfoldbussen/

# De to demo-spørsmålene
python3 -m prototype.cli "Når går buss 22 fra Skredderåsen?"
python3 -m prototype.cli "Hvordan kommer jeg fra Skredderåsen til Refsnes?"

# Maskinlesbar JSON
python3 -m prototype.cli "Hvordan kommer jeg fra Skredderåsen til Refsnes?" --json

# Fast referansetid (reproduserbar test mot kjente data)
python3 -m prototype.cli "Hvordan kommer jeg fra Skredderåsen til Refsnes?" \
  --now 2026-11-06T08:30:00+01:00

# Terskler er KONFIGURERBARE (ingen er vedtatt)
python3 -m prototype.cli "Hvordan kommer jeg fra Skredderåsen til Refsnes?" \
  --transfer-slack 300 --min-transfer 300 --max-walk 500

# Lagre rå Entur-svar (for bevis/reproduksjon)
python3 -m prototype.cli "Når går buss 22 fra Skredderåsen?" \
  --save-raw /tmp/departures.json
```

CLI-flag:

| Flagg | Betydning | Standard |
|---|---|---|
| `--transfer-slack` | `transferSlack` sendt til Entur (sekunder) | `120` (API-default) |
| `--min-transfer` | ettervalideringsminimum for overgang | `= --transfer-slack` |
| `--warn-transfer` | advarsel for stramt bytte (ikke filter) | `300` |
| `--max-walk` | maks sum gangavstand i meter (hard grense) | ingen |
| `--max-walk-leg` | maks gangavstand per bein | ingen |
| `--max-walk-time` | maks sum gangtid i sekunder | ingen |
| `--num-patterns` | `numTripPatterns` | `10` |
| `--search-window` | `searchWindow` (minutter) | API-default |
| `--now` | fast referansetid (ISO 8601) | nå |
| `--json` | skriv JSON | av |
| `--save-raw` | lagre rå Entur-svar | av |

## Tester

```bash
# Enhetstester (hermetiske, ingen nett)
python3 -m unittest discover -s prototype/tests -t . -v

# Live-integrasjonstester (ekte Entur-kall; kan hoppes over)
RUN_LIVE=1 python3 -m unittest prototype.tests.test_live_integration -v

```

## Terskelmatrise

`prototype/threshold_matrix.py` er tilgjengelig som Python-modul for å generere
sammenligningsgrunnlag. Den er ikke en del av standard-CI og vedtar ingen terskel.
## Moduler

| Modul | Ansvar |
|---|---|
| `config.py` | Endepunkter, `ET-Client-Name`, Østfold-fylke, konfigurerbare terskler, alias-tabell (produktvalg) |
| `entur_client.py` | GraphQL POST + Geocoder GET, timeout, 429-backoff (`rate-limit-expiry-time`; ingen `Retry-After`), validering av `errors`/`data==null`, partial errors, raw-capture |
| `geocoder.py` | Stedsoppslag i Østfold: `q` + `counties` + `layers=stopPlace`, ettervalider `layer`/`countyId==31`, alias, batch `/place` for scope-vakt |
| `departures.py` | `stopPlace.estimatedCalls`: linje, retning, quay, aimed/expected, realtime, cancellation, situations, rutetid/sanntid |
| `journeys.py` | `trip(...transferSlack...)`, ettervalidering av overgang/gange, scope-vakt, deterministisk valg av reise |
| `formatting.py` | Deterministisk norsk tekst + GSM-7-sanitering, SMS-utkast |
| `sms.py` | GSM-7/UCS-2-segmenttelling |
| `intent.py` | Liten deterministisk norsk intensjonsparser (ingen LLM) |
| `cli.py` | Demo-CLI med full sporbarhet |
| `threshold_matrix.py` | Terskelmatrise (oppgave 4) |
| `tests/` | Enhetstester + live-integrasjonstester + live-captured fixtures |

## Designvalg (dokumentert, ikke produktvedtatt)

1. **`transferSlack` er både API-parameter og ettervalideringsminimum.**
   API-et håndhever grensen hardt; ettervalideringen er en uavhengig kontroll. `--min-transfer` kan settes
   høyere enn `--transfer-slack`.
2. **Gangavstand kan ikke tvinges i API-et** — den etterfiltreres. Både sum,
   per-bein og gangtid kan konfigureres.
3. **Scope-vakt flagger, skjuler ikke.** Valg rekkefølge: egnet uten
   scope-flagg → egnet med flagg (tydelig advarsel) → første forslag.
   Ukjent fylke (geocoder-feil) behandles som flagg, ikke som «OK».
4. **Rutetider vs. sanntid** leses fra `realtime`; når `realtime=false` merkes
   svaret «Rutetider».
5. **Alias** (`Moss sentrum`/`byen` → Moss bussterminal) er merket
   `produktvalg-alias`; ID-en verifiseres mot Geocoder `/place`.
6. **Ingen hardkodede linjer/tider/reiser** i tjenestelogikken; linje og sted
   kommer fra spørsmålet. Bare alias-tabellen og testutvalget i
   `threshold_matrix.py` inneholder faste ID-er.

## Sikkerhet/personvern

Ingen nøkler, tokens eller persondata. Ingen SMS sendes. Rå API-svar lagres
bare lokalt når `--save-raw` brukes. NLOD-attribusjon er dokumentert i [NOTICE](../NOTICE) og på nettsidens
data-side. SMS-utkastene har en kort `Kilde: Entur`-hale.
