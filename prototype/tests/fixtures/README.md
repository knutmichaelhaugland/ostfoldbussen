# Testfixtures

Disse filene er **LIVE-CAPTURED** fra Entur (2026-11-05, Europe/Oslo) med
`ET-Client-Name: ostfoldbussen-selfhosted`, lagret av `prototype/cli.py --save-raw`.

| Fil | Spørsmål | Referansetid | Bruk |
|---|---|---|---|
| `live-trip-skredderasen-refsnes.json` | Hvordan kommer jeg fra Skredderåsen til Refsnes? | 2026-11-06T08:30:00+01:00 | `test_journeys.py` (parsing, overgang 120 s, ettervalidering) |
| `live-departures-skredderasen-22.json` | Når går buss 22 fra Skredderåsen? | 2026-11-06T08:30:00+01:00 | `test_departures.py` (rutetid/sanntid, linjefilter) |

Fixtures er eksplisitt merket som live-captured; enhetstestene er hermetiske
og krever ikke nett. Nye fixtures genereres med:

```bash
python3 -m prototype.cli "Hvordan kommer jeg fra Skredderåsen til Refsnes?" \
  --now 2026-11-06T08:30:00+01:00 --json \
  --save-raw prototype/tests/fixtures/live-trip-skredderasen-refsnes.json > /dev/null
```
