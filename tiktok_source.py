"""
tiktok_source.py — откъде идват събитията.

Три източника, еднакъв изход:
  TikTokLive  — пряко към TikTok, без нищо друго
  TikFinity   — през локалния WebSocket на TikFinity, по-стабилно
  Симулатор   — фалшиви зрители, за проба без стрийм

Всеки праща едно и също навън: (Act, key, name, avatar, text, count, coins).
Играта не знае откъде идва събитието.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import random
from dataclasses import dataclass

from game_core import Act

TIKFINITY_URL = "ws://localhost:21213/"


@dataclass
class Incoming:
    act: Act
    key: str
    name: str = ""
    avatar: str = ""
    text: str = ""
    count: int = 1
    coins: int = 0


def _user_key(u) -> str:
    """Еднакъв ключ за човек, каквото и да върне библиотеката."""
    if u is None:
        return "unknown"
    return (getattr(u, "unique_id", None)
            or str(getattr(u, "user_id", "") or "")
            or getattr(u, "nickname", "") or "unknown")


def _avatar(u) -> str:
    """
    Снимката на зрителя. Библиотеката я дава на различни места според
    събитието, затова пробваме по ред и връщаме първото намерено.
    """
    if u is None:
        return ""
    for attr in ("avatar_thumb", "avatar_medium", "avatar_large"):
        img = getattr(u, attr, None)
        urls = getattr(img, "url_list", None) if img is not None else None
        if urls:
            return str(urls[0])
    return ""


# ---------------------------------------------------------------------------
# TikTokLive
# ---------------------------------------------------------------------------

class TikTokLiveSource:
    name = "TikTokLive"

    def __init__(self, username: str, out: asyncio.Queue, log=print):
        self.username = username.strip().lstrip("@")
        self.out = out
        self.log = log
        self.client = None
        self._stop = False

    def _put(self, inc: Incoming) -> None:
        with contextlib.suppress(Exception):
            self.out.put_nowait(inc)

    async def run(self) -> None:
        from TikTokLive import TikTokLiveClient
        from TikTokLive.events import (CommentEvent, ConnectEvent,
                                       DisconnectEvent, FollowEvent, GiftEvent,
                                       JoinEvent, LikeEvent, LiveEndEvent,
                                       ShareEvent)

        client = TikTokLiveClient(unique_id=self.username)
        self.client = client

        @client.on(ConnectEvent)
        async def _on_connect(_e):
            self.log(f"[TikTok] Свързан към @{self.username}.")

        @client.on(CommentEvent)
        async def _on_comment(e):
            self._put(Incoming(Act.COMMENT, _user_key(e.user),
                               getattr(e.user, "nickname", "") or "",
                               _avatar(e.user), text=e.comment or ""))

        @client.on(LikeEvent)
        async def _on_like(e):
            # count е колко лайка носи този пакет, не общо за стрийма
            self._put(Incoming(Act.LIKE, _user_key(e.user),
                               getattr(e.user, "nickname", "") or "",
                               _avatar(e.user),
                               count=int(getattr(e, "count", 1) or 1)))

        @client.on(FollowEvent)
        async def _on_follow(e):
            self._put(Incoming(Act.FOLLOW, _user_key(e.user),
                               getattr(e.user, "nickname", "") or "",
                               _avatar(e.user)))

        @client.on(ShareEvent)
        async def _on_share(e):
            self._put(Incoming(Act.SHARE, _user_key(e.user),
                               getattr(e.user, "nickname", "") or "",
                               _avatar(e.user)))

        @client.on(JoinEvent)
        async def _on_join(e):
            self._put(Incoming(Act.JOIN, _user_key(e.user),
                               getattr(e.user, "nickname", "") or "",
                               _avatar(e.user)))

        @client.on(GiftEvent)
        async def _on_gift(e):
            if not e.user or not e.gift:
                return
            # TikTok праща купища междинни събития, докато трае серия за
            # един и същ подарък. Броим само финалното, иначе един гифт
            # влиза десет пъти.
            streakable = bool(getattr(e.gift, "streakable", False))
            if streakable and int(getattr(e, "repeat_end", 0) or 0) != 1:
                return
            count = int(getattr(e, "repeat_count", 0) or 1)
            per = int(getattr(e.gift, "diamond_count", 0) or 0)
            self._put(Incoming(Act.GIFT, _user_key(e.user),
                               getattr(e.user, "nickname", "") or "",
                               _avatar(e.user),
                               text=getattr(e.gift, "name", "") or "",
                               count=count, coins=max(0, per * count)))

        @client.on(DisconnectEvent)
        async def _on_disc(_e):
            self.log("[TikTok] Връзката прекъсна.")

        @client.on(LiveEndEvent)
        async def _on_end(_e):
            self.log("[TikTok] Стриймът приключи.")

        await client.connect(fetch_live_check=True)

    async def stop(self) -> None:
        self._stop = True
        if self.client is not None:
            with contextlib.suppress(Exception):
                await self.client.disconnect()


# ---------------------------------------------------------------------------
# TikFinity
# ---------------------------------------------------------------------------

class TikFinitySource:
    name = "TikFinity"

    def __init__(self, out: asyncio.Queue, log=print, url: str = TIKFINITY_URL):
        self.out = out
        self.log = log
        self.url = url
        self._stop = False

    async def run(self) -> None:
        import websockets

        while not self._stop:
            try:
                async with websockets.connect(self.url, ping_interval=20) as ws:
                    self.log("[TikFinity] Свързан.")
                    async for raw in ws:
                        self._handle(raw)
            except Exception as e:
                if self._stop:
                    return
                self.log(f"[TikFinity] Няма връзка ({e}). Пробвам пак след 5 сек.")
                await asyncio.sleep(5)

    def _handle(self, raw) -> None:
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8", errors="ignore")
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return

        ev = msg.get("event") or ""
        d = msg.get("data") or {}
        key = str(d.get("uniqueId") or d.get("userId") or "") or "unknown"
        name = d.get("nickname") or d.get("uniqueId") or ""
        avatar = d.get("profilePictureUrl") or ""

        def put(inc: Incoming):
            with contextlib.suppress(Exception):
                self.out.put_nowait(inc)

        if ev == "chat":
            put(Incoming(Act.COMMENT, key, name, avatar,
                         text=d.get("comment") or ""))
        elif ev == "like":
            put(Incoming(Act.LIKE, key, name, avatar,
                         count=int(d.get("likeCount") or 1)))
        elif ev == "follow":
            put(Incoming(Act.FOLLOW, key, name, avatar))
        elif ev == "share":
            put(Incoming(Act.SHARE, key, name, avatar))
        elif ev == "member":
            put(Incoming(Act.JOIN, key, name, avatar))
        elif ev == "gift":
            # Същото правило за серии като при TikTokLive
            if d.get("giftType") == 1 and not d.get("repeatEnd"):
                return
            count = int(d.get("repeatCount") or 1)
            per = int(d.get("diamondCount") or 0)
            put(Incoming(Act.GIFT, key, name, avatar,
                         text=d.get("giftName") or "",
                         count=count, coins=max(0, per * count)))

    async def stop(self) -> None:
        self._stop = True


# ---------------------------------------------------------------------------
# Нищо — играта стои и чака само пулта за проба
# ---------------------------------------------------------------------------

class NullSource:
    name = "Само пултът"

    def __init__(self, log=print):
        self.log = log

    async def run(self) -> None:
        self.log("[Източник] Няма външни събития — само бутоните от /test.")
        await asyncio.Event().wait()

    async def stop(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Симулатор — за да се види играта без стрийм
# ---------------------------------------------------------------------------

NAMES = [
    "Мария", "Георги", "Иван", "Елена", "Петър", "Виктория", "Николай",
    "Габриела", "Димитър", "Теодора", "Стоян", "Ивайла", "Калоян", "Веселина",
    "Борис", "Радост", "Мартин", "Силвия", "Емил", "Йоана", "Христо", "Дани",
    "Валентин", "Моника", "Красимир", "Петя", "Асен", "Лора", "Тодор", "Ния",
]


class SimSource:
    """
    Фалшива публика. Държи се като истинска: повечето само тапат, малцина
    коментират, от време на време някой следва или праща гифт.
    """
    name = "Симулатор"

    def __init__(self, out: asyncio.Queue, log=print, viewers: int = 40,
                 intensity: float = 1.0):
        self.out = out
        self.log = log
        self.n = max(2, viewers)
        self.intensity = max(0.1, intensity)
        self._stop = False

    async def run(self) -> None:
        self.log(f"[Проба] Пускам {self.n} фалшиви зрители.")
        people = []
        for i in range(self.n):
            people.append({
                "key": f"sim{i}",
                "name": random.choice(NAMES) + str(random.randint(1, 99)),
                "avatar": "",
                "team": None,
            })

        def put(inc):
            with contextlib.suppress(Exception):
                self.out.put_nowait(inc)

        # Първо повечето си избират отбор — както на истински стрийм,
        # след като стриймърът им каже да напишат М или Ж
        for p in random.sample(people, k=int(self.n * 0.7)):
            p["team"] = random.choice(("М", "Ж"))
            put(Incoming(Act.COMMENT, p["key"], p["name"], text=p["team"]))
            await asyncio.sleep(random.uniform(0.05, 0.2))

        chatter = ["хаха", "яко", "давай", "мн е жестоко", "здравей",
                   "поздрави", "кой печели", "хайде момчета", "хайде момичета",
                   "не се предавайте", "тапайте", "абсурд"]

        while not self._stop:
            await asyncio.sleep(max(0.05, 0.25 / self.intensity))

            # тапове
            for p in random.sample(people, k=max(1, self.n // 4)):
                put(Incoming(Act.LIKE, p["key"], p["name"],
                             count=random.randint(1, 4)))

            r = random.random()
            who = random.choice(people)
            if r < 0.07:
                put(Incoming(Act.COMMENT, who["key"], who["name"],
                             text=random.choice(chatter)))
            elif r < 0.085:
                put(Incoming(Act.FOLLOW, who["key"], who["name"]))
            elif r < 0.095:
                put(Incoming(Act.SHARE, who["key"], who["name"]))
            elif r < 0.105:
                coins = random.choice([1, 1, 5, 10, 10, 99, 100, 500, 2000])
                put(Incoming(Act.GIFT, who["key"], who["name"], coins=coins))
            elif r < 0.115:
                # нов зрител влиза и си избира отбор
                np = {"key": f"sim{len(people)}",
                      "name": random.choice(NAMES) + str(random.randint(1, 99)),
                      "avatar": "", "team": random.choice(("М", "Ж"))}
                people.append(np)
                put(Incoming(Act.JOIN, np["key"], np["name"]))
                put(Incoming(Act.COMMENT, np["key"], np["name"],
                             text=np["team"]))

    async def stop(self) -> None:
        self._stop = True
