"""JC ADS Checkout - AI campaign planner + PayPal (sandbox) checkout for ad impression packages.

Run:  pip install -r requirements.txt && uvicorn main:app --reload
Env:  PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET (sandbox), GEMINI_API_KEY
"""
import json
import os
import re
import time
import uuid
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

PAYPAL_BASE = os.getenv("PAYPAL_BASE", "https://api-m.sandbox.paypal.com")
PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID", "")
PAYPAL_CLIENT_SECRET = os.getenv("PAYPAL_CLIENT_SECRET", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

CPM_USD = 3.43            # price per 1,000 impressions
DISCOUNT_FROM = 50_000    # 10% off from 50k impressions
MIN_IMPRESSIONS = 1_000
MAX_IMPRESSIONS = 1_000_000
PACKAGES = [1_000, 2_000, 3_000, 10_000, 20_000, 30_000, 50_000, 100_000]

STATIC = Path(__file__).parent
app = FastAPI(title="JC ADS Checkout", version="1.0.0")

# In-memory store (demo). Campaigns become ACTIVE only after PayPal capture COMPLETED
# with the exact expected amount.
ORDERS: dict[str, dict] = {}
CAMPAIGNS: dict[str, dict] = {}


def price_usd(impressions: int) -> float:
    if impressions < MIN_IMPRESSIONS or impressions > MAX_IMPRESSIONS:
        raise HTTPException(400, f"impressions must be between {MIN_IMPRESSIONS} and {MAX_IMPRESSIONS}")
    total = impressions / 1000 * CPM_USD
    if impressions >= DISCOUNT_FROM:
        total *= 0.9
    return round(total + 1e-9, 2)


# ---------------------------------------------------------------- AI planner
class PlanIn(BaseModel):
    business: str = Field(..., min_length=3, max_length=500)
    goal: str = Field("more customers", max_length=200)
    budget_usd: float = Field(..., ge=3.43, le=3000)
    language: str = Field("English", max_length=30)


def nearest_package(budget: float) -> int:
    best = PACKAGES[0]
    for p in PACKAGES:
        if price_usd(p) <= budget:
            best = p
    return best


def fallback_plan(data: PlanIn) -> dict:
    imp = nearest_package(data.budget_usd)
    name = data.business.strip().split(".")[0][:60]
    return {
        "impressions": imp,
        "reason": f"The largest package that fits a US${data.budget_usd:.2f} budget.",
        "ads": [
            {"headline": f"{name}: discover us today", "text": f"{name}. {data.goal.capitalize()} starts here."},
            {"headline": f"Why choose {name}?", "text": "Quality, fair prices and real service. Visit us now."},
            {"headline": "Limited-time offer", "text": f"Get to know {name} this week."},
        ],
        "source": "fallback",
    }


def parse_json_block(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no json")
    return json.loads(m.group(0))


@app.post("/api/ai/plan")
async def ai_plan(data: PlanIn):
    """Gemini acts as a campaign agent: picks the package and writes 3 ad variants."""
    if not GEMINI_API_KEY:
        return fallback_plan(data)
    options = ", ".join(f"{p} impressions = US${price_usd(p):.2f}" for p in PACKAGES)
    prompt = (
        "You are the campaign planner of JC ADS, a digital ad network. "
        f"Business: {data.business}\nGoal: {data.goal}\nBudget: US${data.budget_usd:.2f}\n"
        f"Packages: {options}. Custom amounts >= 1000 impressions also allowed at US$3.43 per 1000 "
        "(10% off from 50,000).\n"
        "Pick the best number of impressions that does NOT exceed the budget. Then write 3 short, honest "
        f"ad variants in {data.language} (headline max 40 chars, text max 90 chars). No fake claims, "
        "no 'easy money', no prices. Reply ONLY with JSON: "
        '{"impressions": int, "reason": str, "ads": [{"headline": str, "text": str}]}'
    )
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(url, params={"key": GEMINI_API_KEY},
                             json={"contents": [{"parts": [{"text": prompt}]}],
                                   "generationConfig": {"temperature": 0.7,
                                                        "responseMimeType": "application/json"}})
        r.raise_for_status()
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        plan = parse_json_block(text)
        imp = int(plan.get("impressions", 0))
        imp = max(MIN_IMPRESSIONS, min(imp, MAX_IMPRESSIONS))
        while imp > MIN_IMPRESSIONS and price_usd(imp) > data.budget_usd:
            imp -= 1000
        plan["impressions"] = imp
        plan["ads"] = plan.get("ads", [])[:3]
        plan["source"] = "gemini"
        return plan
    except Exception:
        return fallback_plan(data)


@app.get("/api/quote")
def quote(impressions: int):
    return {"impressions": impressions, "amount_usd": f"{price_usd(impressions):.2f}"}


# ---------------------------------------------------------------- PayPal
_token = {"value": None, "exp": 0}


async def paypal_token() -> str:
    if not PAYPAL_CLIENT_ID or not PAYPAL_CLIENT_SECRET:
        raise HTTPException(500, "PayPal sandbox credentials are not configured")
    if _token["value"] and _token["exp"] > time.time() + 60:
        return _token["value"]
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{PAYPAL_BASE}/v1/oauth2/token", data={"grant_type": "client_credentials"},
                         auth=(PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET))
    if r.status_code != 200:
        raise HTTPException(502, "PayPal auth failed")
    j = r.json()
    _token.update(value=j["access_token"], exp=time.time() + int(j.get("expires_in", 3000)))
    return _token["value"]


class OrderIn(BaseModel):
    impressions: int
    headline: str = Field(..., min_length=2, max_length=60)
    text: str = Field(..., min_length=2, max_length=140)
    url: str = Field("https://jcads.net", max_length=300)


@app.post("/api/orders")
async def create_order(o: OrderIn):
    amount = f"{price_usd(o.impressions):.2f}"
    ref = uuid.uuid4().hex[:12]
    token = await paypal_token()
    body = {
        "intent": "CAPTURE",
        "purchase_units": [{
            "reference_id": ref,
            "description": f"JC ADS - {o.impressions:,} ad impressions",
            "amount": {"currency_code": "USD", "value": amount},
        }],
        "application_context": {"brand_name": "JC ADS", "shipping_preference": "NO_SHIPPING",
                                "user_action": "PAY_NOW"},
    }
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{PAYPAL_BASE}/v2/checkout/orders", json=body,
                         headers={"Authorization": f"Bearer {token}", "PayPal-Request-Id": ref})
    if r.status_code not in (200, 201):
        raise HTTPException(502, f"PayPal create order failed: {r.text[:200]}")
    oid = r.json()["id"]
    ORDERS[oid] = {"ref": ref, "amount": amount, "impressions": o.impressions,
                   "ad": o.model_dump(), "status": "CREATED"}
    return {"id": oid, "amount_usd": amount}


@app.post("/api/orders/{order_id}/capture")
async def capture_order(order_id: str):
    order = ORDERS.get(order_id)
    if not order:
        raise HTTPException(404, "unknown order")
    if order["status"] == "COMPLETED":
        return {"status": "COMPLETED", "campaign": CAMPAIGNS[order_id]}
    token = await paypal_token()
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{PAYPAL_BASE}/v2/checkout/orders/{order_id}/capture",
                         headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    if r.status_code not in (200, 201):
        raise HTTPException(502, f"PayPal capture failed: {r.text[:200]}")
    j = r.json()
    cap = j["purchase_units"][0]["payments"]["captures"][0]
    paid = cap["amount"]["value"]
    if j.get("status") != "COMPLETED" or paid != order["amount"] or cap["amount"]["currency_code"] != "USD":
        order["status"] = "MISMATCH"
        raise HTTPException(409, "payment not completed or amount mismatch; campaign not activated")
    order["status"] = "COMPLETED"
    CAMPAIGNS[order_id] = {"order_id": order_id, "capture_id": cap["id"], "paid_usd": paid,
                           "impressions_paid": order["impressions"], "impressions_served": 0,
                           "ad": order["ad"], "status": "ACTIVE"}
    return {"status": "COMPLETED", "campaign": CAMPAIGNS[order_id]}


@app.get("/api/campaigns")
def campaigns():
    return list(CAMPAIGNS.values())


@app.get("/api/config")
def config():
    return {"paypal_client_id": PAYPAL_CLIENT_ID, "cpm_usd": CPM_USD, "packages": PACKAGES,
            "ai": bool(GEMINI_API_KEY)}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")

