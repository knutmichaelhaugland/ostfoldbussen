# Deploy

Denne mappen inneholder eksempelkonfigurasjon for Caddy:

- `Caddyfile` — lokal/privat Caddy på `127.0.0.1:8080`.
- `Caddyfile.public` — offentlig HTTPS med allowlist for de offentlige sidene.
  Webhook-ruter, Matomo og operatørspesifikke leverandør-IP-er må legges til av
  operatøren etter egen avtale; de er bevisst ikke hardkodet i det offentlige
  eksempelet.

Produksjon skal bruke egne env-/secret-filer utenfor repoet, HTTPS og en egen
databasekatalog. Offentlig eksempel startes med:

```bash
docker-compose -f docker-compose.yml -f docker-compose.public.yml up -d
``` Se [docs/quickstart.md](../docs/quickstart.md) og
[docs/operations.md](../docs/operations.md). Ingen hemmeligheter skal ligge her.
