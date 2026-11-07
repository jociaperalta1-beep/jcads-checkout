import main
from fastapi.testclient import TestClient

c = TestClient(main.app)

def test_prices():
    assert main.price_usd(1000) == 3.43
    assert main.price_usd(10000) == 34.30
    assert main.price_usd(100000) == 308.70

def test_quote_min():
    assert c.get("/api/quote?impressions=500").status_code == 400

def test_fallback_plan_fits_budget():
    main.GEMINI_API_KEY = ""
    r = c.post("/api/ai/plan", json={"business": "Bakery", "budget_usd": 35}).json()
    assert r["impressions"] == 10000 and len(r["ads"]) == 3

def test_capture_unknown_order():
    assert c.post("/api/orders/NOPE/capture").status_code == 404

def test_index():
    assert c.get("/").status_code == 200
