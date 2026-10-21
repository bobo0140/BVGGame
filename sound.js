/* ==========================================================================
   sound.js — звукът на играта, направен на място.

   Няма звукови файлове. Всичко се сглобява от осцилатори и шум в самия
   браузър: нищо за сваляне, нищо за лицензиране и тежи под 10 килобайта.

   В OBS: сложи отметка „Control audio via OBS" на Browser source-а, за да
   влезе звукът в стрийма. Ако не се чува, цъкни веднъж „Interact".
   За без звук — отвори адреса с ?sound=0 накрая.
   ========================================================================== */

window.BVGSound = (function () {
  "use strict";

  var ctx = null, bus = null, noiseBuf = null;
  var enabled = true, started = false;
  var sirenOsc = null, sirenGain = null, sirenLfo = null;

  function wanted() {
    try {
      return new URLSearchParams(location.search).get("sound") !== "0";
    } catch (e) { return true; }
  }
  enabled = wanted();

  function start() {
    if (!enabled || started) return;
    var AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) { enabled = false; return; }
    try {
      ctx = new AC();
      bus = ctx.createGain();
      bus.gain.value = 0.55;
      bus.connect(ctx.destination);
      noiseBuf = makeNoise();
      started = true;
    } catch (e) { enabled = false; }
  }

  function makeNoise() {
    var n = Math.floor(ctx.sampleRate * 1.2);
    var b = ctx.createBuffer(1, n, ctx.sampleRate);
    var d = b.getChannelData(0);
    for (var i = 0; i < n; i++) d[i] = Math.random() * 2 - 1;
    return b;
  }

  function ok() {
    if (!enabled) return false;
    if (!started) start();
    if (!ctx) return false;
    if (ctx.state === "suspended") { try { ctx.resume(); } catch (e) {} }
    return ctx.state === "running";
  }

  /* -------------------------------------------------------- тухличките */

  function tone(o) {
    if (!ok()) return;
    var t0 = ctx.currentTime + (o.when || 0);
    var dur = o.dur || 0.2;
    var osc = ctx.createOscillator();
    var g = ctx.createGain();
    osc.type = o.type || "sine";
    osc.frequency.setValueAtTime(o.freq, t0);
    if (o.to) {
      osc.frequency.exponentialRampToValueAtTime(Math.max(20, o.to), t0 + dur);
    }
    var vol = o.vol == null ? 0.2 : o.vol;
    g.gain.setValueAtTime(0.0001, t0);
    g.gain.exponentialRampToValueAtTime(vol, t0 + (o.attack || 0.008));
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    osc.connect(g); g.connect(bus);
    osc.start(t0); osc.stop(t0 + dur + 0.02);
  }

  function hit(o) {
    // Шумов удар — за тупване, аплодисменти, замах
    if (!ok()) return;
    var t0 = ctx.currentTime + (o.when || 0);
    var dur = o.dur || 0.2;
    var src = ctx.createBufferSource();
    src.buffer = noiseBuf;
    var f = ctx.createBiquadFilter();
    f.type = o.filter || "bandpass";
    f.frequency.setValueAtTime(o.freq || 900, t0);
    if (o.to) f.frequency.exponentialRampToValueAtTime(Math.max(40, o.to), t0 + dur);
    f.Q.value = o.q == null ? 1.1 : o.q;
    var g = ctx.createGain();
    var vol = o.vol == null ? 0.18 : o.vol;
    g.gain.setValueAtTime(0.0001, t0);
    g.gain.exponentialRampToValueAtTime(vol, t0 + (o.attack || 0.006));
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    src.connect(f); f.connect(g); g.connect(bus);
    src.start(t0); src.stop(t0 + dur + 0.02);
  }

  /* ------------------------------------------------------------ гласът */

  // Момчетата звучат ниско, момичетата високо — чува се кой дърпа, без
  // да се гледа екранът.
  var BASE = { M: 150, F: 260 };

  var lastTap = 0;
  function tap(team, strength) {
    // Таповете валят по стотици; пускаме рядко и тихо, иначе става каша
    var now = performance.now();
    var gap = 150 - 90 * Math.min(1, strength || 0);
    if (now - lastTap < gap) return;
    lastTap = now;
    var f = (BASE[team] || 200) * (1 + Math.random() * 0.12);
    tone({ freq: f * 2, type: "triangle", dur: 0.06,
           vol: 0.04 + 0.09 * Math.min(1, strength || 0) });
  }

  function join(team) {
    var f = BASE[team] || 200;
    tone({ freq: f, type: "square", dur: 0.09, vol: 0.09 });
    tone({ freq: f * 1.5, type: "square", dur: 0.11, vol: 0.07, when: 0.07 });
  }

  function follow() {
    // Най-важният звук в играта — последовател. Светло и нагоре.
    var f = 392;
    [0, 0.09, 0.18].forEach(function (w, i) {
      tone({ freq: f * Math.pow(1.26, i), type: "triangle",
             dur: 0.3, vol: 0.2, when: w });
      tone({ freq: f * 2 * Math.pow(1.26, i), type: "sine",
             dur: 0.25, vol: 0.09, when: w });
    });
    hit({ freq: 5000, to: 1800, dur: 0.5, vol: 0.1, filter: "highpass", when: 0.02 });
  }

  function share() {
    tone({ freq: 520, to: 880, type: "triangle", dur: 0.22, vol: 0.14 });
  }

  function power(kind) {
    if (kind === "storm") {
      tone({ freq: 200, to: 1400, type: "sawtooth", dur: 0.7, vol: 0.16 });
      hit({ freq: 400, to: 4000, dur: 0.7, vol: 0.12, filter: "highpass" });
    } else if (kind === "sabotage") {
      tone({ freq: 500, to: 70, type: "sawtooth", dur: 0.8, vol: 0.2 });
      hit({ freq: 1200, to: 150, dur: 0.8, vol: 0.14 });
    } else if (kind === "reverse") {
      hit({ freq: 300, to: 4000, dur: 0.28, vol: 0.18, filter: "highpass" });
      tone({ freq: 900, to: 160, type: "square", dur: 0.4, vol: 0.18, when: 0.2 });
      hit({ freq: 120, dur: 0.4, vol: 0.3, filter: "lowpass", q: 0.7, when: 0.24 });
    } else if (kind === "giant") {
      [65, 98, 131].forEach(function (f, i) {
        tone({ freq: f, type: "sawtooth", dur: 1.1, vol: 0.15, when: i * 0.03 });
      });
      hit({ freq: 90, dur: 0.9, vol: 0.3, filter: "lowpass", q: 0.6 });
    } else {
      tone({ freq: 660, type: "sine", dur: 0.25, vol: 0.14 });
      tone({ freq: 990, type: "sine", dur: 0.3, vol: 0.1, when: 0.08 });
    }
  }

  function yank(team, force) {
    // Силно дърпане — опъване на въже
    hit({ freq: team === "M" ? 700 : 1100, to: team === "M" ? 200 : 400,
          dur: 0.18, vol: 0.08 + 0.12 * Math.min(1, force || 0), q: 0.9 });
  }

  function beep(last) {
    tone({ freq: last ? 880 : 620, type: "square",
           dur: last ? 0.22 : 0.1, vol: 0.18 });
  }

  function roundEnd(winner) {
    var root = winner === "M" ? 147 : 196;    // ниско за момчета, високо за момичета
    [1, 1.26, 1.5, 2].forEach(function (m, i) {
      tone({ freq: root * m, type: "sawtooth", dur: 1.0 - i * 0.08,
             vol: 0.17, when: i * 0.05 });
    });
    hit({ freq: 2500, dur: 1.4, vol: 0.14, filter: "highpass", when: 0.1 });
  }

  function roundStart() {
    tone({ freq: 300, to: 600, type: "square", dur: 0.18, vol: 0.16 });
    tone({ freq: 600, type: "square", dur: 0.3, vol: 0.18, when: 0.2 });
  }

  /* ----------------------------------------------- сирената за опасност */

  function siren(on) {
    if (!ok()) return;
    if (on && !sirenOsc) {
      sirenOsc = ctx.createOscillator();
      sirenGain = ctx.createGain();
      sirenLfo = ctx.createOscillator();
      var lfoGain = ctx.createGain();
      sirenOsc.type = "sawtooth";
      sirenOsc.frequency.value = 300;
      sirenLfo.frequency.value = 2.2;
      lfoGain.gain.value = 90;
      sirenLfo.connect(lfoGain); lfoGain.connect(sirenOsc.frequency);
      sirenGain.gain.setValueAtTime(0.0001, ctx.currentTime);
      sirenGain.gain.exponentialRampToValueAtTime(0.07, ctx.currentTime + 0.3);
      sirenOsc.connect(sirenGain); sirenGain.connect(bus);
      sirenOsc.start(); sirenLfo.start();
    } else if (!on && sirenOsc) {
      var t = ctx.currentTime;
      try {
        sirenGain.gain.cancelScheduledValues(t);
        sirenGain.gain.setValueAtTime(sirenGain.gain.value || 0.0001, t);
        sirenGain.gain.exponentialRampToValueAtTime(0.0001, t + 0.25);
        sirenOsc.stop(t + 0.3); sirenLfo.stop(t + 0.3);
      } catch (e) {}
      sirenOsc = null; sirenGain = null; sirenLfo = null;
    }
  }

  /* ------------------------------------------------------------ отвън */

  // Браузърите не пускат звук, преди човек да цъкне. В OBS обикновено е
  // разрешено, но ако не е — първото цъкване или бутон отпушва всичко.
  ["pointerdown", "keydown", "touchstart"].forEach(function (ev) {
    window.addEventListener(ev, function () { ok(); }, { once: false });
  });

  return {
    start: start,
    ready: function () { return !!(ctx && ctx.state === "running"); },
    // За проверка отвън: позволява да се закачи измервател и да се види,
    // че наистина излиза звук, а не само че контекстът е жив.
    graph: function () { return { ctx: ctx, bus: bus }; },
    enabled: function () { return enabled; },
    tap: tap, join: join, follow: follow, share: share,
    power: power, yank: yank, beep: beep,
    roundEnd: roundEnd, roundStart: roundStart, siren: siren
  };
})();
