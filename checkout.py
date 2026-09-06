import html
import os
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException
from fastapi.responses import HTMLResponse

from main import app, extract_product, fetch_html, make_proof

STRIPE_API_BASE = "https://api.stripe.com/v1"


def _safe(value) -> str:
    return html.escape(str(value or ""))


def _field_value(session: dict, needle: str) -> str | None:
    needle = needle.casefold()
    for field in session.get("custom_fields") or []:
        label = ((field.get("label") or {}).get("custom") or "").casefold()
        if needle not in label:
            continue
        field_type = field.get("type")
        payload = field.get(field_type) if field_type else None
        if isinstance(payload, dict):
            value = payload.get("value")
            if value:
                return str(value).strip()
    return None


async def _stripe_session(session_id: str) -> dict:
    secret = os.getenv("STRIPE_SECRET_KEY", "").strip()
    if not secret:
        raise RuntimeError("STRIPE_SECRET_KEY is not configured")
    if not session_id.startswith("cs_"):
        raise ValueError("Invalid Checkout Session ID")

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            f"{STRIPE_API_BASE}/checkout/sessions/{session_id}",
            headers={"Authorization": f"Bearer {secret}"},
        )
    if response.status_code != 200:
        raise RuntimeError("Unable to verify the Stripe payment")
    return response.json()


def _page(title: str, body: str, status_code: int = 200) -> HTMLResponse:
    page = f"""<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_safe(title)} · Value Proof</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f6f7f9;color:#111;margin:0;padding:24px}}
.wrap{{max-width:720px;margin:0 auto}}
.brand{{font-size:24px;font-weight:800;margin:8px 0 28px}}
.card{{background:#fff;border:1px solid #e4e7eb;border-radius:18px;padding:24px;box-shadow:0 4px 18px rgba(0,0,0,.05)}}
h1{{font-size:28px;margin:0 0 12px}}
.big{{font-size:42px;font-weight:800;margin:12px 0}}
.row{{display:flex;justify-content:space-between;gap:16px;padding:12px 0;border-top:1px solid #eee}}
.muted{{color:#666;font-size:14px;line-height:1.5}}
</style>
</head>
<body><div class="wrap"><div class="brand">✓ Value Proof</div><div class="card">{body}</div></div></body>
</html>"""
    return HTMLResponse(page, status_code=status_code)


@app.get("/result", response_class=HTMLResponse)
async def checkout_result(session_id: str):
    try:
        session = await _stripe_session(session_id)

        if session.get("payment_status") != "paid":
            return _page(
                "Pagamento in elaborazione",
                "<h1>Pagamento non ancora confermato</h1><p>Stripe sta ancora elaborando il pagamento. Ricarica questa pagina tra poco.</p>",
                202,
            )

        before_url = _field_value(session, "offerta iniziale")
        after_url = _field_value(session, "offerta finale")
        if not before_url or not after_url:
            return _page(
                "Dati mancanti",
                "<h1>Non riesco a leggere le due offerte</h1><p>Il pagamento risulta confermato, ma mancano uno o entrambi gli URL necessari alla verifica.</p>",
                422,
            )

        before_html, before_final = await fetch_html(before_url)
        after_html, after_final = await fetch_html(after_url)
        before = extract_product(before_html, before_final)
        after = extract_product(after_html, after_final)
        proof = make_proof(before, after)

        if proof.get("status") == "REJECTED":
            reason = _safe(proof.get("reason"))
            return _page(
                "Verifica non conclusa",
                f"<h1>Confronto non verificabile</h1><p>Le due pagine non forniscono abbastanza prove per certificare che si tratti dello stesso prodotto.</p><p class='muted'>Motivo tecnico: {reason}</p>",
                422,
            )

        currency = _safe(proof.get("currency") or "EUR")
        before_total = _safe(proof.get("before_total"))
        after_total = _safe(proof.get("after_total"))
        delta = _safe(proof.get("verified_value_delta"))
        method = _safe(proof.get("identity_method"))
        confidence = _safe(proof.get("identity_confidence"))
        scope = _safe(proof.get("verification_scope"))
        proof_hash = _safe(proof.get("proof_hash_sha256"))
        before_host = _safe(urlparse(before_final).netloc)
        after_host = _safe(urlparse(after_final).netloc)
        positive = proof.get("status") == "VERIFIED"

        headline = "Risparmio verificato" if positive else "Nessun risparmio positivo rilevato"
        body = f"""
<h1>{headline}</h1>
<div class="big">{delta} {currency}</div>
<div class="row"><span>Offerta iniziale</span><strong>{before_total} {currency}</strong></div>
<div class="row"><span>Offerta finale</span><strong>{after_total} {currency}</strong></div>
<div class="row"><span>Origini</span><strong>{before_host} → {after_host}</strong></div>
<div class="row"><span>Identità prodotto</span><strong>{method} · {confidence}</strong></div>
<div class="row"><span>Ambito verifica</span><strong>{scope}</strong></div>
<p class="muted">Value Proof certifica una differenza monetaria osservabile tra due offerte pubbliche comparabili. Non garantisce disponibilità futura, costi non pubblicati o causalità economica perfetta.</p>
<p class="muted">Proof hash: {proof_hash}</p>
"""
        return _page(headline, body)

    except HTTPException as exc:
        return _page("Errore di verifica", f"<h1>Verifica non completata</h1><p>{_safe(exc.detail)}</p>", exc.status_code)
    except Exception as exc:
        return _page("Errore di verifica", f"<h1>Verifica non completata</h1><p>{_safe(str(exc))}</p>", 400)
