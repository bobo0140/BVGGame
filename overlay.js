/* ==========================================================================
   overlay.js — рисува състоянието, нищо повече.

   Правилата са в game_core.py. Тук само гледаме какво е дошло по
   WebSocket и го показваме. Ако връзката падне, казваме го на екрана и
   чакаме — играта пак ще се появи, като се пусне приложението.
   ========================================================================== */

(function () {
  "use strict";

  var BOYS = "M", GIRLS = "F";
  var POWER_FULL = { storm: 15, sabotage: 10, giant: 20 };
  // Трима на страна. С повече въжето изчезва зад лицата, а въжето е
  // това, което зрителят гледа.
  var MAX_PULLERS_PER_SIDE = 3;
  var PULLER_GAP = 104;      // кръговете са 92 — под 100 се слепват
  var PULLER_EDGE = 60;      // най-задният стои до своя стълб
  var PULLER_DRAG = 70;      // колко ги влачи въжето, когато губят
  var NAMES_SHOWN = 3;       // по-назад имената само се слепват
  var MSG_LIFE_MS = 4500;
  var MSG_MAX = 3;
  var CURTAIN_MS = 5200;

  var $ = function (id) { return document.getElementById(id); };

  var stage = $("stage");
  var knot = $("knot");
  var pullersBox = $("pullers");
  var powersBox = $("powers");
  var ticker = $("ticker");
  var curtain = $("curtain");
  var offline = $("offline");

  /* ---------------------------------------------------------------- мащаб */

  function fit() {
    var s = Math.min(window.innerWidth / 1080, window.innerHeight / 1920);
    stage.style.transform = "scale(" + s + ")";
  }
  window.addEventListener("resize", fit);
  fit();

  /* --------------------------------------------------------------- таблото */

  var lastRope = 0;
  var lastWins = null;

  function fmtClock(sec) {
    sec = Math.max(0, Math.round(sec));
    var m = Math.floor(sec / 60), s = sec % 60;
    return m + ":" + (s < 10 ? "0" : "") + s;
  }

  function drawBoard(st) {
    var names = st.team_names || {};
    $("name-boys").textContent = names[BOYS] || "Момчета";
    $("name-girls").textContent = names[GIRLS] || "Момичета";

    var c = st.team_counts || {};
    $("meta-boys").textContent = (c[BOYS] || 0) + " души";
    $("meta-girls").textContent = (c[GIRLS] || 0) + " души";

    var w = st.wins || {};
    $("wins-boys").textContent = w[BOYS] || 0;
    $("wins-girls").textContent = w[GIRLS] || 0;

    $("round-label").textContent = "Кръг " + (st.round_no || 1);

    var clock = $("clock");
    if (st.running) {
      clock.textContent = fmtClock(st.seconds_left);
      clock.classList.toggle("urgent", st.seconds_left <= 10);
    } else {
      clock.textContent = "Пауза";
      clock.classList.remove("urgent");
    }

    var howto = $("howto");
    if (!st.running) {
      howto.innerHTML = "Следващият кръг започва…";
      howto.className = "";
    } else {
      howto.innerHTML = "Напиши <b>М</b> или <b>Ж</b> и тапай";
      // Леко подсказваме кой има нужда от помощ — цветът на кутията.
      howto.className = st.rope > 0.25 ? "boys-help"
                      : st.rope < -0.25 ? "girls-help" : "";
    }
  }

  /* ----------------------------------------------------------------- въжето */

  function knotPercent(rope) {
    // 50% е центърът; до 41% в двете страни, за да не излиза от стълбовете
    return 50 + Math.max(-1, Math.min(1, rope)) * 41;
  }

  function drawRope(st) {
    var rope = st.rope || 0;
    knot.style.left = knotPercent(rope) + "%";

    var d = rope - lastRope;
    if (Math.abs(d) > 0.035) {
      knot.classList.remove("yank-l", "yank-r");
      // Рестартиране на анимацията — без това втори силен тап не се вижда
      void knot.offsetWidth;
      knot.classList.add(d < 0 ? "yank-l" : "yank-r");
    }
    lastRope = rope;
  }

  /* --------------------------------------------------------------- теглачите */

  var pullerEls = {};   // key -> element

  function sideFor(key) {
    // Стабилна страна за човек без отбор: едно и също име винаги
    // застава на едно и също място.
    var h = 0;
    for (var i = 0; i < key.length; i++) {
      h = (h * 31 + key.charCodeAt(i)) & 0x7fffffff;
    }
    return (h % 2) ? GIRLS : BOYS;
  }

  function pullerEl(f) {
    var el = document.createElement("div");
    el.className = "puller fresh";
    var pic;
    if (f.avatar) {
      pic = document.createElement("img");
      pic.src = f.avatar;
      pic.alt = "";
      // Счупена снимка -> буква, иначе остава празен кръг
      pic.onerror = function () {
        var ph = document.createElement("div");
        ph.className = "ph";
        ph.textContent = (f.name || "?").charAt(0).toUpperCase();
        if (pic.parentNode) pic.parentNode.replaceChild(ph, pic);
      };
    } else {
      pic = document.createElement("div");
      pic.className = "ph";
      pic.textContent = (f.name || "?").charAt(0).toUpperCase();
    }
    el.appendChild(pic);

    var tag = document.createElement("div");
    tag.className = "tag";
    tag.textContent = f.name || "";
    el.appendChild(tag);

    setTimeout(function () { el.classList.remove("fresh"); }, 600);
    return el;
  }

  function drawPullers(st) {
    var followers = st.followers || [];
    var rope = st.rope || 0;

    var sides = {};
    sides[BOYS] = [];
    sides[GIRLS] = [];
    var neutral = {};

    for (var i = 0; i < followers.length; i++) {
      var f = followers[i];
      var team = f.team;
      if (team !== BOYS && team !== GIRLS) {
        // Още няма отбор. Таповете му отиват при губещия, но мястото му
        // на екрана се избира по името — иначе, щом въжето мине през
        // нулата, всички без отбор прескачат от страна на страна.
        team = sideFor(f.key);
        neutral[f.key] = true;
      }
      sides[team].push(f);
    }

    var seen = {};
    // Всеки отбор стои при своя стълб, не до възела. Въжето ги влачи:
    // губещите се местят към центъра, печелещите — назад.
    var drag = rope * PULLER_DRAG;

    function place(list, dir) {
      // Последните са най-отпред — новият последовател излиза най-напред
      var recent = list.slice(-MAX_PULLERS_PER_SIDE).reverse();
      for (var j = 0; j < recent.length; j++) {
        var f = recent[j];
        seen[f.key] = true;
        var el = pullerEls[f.key];
        if (!el) {
          el = pullerEl(f);
          pullerEls[f.key] = el;
          pullersBox.appendChild(el);
        }
        var cls = "puller";
        if (neutral[f.key]) cls += " neutral";
        else cls += dir < 0 ? " boys" : " girls";
        if (el.classList.contains("fresh")) cls += " fresh";
        if (j >= NAMES_SHOWN) cls += " quiet";
        el.className = cls;

        var x = dir < 0
          ? PULLER_EDGE + (MAX_PULLERS_PER_SIDE - 1 - j) * PULLER_GAP
          : 1080 - PULLER_EDGE - 92 - (MAX_PULLERS_PER_SIDE - 1 - j) * PULLER_GAP;
        el.style.left = Math.max(6, Math.min(1080 - 98, x + drag)) + "px";
        el.style.zIndex = String(20 - j);
      }
    }

    place(sides[BOYS], -1);
    place(sides[GIRLS], +1);

    for (var key in pullerEls) {
      if (!seen[key]) {
        if (pullerEls[key].parentNode) {
          pullerEls[key].parentNode.removeChild(pullerEls[key]);
        }
        delete pullerEls[key];
      }
    }
  }

  /* ------------------------------------------------------------------ силите */

  var powerEls = {};    // kind|team -> element

  function drawPowers(st) {
    var list = st.powers || [];
    var seen = {};

    for (var i = 0; i < list.length; i++) {
      var p = list[i];
      var id = p.kind + "|" + p.team;
      seen[id] = true;
      var el = powerEls[id];
      if (!el) {
        el = document.createElement("div");
        el.className = "power " + (p.team === BOYS ? "boys" : "girls");
        el.innerHTML = '<div class="pname"></div><div class="pwho"></div>'
                     + '<div class="pbar"><i></i></div>';
        powerEls[id] = el;
        powersBox.appendChild(el);
      }
      el.querySelector(".pname").textContent = p.name || p.kind;
      el.querySelector(".pwho").textContent = p.who || "";
      var full = POWER_FULL[p.kind] || 15;
      var pct = Math.max(0, Math.min(100, (p.left / full) * 100));
      el.querySelector(".pbar i").style.width = pct + "%";
    }

    for (var id2 in powerEls) {
      if (!seen[id2]) {
        if (powerEls[id2].parentNode) {
          powerEls[id2].parentNode.removeChild(powerEls[id2]);
        }
        delete powerEls[id2];
      }
    }
  }

  /* ------------------------------------------------------------- съобщенията */

  function say(text, cls) {
    if (!text) return;
    var el = document.createElement("div");
    el.className = "msg" + (cls ? " " + cls : "");
    el.textContent = text;
    ticker.appendChild(el);
    while (ticker.children.length > MSG_MAX) {
      ticker.removeChild(ticker.firstChild);
    }
    setTimeout(function () {
      if (el.parentNode) el.parentNode.removeChild(el);
    }, MSG_LIFE_MS);
  }

  /* ---------------------------------------------------------- краят на кръга */

  var curtainTimer = null;

  var HOW_TEXT = {
    "изтеглиха въжето": "изтеглиха въжето до края",
    "по време": "водеха, когато времето свърши"
  };

  function showCurtain(item, st) {
    var names = (st && st.team_names) || {};
    var who = item.winner
      ? (names[item.winner] || item.winner)
      : "Равенство";
    $("cur-who").textContent = who;
    $("cur-how").textContent = item.winner
      ? (HOW_TEXT[item.how] || item.how || "")
      : "никой не изтегли въжето";

    var box = $("cur-hero");
    box.innerHTML = "";
    var h = item.hero;
    if (h && h.name) {
      var pic;
      if (h.avatar) {
        pic = document.createElement("img");
        pic.src = h.avatar;
        pic.alt = "";
      } else {
        pic = document.createElement("div");
        pic.className = "ph";
        pic.textContent = h.name.charAt(0).toUpperCase();
      }
      box.appendChild(pic);

      var txt = document.createElement("div");
      txt.className = "txt";
      txt.innerHTML = '<div class="lbl">Най-много изтегли</div>'
                    + '<div class="nm"></div>';
      txt.querySelector(".nm").textContent = h.name;
      box.appendChild(txt);
    }

    curtain.classList.add("show");
    stage.classList.add("curtain-on");
    if (curtainTimer) clearTimeout(curtainTimer);
    curtainTimer = setTimeout(function () {
      curtain.classList.remove("show");
      stage.classList.remove("curtain-on");
    }, CURTAIN_MS);
  }

  function handleFeed(feed, st) {
    for (var i = 0; i < feed.length; i++) {
      var it = feed[i];
      switch (it.kind) {
        case "follow":
          say(it.text, "follow");
          break;
        case "power":
        case "gift_no_team":
          say(it.text, "gift");
          break;
        case "switched_team":
          say(it.text, null);
          break;
        case "round_end":
          showCurtain(it, st);
          break;
        default:
          break;    // joined_team, join, tuned, power_end, round_start
      }
    }
  }

  /* -------------------------------------------------------------- връзката */

  var ws = null;
  var retry = null;

  function draw(st) {
    if (!st) return;
    drawBoard(st);
    drawRope(st);
    drawPullers(st);
    drawPowers(st);
  }

  function connect() {
    var url = (location.protocol === "https:" ? "wss://" : "ws://")
            + location.host + "/ws";
    try {
      ws = new WebSocket(url);
    } catch (e) {
      schedule();
      return;
    }

    ws.onopen = function () {
      offline.classList.remove("show");
    };

    ws.onmessage = function (ev) {
      var msg;
      try { msg = JSON.parse(ev.data); } catch (e) { return; }
      if (msg.type === "hello") {
        draw(msg.state);
      } else if (msg.type === "tick") {
        draw(msg.state);
        if (msg.feed && msg.feed.length) handleFeed(msg.feed, msg.state);
      }
    };

    ws.onclose = function () { schedule(); };
    ws.onerror = function () { /* onclose идва след това */ };
  }

  function schedule() {
    offline.classList.add("show");
    if (retry) return;
    retry = setTimeout(function () { retry = null; connect(); }, 2000);
  }

  connect();
})();
