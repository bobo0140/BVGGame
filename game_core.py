"""
game_core.py — правилата на „Момчета срещу момичета".

Тук няма мрежа, няма TikTok и няма картина. Само състоянието на играта
и какво го променя, за да може всичко да се тества без стрийм.

Въжето е едно число: -1 значи момчетата са го изтеглили докрай,
+1 значи момичетата. Нулата е центърът.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass
from enum import Enum

BOYS = "M"
GIRLS = "F"

TEAM_NAMES = {BOYS: "Момчета", GIRLS: "Момичета"}
TEAM_SIGN = {BOYS: -1.0, GIRLS: +1.0}


class Act(str, Enum):
    """Какво е направил зрителят."""
    LIKE = "like"
    COMMENT = "comment"
    SHARE = "share"
    FOLLOW = "follow"
    GIFT = "gift"
    JOIN = "join"


# Колко тегли всяко действие. Числата са спрямо win_threshold по-долу:
# при праг 1000 един човек, който тапа без прекъсване, няма да реши
# кръга сам, но двайсет души заедно — ще го решат.
PULL = {
    Act.LIKE: 1.0,
    Act.COMMENT: 5.0,
    Act.SHARE: 25.0,
    Act.FOLLOW: 50.0,
}

# Гифтовете купуват СИЛА, не само точки. Прагът е в монети и се избира
# най-високият, който се вписва. Силата е по-важна от точките: когато
# другият отбор види, че лайковете му спират, започва да тапа бясно —
# а това е целта на цялата игра.
GIFT_TIERS = [
    (2000, "giant"),
    (500, "reverse"),
    (100, "sabotage"),
    (10, "storm"),
    (1, "boost"),
]

POWER_NAMES = {
    "storm": "БУРЯ",
    "sabotage": "САБОТАЖ",
    "reverse": "ОБРАТ",
    "giant": "ВЕЛИКАН",
    "boost": "ПОДКРЕПА",
}

POWER_TEXT = {
    "storm": "{who} вика БУРЯ за {team}! Лайковете им се удвояват!",
    "sabotage": "{who} саботира! {other} тапат напразно!",
    "reverse": "{who} обръща въжето! Всичко се преобърна!",
    "giant": "{who} става ВЕЛИКАН и тегли сам!",
    "boost": "{who} се качва на въжето за {team}!",
}

POWER_SECONDS = {"storm": 15.0, "sabotage": 10.0, "giant": 20.0}

# „Жар" — колко силно даден отбор дърпа ПРЕЗ ПОСЛЕДНИТЕ СЕКУНДИ. Позицията
# на въжето сама по себе си не го казва: при две равни групи възелът стои
# в центъра, а всъщност и двете страни блъскат като луди. Картината ползва
# жарта за искрите, напъна на теглачите и звука — без нея екранът изглежда
# мъртъв, докато всъщност се води бой.
HEAT_TAU = 1.2        # секунди, докато жарта изстине
HEAT_FULL = 0.22      # колко е „пълен огън", в части от прага за победа

# Монета -> точки, но с таван. Без тавана един голям гифт решава кръга
# сам и ограбва всички останали; с тавана е ефектен, без да е бутон
# за моментална победа.
GIFT_POINTS_PER_COIN = 3.0
GIFT_POINTS_CAP_SHARE = 0.4        # най-много 40% от прага за победа


@dataclass
class Power:
    kind: str
    team: str
    who: str
    until: float

    @property
    def left(self) -> float:
        return max(0.0, self.until - time.time())


@dataclass
class Viewer:
    """Зрител, както го помни играта за целия стрийм."""
    key: str
    name: str
    avatar: str = ""
    team: str | None = None
    total: float = 0.0          # принос за целия стрийм
    round_points: float = 0.0   # принос в текущия кръг
    gifts: int = 0
    is_follower: bool = False


@dataclass
class Settings:
    round_seconds: float = 90.0
    win_threshold: float = 250.0     # точки от центъра до победа

    # Прагът НЕ бива да е константа. При 30 зрители възелът почти не се
    # движи и играта е скучна; при 500 хвърчи до края за секунди. След
    # всеки кръг прагът се нагласява по това колко е теглила публиката
    # наистина, така че възелът винаги да се вижда как се движи.
    # Пружината. Без нея два равни отбора държат възела в центъра цял
    # кръг — случайна разходка около нулата, скучно за гледане. С нея
    # позицията показва кой натиска СЕГА: спреш ли да дърпаш, въжето се
    # връща. Това е и най-силната причина зрителят да не спира да тапа.
    decay_tau: float = 45.0          # секунди до връщане към центъра

    auto_tune: bool = True
    tune_target_peak: float = 0.65   # докъде да стига възелът обикновено
    min_threshold: float = 150.0
    max_threshold: float = 40000.0

    # Един човек не бива да реши кръга с автоматичен тапер
    like_cap_per_second: float = 10.0

    # Колко по-силно тегли губещият. 1.0 значи изключено.
    comeback_max: float = 2.5

    # Таповете на тези, които не са си избрали отбор, помагат на
    # губещия — така мълчаливите зрители неволно държат играта напечена
    neutral_helps_loser: bool = True

    join_bonus_multiplier: float = 3.0   # първото действие на нов зрител
    show_hero: bool = True
    team_keywords_boys: tuple = ("м", "m", "момче", "момчета", "boys", "boy")
    team_keywords_girls: tuple = ("ж", "f", "g", "момиче", "момичета", "girls", "girl")


class Game:
    def __init__(self, settings: Settings | None = None, now: float | None = None):
        self.s = settings or Settings()
        self.viewers: dict[str, Viewer] = {}
        self.rope: float = 0.0
        self.wins: dict[str, int] = {BOYS: 0, GIRLS: 0}
        self.round_no: int = 0
        self.round_ends_at: float = 0.0
        self.powers: list[Power] = []
        self.followers: list[dict] = []      # аватарите на въжето
        self.heroes: list[dict] = []         # герои на минали кръгове
        self.feed: list[dict] = []           # какво да покаже картината
        self.neutral_pulls: int = 0
        self._like_bucket: dict[str, tuple[float, float]] = {}
        self._peak_net: float = 0.0          # за нагласяването на прага
        self.heat: dict[str, float] = {BOYS: 0.0, GIRLS: 0.0}
        # ВНИМАНИЕ: 'now or time.time()' е грешно — now=0.0 е лъжа в
        # Python и прескача на часовника, при което dt излиза нула
        # и пружината никога не сработва.
        self._last_tick: float = now if now is not None else time.time()
        self.running: bool = False

    # ------------------------------------------------------------------
    # кръгове
    # ------------------------------------------------------------------

    def start_round(self, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        self.round_no += 1
        self.rope = 0.0
        self.powers.clear()
        self.neutral_pulls = 0
        self.heat = {BOYS: 0.0, GIRLS: 0.0}
        for v in self.viewers.values():
            v.round_points = 0.0
        self.round_ends_at = now + self.s.round_seconds
        self._peak_net = 0.0
        # Без това първият такт след началото хваща огромно dt и
        # пружината изсмуква въжето наведнъж
        self._last_tick = now
        self.running = True
        self._say("round_start", f"Кръг {self.round_no} започва!", round_no=self.round_no)

    def _say(self, kind: str, text: str = "", **extra) -> None:
        """Слага събитие за картината. Пази последните 60."""
        item = {"kind": kind, "text": text, "at": time.time()}
        item.update(extra)
        self.feed.append(item)
        del self.feed[:-60]

    def take_feed(self) -> list[dict]:
        out = self.feed
        self.feed = []
        return out

    # ------------------------------------------------------------------
    # зрители и отбори
    # ------------------------------------------------------------------

    def viewer(self, key: str, name: str = "", avatar: str = "") -> Viewer:
        v = self.viewers.get(key)
        if v is None:
            v = Viewer(key=key, name=name or key, avatar=avatar)
            self.viewers[key] = v
        else:
            if name:
                v.name = name
            if avatar:
                v.avatar = avatar
        return v

    def team_from_text(self, text: str) -> str | None:
        """
        Разпознава избора на отбор от коментар. Приема само когато ЦЕЛИЯТ
        коментар е избор — иначе „може ли малко музика" би закачило
        човека за момичетата заради едно 'ж'.
        """
        t = (text or "").strip().lower().strip(".,!?-–—")
        if not t:
            return None
        if t in self.s.team_keywords_boys:
            return BOYS
        if t in self.s.team_keywords_girls:
            return GIRLS
        return None

    def assign(self, v: Viewer, team: str) -> bool:
        """Връща True, ако това е нов избор (или смяна)."""
        if v.team == team:
            return False
        was = v.team
        v.team = team
        if was is None:
            self._say("joined_team",
                      f"{v.name} е с {TEAM_NAMES[team].lower()}!",
                      team=team, name=v.name, avatar=v.avatar)
        else:
            self._say("switched_team",
                      f"{v.name} сменя страната! Вече е с {TEAM_NAMES[team].lower()}!",
                      team=team, name=v.name, avatar=v.avatar)
        return True

    # ------------------------------------------------------------------
    # множители
    # ------------------------------------------------------------------

    def _deficit(self, team: str) -> float:
        """Колко назад е отборът, от 0 до 1."""
        return max(0.0, self.rope * -TEAM_SIGN[team])

    def comeback(self, team: str) -> float:
        if self.s.comeback_max <= 1.0:
            return 1.0
        return 1.0 + (self.s.comeback_max - 1.0) * self._deficit(team)

    def power_multiplier(self, team: str, now: float) -> float:
        mult = 1.0
        for p in self.powers:
            if p.until <= now:
                continue
            if p.kind == "storm" and p.team == team:
                mult *= 2.0
            elif p.kind == "sabotage" and p.team != team:
                mult = 0.0
        return mult

    def losing_team(self) -> str:
        if self.rope > 0:
            return BOYS
        if self.rope < 0:
            return GIRLS
        return random.choice((BOYS, GIRLS))

    # ------------------------------------------------------------------
    # самото теглене
    # ------------------------------------------------------------------

    def _apply(self, team: str, points: float, v: Viewer | None, now: float) -> float:
        """Мести въжето. Връща реално приложените точки."""
        if points <= 0 or not self.running:
            return 0.0
        points *= self.comeback(team) * self.power_multiplier(team, now)
        if points <= 0:
            return 0.0

        self.rope += TEAM_SIGN[team] * points / self.s.win_threshold
        self.rope = max(-1.0, min(1.0, self.rope))
        # Докъде е стигал възелът в точки — това казва колко е била
        # публиката и по него нагласяваме прага за следващия кръг.
        self._peak_net = max(self._peak_net,
                             abs(self.rope) * self.s.win_threshold)
        self.heat[team] = self.heat.get(team, 0.0) + points / self.s.win_threshold
        if v is not None:
            v.round_points += points
            v.total += points
        return points

    def _is_new(self, v: Viewer) -> bool:
        return v.total == 0.0

    def act(self, kind: Act, key: str, name: str = "", avatar: str = "",
            text: str = "", count: int = 1, coins: int = 0,
            now: float | None = None) -> dict:
        """
        Единствената входна точка за събития отвън. Връща кратко описание
        на случилото се, за да може викащият да го запише в лога.
        """
        now = now if now is not None else time.time()
        v = self.viewer(key, name, avatar)
        new_viewer = self._is_new(v)
        out: dict = {"act": kind.value, "name": v.name, "points": 0.0}

        # --- коментар: може да е избор на отбор
        if kind is Act.COMMENT:
            picked = self.team_from_text(text)
            if picked is not None:
                self.assign(v, picked)
                out["picked"] = picked

        # --- последовател: лицето му се качва на въжето
        if kind is Act.FOLLOW:
            v.is_follower = True
            if not any(f["key"] == v.key for f in self.followers):
                self.followers.append({"key": v.key, "name": v.name,
                                       "avatar": v.avatar,
                                       "team": v.team or ""})
                del self.followers[:-40]
            self._say("follow", f"{v.name} ни последва!",
                      name=v.name, avatar=v.avatar, team=v.team or "")

        # --- гифт: сила плюс точки
        if kind is Act.GIFT:
            return self._gift(v, coins, now, out)

        if kind is Act.JOIN:
            self._say("join", f"{v.name} влезе", name=v.name, avatar=v.avatar)
            return out

        # --- колко тегли това действие
        base = PULL.get(kind, 0.0)
        if kind is Act.LIKE:
            base *= self._allowed_likes(v.key, count, now)
        if new_viewer and kind in (Act.COMMENT, Act.LIKE, Act.SHARE):
            base *= self.s.join_bonus_multiplier
            out["join_bonus"] = True

        team = v.team
        if team is None:
            # Няма избран отбор — помага на губещия, ако е включено
            if not self.s.neutral_helps_loser or base <= 0:
                out["neutral"] = True
                return out
            team = self.losing_team()
            self.neutral_pulls += 1
            out["neutral_to"] = team
            applied = self._apply(team, base, None, now)
        else:
            applied = self._apply(team, base, v, now)

        out["points"] = round(applied, 1)
        out["team"] = team
        return out

    def _allowed_likes(self, key: str, count: int, now: float) -> float:
        """
        Таван на лайковете за човек в секунда. TikTok праща лайковете на
        пакети, затова броим по кофа, а не по събитие.
        """
        cap = self.s.like_cap_per_second
        if cap <= 0:
            return float(max(0, count))
        window_start, used = self._like_bucket.get(key, (now, 0.0))
        if now - window_start >= 1.0:
            window_start, used = now, 0.0
        room = max(0.0, cap - used)
        taken = min(float(max(0, count)), room)
        self._like_bucket[key] = (window_start, used + taken)
        return taken

    # ------------------------------------------------------------------
    # гифтове
    # ------------------------------------------------------------------

    def gift_tier(self, coins: int) -> str:
        for threshold, kind in GIFT_TIERS:
            if coins >= threshold:
                return kind
        return "boost"

    def _gift(self, v: Viewer, coins: int, now: float, out: dict) -> dict:
        v.gifts += 1
        team = v.team
        if team is None:
            # Гифт без избран отбор — пита се, но не се губи: отива при
            # губещия, както и неутралните тапове
            team = self.losing_team()
            out["neutral_to"] = team
            self._say("gift_no_team",
                      f"{v.name} праща гифт, но няма отбор! Отива при "
                      f"{TEAM_NAMES[team].lower()}. Напиши М или Ж!",
                      name=v.name)

        kind = self.gift_tier(max(0, coins))
        out["power"] = kind
        out["team"] = team

        # точките, с таван
        cap = self.s.win_threshold * GIFT_POINTS_CAP_SHARE
        pts = min(coins * GIFT_POINTS_PER_COIN, cap)
        if kind == "boost":
            pts = max(pts, 20.0)

        if kind == "reverse":
            # Обратът НЕ дава точки. Иначе сам се отменя: преобръщаш
            # въжето, а после собствените ти точки го дърпат обратно —
            # и ефектът, за който човекът е платил, изчезва.
            pts = 0.0
            self.rope = -self.rope
            self._say("power", POWER_TEXT["reverse"].format(
                who=v.name, team=TEAM_NAMES[team].lower(),
                other=TEAM_NAMES[BOYS if team == GIRLS else GIRLS].lower()),
                power="reverse", team=team, name=v.name, avatar=v.avatar)
        elif kind in POWER_SECONDS:
            self.powers = [p for p in self.powers
                           if p.until > now and not (p.kind == kind and p.team == team)]
            self.powers.append(Power(kind=kind, team=team, who=v.name,
                                     until=now + POWER_SECONDS[kind]))
            self._say("power", POWER_TEXT[kind].format(
                who=v.name, team=TEAM_NAMES[team].lower(),
                other=TEAM_NAMES[BOYS if team == GIRLS else GIRLS].lower()),
                power=kind, team=team, name=v.name, avatar=v.avatar,
                seconds=POWER_SECONDS[kind])
        else:
            self._say("power", POWER_TEXT["boost"].format(
                who=v.name, team=TEAM_NAMES[team].lower(), other=""),
                power="boost", team=team, name=v.name, avatar=v.avatar)

        applied = self._apply(team, pts, v if v.team else None, now)
        out["points"] = round(applied, 1)
        out["coins"] = coins
        return out

    # ------------------------------------------------------------------
    # такт
    # ------------------------------------------------------------------

    def tick(self, now: float | None = None) -> None:
        """Непрекъснатите ефекти и краят на кръга. Вика се често."""
        now = now if now is not None else time.time()
        dt = max(0.0, now - self._last_tick)
        self._last_tick = now

        # Жарта изстива винаги, не само докато тече кръг — иначе остава
        # запалена през паузата и екранът кипи при спряна игра
        if dt > 0:
            cool = math.exp(-dt / HEAT_TAU)
            for t in self.heat:
                self.heat[t] *= cool

        if not self.running:
            return

        # Пружината — въжето се връща към центъра, ако никой не дърпа
        if self.s.decay_tau > 0 and abs(self.rope) > 1e-6 and dt > 0:
            self.rope *= math.exp(-dt / self.s.decay_tau)

        # Великанът тегли сам, непрекъснато
        for p in list(self.powers):
            if p.until <= now:
                if p.kind in POWER_SECONDS:
                    self._say("power_end", f"{POWER_NAMES[p.kind]} свърши.",
                              power=p.kind, team=p.team)
                self.powers.remove(p)
                continue
            if p.kind == "giant":
                self._apply(p.team, 60.0 * dt, None, now)

        if abs(self.rope) >= 1.0 - 1e-9:
            self._finish(GIRLS if self.rope > 0 else BOYS, "изтеглиха въжето", now)
        elif now >= self.round_ends_at:
            if abs(self.rope) < 1e-9:
                self._finish(None, "равенство", now)
            else:
                self._finish(GIRLS if self.rope > 0 else BOYS, "по време", now)

    def _retune(self) -> None:
        """
        Нагласява прага по това колко е теглила публиката този кръг.
        Целта е възелът следващия път да стига до tune_target_peak.
        Смесва се с досегашния праг, за да не подскача при един тих кръг.
        """
        if not self.s.auto_tune or self._peak_net <= 0:
            return
        want = self._peak_net / max(0.05, self.s.tune_target_peak)
        want = max(self.s.min_threshold, min(self.s.max_threshold, want))
        old = self.s.win_threshold
        # В първите кръгове вярваме повече на измереното, за да не чака
        # шест кръга, докато дойде на място
        w = 0.85 if self.round_no <= 3 else 0.6
        new = old * (1.0 - w) + want * w
        self.s.win_threshold = max(self.s.min_threshold,
                                   min(self.s.max_threshold, new))
        if abs(new - old) / max(1.0, old) > 0.1:
            self._say("tuned",
                      f"Нагласих трудността по публиката: "
                      f"{old:.0f} -> {self.s.win_threshold:.0f}",
                      old=round(old), new=round(self.s.win_threshold))

    def _finish(self, winner: str | None, how: str, now: float) -> None:
        self.running = False
        self._retune()
        hero = None
        if self.s.show_hero:
            candidates = [v for v in self.viewers.values() if v.round_points > 0]
            if candidates:
                best = max(candidates, key=lambda v: v.round_points)
                hero = {"name": best.name, "avatar": best.avatar,
                        "team": best.team or "", "points": round(best.round_points)}
                self.heroes.append({**hero, "round_no": self.round_no})
                del self.heroes[:-20]

        if winner:
            self.wins[winner] += 1
            self._say("round_end",
                      f"{TEAM_NAMES[winner]} печелят кръг {self.round_no} — {how}!",
                      winner=winner, how=how, hero=hero,
                      wins=dict(self.wins), round_no=self.round_no)
        else:
            self._say("round_end", f"Кръг {self.round_no} завърши наравно!",
                      winner="", how=how, hero=hero,
                      wins=dict(self.wins), round_no=self.round_no)

    # ------------------------------------------------------------------
    # състояние за картината
    # ------------------------------------------------------------------

    def leaders(self, team: str, n: int = 3) -> list[dict]:
        vs = [v for v in self.viewers.values()
              if v.team == team and v.round_points > 0]
        vs.sort(key=lambda v: v.round_points, reverse=True)
        return [{"name": v.name, "avatar": v.avatar,
                 "points": round(v.round_points)} for v in vs[:n]]

    def state(self, now: float | None = None) -> dict:
        now = now if now is not None else time.time()
        counts = {BOYS: 0, GIRLS: 0}
        for v in self.viewers.values():
            if v.team in counts:
                counts[v.team] += 1
        return {
            "rope": round(self.rope, 4),
            "running": self.running,
            "round_no": self.round_no,
            "seconds_left": max(0.0, round(self.round_ends_at - now, 1)),
            "wins": dict(self.wins),
            "team_counts": counts,
            "team_names": TEAM_NAMES,
            "powers": [{"kind": p.kind, "name": POWER_NAMES[p.kind],
                        "team": p.team, "who": p.who,
                        "left": round(p.left, 1)}
                       for p in self.powers if p.until > now],
            "followers": self.followers[-12:],
            "leaders": {BOYS: self.leaders(BOYS), GIRLS: self.leaders(GIRLS)},
            "hero": self.heroes[-1] if self.heroes else None,
            "neutral_pulls": self.neutral_pulls,
            "viewers_known": len(self.viewers),
            "comeback": {BOYS: round(self.comeback(BOYS), 2),
                         GIRLS: round(self.comeback(GIRLS), 2)},
            "heat": {BOYS: round(min(1.0, self.heat[BOYS] / HEAT_FULL), 3),
                     GIRLS: round(min(1.0, self.heat[GIRLS] / HEAT_FULL), 3)},
            "threshold": round(self.s.win_threshold),
        }
