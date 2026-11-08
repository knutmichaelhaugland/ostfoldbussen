# Valgfri live-test av LLM-adapteren

Den generiske OpenAI-kompatible adapteren testes alltid lokalt mot en
mock-HTTP-server. En ekstern live-test er valgfri og kjøres aldri i vanlig CI.

```bash
LLM_LIVE_TEST=1 \
LLM_LIVE_BASE_URL=https://leverandor.example/v1 \
LLM_LIVE_MODEL=modellnavn \
LLM_LIVE_API_KEY='...' \
python -m unittest tests.test_llm_live
```

Testen sender én syntetisk reiseforespørsel, bruker lavt antall kall og logger
verken nøkkel eller persondata. `LLM_LIVE_BASE_URL`, modell og nøkkel er
leverandøruavhengige; ingen leverandør er hardkodet. Uten de tre
variablene og `LLM_LIVE_TEST=1` hoppes testen over.
