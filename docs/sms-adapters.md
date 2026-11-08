# SMS-adaptergrensesnitt

SMS-kjernen er leverandøruavhengig. inMobile er første støttede implementasjon.
Twilio-adapteren er ikke aktiv i gjeldende kode. En databasekompatibilitetsmigrering kan fortsatt gjenkjenne den historiske kolonnen `twilio_sid` for eksisterende installasjoner.

## Ansvar

| Lag | Ansvar |
|---|---|
| `app/sms_adapter.py` | Protokoll og dataklasser |
| `app/inmobile_adapter.py` | inMobile-webhook, signatur, request-ID og sending |
| `app/inmobile_sender.py` | inMobile REST-transport |
| `app/server.py` | Felles inbound/outbound-flyt, DB og kostnadsreservasjon |
| `app/db.py` | Idempotens, leveringsstatus og atomisk kapasitet |

## Protokoll

```python
class SmsAdapter(Protocol):
    name: str
    def verify_inbound(headers, body) -> InboundVerification: ...
    def claim_inbound(inbound) -> bool: ...
    def mark_inbound(inbound, status) -> None: ...
    def send(to_number, body, *, pseudonym, idempotency_key, request_id=None) -> SmsSendResult: ...
    def parse_status(params) -> DeliveryStatus | None: ...
```

- `verify_inbound()` eier leverandørens signaturvalidering og må være fail-closed.
- `claim_inbound()` eier leverandørens idempotensnøkkel. Fullførte duplikater skal
  ikke behandles på nytt.
- `send()` skal returnere `sent`, `suppressed` eller en tvetydig feil. Kjernen
  behandler `unknown` konservativt og gjør ingen automatisk retry.
- `parse_status()` er valgfri for leverandører med status-callback.

## Ny adapter

1. Implementer protokollen i egen modul.
2. Valider signatur før noe annet; returner `accepted=False` ved feil.
3. Bruk en leverandørunik request-ID som idempotensnøkkel.
4. Konfigurer adapteren eksplisitt i `create_app()`/`Pipeline`-oppsettet.
5. Legg til en kontraktstest lik `tests/test_sms_adapter.py`.

Kjernen og databasen trenger ikke endres for en ny adapter. Ingen adapter skal
åpne en usignert webhook eller sende utenfor den felles kostnadsreservasjonen.

## inMobile

inMobile bruker ECDSA P-256/SHA-256 over request-ID + timestamp + body.
Hemmeligheter og offentlig nøkkel ligger utenfor repoet. Webhooken er av som
standard, og utgående sending krever eksplisitt aktivering.
