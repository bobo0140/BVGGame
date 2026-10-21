"""
main.py — свързва всичко: източник на събития, правила, картина.

Пускане:
    python main.py                       -> проба със фалшиви зрители
    python main.py --user mojatikok      -> пряко към TikTok
    python main.py --source tikfinity    -> през TikFinity

После в OBS: Browser source -> http://127.0.0.1:8900/ , 1080x1920,
"Shutdown source when not visible" изключено.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from game_core import Act, Game, Settings
from server import Server
from testpanel import TestPanel
from tiktok_source import (Incoming, NullSource, SimSource, TikFinitySource,
                           TikTokLiveSource)

if getattr(sys, "frozen", False):
    BASE = Path(sys.executable).parent
else:
    BASE = Path(__file__).parent

CONFIG_FILE = BASE / "igra-nastroiki.json"

DEFAULTS = {
    "source": "sim",            # sim | tiktok | tikfinity
    "tiktok_username": "",
    "port": 8900,
    "round_seconds": 90,
    "break_seconds": 8,
    "sim_viewers": 40,
    "sim_intensity": 1.0,
}

HELLO = """
  МОМЧЕТА СРЕЩУ МОМИЧЕТА — игра за TikTok Live

  Зрителите пишат М или Ж в чата и си избират отбор. После тапат —
  всеки тап дърпа въжето към техния отбор. Гифтовете дават СИЛА.
"""


def log(msg: str) -> None:
    print(f"{datetime.now():%H:%M:%S}  {msg}", flush=True)


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg.update({k: v for k, v in data.items() if k in DEFAULTS})
        except Exception as e:
            log(f"[Настройки] Файлът не се чете ({e}). Ползвам стандартните.")
    return cfg


def save_config(cfg: dict) -> None:
    with contextlib.suppress(Exception):
        CONFIG_FILE.write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------


async def consume(game: Game, q: asyncio.Queue) -> None:
    """Вади събитията от опашката и ги подава на правилата."""
    while True:
        inc: Incoming = await q.get()
        try:
            game.act(inc.act, inc.key, name=inc.name, avatar=inc.avatar,
                     text=inc.text, count=inc.count, coins=inc.coins)
        except Exception as e:
            log(f"[Игра] Събитие {inc.act} пропадна: {e}")
        finally:
            q.task_done()


async def rounds(game: Game, break_seconds: float) -> None:
    """
    Тактът и въртенето на кръговете. Играта никога не спира сама —
    щом свърши кръг, след кратка пауза започва следващият.
    """
    next_at: float | None = time.time() + 3.0
    last_report = 0.0

    while True:
        await asyncio.sleep(0.05)
        now = time.time()
        game.tick(now)

        if not game.running:
            if next_at is None:
                next_at = now + break_seconds
            elif now >= next_at:
                next_at = None
                game.start_round(now)
                log(f"[Кръг {game.round_no}] Започва. Праг: "
                    f"{game.s.win_threshold:.0f} точки.")
        else:
            next_at = None

        # Ред в конзолата, за да се вижда, че работи, и без OBS
        if now - last_report >= 15.0:
            last_report = now
            st = game.state(now)
            side = ("момчета" if st["rope"] < -0.05
                    else "момичета" if st["rope"] > 0.05 else "центъра")
            log(f"[Въже] {st['rope']:+.2f} ({side}) · "
                f"М {st['team_counts']['M']} / Ж {st['team_counts']['F']} · "
                f"зрители {st['viewers_known']} · "
                f"резултат {st['wins']['M']}–{st['wins']['F']}")


def build_source(cfg: dict, q: asyncio.Queue):
    kind = (cfg.get("source") or "sim").lower()
    if kind == "tiktok":
        user = (cfg.get("tiktok_username") or "").strip().lstrip("@")
        if not user:
            log("[Източник] Няма потребителско име за TikTok. Пускам проба.")
            return SimSource(q, log, int(cfg["sim_viewers"]),
                             float(cfg["sim_intensity"]))
        return TikTokLiveSource(user, q, log)
    if kind == "tikfinity":
        return TikFinitySource(q, log)
    if kind == "none":
        return NullSource(log)
    return SimSource(q, log, int(cfg["sim_viewers"]),
                     float(cfg["sim_intensity"]))


async def run(cfg: dict) -> None:
    q: asyncio.Queue = asyncio.Queue(maxsize=5000)
    game = Game(Settings(round_seconds=float(cfg["round_seconds"])))
    server = Server(game, log, int(cfg["port"]))

    server.on_cmd = TestPanel(game, q, log).handle

    url = await server.start()
    source = build_source(cfg, q)
    server.status = {"source": source.name, "connected": True, "note": ""}
    log(f"[Източник] {source.name}")

    tasks = [
        asyncio.create_task(consume(game, q)),
        asyncio.create_task(rounds(game, float(cfg["break_seconds"]))),
        asyncio.create_task(source.run()),
    ]

    log("")
    log("=" * 58)
    log(f"  Картината за OBS:  {url}")
    log("  Browser source, 1080x1920, прозрачен фон.")
    log(f"  Пулт с бутони:     {url}test")
    log("  Смяна на източника: BVGGame.exe --menu")
    log("  Спиране: Ctrl+C")
    log("=" * 58)
    log("")

    # При първо пускане отваряме и в браузъра, за да се види веднага,
    # че работи, без да се пипа OBS
    if cfg.get("_open_browser"):
        with contextlib.suppress(Exception):
            import webbrowser
            webbrowser.open(url)

    try:
        done, pending = await asyncio.wait(
            tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in done:
            exc = t.exception()
            if exc is not None:
                log(f"[Грешка] {exc}")
    finally:
        for t in tasks:
            t.cancel()
        with contextlib.suppress(Exception):
            await source.stop()
        await server.stop()


def ask_setup(cfg: dict) -> None:
    """
    Менюто при първо пускане. Пита веднъж и помни избора. Ако няма кой
    да отговори (пуснато от скрипт или от Task Scheduler), не блокира.
    """
    if not sys.stdin or not sys.stdin.isatty():
        return
    print(HELLO)
    print("  Какво да пусна?\n")
    print("    1   TikTok — твоят стрийм")
    print("    2   Проба — фалшиви зрители играят сами")
    print("    3   Само пултът с бутоните\n")
    try:
        ans = input("  Избери 1, 2 или 3 (Enter = 2): ").strip()
    except (EOFError, KeyboardInterrupt):
        return

    if ans == "1":
        try:
            user = input("  TikTok потребител (без @): ").strip().lstrip("@")
        except (EOFError, KeyboardInterrupt):
            return
        if user:
            cfg["source"], cfg["tiktok_username"] = "tiktok", user
            return
        print("  Няма име — пускам проба.")
        cfg["source"] = "sim"
    elif ans == "3":
        cfg["source"] = "none"
    else:
        cfg["source"] = "sim"


def main() -> int:
    first_run = not CONFIG_FILE.exists()
    cfg = load_config()

    ap = argparse.ArgumentParser(description="Момчета срещу момичета")
    ap.add_argument("--source", choices=("sim", "tiktok", "tikfinity", "none"))
    ap.add_argument("--user", help="TikTok потребител (без @)")
    ap.add_argument("--port", type=int)
    ap.add_argument("--viewers", type=int, help="колко фалшиви зрители")
    ap.add_argument("--intensity", type=float, help="колко бързо тапат")
    ap.add_argument("--round", type=float, help="секунди на кръг")
    ap.add_argument("--menu", action="store_true",
                    help="пита пак какво да пусне")
    a = ap.parse_args()

    if a.source:    cfg["source"] = a.source
    if a.user:      cfg["source"], cfg["tiktok_username"] = "tiktok", a.user
    if a.port:      cfg["port"] = a.port
    if a.viewers:   cfg["sim_viewers"] = a.viewers
    if a.intensity: cfg["sim_intensity"] = a.intensity
    if a.round:     cfg["round_seconds"] = a.round

    # При първо пускане, или когато изрично е поискано меню
    if (first_run or a.menu) and not (a.source or a.user):
        ask_setup(cfg)

    save_config(cfg)
    if first_run:
        cfg["_open_browser"] = True

    try:
        asyncio.run(run(cfg))
    except KeyboardInterrupt:
        log("Спряно.")
    except RuntimeError as e:
        log(f"[Грешка] {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
