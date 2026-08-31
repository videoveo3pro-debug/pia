from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.vpn_manager import VPNManager

router = APIRouter(prefix="/api", tags=["socks5"])


class LoginRequest(BaseModel):
    username: str | None = Field(None, description="PIA account username for worker 1-8.")
    username_1: str | None = Field(None, description="Alias for username. PIA account username for worker 1-8.")
    username_2: str | None = Field(None, description="PIA account username for optional credential slot 2.")
    email: str | None = Field(None, description="Compatibility alias for username.")
    password: str | None = Field(None, description="PIA account password for worker 1-8. The password is never returned by the API.")
    email_1: str | None = Field(None, description="Compatibility alias for username_1.")
    password_1: str | None = Field(None, description="Alias for password. PIA account password for worker 1-8.")
    email_2: str | None = Field(None, description="Compatibility alias for username_2.")
    password_2: str | None = Field(None, description="PIA account password for optional credential slot 2.")
    token: str = Field("", description="Compatibility alias: packed PIA credential as username|password or username/password lines.")
    token_1: str | None = Field(None, description="Compatibility alias: packed credential for worker 1-8.")
    token_2: str | None = Field(None, description="Compatibility alias: packed credential for optional slot 2.")
    persist: bool = Field(True, description="Save account credentials under credentials/ for future starts.")


class ModeRequest(BaseModel):
    worker_count: int = Field(..., ge=1, le=14, description="Active workers (1-14).")


class TokenUpdateRequest(BaseModel):
    username_1: str | None = Field(None, description="PIA account username for worker 1-8.")
    password_1: str | None = Field(None, description="PIA account password for worker 1-8.")
    username_2: str | None = Field(None, description="PIA account username for optional credential slot 2.")
    password_2: str | None = Field(None, description="PIA account password for optional credential slot 2.")
    email_1: str | None = Field(None, description="Compatibility alias for username_1.")
    email_2: str | None = Field(None, description="Compatibility alias for username_2.")
    token_1: str | None = Field(None, description="Compatibility alias: packed credential for worker 1-8.")
    token_2: str | None = Field(None, description="Compatibility alias: packed credential for optional slot 2.")
    persist: bool = Field(True, description="Save updated account credentials under credentials/.")
    apply: bool = Field(True, description="Immediately login affected active workers and trigger recovery.")


class ConnectRequest(BaseModel):
    country: str | None = Field(None, examples=["Japan", "Singapore", "United_States", "jp"], description="PIA country/code/name. Empty means worker startup hint or quick connect.")
    server: str | None = Field(None, examples=["jp555", "sg521"], description="Optional exact PIA server.")
    force: bool = Field(True, description="Reconnect even if already connected.")


class RotateRequest(BaseModel):
    country: str | None = Field(None, description="Optional PIA target country/code/name.")
    server: str | None = Field(None, description="Optional exact PIA server.")
    wait_for_ready: bool = Field(False, description="False = faster API response; health monitor re-enables worker when ready.")


class SessionRotateRequest(BaseModel):
    country: str | None = None
    server: str | None = None


class RecoverRequest(BaseModel):
    force: bool = Field(False, description="True = recover even if the worker is currently READY or in cooldown.")


def get_manager() -> VPNManager:
    from app.main import manager

    return manager


ManagerDep = Annotated[VPNManager, Depends(get_manager)]


def _pack_credential(username: str | None, password: str | None) -> str | None:
    username = (username or "").strip()
    password = (password or "").strip()
    if not username and not password:
        return None
    if not username or not password:
        raise ValueError("Both PIA username and password are required.")
    return f"{username}\n{password}"


@router.get("/status")
def status(manager: ManagerDep, refresh: bool = Query(False)):
    """Current multi-worker PIA + SOCKS5 gateway status."""
    return manager.status(refresh=refresh)


@router.get("/mode")
def get_mode(manager: ManagerDep):
    return manager.runtime_mode()


@router.post("/mode")
def set_mode(payload: ModeRequest, manager: ManagerDep):
    try:
        return manager.set_runtime_mode(payload.worker_count)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/tokens")
def tokens(manager: ManagerDep, refresh: bool = Query(False)):
    return manager.token_status(refresh=refresh)


@router.post("/tokens")
def update_tokens(payload: TokenUpdateRequest, manager: ManagerDep):
    try:
        token_1 = _pack_credential(payload.username_1 or payload.email_1, payload.password_1) or payload.token_1
        token_2 = _pack_credential(payload.username_2 or payload.email_2, payload.password_2) or payload.token_2
        return manager.update_tokens(token_1=token_1, token_2=token_2, persist=payload.persist, apply=payload.apply)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/diagnostics")
def diagnostics(manager: ManagerDep):
    return manager.diagnostics()


@router.get("/nodes")
def nodes(manager: ManagerDep, refresh: bool = Query(False)):
    return {"ok": True, "nodes": manager.nodes_status(refresh=refresh)}


@router.get("/nodes/healthy")
def healthy_nodes(manager: ManagerDep):
    return manager.healthy_nodes()


@router.post("/recover")
def recover_all(manager: ManagerDep, payload: RecoverRequest | None = None):
    try:
        request = payload or RecoverRequest()
        return manager.recover_all(force=request.force)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/nodes/{node_id}/recover")
def recover_node(node_id: str, manager: ManagerDep, payload: RecoverRequest | None = None):
    try:
        request = payload or RecoverRequest()
        return manager.recover_node(node_id, force=request.force)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/nodes/{node_id}")
def node_status(node_id: str, manager: ManagerDep):
    try:
        return manager.node_status(node_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/nodes/{node_id}/rotate")
def rotate_node(node_id: str, payload: RotateRequest, manager: ManagerDep):
    try:
        result = manager.rotate_node(node_id, country=payload.country, server=payload.server, wait_for_ready=payload.wait_for_ready)
        if not result.get("ok"):
            raise HTTPException(status_code=409, detail=result)
        return result
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/nodes/{node_id}/disable")
def disable_node(node_id: str, manager: ManagerDep):
    try:
        return manager.disable_node(node_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/nodes/{node_id}/enable")
def enable_node(node_id: str, manager: ManagerDep):
    try:
        return manager.enable_node(node_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/rotate-any")
def rotate_any(payload: RotateRequest, manager: ManagerDep):
    try:
        return manager.rotate_any(country=payload.country, server=payload.server, wait_for_ready=payload.wait_for_ready)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/rotate")
def rotate_session(session_id: str, payload: SessionRotateRequest, manager: ManagerDep):
    try:
        return manager.session_rotate(session_id, country=payload.country, server=payload.server)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/login")
def login(payload: LoginRequest, manager: ManagerDep):
    """Login all PIA worker containers by account credentials."""
    try:
        token_1 = (
            _pack_credential(payload.username_1 or payload.username or payload.email_1 or payload.email, payload.password_1 or payload.password)
            or payload.token_1
            or payload.token
            or ""
        ).strip()
        token_2 = (
            _pack_credential(payload.username_2 or payload.email_2, payload.password_2)
            or payload.token_2
        )
        if not token_1:
            raise ValueError("PIA account credential 1 is required.")
        result = manager.pia_login(token=token_1, token_2=token_2, persist=payload.persist, reconnect=False, country=None, server=None)
        if not result.get("ok"):
            raise HTTPException(status_code=401, detail=result)
        return result
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/logout")
def logout(manager: ManagerDep):
    """Logout all workers and clear stored token."""
    try:
        return manager.pia_logout(clear_stored_token=True)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/countries")
def countries(manager: ManagerDep, refresh: bool = Query(False)):
    """Countries returned by `piactl get regions` from the first reachable worker."""
    return manager.countries(refresh=refresh)


@router.post("/connect")
def connect(payload: ConnectRequest, manager: ManagerDep):
    """Compatibility API: connect/prepare all workers in the pool."""
    try:
        return manager.connect(country=payload.country, server=payload.server, force=payload.force)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        detail = str(exc)
        status_code = 409 if "not logged in" in detail.lower() else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/random-ip")
def random_ip(manager: ManagerDep):
    """Compatibility API: rotate one worker behind the gateway while others keep serving."""
    try:
        return manager.random_ip()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        detail = str(exc)
        status_code = 409 if "not logged in" in detail.lower() else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/disconnect")
def disconnect(manager: ManagerDep):
    """Disconnect all PIA workers."""
    try:
        return manager.disconnect()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/test-proxy")
def test_proxy(manager: ManagerDep):
    """Test the fixed HAProxy SOCKS5 gateway."""
    return manager.test_proxy()


@router.get("/logs")
def logs(manager: ManagerDep, tail: int = Query(120, ge=1, le=500)):
    """Tail worker logs and PIA status."""
    return manager.logs(tail=tail)
