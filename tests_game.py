"""
tests_game.py — правилата, проверени без стрийм.

Последният тест е най-важният: пуска симулиран кръг с реалистична
публика и гледа дали играта свършва както трябва. Баланс, който
изглежда добре на хартия, често е скучен или свършва за 10 секунди.
"""

from __future__ import annotations

import random
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from game_core import (BOYS, GIRLS, Act, Game, Settings)

PASS = 0
FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[ ok ] {name}" + (f" — {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"[FAIL] {name}" + (f" — {detail}" if detail else ""))


def fresh(**kw) -> Game:
    g = Game(Settings(**kw), now=1000.0)
    g.start_round(now=1000.0)
    return g


# ---------------------------------------------------------------------------

def test_teams() -> None:
    print("\n--- Избор на отбор от коментар ---")
    g = fresh()

    for text in ("М", "м", " m ", "момче", "момчета", "BOYS"):
        check(f"{text!r} избира момчетата",
              g.team_from_text(text) == BOYS, str(g.team_from_text(text)))
    for text in ("Ж", "ж", "F", "момиче", "момичета", "girls"):
        check(f"{text!r} избира момичетата",
              g.team_from_text(text) == GIRLS, str(g.team_from_text(text)))

    # Най-важното: обикновен коментар НЕ бива да закача човек за отбор
    for text in ("може ли малко музика", "жестоко!", "мерси", "здравей",
                 "мн яко брат", "кажи здравей на мама"):
        check(f"{text!r} не избира отбор", g.team_from_text(text) is None,
              str(g.team_from_text(text)))

    r = g.act(Act.COMMENT, "u1", "Иван", text="М")
    check("коментарът хем избира отбор, хем тегли",
          r.get("picked") == BOYS and r["points"] > 0, str(r))

    g.act(Act.COMMENT, "u1", "Иван", text="Ж")
    check("смяната на отбор се помни", g.viewers["u1"].team == GIRLS)


def test_rope() -> None:
    print("\n--- Посока и граници на въжето ---")
    g = fresh(comeback_max=1.0, join_bonus_multiplier=1.0)

    g.act(Act.COMMENT, "b", "Боян", text="М")
    before = g.rope
    g.act(Act.LIKE, "b", count=10)
    check("момчетата теглят наляво (отрицателно)", g.rope < before,
          f"{before} -> {g.rope:.4f}")

    g.act(Act.COMMENT, "d", "Дани", text="Ж")
    before = g.rope
    g.act(Act.LIKE, "d", count=10)
    check("момичетата теглят надясно", g.rope > before,
          f"{before:.4f} -> {g.rope:.4f}")

    g2 = fresh(comeback_max=1.0)
    g2.act(Act.COMMENT, "x", text="М")
    for _ in range(500):
        g2.act(Act.SHARE, "x")
    check("въжето не минава -1", g2.rope >= -1.0, f"{g2.rope}")


def test_comeback() -> None:
    print("\n--- Бонус за отчаяние ---")
    g = fresh(comeback_max=2.5)
    check("в центъра няма бонус", abs(g.comeback(BOYS) - 1.0) < 1e-9,
          f"{g.comeback(BOYS)}")

    g.rope = 0.5     # момичетата водят
    cb_boys, cb_girls = g.comeback(BOYS), g.comeback(GIRLS)
    check("губещият тегли по-силно", cb_boys > cb_girls,
          f"момчета {cb_boys:.2f} срещу момичета {cb_girls:.2f}")
    check("водещият няма бонус", abs(cb_girls - 1.0) < 1e-9, f"{cb_girls}")

    g.rope = 1.0
    check("на ръба бонусът е максималният",
          abs(g.comeback(BOYS) - 2.5) < 1e-9, f"{g.comeback(BOYS)}")


def test_like_cap() -> None:
    print("\n--- Таван на лайковете ---")
    g = fresh(like_cap_per_second=10.0, comeback_max=1.0,
              join_bonus_multiplier=1.0)
    g.act(Act.COMMENT, "spam", text="М", now=1000.0)
    start = g.rope

    # Автоматичен тапер: 100 лайка в една секунда
    for _ in range(10):
        g.act(Act.LIKE, "spam", count=10, now=1000.2)
    moved = abs(g.rope - start)
    expected = 10.0 / g.s.win_threshold     # само 10 са минали
    check("сто лайка в секунда се режат до десет",
          abs(moved - expected) < 1e-6, f"преместване {moved:.5f}")

    # След секунда кофата се отваря пак
    g.act(Act.LIKE, "spam", count=10, now=1002.0)
    check("следващата секунда пак брои", abs(g.rope - start) > expected)

    g3 = fresh(like_cap_per_second=0, comeback_max=1.0,
               join_bonus_multiplier=1.0)
    g3.act(Act.COMMENT, "u", text="М")
    s = g3.rope
    g3.act(Act.LIKE, "u", count=50)
    check("нулев таван значи без ограничение",
          abs(abs(g3.rope - s) - 50.0 / g3.s.win_threshold) < 1e-6)


def test_gift_tiers() -> None:
    print("\n--- Силите от гифтовете ---")
    g = fresh()
    cases = {1: "boost", 5: "boost", 9: "boost", 10: "storm", 99: "storm",
             100: "sabotage", 499: "sabotage", 500: "reverse",
             1999: "reverse", 2000: "giant", 34999: "giant"}
    for coins, want in cases.items():
        got = g.gift_tier(coins)
        check(f"{coins} монети -> {want}", got == want, got)


def test_powers() -> None:
    print("\n--- Какво правят силите ---")

    # ОБРАТ
    g = fresh()
    g.act(Act.COMMENT, "a", "Ани", text="Ж")
    g.rope = 0.8
    g.act(Act.GIFT, "a", "Ани", coins=500, now=1001.0)
    check("обратът преобръща въжето", g.rope < 0, f"{g.rope:.3f}")

    # САБОТАЖ
    g = fresh(comeback_max=1.0, join_bonus_multiplier=1.0)
    g.act(Act.COMMENT, "b", "Боян", text="М", now=1000.0)
    g.act(Act.COMMENT, "d", "Дани", text="Ж", now=1000.0)
    g.act(Act.GIFT, "b", "Боян", coins=100, now=1001.0)
    before = g.rope
    g.act(Act.LIKE, "d", count=10, now=1002.0)
    check("саботираният отбор тапа напразно", abs(g.rope - before) < 1e-9,
          f"{before:.4f} -> {g.rope:.4f}")
    before = g.rope
    g.act(Act.LIKE, "b", count=10, now=1002.0)
    check("саботиращият продължава да тегли", g.rope != before)
    g.tick(now=1020.0)
    before = g.rope
    g.act(Act.LIKE, "d", count=10, now=1020.0)
    check("след изтичане саботажът пада", g.rope != before)

    # БУРЯ
    g = fresh(comeback_max=1.0, join_bonus_multiplier=1.0)
    g.act(Act.COMMENT, "b", text="М", now=1000.0)
    rope_before_likes = g.rope
    g.act(Act.LIKE, "b", count=10, now=1000.0)
    plain = abs(g.rope - rope_before_likes)
    g2 = fresh(comeback_max=1.0, join_bonus_multiplier=1.0)
    g2.act(Act.COMMENT, "b", text="М", now=1000.0)
    g2.act(Act.GIFT, "b", coins=10, now=1000.0)
    rope_after_gift = g2.rope
    g2.act(Act.LIKE, "b", count=10, now=1001.0)
    stormed = abs(g2.rope - rope_after_gift)
    check("бурята удвоява лайковете",
          abs(stormed - 2 * plain) < 1e-6, f"{plain:.5f} -> {stormed:.5f}")

    # ВЕЛИКАН
    g = fresh(comeback_max=1.0)
    g.act(Act.COMMENT, "v", "Велин", text="М", now=1000.0)
    g.act(Act.GIFT, "v", "Велин", coins=2000, now=1000.0)
    after_gift = g.rope
    g.tick(now=1005.0)
    check("великанът тегли сам, без да пипа никой",
          g.rope < after_gift, f"{after_gift:.3f} -> {g.rope:.3f}")
    check("великанът е вписан като сила",
          any(p.kind == "giant" for p in g.powers))


def test_gift_cap() -> None:
    print("\n--- Таванът на гифтовете ---")
    g = fresh(comeback_max=1.0)
    g.act(Act.COMMENT, "rich", "Богатия", text="М", now=1000.0)
    g.act(Act.GIFT, "rich", "Богатия", coins=34999, now=1000.0)
    check("най-големият гифт НЕ печели кръга моментално",
          abs(g.rope) < 1.0, f"въже на {g.rope:.3f}")
    check("но дърпа чувствително", abs(g.rope) > 0.3, f"{g.rope:.3f}")


def test_neutral() -> None:
    print("\n--- Неутралните помагат на губещия ---")
    g = fresh(comeback_max=1.0, join_bonus_multiplier=1.0,
              neutral_helps_loser=True)
    g.rope = 0.6     # момичетата водят
    r = g.act(Act.LIKE, "nobody", "Минувач", count=5)
    check("тапът без отбор отива при губещия",
          r.get("neutral_to") == BOYS, str(r))
    check("и наистина мести въжето", g.rope < 0.6, f"{g.rope:.4f}")
    check("броячът на неутрални расте", g.neutral_pulls == 1)

    g2 = fresh(neutral_helps_loser=False)
    before = g2.rope
    r = g2.act(Act.LIKE, "nobody", count=5)
    check("при изключено — тапът не прави нищо",
          abs(g2.rope - before) < 1e-9 and r.get("neutral") is True, str(r))


def test_follow() -> None:
    print("\n--- Последователят се качва на въжето ---")
    g = fresh()
    g.act(Act.COMMENT, "f", "Фен", text="М")
    r = g.act(Act.FOLLOW, "f", "Фен", avatar="http://x/a.jpg")
    check("последователят тегли сериозно", r["points"] >= 50, str(r["points"]))
    check("влиза в списъка за въжето", len(g.followers) == 1)
    check("със снимка и отбор",
          g.followers[0]["avatar"] == "http://x/a.jpg"
          and g.followers[0]["team"] == BOYS, str(g.followers[0]))
    g.act(Act.FOLLOW, "f", "Фен")
    check("два пъти не се дублира", len(g.followers) == 1)


def test_round_end() -> None:
    print("\n--- Край на кръга ---")
    g = fresh(comeback_max=1.0)
    g.act(Act.COMMENT, "b", "Боян", text="М", now=1000.0)
    for _ in range(60):
        g.act(Act.SHARE, "b", now=1000.0)
    g.tick(now=1000.0)
    check("изтегленото докрай въже печели веднага", not g.running)
    check("победата е за момчетата", g.wins[BOYS] == 1, str(g.wins))
    end = [e for e in g.feed if e["kind"] == "round_end"]
    check("има съобщение за край", bool(end))
    check("героят е най-големият принос",
          end and end[0]["hero"] and end[0]["hero"]["name"] == "Боян",
          str(end[0].get("hero") if end else None))

    g = fresh(comeback_max=1.0, round_seconds=90.0)
    g.act(Act.COMMENT, "d", "Дани", text="Ж", now=1000.0)
    g.act(Act.LIKE, "d", count=5, now=1000.0)
    g.tick(now=1091.0)
    check("по време печели водещият",
          not g.running and g.wins[GIRLS] == 1, str(g.wins))

    g = fresh(round_seconds=90.0)
    g.tick(now=1091.0)
    check("без никакви действия е равенство",
          not g.running and g.wins == {BOYS: 0, GIRLS: 0}, str(g.wins))

    g.start_round(now=1100.0)
    check("новият кръг връща въжето в центъра", g.rope == 0.0 and g.running)
    check("броячът на кръгове расте", g.round_no == 2)


def test_state() -> None:
    print("\n--- Състоянието за картината ---")
    g = fresh()
    g.act(Act.COMMENT, "b", "Боян", text="М", avatar="a1")
    g.act(Act.COMMENT, "d", "Дани", text="Ж", avatar="a2")
    g.act(Act.LIKE, "b", count=8)
    st = g.state(now=1010.0)

    for key in ("rope", "running", "round_no", "seconds_left", "wins",
                "team_counts", "powers", "followers", "leaders", "hero",
                "comeback", "neutral_pulls"):
        check(f"състоянието носи '{key}'", key in st)
    check("брои хората по отбори",
          st["team_counts"] == {BOYS: 1, GIRLS: 1}, str(st["team_counts"]))
    check("показва водачите",
          st["leaders"][BOYS] and st["leaders"][BOYS][0]["name"] == "Боян",
          str(st["leaders"]))
    check("остатъкът от времето е разумен",
          0 < st["seconds_left"] <= 90, str(st["seconds_left"]))

    import json
    try:
        json.dumps(st)
        check("състоянието минава в JSON", True)
    except Exception as e:
        check("състоянието минава в JSON", False, str(e))


def test_balance() -> None:
    """
    Симулира реалистичен кръг: 30 души, от които част тапат,
    част коментират, някой праща гифт. Гледаме дали кръгът свършва
    в разумно време и дали не е решен от един човек.
    """
    print("\n--- Баланс при симулиран кръг ---")
    random.seed(7)
    results = []

    for run in range(12):
        g = Game(Settings(), now=0.0)
        g.start_round(now=0.0)
        people = []
        for i in range(30):
            team = BOYS if i % 2 == 0 else GIRLS
            key = f"u{i}"
            g.act(Act.COMMENT, key, f"Зрител{i}",
                  text="М" if team == BOYS else "Ж", now=0.0)
            people.append(key)

        t = 0.0
        peak = 0.0
        while g.running and t < 200.0:
            t += 0.5
            peak = max(peak, abs(g.rope))
            # всеки втори човек тапа по 1-3 пъти на половин секунда
            for key in random.sample(people, k=12):
                g.act(Act.LIKE, key, count=random.randint(1, 3), now=t)
            if random.random() < 0.04:
                g.act(Act.COMMENT, random.choice(people), text="хаха", now=t)
            if random.random() < 0.01:
                g.act(Act.GIFT, random.choice(people),
                      coins=random.choice([1, 5, 10, 100]), now=t)
            g.tick(now=t)

        top = max((v.round_points for v in g.viewers.values()), default=0)
        total = sum(v.round_points for v in g.viewers.values()) or 1
        results.append((t, top / total, peak, g.s.win_threshold))

    times = [r[0] for r in results]
    shares = [r[1] for r in results]
    peaks = [r[2] for r in results]
    avg_t = sum(times) / len(times)
    worst_share = max(shares)
    avg_peak = sum(peaks) / len(peaks)

    print(f"       кръгът свършва средно за {avg_t:.0f} сек "
          f"(най-бързо {min(times):.0f}, най-бавно {max(times):.0f})")
    print(f"       най-големият принос на един човек: {worst_share*100:.0f}% "
          "от всичко")

    check("кръгът свършва, не виси", all(t < 200 for t in times))
    check("не свършва за секунди", avg_t > 15, f"{avg_t:.0f} сек")
    check("не се точи безкрайно", avg_t < 150, f"{avg_t:.0f} сек")
    check("един човек не решава кръга сам", worst_share < 0.45,
          f"{worst_share*100:.0f}%")
    print(f"       при равни отбори възелът стига до {avg_peak:.2f} "
          f"(най-далеч {max(peaks):.2f})")
    check("при равни отбори кръгът остава оспорван", avg_peak < 0.6,
          f"{avg_peak:.2f}")
    check("но възелът все пак се движи видимо", avg_peak > 0.08,
          f"{avg_peak:.2f}")

    # А когато един отбор наистина доминира, трябва да се вижда ясно
    random.seed(5)
    g = Game(Settings(), now=0.0)
    g.start_round(now=0.0)
    boys = [f"b{i}" for i in range(21)]
    girls = [f"g{i}" for i in range(9)]
    for k in boys:
        g.act(Act.COMMENT, k, text="М", now=0.0)
    for k in girls:
        g.act(Act.COMMENT, k, text="Ж", now=0.0)
    t = 0.0
    peak = 0.0
    while g.running and t < 200.0:
        t += 0.5
        peak = max(peak, abs(g.rope))
        for k in random.sample(boys, k=7):
            g.act(Act.LIKE, k, count=2, now=t)
        for k in random.sample(girls, k=3):
            g.act(Act.LIKE, k, count=2, now=t)
        g.tick(now=t)
    print(f"       при 70/30 доминация възелът стига до {peak:.2f}")
    check("доминацията се вижда ясно", peak > 0.4, f"{peak:.2f}")
    check("доминиращият отбор печели", g.wins[BOYS] == 1, str(g.wins))

    # Пружината: спре ли активността, въжето се връща към центъра
    g2 = Game(Settings(), now=0.0)
    g2.start_round(now=0.0)
    g2.act(Act.COMMENT, "x", text="М", now=0.0)
    g2.rope = -0.8
    # След време, равно на пружината, трябва да е паднало до ~37%.
    # Мери се спрямо настройката, за да не зависи от нейната стойност.
    g2.tick(now=g2.s.decay_tau)
    check("спре ли дърпането, въжето се връща към центъра",
          abs(g2.rope) < 0.8 * 0.45,
          f"{g2.rope:.3f} след {g2.s.decay_tau:.0f} сек тишина")


def test_heat():
    """
    Жарта е това, което кара картината да кипи. Тя трябва да пламва от
    дърпане, да изстива сама и да НЕ зависи от прага — иначе при голяма
    публика екранът ще гори вечно, а при малка няма да светне никога.
    """
    print("\n--- Жар: колко силно се дърпа в момента ---")

    g = Game(Settings(), now=0.0)
    g.start_round(now=0.0)
    check("в началото е студено", g.state(now=0.0)["heat"][BOYS] == 0.0)

    # Изборът на отбор е коментар, а коментарът дърпа — значи пали
    g.act(Act.COMMENT, "a", text="М", now=0.0)
    check("дори изборът на отбор я пали", g.state(now=0.0)["heat"][BOYS] > 0,
          f"{g.state(now=0.0)['heat'][BOYS]:.2f}")

    for _ in range(40):
        g.act(Act.LIKE, "a", count=10, now=0.0)
    hot = g.state(now=0.0)["heat"]
    check("тапането я вдига", hot[BOYS] > 0.3, f"{hot[BOYS]:.2f}")
    check("другият отбор остава студен", hot[GIRLS] == 0.0)

    g.tick(now=6.0)
    cold = g.state(now=6.0)["heat"][BOYS]
    check("изстива сама за секунди", cold < 0.05, f"{cold:.3f} след 6 сек")

    # Едно и също дърпане, измерено като дял от прага, трябва да дава
    # една и съща жар. Иначе при голяма публика екранът гори вечно, а
    # при малка не светва никога.
    def heat_at(threshold):
        gg = Game(Settings(win_threshold=threshold, auto_tune=False), now=0.0)
        gg.start_round(now=0.0)
        gg._apply(BOYS, threshold * 0.2, None, 0.0)
        return gg.state(now=0.0)["heat"][BOYS]

    a, b = heat_at(250.0), heat_at(25000.0)
    check("не зависи от големината на публиката", abs(a - b) < 0.01,
          f"{a:.2f} срещу {b:.2f}")

    # И накрая: жарта не бива да остава запалена през паузата
    g.heat[BOYS] = 1.0
    g.running = False
    g.tick(now=12.0)
    check("изстива и когато кръгът е свършил",
          g.state(now=12.0)["heat"][BOYS] < 0.05,
          f"{g.state(now=12.0)['heat'][BOYS]:.3f}")


def main() -> int:
    print("=" * 64)
    print("Момчета срещу момичета — проверка на правилата")
    print("=" * 64)
    test_teams()
    test_rope()
    test_comeback()
    test_like_cap()
    test_gift_tiers()
    test_powers()
    test_gift_cap()
    test_neutral()
    test_follow()
    test_round_end()
    test_state()
    test_heat()
    test_balance()
    print("\n" + "=" * 64)
    print(f"Успешни: {PASS}   Неуспешни: {FAIL}")
    print("=" * 64)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
