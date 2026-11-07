# JC ADS Checkout — AI campaign planner + PayPal checkout

JC ADS is an international digital ad network for small businesses. This app lets a small business
owner go from "I have US$35" to a paid, live ad campaign in under a minute:

1. **AI campaign planner (Google Gemini).** The owner describes the business, goal and budget. Gemini
   acts as a campaign agent: it picks the impression package that fits the budget (never above it) and
   writes three honest ad variants in English, Spanish, Portuguese or German.
2. **PayPal checkout (Orders v2, Sandbox).** The owner edits the ad and pays with PayPal Smart Buttons.
   The server creates the order with the exact package price and captures it after approval.
3. **Pay-before-serve safety.** The campaign becomes ACTIVE only when PayPal returns `COMPLETED` and the
   captured amount and currency match the server-side price exactly. JC ADS never serves more
   impressions than were paid for.

Pricing: US$3.43 per 1,000 impressions, minimum 1,000, 10% off from 50,000 impressions.

## Problem
Small businesses want to advertise online but big ad platforms are complex and they fear overspending.
JC ADS shows the exact price first, writes the ads for them, and takes payment in one trusted step.

## Tech
- Python FastAPI backend (`main.py`), single-page frontend (`index.html`)
- PayPal REST: OAuth2 client credentials, `POST /v2/checkout/orders`, `POST /v2/checkout/orders/{id}/capture`, PayPal JS SDK buttons
- Google Gemini `generateContent` (JSON output) with a safe fallback planner when no key is set

## Run locally
```bash
pip install -r requirements.txt
export PAYPAL_CLIENT_ID=your_sandbox_client_id
export PAYPAL_CLIENT_SECRET=your_sandbox_secret
export GEMINI_API_KEY=your_gemini_key        # optional, free at https://aistudio.google.com/app/apikey
uvicorn main:app --reload
# open http://127.0.0.1:8000
```
Pay with a PayPal **sandbox personal account** (Developer Dashboard → Testing Tools → Sandbox accounts).

## Tests
```bash
pip install pytest && pytest -q
```

## API
| Method | Path | What it does |
|---|---|---|
| GET | `/api/quote?impressions=N` | Exact price for N impressions |
| POST | `/api/ai/plan` | Gemini picks package + writes 3 ads |
| POST | `/api/orders` | Creates PayPal order at server price |
| POST | `/api/orders/{id}/capture` | Captures, verifies amount, activates campaign |
| GET | `/api/campaigns` | Active (paid) campaigns |

## What's next
Connect activated campaigns to the JC ADS ad server (jcads.net), PayPal Payouts for partner sites,
and PayPal Subscriptions for monthly ad plans.

## License
MIT
