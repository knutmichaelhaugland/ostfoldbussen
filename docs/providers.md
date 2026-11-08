# Leverandører

Kjernen er leverandørnøytral. Alle integrasjoner utenom Entur er valgfrie og av som
standard.

| Provider | Type | Status | Merknad |
|---|---|---|---|
| Entur | Reise- og stedsdata | **Støttet** | Åpen tjeneste; `ET-Client-Name` |
| inMobile | SMS webhook/utgang | **Støttet** | Webhook-signatur og rate limits |
| Bineric | Språkmodell | **Støttet adapter** | Timeout, 429-retry, budsjett |
| Generisk OpenAI-kompatibel | Språkmodell | **Eksperimentell** | Ikke leverandørspesifikk garanti |

## Bytte av leverandør

- Modell: foretrukket grensesnitt er `LLM_ENABLED` med `LLM_BASE_URL`,
  `LLM_MODEL` og `LLM_API_KEY` (OpenAI-kompatibelt). `BINERIC_ENABLED` er en
  valgfri adapter og har ingen standard-URL eller standardmodell.
- SMS: inMobile er første støttede adapter. En ny leverandør implementerer
  [SMS-adaptergrensesnittet](sms-adapters.md) uten endring av reiselogikk eller database.
- Utgående SMS reserverer daglig kapasitet og segmenter atomisk før sending.
  Ukjent sendestatus beholdes som `unknown`; kjernen gjør ingen automatisk retry.
- Ved feil faller appen tilbake til regler; den bytter ikke automatisk til en annen
  betalt leverandør.

## Offisiell tjeneste og selvhosting

Dette er åpen programvare. Den offisielle tjenestens personvernerklæring beskriver
hvilke leverandører og behandlinger som gjelder for den driften. Valgene der er
ikke en teknisk eller lisensmessig forutsetning for andre installasjoner.

En selvhostet installasjon kan velge inMobile eller en egen SMS-adapter, og kan
bruke en OpenAI-kompatibel LLM som operatøren konfigurerer, eller ingen LLM.
Alternative leverandører kan kreve egen adapter, konfigurasjon og
personvernvurdering. `BINERIC_ENABLED` og `LLM_ENABLED` er uavhengige valg; ved
feil bytter applikasjonen ikke automatisk til en annen betalt leverandør.

Ingen leverandør er en forutsetning for å kjøre applikasjonen.

## Vilkår

Den enkelte operatør må avklare leverandørens DPA, vilkår, priser og databehandling.
Navnene innebærer ikke godkjenning eller offisiell tilknytning.
