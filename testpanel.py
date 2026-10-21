"""
testpanel.py — бутоните от страницата /test стават истински събития.

Пултът не заобикаля правилата. Всеки бутон праща същото, което би
пратил истински зрител, през същата опашка. Затова, ако нещо работи с
пулта, ще работи и на стрийм.
"""

from __future__ import annotations

import contextlib
import random
import time

from game_core import BOYS, GIRLS, Act
from tiktok_source import NAMES, Incoming

TEAM_WORD = {BOYS: "М", GIRLS: "Ж"}

ACTS = {
    "like": Act.LIKE,
    "comment": Act.COMMENT,
    "share": Act.SHARE,
    "follow": Act.FOLLOW,
    "gift": Act.GIFT,
}

CHATTER = ["давай", "хаха", "яко", "не се предавайте", "тапайте",
           "кой печели", "хайде", "абсурд", "браво"]


class TestPanel:
    """
    Държи шепа измислени зрители и ги кара да правят неща. Пази ги
    между натисканията, за да не излиза нов човек при всеки тап.
    """

    def __init__(self, game, queue, log=print):
        self.game = game
        self.q = queue
        self.log = log
        self.pool: dict[str | None, list[dict]] = {BOYS: [], GIRLS: [], None: []}
        self._n = 0

    # -- вътрешно ----------------------------------------------------------

    def _put(self, inc: Incoming) -> None:
        with contextlib.suppress(Exception):
            self.q.put_nowait(inc)

    def _new_person(self, team: str | None) -> dict:
        self._n += 1
        p = {"key": f"test{self._n}",
             "name": f"{random.choice(NAMES)}{random.randint(10, 99)}"}
        self.pool[team].append(p)
        self._put(Incoming(Act.JOIN, p["key"], p["name"]))
        if team is not None:
            # Избира отбора точно както би го направил зрител — с коментар
            self._put(Incoming(Act.COMMENT, p["key"], p["name"],
                               text=TEAM_WORD[team]))
        return p

    def _someone(self, team: str | None) -> dict:
        people = self.pool[team]
        if not people:
            return self._new_person(team)
        return random.choice(people)

    # -- командите от страницата -------------------------------------------

    def handle(self, data: dict) -> None:
        cmd = data.get("cmd")
        if cmd == "add":
            self._cmd_add(data)
        elif cmd == "act":
            self._cmd_act(data)
        elif cmd == "round":
            self._cmd_round(data)

    def _team_of(self, data: dict) -> str | None:
        t = data.get("team")
        if t == BOYS or t == GIRLS:
            return t
        return None      # без отбор

    def _cmd_add(self, data: dict) -> None:
        team = self._team_of(data)
        n = max(1, min(50, int(data.get("n") or 1)))
        for _ in range(n):
            self._new_person(team)
        where = "без отбор" if team is None else TEAM_WORD[team]
        self.log(f"[Пулт] +{n} зрители ({where})")

    def _cmd_act(self, data: dict) -> None:
        act = ACTS.get(data.get("act") or "")
        if act is None:
            return
        team = self._team_of(data)
        times = max(1, min(200, int(data.get("times") or 1)))

        for _ in range(times):
            p = self._someone(team)
            if act is Act.LIKE:
                self._put(Incoming(Act.LIKE, p["key"], p["name"],
                                   count=max(1, int(data.get("count") or 1))))
            elif act is Act.COMMENT:
                self._put(Incoming(Act.COMMENT, p["key"], p["name"],
                                   text=random.choice(CHATTER)))
            elif act is Act.GIFT:
                self._put(Incoming(Act.GIFT, p["key"], p["name"],
                                   coins=max(1, int(data.get("coins") or 1))))
            else:
                self._put(Incoming(act, p["key"], p["name"]))

        self.log(f"[Пулт] {data.get('act')} x{times}")

    def _cmd_round(self, data: dict) -> None:
        do = data.get("do")
        if do == "start":
            if not self.game.running:
                self.game.start_round()
                self.log("[Пулт] Кръгът започна ръчно.")
        elif do == "end":
            if self.game.running:
                # Същият път, по който свършва и сам — само часовникът
                # се премества напред
                self.game.round_ends_at = time.time()
                self.log("[Пулт] Кръгът свършва.")
