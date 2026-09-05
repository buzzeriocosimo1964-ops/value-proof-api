
import asyncio
import hashlib
import ipaddress
import json
import re
import socket
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl

APP_VERSION = "0.4"
MAX_BYTES = 2_000_000
TIMEOUT_SECONDS = 8.0
MAX_REDIRECTS = 3
USER_AGENT = "ValueProofBot/0.4 (+price-verification prototype)"

app = FastAPI(
    title="VALUE PROOF",
    version=APP_VERSION,
    description="Evidence-backed economic delta verification from two public product URLs."
)

class CompareRequest(BaseModel):
    before_url: HttpUrl
    after_url: HttpUrl

def money(v: Any) -> Decimal:
    try:
        return Decimal(str(v).replace(",", ".")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"Invalid money value: {v!r}")

def norm(s: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()

def token_similarity(a: str, b: str) -> float:
    sa, sb = set(norm(a).split()), set(norm(b).split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)

def is_public_ip(ip: str) -> bool:
    obj = ipaddress.ip_address(ip)
    return not (
        obj.is_private or obj.is_loopback or obj.is_link_local or
        obj.is_multicast or obj.is_reserved or obj.is_unspecified
    )

async def validate_public_url(url: str) -> None:
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        raise ValueError("Only http/https URLs are allowed")
    if not p.hostname:
        raise ValueError("URL has no hostname")
    if p.hostname.lower() in {"localhost", "localhost.localdomain"}:
        raise ValueError("Local hosts are not allowed")
    try:
        infos = await asyncio.get_running_loop().run_in_executor(
            None, socket.getaddrinfo, p.hostname, p.port or (443 if p.scheme == "https" else 80)
        )
    except socket.gaierror as e:
        raise ValueError(f"DNS resolution failed: {e}") from e
    ips = {info[4][0] for info in infos}
    if not ips or not all(is_public_ip(ip) for ip in ips):
        raise ValueError("URL resolves to a private or non-public IP")

async def fetch_html(url: str) -> tuple[str, str]:
    current = url
    async with httpx.AsyncClient(
        timeout=TIMEOUT_SECONDS,
        follow_redirects=False,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            await validate_public_url(current)
            async with client.stream("GET", current) as resp:
                if 300 <= resp.status_code < 400:
                    loc = resp.headers.get("location")
                    if not loc:
                        raise ValueError("Redirect without Location header")
                    current = urljoin(current, loc)
                    continue
                resp.raise_for_status()
                ctype = resp.headers.get("content-type", "").lower()
                if "text/html" not in ctype and "application/xhtml+xml" not in ctype:
                    raise ValueError(f"Unsupported content type: {ctype or 'unknown'}")
                data = bytearray()
                async for chunk in resp.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_BYTES:
                        raise ValueError("Page exceeds 2 MB safety limit")
                encoding = resp.encoding or "utf-8"
                return data.decode(encoding, errors="replace"), str(resp.url)
        raise ValueError("Too many redirects")

def flatten_jsonld(obj: Any) -> list[dict]:
    out = []
    if isinstance(obj, dict):
        out.append(obj)
        for k in ("@graph", "itemListElement"):
            if k in obj:
                out.extend(flatten_jsonld(obj[k]))
    elif isinstance(obj, list):
        for x in obj:
            out.extend(flatten_jsonld(x))
    return out

def first_offer(product: dict) -> dict:
    offers = product.get("offers") or {}
    if isinstance(offers, list):
        return next((x for x in offers if isinstance(x, dict)), {})
    return offers if isinstance(offers, dict) else {}

def extract_product(html: str, source_url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    candidates = []
    for tag in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        raw = tag.string or tag.get_text()
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        for item in flatten_jsonld(obj):
            typ = item.get("@type")
            types = typ if isinstance(typ, list) else [typ]
            if any(str(t).lower() == "product" for t in types if t):
                candidates.append(item)

    for p in candidates:
        offer = first_offer(p)
        price = offer.get("price")
        if price is None and isinstance(offer.get("priceSpecification"), dict):
            price = offer["priceSpecification"].get("price")
        currency = offer.get("priceCurrency")
        if price is not None:
            shipping = Decimal("0.00")
            # V0.4 only counts explicit zero shipping; unknown shipping stays unknown.
            ship_details = offer.get("shippingDetails")
            shipping_known = False
            if isinstance(ship_details, dict):
                rate = ship_details.get("shippingRate")
                if isinstance(rate, dict) and rate.get("value") is not None:
                    shipping = money(rate["value"])
                    shipping_known = True
            return {
                "source_url": source_url,
                "name": p.get("name"),
                "sku": p.get("sku"),
                "gtin": p.get("gtin13") or p.get("gtin14") or p.get("gtin12") or p.get("gtin"),
                "mpn": p.get("mpn"),
                "brand": (p.get("brand") or {}).get("name") if isinstance(p.get("brand"), dict) else p.get("brand"),
                "price": str(money(price)),
                "currency": currency,
                "shipping": str(shipping) if shipping_known else None,
                "availability": offer.get("availability"),
                "extraction_method": "jsonld_product_offer",
            }

    # Conservative fallback: OpenGraph/meta price. Identity may be too weak, so comparator can reject.
    def meta_value(*keys):
        for key in keys:
            t = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
            if t and t.get("content"):
                return t["content"].strip()
        return None

    price = meta_value("product:price:amount", "og:price:amount")
    currency = meta_value("product:price:currency", "og:price:currency")
    title = meta_value("og:title") or (soup.title.string.strip() if soup.title and soup.title.string else None)
    if price:
        return {
            "source_url": source_url,
            "name": title,
            "sku": None, "gtin": None, "mpn": None, "brand": None,
            "price": str(money(price)),
            "currency": currency,
            "shipping": None,
            "availability": None,
            "extraction_method": "meta_fallback",
        }
    raise ValueError("No machine-readable Product/Offer price found")

def identity_check(a: dict, b: dict) -> tuple[bool, str, float]:
    for key in ("gtin", "sku", "mpn"):
        if a.get(key) and b.get(key):
            if norm(a[key]) == norm(b[key]):
                return True, f"matching_{key}", 1.0
            return False, f"conflicting_{key}", 0.0

    sim = token_similarity(a.get("name", ""), b.get("name", ""))
    brand_ok = (not a.get("brand") or not b.get("brand") or norm(a["brand"]) == norm(b["brand"]))
    if sim >= 0.80 and brand_ok:
        return True, "high_name_similarity", round(sim, 3)
    return False, "insufficient_identity_evidence", round(sim, 3)

def make_proof(before: dict, after: dict) -> dict:
    same, reason, confidence = identity_check(before, after)
    if not same:
        return {"status": "REJECTED", "proof_version": APP_VERSION,
                "reason": reason, "identity_confidence": confidence,
                "before": before, "after": after}

    if not before.get("currency") or not after.get("currency") or before["currency"] != after["currency"]:
        return {"status": "REJECTED", "proof_version": APP_VERSION, "reason": "currency_mismatch_or_missing"}

    # Shipping is counted only if known on BOTH sides. Otherwise we certify price delta only.
    bp, ap = money(before["price"]), money(after["price"])
    if before.get("shipping") is not None and after.get("shipping") is not None:
        bt = bp + money(before["shipping"])
        at = ap + money(after["shipping"])
        scope = "price_plus_known_shipping"
    else:
        bt, at = bp, ap
        scope = "item_price_only"

    delta = (bt - at).quantize(Decimal("0.01"))
    evidence_before = hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest()
    evidence_after = hashlib.sha256(json.dumps(after, sort_keys=True).encode()).hexdigest()

    proof = {
        "status": "VERIFIED" if delta > 0 else "NO_POSITIVE_VALUE",
        "proof_version": APP_VERSION,
        "currency": before["currency"],
        "before_total": str(bt),
        "after_total": str(at),
        "verified_value_delta": str(delta),
        "verification_scope": scope,
        "identity_method": reason,
        "identity_confidence": confidence,
        "evidence_hashes": {"before": evidence_before, "after": evidence_after},
        "before": before,
        "after": after,
        "limitations": [
            "Public page data can change after capture.",
            "A VERIFIED result means a comparable observed monetary delta, not perfect causal attribution.",
            "Unknown shipping/taxes/fees are excluded unless machine-readable on both offers."
        ],
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }
    canonical = json.dumps(proof, sort_keys=True, separators=(",", ":")).encode()
    proof["proof_hash_sha256"] = hashlib.sha256(canonical).hexdigest()
    return proof

@app.get("/")
def root():
    return {"service": "VALUE PROOF", "version": APP_VERSION, "status": "ready"}

@app.get("/health")
def health():
    return {"status": "ok", "version": APP_VERSION}

@app.post("/compare")
async def compare(req: CompareRequest):
    try:
        before_html, before_final = await fetch_html(str(req.before_url))
        after_html, after_final = await fetch_html(str(req.after_url))
        before = extract_product(before_html, before_final)
        after = extract_product(after_html, after_final)
        result = make_proof(before, after)
        if result["status"] == "REJECTED":
            raise HTTPException(status_code=422, detail=result)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail={"error": str(e), "version": APP_VERSION})
