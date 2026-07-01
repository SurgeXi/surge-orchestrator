# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""Bootstrap admin UI router. Server-rendered FastAPI + Jinja2.

Phase 3.1 ships a minimal version: shows pending approvals + capability list.
Full UI (decide buttons, audit search, policy editor) lands Phase 3 mid.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ..api.deps import require_approver
from ..db import get_db
from ..models import Approval, Capability

TEMPLATES = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

router = APIRouter()


@router.get("/admin", response_class=HTMLResponse)
def home(
    request: Request,
    db: Session = Depends(get_db),
    _=Depends(require_approver),
):
    pending = db.query(Approval).filter(Approval.status == "pending").limit(50).all()
    caps = db.query(Capability).filter(Capability.status == "active").all()
    return TEMPLATES.TemplateResponse(
        "home.html",
        {"request": request, "pending": pending, "caps": caps},
    )
