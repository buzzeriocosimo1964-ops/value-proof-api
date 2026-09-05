# VALUE PROOF V0.4

## Cosa fa
Riceve due URL pubblici di prodotto, scarica le pagine, prova a leggere dati machine-readable
(JSON-LD `Product` / `Offer`, con fallback meta), verifica che i due prodotti siano confrontabili
e restituisce un `verified_value_delta`.

Endpoint:
- `GET /health`
- `POST /compare`
- Swagger UI: `/docs`

Body:
```json
{
  "before_url": "https://negozio-a.example/prodotto",
  "after_url": "https://negozio-b.example/prodotto"
}
```

## Regole conservative
- Accetta solo http/https.
- Blocca localhost e IP privati per ridurre il rischio SSRF.
- Limita redirect, timeout e dimensione pagina.
- Preferisce GTIN/SKU/MPN; altrimenti richiede alta similarità del nome.
- Se spedizione non è nota su entrambe le offerte, certifica solo il delta di prezzo.
- `VERIFIED` non significa causalità perfetta: significa delta economico osservato su offerte ritenute comparabili.

## Test locale
```bash
pip install -r requirements.txt
python test_local.py
uvicorn main:app --reload
```

## Deploy Render
Il repository è già predisposto con `render.yaml`.
Render per FastAPI usa normalmente:
- build: `pip install -r requirements.txt`
- start: `uvicorn main:app --host 0.0.0.0 --port $PORT`

Dopo il deploy:
- visita `/health`
- poi `/docs`
- usa `POST /compare`

## Cosa manca prima di far pagare
1. Persistenza delle prove (database).
2. Snapshot verificabili del contenuto sorgente.
3. API key/rate limiting.
4. Billing.
5. Test con più merchant e pagine dinamiche/anti-bot.
