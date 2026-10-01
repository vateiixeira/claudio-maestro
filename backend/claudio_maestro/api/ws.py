"""Event WebSocket. Host and Origin are checked by the middleware."""

from fastapi import APIRouter, WebSocket

router = APIRouter()


@router.websocket("/ws")
async def events(websocket: WebSocket) -> None:
    await websocket.app.state.hub.serve(websocket)
