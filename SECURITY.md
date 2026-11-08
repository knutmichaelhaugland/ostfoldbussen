# Sikkerhet

## Rapportering

Rapporter sårbarheter privat til `hjelp@ostfoldbussen.no` eller via GitHubs
private security advisory. Ikke legg hemmeligheter eller personopplysninger i
offentlige issues.

## CI og forsyningskjede

- Alle eksterne GitHub Actions er pinnet til full commit-SHA.
- Gitleaks kjører på full historikk og er hovedkontroll for hemmeligheter.
- Den prosjektspesifikke skanningen i `tools/project_secret_scan.py` er et
  supplement, ikke full dekning.
- Docker-baseimages og Caddy/Matomo-images er pinnet til OCI-digest der de
  brukes i compose; app-imaget bygges lokalt fra Dockerfile.
- PR-bygg bruker GitHub-hostede isolerte runnere uten secrets og med
  `contents: read`.
- Ingen PR-jobb deployer, publiserer eller bruker produksjonsnøkler.

## Personvern

Rå telefonnummer, rå meldingstekst og leverandørnøkler skal ikke logges. Se
[docs/security.md](docs/security.md).
