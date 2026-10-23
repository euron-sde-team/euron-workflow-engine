"""Deterministic demo APIs for "Northwind Outfitters", a fictional outdoor-gear retailer.

They give the templates, `make demo` and the tests real HTTP endpoints to call without the
internet: a shop, a fulfillment service that fails a shipment's first attempt (so retries
show up in the history), a CRM for lead enrichment, a billing service, a status page and a
Slack-compatible incoming-webhook receiver that keeps what it receives.

    wfe demo-apis --port 9131

Every answer is derived from its inputs, so runs are reproducible. State (the received
Slack messages, first-attempt failures) lives in memory and resets with the process.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections import deque
from datetime import UTC, datetime, timedelta
from html import escape
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse

CUSTOMERS = [
    ("Maya Patel", "maya@trailhead.example.com", "gold"),
    ("Jonas Berg", "jonas@fjordline.example.com", "silver"),
    ("Aiko Tanaka", "aiko@summitworks.example.com", "gold"),
    ("Liam O'Connor", "liam@harborview.example.com", "bronze"),
    ("Sofia Rossi", "sofia@dolomiti.example.com", "silver"),
    ("Kwame Mensah", "kwame@savanna.example.com", "bronze"),
]
PRODUCTS = [
    ("TENT-2P", "Ridge 2-person tent", 249.0),
    ("BAG-20F", "Down sleeping bag 20F", 189.0),
    ("LAMP-USB", "Rechargeable camp lantern", 39.5),
    ("PACK-45", "Alpine pack 45L", 159.0),
    ("STOVE-1", "Ultralight stove", 64.0),
    ("JKT-RAIN", "Storm rain jacket", 129.0),
]
INVENTORY = {
    "TENT-2P": 42,
    "BAG-20F": 6,
    "LAMP-USB": 3,
    "PACK-45": 18,
    "STOVE-1": 2,
    "JKT-RAIN": 25,
}
COMPANIES = {
    "trailhead.example.com": ("Trailhead Guides", 1200, "Tourism"),
    "fjordline.example.com": ("Fjordline Ferries", 340, "Transport"),
    "summitworks.example.com": ("Summit Works", 5400, "Manufacturing"),
    "harborview.example.com": ("Harborview Cafe", 18, "Hospitality"),
}


def _digest(*parts: object) -> int:
    return int(hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:8], 16)


def order(number: int) -> dict[str, Any]:
    name, email, tier = CUSTOMERS[number % len(CUSTOMERS)]
    lines: list[dict[str, Any]] = []
    total = 0.0
    for offset in range(1 + number % 3):
        sku, title, price = PRODUCTS[(number + offset * 2) % len(PRODUCTS)]
        qty = 1 + (number + offset) % 3
        lines.append({"sku": sku, "title": title, "qty": qty, "price": price})
        total += qty * price
    total = round(total, 2)
    return {
        "id": f"SO-{1000 + number}",
        "customer": {"name": name, "email": email, "tier": tier},
        "items": lines,
        "total": total,
        "currency": "USD",
        "status": "open" if number % 4 else "paid",
        "placed_at": (datetime(2026, 10, 1, tzinfo=UTC) + timedelta(hours=number * 7)).isoformat(),
    }


def create_app() -> FastAPI:
    app = FastAPI(title="Northwind demo APIs", docs_url="/docs", redoc_url=None)
    slack: deque[dict[str, Any]] = deque(maxlen=500)
    seen_shipments: set[str] = set()
    seen_batches: set[str] = set()
    flaky: dict[str, int] = {}

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    # Shop ---------------------------------------------------------------------------

    @app.get("/shop/orders")
    async def orders(status: str | None = None, limit: int = 20) -> dict[str, Any]:
        rows = [order(n) for n in range(1, 41)]
        if status:
            rows = [o for o in rows if o["status"] == status]
        return {"orders": rows[: max(1, min(limit, 100))], "count": min(len(rows), limit)}

    @app.get("/shop/orders/{order_id}")
    async def one_order(order_id: str) -> Response:
        if not order_id.startswith("SO-") or not order_id[3:].isdigit():
            return JSONResponse({"error": "not_found"}, status_code=404)
        return JSONResponse(order(int(order_id[3:]) - 1000))

    @app.get("/shop/inventory")
    async def inventory(below: int | None = None) -> dict[str, Any]:
        items = [
            {"sku": sku, "title": title, "on_hand": INVENTORY[sku], "reorder_point": 10}
            for sku, title, _ in PRODUCTS
            if below is None or INVENTORY[sku] < below
        ]
        return {"items": items}

    # Fulfillment: the first attempt for each order fails, the retry succeeds ---------

    @app.post("/fulfillment/shipments")
    async def ship(request: Request) -> Response:
        body = await request.json()
        order_id = str(body.get("order_id", ""))
        if not order_id:
            return JSONResponse({"error": "order_id is required"}, status_code=422)
        if order_id not in seen_shipments:
            seen_shipments.add(order_id)
            return JSONResponse(
                {"error": "warehouse_busy", "message": "Try again shortly."},
                status_code=503,
                headers={"retry-after": "1"},
            )
        carriers = ["UPS", "DHL", "FedEx"]
        return JSONResponse(
            {
                "shipment_id": f"SHP-{_digest(order_id) % 100000:05d}",
                "order_id": order_id,
                "carrier": carriers[_digest(order_id, "carrier") % len(carriers)],
                "eta_days": 2 + _digest(order_id, "eta") % 4,
            },
            status_code=201,
        )

    # CRM ----------------------------------------------------------------------------

    @app.get("/crm/companies/{domain}")
    async def company(domain: str) -> Response:
        found = COMPANIES.get(domain.lower())
        if found is None:
            return JSONResponse({"error": "unknown_company", "domain": domain}, status_code=404)
        name, employees, industry = found
        segment = "enterprise" if employees >= 1000 else "mid_market" if employees >= 100 else "smb"
        return JSONResponse(
            {
                "domain": domain,
                "name": name,
                "employees": employees,
                "industry": industry,
                "segment": segment,
            }
        )

    @app.post("/crm/leads/{lead_id}/assign")
    async def assign(lead_id: str, request: Request) -> dict[str, Any]:
        body = await request.json()
        return {"lead_id": lead_id, "owner": body.get("owner"), "assigned": True}

    # Billing ------------------------------------------------------------------------

    @app.get("/billing/invoices")
    async def invoices(status: str = "pending") -> dict[str, Any]:
        rows = [
            {
                "id": f"INV-2026-{n:04d}",
                "customer": CUSTOMERS[n % len(CUSTOMERS)][0],
                "amount": round(120 + (n * 37.5) % 900, 2),
                "due": (datetime(2026, 10, 25, tzinfo=UTC) + timedelta(days=n % 9))
                .date()
                .isoformat(),
                "status": status,
            }
            for n in range(1, 13)
        ]
        return {"invoices": rows}

    @app.post("/billing/invoices/batch")
    async def charge(request: Request) -> Response:
        body = await request.json()
        ids = [str(i.get("id")) for i in body.get("invoices", []) if isinstance(i, dict)]
        key = ",".join(ids)
        # One batch in three fails its first attempt, the way payment gateways do.
        if key and _digest(key) % 3 == 0 and key not in seen_batches:
            seen_batches.add(key)
            return JSONResponse({"error": "gateway_timeout"}, status_code=504)
        return JSONResponse({"charged": ids, "count": len(ids)})

    # Status page --------------------------------------------------------------------

    @app.get("/status/{service}")
    async def status_page(service: str, at: str | None = None) -> dict[str, Any]:
        moment = datetime.fromisoformat(at.replace("Z", "+00:00")) if at else datetime.now(UTC)
        bucket = moment.replace(second=0, microsecond=0).isoformat()
        degraded = _digest(service, bucket) % 9 == 0
        return {
            "service": service,
            "status": "degraded" if degraded else "operational",
            "latency_ms": 40 + _digest(service, bucket, "lat") % (900 if degraded else 120),
            "checked_at": moment.isoformat(),
        }

    # Slack-compatible incoming webhooks ---------------------------------------------

    @app.post("/slack/{channel}")
    async def slack_message(channel: str, request: Request) -> Response:
        try:
            body = await request.json()
        except ValueError:
            return Response("invalid_payload", status_code=400)
        if not isinstance(body, dict) or not body.get("text"):
            return Response("no_text", status_code=400)
        slack.appendleft(
            {
                "channel": f"#{channel}",
                "text": body.get("text"),
                "username": body.get("username") or "WorkflowEngine",
                "icon_emoji": body.get("icon_emoji"),
                "received_at": datetime.now(UTC).isoformat(),
            }
        )
        return Response("ok", media_type="text/plain")

    @app.get("/slack/messages")
    async def slack_messages(channel: str | None = None) -> dict[str, Any]:
        rows = [m for m in slack if channel is None or m["channel"] == f"#{channel}"]
        return {"messages": rows}

    @app.get("/slack", response_class=HTMLResponse)
    async def slack_page() -> str:
        items = "".join(
            f"<li><b>{escape(m['channel'])}</b> <small>{escape(m['received_at'])}</small>"
            f"<p>{escape(str(m['text']))}</p></li>"
            for m in slack
        )
        return (
            "<!doctype html><title>Demo Slack</title>"
            "<body style='font-family:sans-serif;max-width:720px;margin:2rem auto'>"
            f"<h1>Messages received</h1><ul>{items or '<li>Nothing yet.</li>'}</ul></body>"
        )

    # Test helpers -------------------------------------------------------------------

    @app.api_route("/echo", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def echo(request: Request) -> dict[str, Any]:
        raw = await request.body()
        return {
            "method": request.method,
            "query": dict(request.query_params),
            "headers": {k: v for k, v in request.headers.items() if k != "host"},
            "body": raw.decode("utf-8", errors="replace"),
        }

    @app.get("/flaky/{key}")
    async def flaky_endpoint(key: str, fail: int = 2) -> Response:
        flaky[key] = flaky.get(key, 0) + 1
        if flaky[key] <= fail:
            return JSONResponse({"attempt": flaky[key]}, status_code=503)
        return JSONResponse({"attempt": flaky[key], "ok": True})

    @app.get("/slow")
    async def slow(seconds: float = 2.0) -> dict[str, float]:
        await asyncio.sleep(min(seconds, 30.0))
        return {"slept": seconds}

    return app
