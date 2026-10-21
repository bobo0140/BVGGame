"""
server.py — раздава картината и ѝ праща състоянието.

OBS отваря http://127.0.0.1:8900/ като browser source. Страницата държи
WebSocket отворен и получава състоянието десет пъти в секунда плюс
събитията, които трябва да покаже (гифт, последовател, край на кръг).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import sys
from pathlib import Path

from aiohttp import WSMsgType, web

if getattr(sys, "frozen", False):
    WEB_DIR = Path(sys._MEIPASS)          # type: ignore[attr-defined]
else:
    WEB_DIR = Path(__file__).parent

PUSH_HZ = 10.0


class Server:
    def __init__(self, game, log=print, port: int = 8900):
        self.game = game
        self.log = log
        self.port = port
        self.clients: set[web.WebSocketResponse] = set()
        self._runner: web.AppRunner | None = None
        self._pump: asyncio.Task | None = None
        self.status: dict = {"source": "", "connected": False, "note": ""}
        # Пулта за проба го закача main.py. Без него страницата /test се
        # отваря, но бутоните не правят нищо.
        self.on_cmd = None

    # -- маршрути ----------------------------------------------------------

    async def _h_index(self, _req: web.Request) -> web.Response:
        return web.FileResponse(WEB_DIR / "overlay.html")

    async def _h_test(self, _req: web.Request) -> web.Response:
        return web.FileResponse(WEB_DIR / "test.html")

    async def _h_file(self, req: web.Request) -> web.Response:
        name = req.match_info["name"]
        # Само нашите файлове — без ходене по папки
        if name not in {"overlay.js", "overlay.css"}:
            raise web.HTTPNotFound()
        return web.FileResponse(WEB_DIR / name)

    async def _h_ws(self, req: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(req)
        self.clients.add(ws)
        with contextlib.suppress(Exception):
            await ws.send_json({"type": "hello",
                                "state": self.game.state(),
                                "status": self.status})
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                with contextlib.suppress(Exception):
                    data = json.loads(msg.data)
                    cmd = data.get("cmd")
                    if cmd == "ping":
                        await ws.send_json({"type": "pong"})
                    elif cmd and self.on_cmd is not None:
                        self.on_cmd(data)
        except Exception:
            pass
        finally:
            self.clients.discard(ws)
        return ws

    # -- изпращане ---------------------------------------------------------

    async def broadcast(self, payload: dict) -> None:
        if not self.clients:
            return
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    async def _pump_loop(self) -> None:
        interval = 1.0 / PUSH_HZ
        while True:
            await asyncio.sleep(interval)
            feed = self.game.take_feed()
            await self.broadcast({
                "type": "tick",
                "state": self.game.state(),
                "feed": feed,
                "status": self.status,
            })

    # -- старт/стоп --------------------------------------------------------

    async def start(self) -> str:
        app = web.Application()
        app.router.add_get("/", self._h_index)
        app.router.add_get("/overlay.html", self._h_index)
        app.router.add_get("/test", self._h_test)
        app.router.add_get("/test.html", self._h_test)
        app.router.add_get("/{name}", self._h_file)
        app.router.add_get("/ws", self._h_ws)

        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", self.port)
        try:
            await site.start()
        except OSError as e:
            raise RuntimeError(
                f"Портът {self.port} е зает. Затвори другото приложение, "
                f"което го ползва, или пусни играта на друг порт."
            ) from e

        self._pump = asyncio.create_task(self._pump_loop())
        url = f"http://127.0.0.1:{self.port}/"
        self.log(f"[Картина] Готова на {url}")
        self.log("[OBS] Добави Browser source с този адрес, 1080x1920.")
        self.log(f"[Проба] Пулт с бутони: {url}test")
        return url

    async def stop(self) -> None:
        if self._pump is not None:
            self._pump.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._pump
            self._pump = None
        for ws in list(self.clients):
            with contextlib.suppress(Exception):
                await ws.close()
        self.clients.clear()
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
