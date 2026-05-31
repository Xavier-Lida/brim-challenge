import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.deps import cors_origins
from api.routes import (
    approvals,
    assistant,
    compliance,
    flags,
    notifications,
    policies,
    reports,
    transactions,
    webhooks,
)

load_dotenv()

logger = logging.getLogger("brim")
if not os.getenv("GOOGLE_API_KEY"):
    logger.warning(
        "GOOGLE_API_KEY is not set — the assistant will run in DEGRADED (mock) mode. "
        "Set GOOGLE_API_KEY to enable the real Gemini engine."
    )

app = FastAPI(title="Brim API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(compliance.router)
app.include_router(flags.router)
app.include_router(approvals.router)
app.include_router(reports.router)
app.include_router(transactions.router)
app.include_router(assistant.router)
app.include_router(policies.router)
app.include_router(notifications.router)
app.include_router(webhooks.router)


@app.get("/")
def read_root():
    return {"message": "Brim API", "docs": "/docs"}


@app.get("/health")
def health_check():
    return {"status": "ok"}
