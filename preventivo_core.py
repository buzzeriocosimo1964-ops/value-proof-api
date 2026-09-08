import io
import re
from decimal import Decimal, InvalidOperation

from pypdf import PdfReader


MAX_PDF_BYTES = 8_000_000
MAX_PAGES = 40

CHECKS = {
    "iva": ("IVA e aliquota", (r"\biva\b", r"imposta sul valore aggiunto")),
    "sicurezza": ("Oneri di sicurezza", (r"\bsicurezz\w*\b", r"d[.]?lgs[.]?\s*81")),
    "smaltimento": ("Smaltimento e trasporto macerie", (r"smaltiment\w*", r"macerie", r"discarica")),
    "materiali": ("Materiali, marche o modelli", (r"material\w*", r"marca", r"modello", r"fornitura")),
    "quantita": ("Quantità e unità di misura", (r"\bq[.]?t[aà]\b", r"\bmq\b", r"m²", r"\bml\b", r"\bcad\b")),
    "tempi": ("Tempi di esecuzione", (r"giorni lavorativi", r"settimane", r"durata lavori", r"fine lavori")),
    "pagamenti": ("Scadenze dei pagamenti", (r"acconto", r"saldo", r"pagament\w*", r"s[.]?a[.]?l[.]?")),
    "garanzia": ("Garanzie", (r"garanzi\w*", r"vizi", r"difformit[aà]")),
    "esclusioni": ("Esclusioni e lavori extra", (r"esclus\w*", r"non compres\w*", r"extra", r"a parte")),
    "validita": ("Validità dell'offerta", (r"validit[aà]", r"offerta valida", r"scadenza")),
}

TOTAL_LABELS = (
    "totale preventivo",
    "totale complessivo",
    "importo complessivo",
    "totale lavori",
    "totale generale",
    "totale",
)


def _parse_amount(raw: str) -> Decimal:
    value = re.sub(r"[^0-9,.-]", "", raw.strip())
    if not value:
        raise ValueError("Importo vuoto")
    if "," in value and "." in value:
        if value.rfind(",") > value.rfind("."):
            value = value.replace(".", "").replace(",", ".")
        else:
            value = value.replace(",", "")
    elif "," in value:
        value = value.replace(".", "").replace(",", ".")
    elif value.count(".") > 1:
        value = value.replace(".", "")
    try:
        return Decimal(value).quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ValueError("Importo non riconosciuto") from exc


def extract_pdf_text(data: bytes) -> str:
    if not data or len(data) > MAX_PDF_BYTES:
        raise ValueError("Il PDF deve avere una dimensione massima di 8 MB")
    if not data.startswith(b"%PDF"):
        raise ValueError("Il file non sembra essere un PDF valido")
    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:
        raise ValueError("Non riesco ad aprire il PDF") from exc
    if len(reader.pages) > MAX_PAGES:
        raise ValueError("Il PDF supera il limite di 40 pagine")
    text = "\n".join((page.extract_text() or "") for page in reader.pages).strip()
    if len(text) < 40:
        raise ValueError("Il PDF non contiene testo leggibile; potrebbe essere una scansione")
    return text[:250_000]


def _amounts_in_line(line: str) -> list[Decimal]:
    tokens = re.findall(r"(?<!\d)(?:\d{1,3}(?:[. ]\d{3})+|\d+)(?:,\d{2})?(?!\d)", line)
    amounts = []
    for token in tokens:
        try:
            amounts.append(_parse_amount(token))
        except ValueError:
            continue
    return amounts


def extract_total(text: str) -> Decimal | None:
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]
    for label in TOTAL_LABELS:
        for line in reversed(lines):
            if label in line.casefold():
                amounts = _amounts_in_line(line)
                if amounts:
                    return amounts[-1]
    return None


def analyze_quote_text(text: str, name: str) -> dict:
    normalized = re.sub(r"\s+", " ", text.casefold())
    coverage = {}
    for key, (label, patterns) in CHECKS.items():
        coverage[key] = {
            "label": label,
            "present": any(re.search(pattern, normalized, re.IGNORECASE) for pattern in patterns),
        }
    total = extract_total(text)
    present_count = sum(1 for item in coverage.values() if item["present"])
    return {
        "name": name,
        "total": total,
        "coverage": coverage,
        "score": round(100 * present_count / len(CHECKS)),
        "missing": [item["label"] for item in coverage.values() if not item["present"]],
    }


def compare_quotes(first: dict, second: dict | None = None) -> dict:
    result = {"first": first, "second": second, "delta": None, "lower": None, "different_items": []}
    if not second:
        return result
    if first["total"] is not None and second["total"] is not None:
        result["delta"] = abs(first["total"] - second["total"])
        result["lower"] = first["name"] if first["total"] < second["total"] else second["name"]
    for key in CHECKS:
        if first["coverage"][key]["present"] != second["coverage"][key]["present"]:
            result["different_items"].append(first["coverage"][key]["label"])
    return result
