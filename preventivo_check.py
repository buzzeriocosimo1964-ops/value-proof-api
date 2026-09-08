import html
import os

import httpx
from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import HTMLResponse

from preventivo_core import CHECKS, MAX_PDF_BYTES, analyze_quote_text, compare_quotes, extract_pdf_text


router = APIRouter()
STRIPE_API_BASE = "https://api.stripe.com/v1"


def _safe(value: object) -> str:
    return html.escape(str(value or ""))


async def _paid_session(session_id: str) -> dict:
    secret = os.getenv("STRIPE_SECRET_KEY", "").strip()
    expected_payment_link = os.getenv("PREVENTIVO_CHECK_PAYMENT_LINK_ID", "").strip()
    if not secret or not expected_payment_link.startswith("plink_") or not session_id.startswith("cs_"):
        raise ValueError("Sessione di pagamento non valida")
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            f"{STRIPE_API_BASE}/checkout/sessions/{session_id}",
            headers={"Authorization": f"Bearer {secret}"},
        )
    payload = response.json() if response.status_code == 200 else {}
    if (
        payload.get("payment_status") != "paid"
        or payload.get("amount_total") != 1990
        or payload.get("currency") != "eur"
        or payload.get("payment_link") != expected_payment_link
    ):
        raise ValueError("Pagamento non confermato")
    return payload


def _layout(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(f"""<!doctype html><html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{_safe(title)} · PreventivoCheck</title>
<style>
:root{{--ink:#172033;--muted:#667085;--line:#e2e7ee;--accent:#e8572a;--soft:#fff2ec;--good:#18794e}}
*{{box-sizing:border-box}}body{{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f8fafc;color:var(--ink)}}
.wrap{{width:min(960px,calc(100% - 32px));margin:auto}}header{{padding:22px 0;font-weight:850;font-size:21px}}main{{padding:34px 0 70px}}
.hero{{display:grid;grid-template-columns:1.15fr .85fr;gap:34px;align-items:center}}h1{{font-size:clamp(40px,7vw,68px);line-height:1.02;letter-spacing:-2px;margin:0 0 20px}}
.lead{{font-size:19px;line-height:1.55;color:var(--muted)}}.pill{{display:inline-block;background:var(--soft);color:#b83b16;border-radius:999px;padding:7px 11px;font-weight:750;font-size:13px}}
.cta,button{{display:inline-flex;border:0;border-radius:12px;background:var(--accent);color:white;font-weight:800;padding:15px 20px;text-decoration:none;font-size:16px;cursor:pointer}}
.card{{background:white;border:1px solid var(--line);border-radius:18px;padding:22px;box-shadow:0 14px 42px rgba(20,35,60,.08)}}
.checks{{list-style:none;padding:0;margin:0}}.checks li{{padding:11px 0;border-top:1px solid #edf0f4}}.checks li:before{{content:'✓';color:var(--good);font-weight:900;margin-right:10px}}
.formgrid{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}label{{display:block;font-weight:750;margin-bottom:8px}}input[type=file]{{width:100%;padding:18px;border:1px dashed #aab4c2;border-radius:12px;background:#fff}}
.metric{{font-size:36px;font-weight:850}}.muted{{color:var(--muted);line-height:1.5}}table{{width:100%;border-collapse:collapse}}td,th{{padding:12px;text-align:left;border-bottom:1px solid var(--line)}}
.yes{{color:var(--good);font-weight:800}}.no{{color:#b42318;font-weight:800}}.notice{{padding:14px;background:#fff8e7;border-radius:10px;color:#684900;margin:18px 0}}
@media(max-width:720px){{.hero,.formgrid{{grid-template-columns:1fr}}h1{{letter-spacing:-1px}}.cta,button{{width:100%;justify-content:center}}}}
</style></head><body><div class="wrap"><header>✓ PreventivoCheck <span class="pill">Beta</span></header><main>{body}</main></div></body></html>""")


@router.get("/preventivo-check", response_class=HTMLResponse)
def landing():
    payment_link = os.getenv("PREVENTIVO_CHECK_PAYMENT_LINK_URL", "").strip()
    cta = (
        f'<a class="cta" href="{_safe(payment_link)}">Controlla i preventivi · 19,90 €</a>'
        if payment_link.startswith("https://buy.stripe.com/")
        else '<span class="cta" style="opacity:.55">Apertura vendite a breve</span>'
    )
    return _layout("Controlla il preventivo prima di firmare", f"""
<section class="hero"><div><span class="pill">Per lavori edili e ristrutturazioni</span>
<h1>Il preventivo più basso può costarti di più.</h1>
<p class="lead">Carica uno o due preventivi. PreventivoCheck individua voci mancanti, descrizioni vaghe e differenze che possono trasformarsi in lavori extra.</p>
{cta}<p class="muted">Pagamento sicuro con Stripe · PDF non archiviati dopo l'analisi · In beta sono supportati PDF con testo selezionabile, non scansioni fotografiche</p></div>
<aside class="card"><h2>Controllo immediato</h2><ul class="checks"><li>IVA e totale dichiarato</li><li>Materiali, quantità e unità</li><li>Sicurezza e smaltimento</li><li>Tempi, pagamenti e garanzie</li><li>Esclusioni e possibili extra</li></ul></aside></section>
<section style="margin-top:56px"><h2>Cosa ricevi</h2><div class="formgrid"><div class="card"><h3>Indice di completezza</h3><p class="muted">Una lettura strutturata delle informazioni presenti e mancanti.</p></div><div class="card"><h3>Confronto voce per voce</h3><p class="muted">Le differenze importanti tra due offerte, oltre al semplice totale.</p></div></div></section>
<div class="notice">Strumento informativo: non sostituisce una perizia, un computo metrico o il parere di un tecnico abilitato.</div>
""")


@router.get("/preventivo-check/upload", response_class=HTMLResponse)
async def upload_form(session_id: str):
    try:
        await _paid_session(session_id)
    except ValueError as exc:
        return _layout("Pagamento da verificare", f"<div class='card'><h1>Accesso non disponibile</h1><p>{_safe(exc)}</p></div>")
    return _layout("Carica i preventivi", f"""
<div class="card"><h1 style="font-size:40px">Carica i preventivi</h1><p class="muted">Il primo PDF è obbligatorio; il secondo serve per il confronto diretto.</p>
<form action="/preventivo-check/analyze" method="post" enctype="multipart/form-data">
<input type="hidden" name="session_id" value="{_safe(session_id)}"><div class="formgrid">
<div><label for="first">Preventivo A</label><input id="first" name="first" type="file" accept="application/pdf" required></div>
<div><label for="second">Preventivo B (facoltativo)</label><input id="second" name="second" type="file" accept="application/pdf"></div></div>
<button type="submit" style="margin-top:20px">Analizza ora</button></form></div>
""")


@router.post("/preventivo-check/analyze", response_class=HTMLResponse)
async def analyze_upload(
    session_id: str = Form(...),
    first: UploadFile = File(...),
    second: UploadFile | None = File(None),
):
    try:
        await _paid_session(session_id)
        first_data = await first.read(MAX_PDF_BYTES + 1)
        first_result = analyze_quote_text(extract_pdf_text(first_data), first.filename or "Preventivo A")
        second_result = None
        if second and second.filename:
            second_data = await second.read(MAX_PDF_BYTES + 1)
            second_result = analyze_quote_text(extract_pdf_text(second_data), second.filename)
        report = compare_quotes(first_result, second_result)
    except Exception as exc:
        return _layout("Analisi non completata", f"<div class='card'><h1>Non riesco ad analizzare il file</h1><p>{_safe(exc)}</p></div>")

    quotes = [report["first"]] + ([report["second"]] if report["second"] else [])
    headers = "".join(f"<th>{_safe(q['name'])}</th>" for q in quotes)
    rows = []
    for key, (label, _) in CHECKS.items():
        cells = "".join(
            f"<td class={'yes' if q['coverage'][key]['present'] else 'no'}>{'Presente' if q['coverage'][key]['present'] else 'Da chiarire'}</td>"
            for q in quotes
        )
        rows.append(f"<tr><th>{_safe(label)}</th>{cells}</tr>")
    totals = " · ".join(
        f"{_safe(q['name'])}: {q['total']:.2f} €" if q["total"] is not None else f"{_safe(q['name'])}: totale non rilevato"
        for q in quotes
    )
    delta = ""
    if report["delta"] is not None:
        delta = f"<p><strong>Differenza osservata:</strong> {report['delta']:.2f} € · importo più basso: {_safe(report['lower'])}</p>"
    score_cards = "".join(
        f"<p class='metric'>{q['score']}% "
        f"<span class='muted' style='font-size:16px'>completezza · {_safe(q['name'])}</span></p>"
        for q in quotes
    )
    return _layout("Report", f"""
<div class="card"><span class="pill">Report immediato</span><h1 style="font-size:42px">Confronto preventivi</h1>
{score_cards}
<p>{totals}</p>{delta}<div style="overflow:auto"><table><thead><tr><th>Controllo</th>{headers}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<div class="notice">“Da chiarire” non significa necessariamente che il costo sia scorretto: indica che l'informazione non è stata trovata nel testo del PDF e va chiesta all'impresa prima della firma.</div></div>
""")
