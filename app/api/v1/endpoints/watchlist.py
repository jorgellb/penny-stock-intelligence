"""Stock lists (watchlists): persistent CRUD + legacy routes."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.repositories import WatchlistRepository

router = APIRouter()


def _repo(session: AsyncSession) -> WatchlistRepository:
    return WatchlistRepository(session)


def _item_to_dict(item: Any) -> dict[str, Any]:
    return {
        "symbol": item.symbol,
        "list": item.list_name,
        "notes": item.notes,
        "added_at": item.added_at.isoformat() if item.added_at else None,
    }


@router.get("/watchlists")
async def list_lists(
    user_id: str = Query("default"), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """List all stock lists for a user with symbol counts."""
    lists = await _repo(session).lists(user_id)
    return {"user_id": user_id, "lists": lists, "count": len(lists)}


@router.post("/watchlists")
async def create_list(
    name: str = Query(..., min_length=1, max_length=100),
    user_id: str = Query("default"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Create an empty list (idempotent; a list exists once it has items)."""
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="empty list name")
    existing = await _repo(session).lists(user_id)
    if any(lst["name"] == name for lst in existing):
        return {"status": "exists", "name": name}
    return {"status": "created", "name": name}


@router.get("/watchlists/{name}")
async def get_list(
    name: str,
    user_id: str = Query("default"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get all symbols in a list."""
    items = await _repo(session).items(user_id, name)
    return {"name": name, "items": [_item_to_dict(i) for i in items], "count": len(items)}


@router.post("/watchlists/{name}/symbols")
async def add_symbol(
    name: str,
    symbol: str = Query(..., min_length=1, max_length=20),
    user_id: str = Query("default"),
    notes: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Add a symbol to a list (creates the list implicitly)."""
    try:
        item, created = await _repo(session).add(symbol, user_id, name.strip(), notes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "added" if created else "exists", "symbol": item.symbol, "list": name}


@router.delete("/watchlists/{name}/symbols/{symbol}")
async def remove_symbol(
    name: str,
    symbol: str,
    user_id: str = Query("default"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Remove a symbol from a list."""
    removed = await _repo(session).remove(symbol, user_id, name)
    return {"status": "removed" if removed else "not_found", "symbol": symbol.upper(), "list": name}


@router.delete("/watchlists/{name}")
async def delete_list(
    name: str,
    user_id: str = Query("default"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Delete a whole list."""
    if name == WatchlistRepository.DEFAULT_LIST:
        raise HTTPException(status_code=400, detail="cannot delete the default list")
    deleted = await _repo(session).delete_list(user_id, name)
    return {"status": "deleted", "name": name, "removed": deleted}


# ---- Legacy routes (default list) ----


@router.get("/watchlist")
async def get_watchlist(
    user_id: str = Query("default"), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """Get watchlist (legacy: default list)."""
    items = await _repo(session).items(user_id, WatchlistRepository.DEFAULT_LIST)
    return {"items": [_item_to_dict(i) for i in items], "count": len(items)}


@router.post("/watchlist/add")
async def add_to_watchlist(
    symbol: str,
    user_id: str = Query("default"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Add symbol to watchlist (legacy: default list)."""
    try:
        item, created = await _repo(session).add(symbol, user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "added" if created else "exists", "symbol": item.symbol}


@router.delete("/watchlist/remove/{symbol}")
async def remove_from_watchlist(
    symbol: str,
    user_id: str = Query("default"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Remove symbol from watchlist (legacy: default list)."""
    removed = await _repo(session).remove(symbol, user_id)
    return {"status": "removed" if removed else "not_found", "symbol": symbol.upper()}
