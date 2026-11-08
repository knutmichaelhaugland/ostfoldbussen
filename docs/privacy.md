# Personvern og databehandling

Dette dokumentet beskriver den åpne programvaren og hvilke data den kan behandle.
Den offisielle tjenesten på <https://ostfoldbussen.no/personvern> har sin egen
personvernerklæring med navngitte leverandører, behandlingsansvarlig og avtaler.
En selvhostet installasjon må lage egen personverntekst, egne databehandleravtaler
og egne vurderinger; denne filen er ikke en slik erklæring.

## Hva applikasjonen behandler

- **Telefonnummer** brukes til å sende svar og til leveringsstatus. I applikasjonens
  database lagres normalt en HMAC-basert pseudonymisert verdi. Pseudonymisering er
  ikke anonymisering: med tilgang til nøkkelen kan verdien kobles til nummeret.
- **Meldingstekst** brukes til å forstå spørsmålet og gi reiseinformasjon. Den
  opprinnelige SMS-teksten lagres ikke i driftsstatistikken. Dersom
  `MESSAGE_HASH_KEY` er konfigurert, lagres en HMAC-SHA256 av meldingen; uten
  nøkkelen lagres ingen meldingshash. Det finnes ingen usaltet SHA-256-fallback.
- **Kort samtalekontekst** kan inneholde meldingstekst og stedsnavn i inntil
  **30 minutter** for å forstå oppfølgingsspørsmål. Denne lagres ikke som
  driftsstatistikk og slettes ved utløp/opprydding.
- **Teknisk driftsdata** (tidspunkt, resultattype, responstid, feilkategori,
  leveringsstatus) lagres for feilsøking, kvalitet og kostnadskontroll.
- **Logger** skal ikke inneholde rå meldingstekst eller telefonnummer i klartekst.
  Feilregistreringer kan inneholde pseudonym og steds-ID-er for operativ oppfølging.
- **SMS-leverandøren** må behandle telefonnummer og meldingstekst for å levere
  SMS-en. Leverandørens behandling og underleverandører avhenger av operatørens
  avtale og må dokumenteres av operatøren.

## Språkmodell

En språkmodell er valgfri. Når en LLM er aktivert, kan meldingstekst og kort
samtalekontekst sendes til den konfigurerte leverandøren for å tolke spørsmålet.
Reisedata hentes fra Entur; modellen er ikke autoritativ for transportfakta.

Programvaren har en generisk OpenAI-kompatibel adapter og en separat
Bineric-adapter. Den offisielle tjenesten kan bruke Bineric og en konkret modell;
andre operatører kan velge en annen kompatibel leverandør, eller bruke regelbasert
behandling uten LLM. Bytte av leverandør kan kreve konfigurasjon eller egen adapter.

Operatøren må selv kontrollere hvilke direkte identifikatorer som sendes i alle
kallveier og dokumentere leverandørens behandling, lagring og eventuelle
underdatabehandlere. Påstander fra en leverandør om trening eller logging er
leverandørens dokumentasjon, ikke en automatisk garanti i denne kodebasen.

## Informasjonskapsler og statistikk

Nettsiden bruker ikke informasjonskapsler for statistikk i standardoppsettet.
Matomo kan konfigureres cookiefritt og med IP-anonymisering. Tredjepartsannonser
og sporing på tvers av nettsteder er ikke en del av standardoppsettet.

## Lagring og sletting

Standardoppsettet bruker korte TTL-er for samtalekontekst og konfigurerbare
retensjonsgrenser for driftsdata. Utløpt samtalekontekst brukes ikke etter TTL;
fysisk sletting skjer ved oppslag eller når `purge-retention` kjøres. En
Docker-installasjon må selv aktivere en timer/jobb for dette. Operatøren må
kontrollere at faktiske grenser, backupretensjon og leverandørens lagring stemmer
med egen personvernerklæring.
Backup kan inneholde databaseinnhold og må beskyttes og slettes etter operatørens
policy.

## Selvhosting

Den som drifter en egen instans er selv behandlingsansvarlig og må vurdere
behandlingsgrunnlag, leverandører, databehandleravtaler, retensjon,
informasjonsplikt og sikkerhet. De offisielle leverandørene og formuleringene på
ostfoldbussen.no gjelder ikke automatisk for andre installasjoner.
