import asyncio
import json
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from agent import run_agent

STATIC_DIR = Path(__file__).parent / "static"


async def index(_request: Request) -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


async def health(_request: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, default=str)}\n\n"


async def run_stream(request: Request) -> StreamingResponse:
    body = await request.json()
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        return JSONResponse({"error": "Prompt is required."}, status_code=400)

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    def worker() -> None:
        try:
            for event in run_agent(prompt):
                loop.call_soon_threadsafe(queue.put_nowait, event)
        except Exception as exc:  # noqa: BLE001
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {
                    "stage": "error",
                    "message": f"Agent failed: {type(exc).__name__}: {exc}",
                    "result": str(exc),
                },
            )
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)
    
    asyncio.create_task(asyncio.to_thread(worker))

    async def event_publisher():
        while True:
            if await request.is_disconnected():
                break
            event = await queue.get()
            if event is None:
                yield _sse({"stage": "closed"})
                break
            yield _sse(event)

    return StreamingResponse(
        event_publisher(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


app = Starlette(
    routes=[
        Route("/", index),
        Route("/health", health),
        Route("/api/run", run_stream, methods=["POST"]),
        Mount("/static", StaticFiles(directory=STATIC_DIR), name="static"),
    ]
)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True)
