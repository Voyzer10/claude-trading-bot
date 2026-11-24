"""V6 API: uvicorn api_v6.app:app --host 127.0.0.1 --port 8001. Read-only (GET only)."""
from __future__ import annotations

from fastapi import FastAPI, HTTPException

from . import views

app = FastAPI(title="Trader V6 API (PAPER ONLY)", docs_url="/api/py/v6/docs", openapi_url="/api/py/v6/openapi.json",
              swagger_ui_oauth2_redirect_url=None, redoc_url=None)


def _book(fn, book_id, *a):
    try:
        return fn(book_id, *a)
    except KeyError:
        raise HTTPException(404, "unknown V6 book %s" % book_id) from None


@app.get("/api/py/v6/health")
def health():
    return views.health()


@app.get("/api/py/v6/status")
def status():
    return views.get_status()


@app.get("/api/py/v6/identity")
def identity():
    return views.get_identity()


@app.get("/api/py/v6/books")
def books():
    return views.get_books()


@app.get("/api/py/v6/books/{book_id}")
def book(book_id: str):
    return _book(views.get_book, book_id)


@app.get("/api/py/v6/signals/{book_id}")
def signals(book_id: str, limit: int = 200):
    return _book(views.get_signals, book_id, limit)


@app.get("/api/py/v6/data-health")
def data_health():
    return views.get_data_health()


@app.get("/api/py/v6/performance/{book_id}")
def performance(book_id: str):
    return _book(views.get_performance, book_id)


@app.get("/api/py/v6/backtests")
def backtests():
    return views.list_backtests()


@app.get("/api/py/v6/backtests/{run_id}")
def backtest(run_id: str):
    try:
        return views.get_backtest(run_id)
    except KeyError:
        raise HTTPException(404, "unknown backtest run %s" % run_id) from None
