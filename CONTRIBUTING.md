# Bidra til Østfoldbussen

## Før en pull request

- Kjør `python -m unittest discover -s tests -t .`.
- Kjør `python -m unittest discover -s prototype/tests -t .`.
- Kjør `python -m unittest tests.test_ci_policy`.
- Kjør `python tools/check_markdown_links.py` og `python tools/check_repo_hygiene.py`.
- Hold hemmeligheter, telefonnumre, rå logger og private driftsdata utenfor repo,
  issues, PR-er og CI-logger.
- Nye avhengigheter skal begrunnes; prosjektet bruker Python-standardbiblioteket.

## Sikkerhetsgrense for CI

- Docker-bygg av PR-er skjer på GitHub-hostede, isolerte runnere uten secrets.
- Self-hosted produksjonsrunnere brukes ikke til vilkårlig PR-kode.
- PR-jobber har `contents: read`, eksplisitt timeout og ingen deploy/publisering.
- Eksterne GitHub Actions pinnes til full commit-SHA. Dependabot kan oppdatere
  pins, men endringen må gjennom CI og review.
- Gitleaks er hovedkontroll for hemmeligheter; prosjektets grep-skann er bare
  et supplement.

## Sikkerhetsrapportering

Rapporter sårbarheter privat til `hjelp@ostfoldbussen.no` eller via GitHubs
private security advisory. Ikke legg hemmeligheter eller personopplysninger i
offentlige issues.
