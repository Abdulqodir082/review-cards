/* Kozel Online: lobby, peer-to-peer networking (host is authoritative), and UI. */
(function () {
  "use strict";
  const E = window.KozelEngine;
  const $ = id => document.getElementById(id);
  const PREFIX = "kozel-v1-";
  const RED = s => s === "♥" || s === "♦";
  const FACE = r => r === "J" || r === "Q" || r === "K";

  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : v; } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  };
  let token = store.get("kozel-token", null);
  if (!token) { token = Math.random().toString(36).slice(2) + Date.now().toString(36); store.set("kozel-token", token); }

  const app = {
    role: null,          // "host" | "client"
    seat: null,          // my seat index
    code: null,
    peer: null,
    online: false,
    conns: [],           // host: per seat connection
    seats: [],           // host: [{name, kind: host|remote|bot|empty, token, online}]
    cfg: { n: 2, teams: true, target: 12 },
    state: null,         // host only
    lobby: null,         // last lobby info (both roles)
    view: null,          // last game view
    selected: new Set(),
    botTimer: null,
    dealTimer: null,
    hostConn: null       // client only
  };

  /* ---------- helpers ---------- */
  function toast(msg) {
    const t = $("toast"); t.textContent = msg; t.hidden = false;
    clearTimeout(toast.t); toast.t = setTimeout(() => { t.hidden = true; }, 2600);
  }
  function esc(s) { return String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
  function cardHTML(c, size, extra) {
    size = size || "";
    if (c === "back") return `<div class="card back ${size}" aria-label="face-down card"></div>`;
    const s = c.slice(-1), r = c.slice(0, -1);
    const isT = app.view && app.view.trump === s;
    const cls = ["card", size, RED(s) ? "red" : "", FACE(r) ? "face" : "", isT ? "trump" : "", extra || ""].join(" ");
    const mid = FACE(r) ? r + s : s;
    return `<div class="${cls}" data-card="${c}" role="img" aria-label="${c}${isT ? " trump" : ""}"><span class="c-tl">${r}<small>${s}</small></span><span class="c-mid">${mid}</span></div>`;
  }
  function show(screen) { ["home", "room", "game"].forEach(id => { $(id).hidden = id !== screen; }); }
  function cfgText(c) {
    const who = c.n === 4 ? (c.teams ? "4 players in two pairs" : "4 players, everyone alone") : c.n + " players";
    const len = c.target === 1 ? "one deal" : "first to " + c.target + " bad points is the goat";
    return who + " · " + len;
  }
  function makeCode() {
    const A = "ABCDEFGHJKLMNPQRSTUVWXYZ";
    let s = ""; for (let i = 0; i < 5; i++) s += A[Math.floor(Math.random() * A.length)];
    return s;
  }
  function inviteLink(code) {
    return location.origin + location.pathname + "?room=" + code;
  }

  /* ---------- home screen ---------- */
  $("name").value = store.get("kozel-name", "");
  $("name").addEventListener("input", () => store.set("kozel-name", $("name").value.trim()));
  function myName() { return ($("name").value.trim() || "Player").slice(0, 16); }

  function bindSeg(id, key, parse) {
    const el = $(id);
    el.addEventListener("click", e => {
      const b = e.target.closest("button"); if (!b) return;
      app.cfg[key] = parse(b.dataset.v); renderCfg();
    });
  }
  bindSeg("cfg-n", "n", v => +v);
  bindSeg("cfg-teams", "teams", v => v === "1");
  bindSeg("cfg-target", "target", v => +v);
  function renderCfg() {
    const c = app.cfg;
    $("cfg-n").querySelectorAll("button").forEach(b => b.setAttribute("aria-pressed", +b.dataset.v === c.n));
    $("cfg-teams").querySelectorAll("button").forEach(b => b.setAttribute("aria-pressed", (b.dataset.v === "1") === c.teams));
    $("cfg-target").querySelectorAll("button").forEach(b => b.setAttribute("aria-pressed", +b.dataset.v === c.target));
    $("cfg-teams-row").hidden = c.n !== 4;
    $("cfg-hint").textContent = cfgText(c) + ".";
  }
  renderCfg();

  const params = new URLSearchParams(location.search);
  if (params.get("room")) { $("join-code").value = params.get("room").toUpperCase(); }

  $("create").onclick = () => hostCreate();
  $("join").onclick = () => clientJoin($("join-code").value.trim().toUpperCase());
  $("join-code").addEventListener("keydown", e => { if (e.key === "Enter") $("join").click(); });

  /* ================= HOST ================= */
  function hostCreate() {
    store.set("kozel-name", myName());
    app.role = "host"; app.seat = 0;
    const c = app.cfg;
    app.seats = Array(c.n).fill(null).map((_, i) => i === 0
      ? { name: myName(), kind: "host", token, online: true }
      : { name: "", kind: "empty", token: null, online: false });
    app.conns = Array(c.n).fill(null);
    app.code = makeCode();
    show("room");
    renderRoom();
    startHostPeer();
  }

  function startHostPeer(retry) {
    if (typeof Peer === "undefined") { setOffline("The online library didn't load. You can still play against bots."); return; }
    let peer;
    try { peer = new Peer(PREFIX + app.code); }
    catch (e) { setOffline("Online play isn't available here. You can still play against bots."); return; }
    app.peer = peer;
    peer.on("open", () => { app.online = true; $("room-warn").hidden = true; renderRoom(); });
    peer.on("connection", conn => {
      conn.on("data", msg => hostOnMessage(conn, msg));
      conn.on("close", () => hostOnClose(conn));
      conn.on("error", () => hostOnClose(conn));
    });
    peer.on("disconnected", () => { try { peer.reconnect(); } catch (e) {} });
    peer.on("error", err => {
      if (err && err.type === "unavailable-id" && !retry) {
        app.code = makeCode(); try { peer.destroy(); } catch (e) {}
        renderRoom(); startHostPeer(true); return;
      }
      if (!app.online) setOffline("Couldn't go online (" + (err && err.type || "network") + "). You can still play against bots.");
    });
  }
  function setOffline(msg) { app.online = false; $("room-warn").textContent = msg; $("room-warn").hidden = false; renderRoom(); }

  function lobbyInfo() {
    return { code: app.code, cfg: app.cfg, seats: app.seats.map(s => ({ name: s.name, kind: s.kind, online: s.online })), started: !!app.state };
  }
  function send(conn, msg) { try { if (conn && conn.open) conn.send(msg); } catch (e) {} }

  function hostOnMessage(conn, msg) {
    if (!msg || typeof msg !== "object") return;
    if (msg.t === "join") {
      const name = String(msg.name || "Player").slice(0, 16);
      let idx = app.seats.findIndex(s => s.token && s.token === msg.token);
      if (idx < 0) {
        if (app.state) { send(conn, { t: "reject", reason: "The game has already started." }); return; }
        idx = app.seats.findIndex(s => s.kind === "empty");
        if (idx < 0) { send(conn, { t: "reject", reason: "The room is full." }); return; }
      }
      const seat = app.seats[idx];
      if (seat.kind === "host") { send(conn, { t: "reject", reason: "You're already the host in another tab." }); return; }
      if (seat.kind !== "bot") { seat.kind = "remote"; seat.name = name; }
      seat.token = msg.token; seat.online = true;
      app.conns[idx] = conn; conn.seat = idx;
      send(conn, { t: "welcome", seat: idx });
      if (app.state) { app.state.players[idx].name = seat.name; }
      broadcastAll();
      return;
    }
    if (msg.t === "act" && typeof conn.seat === "number") {
      hostDispatch(conn.seat, msg.a);
    }
  }
  function hostOnClose(conn) {
    const idx = conn.seat;
    if (typeof idx !== "number" || app.conns[idx] !== conn) return;
    app.conns[idx] = null;
    const seat = app.seats[idx];
    seat.online = false;
    if (!app.state) { seat.kind = "empty"; seat.name = ""; seat.token = null; }
    broadcastAll();
  }

  function broadcastAll() {
    const lobby = lobbyInfo();
    app.lobby = lobby;
    app.conns.forEach((c, i) => {
      if (!c) return;
      send(c, { t: "lobby", lobby });
      if (app.state) send(c, { t: "view", view: E.viewFor(app.state, i) });
    });
    if (app.state) { app.view = E.viewFor(app.state, 0); show("game"); renderGame(); }
    else renderRoom();
  }

  function hostStart() {
    app.seats.forEach((s, i) => { if (s.kind === "empty") { s.kind = "bot"; s.name = "Bot " + (i + 1); s.online = true; } });
    newGame();
  }
  function newGame() {
    app.state = E.createGame({ players: app.seats.map(s => ({ name: s.name, bot: s.kind === "bot" })), teams: app.cfg.teams, target: app.cfg.target });
    app.selected.clear();
    tick();
  }

  function hostDispatch(seat, a) {
    const s = app.state;
    if (!s || !a) return;
    try {
      if (a.type === "next") {
        if (seat !== 0) return;
        if (s.phase === "dealEnd") E.startDeal(s);
        else if (s.phase === "gameOver") { newGame(); return; }
        else return;
      } else {
        E.apply(s, seat, a);
      }
    } catch (err) {
      if (seat === 0) toast(err.message); else send(app.conns[seat], { t: "error", msg: err.message });
      return;
    }
    tick();
  }

  function tick() {
    broadcastAll();
    const s = app.state;
    clearTimeout(app.botTimer); clearTimeout(app.dealTimer);
    if (s.phase === "picked") {
      app.dealTimer = setTimeout(() => { if (app.state === s && s.phase === "picked") { E.startDeal(s); tick(); } }, 3200);
      return;
    }
    const w = E.waitingOn(s);
    const botSeat = w.find(i => s.players[i].bot);
    if (botSeat !== undefined) {
      app.botTimer = setTimeout(() => {
        if (app.state !== s) return;
        const a = E.botAction(s, botSeat);
        if (a) { try { E.apply(s, botSeat, a); } catch (e) { console.warn("bot", e); } }
        tick();
      }, s.phase === "pick" ? 700 : 1000);
    }
  }

  /* ================= CLIENT ================= */
  function clientJoin(code) {
    if (!/^[A-Z]{5}$/.test(code)) { $("join-msg").textContent = "Enter the 5-letter code from the host."; return; }
    if (typeof Peer === "undefined") { $("join-msg").textContent = "The online library didn't load. Check your connection and reload."; return; }
    store.set("kozel-name", myName());
    app.role = "client"; app.code = code;
    $("join-msg").textContent = "Connecting…";
    let peer;
    try { peer = new Peer(); }
    catch (e) { $("join-msg").textContent = "Online play isn't available in this browser."; return; }
    app.peer = peer;
    const fail = setTimeout(() => {
      if (!app.hostConn || !app.hostConn.open) $("join-msg").textContent = "Couldn't reach room " + code + ". Check the code, and ask the host to keep their page open.";
    }, 12000);
    peer.on("open", () => {
      const conn = peer.connect(PREFIX + code, { reliable: true });
      app.hostConn = conn;
      conn.on("open", () => { clearTimeout(fail); conn.send({ t: "join", name: myName(), token }); });
      conn.on("data", clientOnMessage);
      conn.on("close", () => { toast("Disconnected from the host."); $("room-status").textContent = "Disconnected from the host."; });
    });
    peer.on("error", err => {
      if (err && err.type === "peer-unavailable") $("join-msg").textContent = "No room with code " + code + ". Check the code with the host.";
      else $("join-msg").textContent = "Connection problem (" + (err && err.type || "network") + ").";
    });
  }
  function clientOnMessage(msg) {
    if (!msg || typeof msg !== "object") return;
    if (msg.t === "welcome") { app.seat = msg.seat; $("join-msg").textContent = ""; history.replaceState(null, "", "?room=" + app.code); }
    else if (msg.t === "reject") { $("join-msg").textContent = msg.reason; show("home"); }
    else if (msg.t === "lobby") { app.lobby = msg.lobby; if (!msg.lobby.started) { show("room"); renderRoom(); } }
    else if (msg.t === "view") { app.view = msg.view; show("game"); renderGame(); }
    else if (msg.t === "error") toast(msg.msg);
  }

  /* ---------- actions from the UI ---------- */
  function act(a) {
    if (app.role === "host") hostDispatch(0, a);
    else send(app.hostConn, { t: "act", a });
  }

  /* ---------- room screen ---------- */
  function renderRoom() {
    const isHost = app.role === "host";
    const L = isHost ? lobbyInfo() : app.lobby;
    if (!L) return;
    $("room-code").textContent = L.code;
    $("room-link").textContent = inviteLink(L.code);
    $("room-cfg").textContent = cfgText(L.cfg) + ".";
    $("seats").innerHTML = L.seats.map((s, i) => {
      const team = L.cfg.n === 4 && L.cfg.teams ? (i % 2 === 0 ? "Team A" : "Team B") : "Seat " + (i + 1);
      const who = s.kind === "empty" ? `<span class="muted">Waiting for a player…</span>` : esc(s.name) + (i === app.seat ? " (you)" : "");
      const tag = s.kind === "host" ? "host" : s.kind === "bot" ? "bot" : s.kind === "remote" ? (s.online ? "joined" : "offline") : "";
      return `<div class="seat"><span><span class="tag">${team}</span> · ${who}</span><span class="tag">${tag}</span></div>`;
    }).join("");
    const empty = L.seats.filter(s => s.kind === "empty").length;
    $("start").hidden = !isHost;
    $("start").textContent = empty ? `Start with ${empty} bot${empty > 1 ? "s" : ""}` : "Start game";
    $("room-status").textContent = isHost
      ? (app.online ? "Share the code. Partners sit opposite: seats 1 & 3, seats 2 & 4." : "")
      : "Waiting for the host to start…";
    if (!(L.cfg.n === 4 && L.cfg.teams) && isHost) $("room-status").textContent = app.online ? "Share the code or the link with your friends." : "";
  }
  $("start").onclick = () => hostStart();
  $("copy-link").onclick = () => {
    const link = $("room-link").textContent;
    try { navigator.clipboard.writeText(link).then(() => toast("Invite link copied"), () => toast("Copy the link below")); }
    catch (e) { toast("Copy the link below"); }
  };
  function leave() { try { app.peer && app.peer.destroy(); } catch (e) {} location.href = location.pathname; }
  $("leave").onclick = leave;
  $("g-leave").onclick = () => {
    if ($("g-leave").dataset.confirm) leave();
    else { $("g-leave").dataset.confirm = "1"; $("g-leave").textContent = "Tap again to leave"; setTimeout(() => { delete $("g-leave").dataset.confirm; $("g-leave").textContent = "Leave game"; }, 3000); }
  };

  /* ---------- game screen ---------- */
  function nameOf(i) { return app.view.players[i].name + (i === app.view.me ? " (you)" : ""); }
  function sideCls(side) { return side === 0 ? "side-a" : side === 1 ? "side-b" : ""; }

  function renderGame() {
    const v = app.view;
    if (!v) return;
    const me = v.me;
    // keep only selected cards still in hand
    const hand = v.hand || [];
    app.selected.forEach(c => { if (!hand.includes(c)) app.selected.delete(c); });

    // top bar
    $("g-deal").textContent = v.dealNo || "–";
    $("g-trump").textContent = v.trump || "?";
    $("g-trump").className = "v trumpv" + (v.trump && RED(v.trump) ? " red" : "");
    $("g-stock").innerHTML = v.dealNo
      ? `<span class="mono">${v.stockCount}</span>` + (v.faceUp ? cardHTML(v.faceUp, "xs") + `<span class="muted" style="font-size:.7rem">face up</span>` : "") +
        (v.hiddenInStock ? cardHTML("back", "xs") + `<span class="muted" style="font-size:.7rem">hidden</span>` : v.hiddenCard ? `<span class="muted" style="font-size:.75rem">hidden was ${v.hiddenCard}</span>` : "")
      : "–";
    $("g-scores").innerHTML = v.sideNames.map((nm, i) => {
      const mine = (v.teams ? me % 2 : me) === i;
      const pct = v.target === 1 ? Math.min(100, v.sideBad[i] / 6 * 100) : Math.min(100, v.sideBad[i] / v.target * 100);
      const short = v.teams ? "Team " + (i === 0 ? "A" : "B") : v.players[i].name;
      return `<div class="chip score ${mine ? "mine" : ""}"><span class="k">${esc(short)}${mine ? " · you" : ""}</span>
        <span class="v mono">${v.sideBad[i]}${v.target > 1 ? ` <span class="muted" style="font-size:.8rem">/ ${v.target}</span>` : ""}</span>
        <span class="bar"><i style="width:${pct}%"></i></span></div>`;
    }).join("") + (v.eggs ? `<div class="chip"><span class="k">Eggs</span><span class="v">×2 next</span></div>` : "");

    // opponents
    const waiting = v.phase === "pick" ? v.pick.current : v.turn ? (v.phase === "lead" ? v.turn.leader : v.turn.toAct) : -1;
    const order = [...Array(v.n).keys()].map(k => (me + 1 + k) % v.n).filter(i => i !== me);
    $("g-opps").innerHTML = order.map(i => {
      const p = v.players[i];
      const partner = v.teams && i % 2 === me % 2;
      const team = v.teams ? `<span class="${sideCls(p.side)}" style="font-size:.75rem">${partner ? "partner" : "Team " + (p.side === 0 ? "A" : "B")}</span>` : "";
      return `<div class="opp ${waiting === i ? "turn" : ""}"><div class="nm"><span>${esc(p.name)}${p.bot ? ' <span class="muted" style="font-size:.75rem">bot</span>' : ""}</span>${team}</div>
        <div class="backs">${Array(p.count).fill(cardHTML("back", "xs")).join("") || '<span class="muted" style="font-size:.8rem">no cards</span>'}</div></div>`;
    }).join("");

    renderTable(v);
    renderControls(v);

    $("g-log").innerHTML = v.log.slice().reverse().map(l => `<div>${esc(l)}</div>`).join("");
    renderOverlay(v);
  }

  function renderTable(v) {
    const t = v.turn;
    let html = "";
    if (t && t.plays.length) {
      html += `<div class="head"><span>${t.fourTrumps ? "Four trumps! " : ""}Led by ${esc(nameOf(t.leader))}</span><span>Beat each card, or throw face down</span></div>`;
      html += t.plays.map(pl => {
        const label = pl.kind === "lead" ? "led" : pl.kind === "beat" ? "beats" : "face down";
        return `<div class="play ${t.winning === pl.p ? "win" : ""}"><div class="who">${esc(nameOf(pl.p))}<small>${label}</small></div>
          <div class="cards">${pl.cards.map(c => cardHTML(c, "sm")).join("")}</div></div>`;
      }).join("");
    } else if (v.lastTurn && v.dealNo) {
      const lt = v.lastTurn;
      html += `<div class="empty-table"><span>${esc(nameOf(lt.winner))} took the last turn (${lt.points} pts).</span>
        <div class="row">${lt.plays.flatMap(p => p.cards).map(c => cardHTML(c, "xs")).join("")}</div></div>`;
    } else {
      html += `<div class="empty-table"><span>The table is empty.</span></div>`;
    }
    $("g-table").innerHTML = html;
  }

  function winningCards(v) {
    const t = v.turn; if (!t) return [];
    for (let i = t.plays.length - 1; i >= 0; i--) if (t.plays[i].p === t.winning) return t.plays[i].cards;
    return [];
  }

  function renderControls(v) {
    const me = v.me, hand = v.hand || [], t = v.turn;
    const sel = [...app.selected];
    let status = "", mine = false, buttons = [];
    if (["lead", "answer"].includes(v.phase) && t) {
      if (v.phase === "lead" && t.leader === me) {
        mine = true;
        status = "Your lead: pick 1–4 cards of one suit.";
        const err = sel.length ? E.validLead(null, sel) : "Select cards";
        buttons.push(`<button type="button" class="btn" data-act="lead" ${err ? "disabled" : ""}>Lead ${sel.length || ""} card${sel.length === 1 ? "" : "s"}</button>`);
        if (sel.length && err) status += " " + err + ".";
      } else if (v.phase === "answer" && t.toAct === me) {
        mine = true;
        const k = t.plays[0].cards.length;
        const partnerWins = v.teams && t.winning % 2 === me % 2;
        status = `Your answer: pick ${k} card${k > 1 ? "s" : ""}. Beat every winning card, or throw face down.`;
        if (partnerWins) status = `Your partner is winning. Throw ${k} card${k > 1 ? "s" : ""} face down (high points help your team), or beat anyway.`;
        const canBeat = sel.length === k && E.findAssignment(sel, winningCards(v), v.trump);
        buttons.push(`<button type="button" class="btn" data-act="beat" ${canBeat ? "" : "disabled"}>Beat</button>`);
        buttons.push(`<button type="button" class="btn ghost" data-act="throw" ${sel.length === k ? "" : "disabled"}>Throw ${k} face down</button>`);
        if (sel.length === k && !canBeat) status += " These cards can't beat all of them.";
      } else {
        const w = v.phase === "lead" ? t.leader : t.toAct;
        status = `Waiting for ${esc(v.players[w].name)}…`;
      }
      if (v.canFour) buttons.unshift(`<button type="button" class="btn gold" data-act="four">Play 4 trumps!</button>`);
    } else if (v.phase === "pick" || v.phase === "picked") {
      status = "Deciding who goes first…";
    } else if (v.phase === "dealEnd") status = "Deal over.";
    else if (v.phase === "gameOver") status = "Game over.";
    $("g-status").innerHTML = status;
    $("g-status").className = "status" + (mine ? " mine" : "");
    $("g-actions").innerHTML = buttons.join("");
    $("g-hand").className = "hand" + (mine || v.canFour ? "" : " off");
    $("g-hand").innerHTML = hand.map(c => cardHTML(c, "", app.selected.has(c) ? "sel" : "")).join("") ||
      `<span class="muted">No cards in hand.</span>`;
  }

  $("g-hand").addEventListener("click", e => {
    const el = e.target.closest("[data-card]"); if (!el) return;
    const c = el.dataset.card;
    if (app.selected.has(c)) app.selected.delete(c); else app.selected.add(c);
    renderControls(app.view);
  });
  $("g-actions").addEventListener("click", e => {
    const b = e.target.closest("[data-act]"); if (!b || b.disabled) return;
    const type = b.dataset.act;
    if (type === "four") act({ type: "four" });
    else act({ type, cards: [...app.selected] });
    app.selected.clear();
  });

  /* ---------- overlays ---------- */
  function optLabel(o) {
    if (o === "red") return `<span style="color:var(--red)">Red</span> ♥♦`;
    if (o === "black") return "Black ♠♣";
    return o;
  }
  function renderOverlay(v) {
    const ov = $("overlay"), m = $("modal");
    let html = null;
    const isHost = app.role === "host";
    if (v.phase === "pick" || v.phase === "picked") {
      const pk = v.pick;
      const what = pk.kind === "color" ? "colour" : "suit";
      const made = Object.keys(pk.choices).map(k => `<div>${esc(nameOf(+k))}: <strong>${pk.choices[k].map(optLabel).join(", ")}</strong></div>`).join("");
      html = `<span class="eyebrow">Who goes first</span><h2>Pick a ${what}</h2>
        <p class="muted">A random card is turned. Whoever picked its ${what} starts the game.${v.teams ? " One player picks for each team." : ""}</p>
        <div class="log" style="color:var(--ink)">${made || ""}</div>`;
      if (v.phase === "pick") {
        if (pk.current === v.me) {
          html += `<div class="opts">${pk.remaining.map(o => `<button type="button" class="opt ${o === "red" || RED(o) ? "red" : ""} ${o.length > 1 ? "wide" : ""}" data-pick="${o}">${optLabel(o)}</button>`).join("")}</div>`;
        } else html += `<p>Waiting for ${esc(v.players[pk.current].name)} to pick…</p>`;
      } else {
        html += `<div class="row">${cardHTML(pk.card)}<div><strong>${esc(nameOf(pk.winner))}</strong> goes first.<br><span class="muted">Dealing…</span></div></div>`;
      }
    } else if (v.phase === "dealEnd" || v.phase === "gameOver") {
      const r = v.lastResult;
      const rows = v.sideNames.map((nm, i) => `<tr><td>${esc(nm)}</td><td class="n">${r.points[i]}</td><td class="n ${r.bad[i] ? "bad" : ""}">${r.bad[i] ? "+" + r.bad[i] : "0"}</td><td class="n">${r.totals[i]}</td></tr>`).join("");
      html = `<span class="eyebrow">Deal ${r.deal} result</span>`;
      if (v.phase === "gameOver") {
        const g = v.goat || [];
        html += g.length ? `<div class="goat">Козёл!</div><h2>${g.map(i => esc(v.sideNames[i])).join(" & ")} ${g.length > 1 || v.teams ? "are" : "is"} the goat.</h2>`
                         : `<h2>No goat this time.</h2>`;
      } else html += `<h2>Deal over</h2>`;
      if (r.eggs) html += `<p class="warn">60 : 60, eggs! Nobody gets bad points. Next deal counts double.</p>`;
      if (r.doubled) html += `<p class="warn">This deal counted double because of eggs.</p>`;
      html += `<div style="overflow-x:auto"><table class="res"><thead><tr><th>Player</th><th style="text-align:right">Card pts</th><th style="text-align:right">Bad</th><th style="text-align:right">Total bad</th></tr></thead><tbody>${rows}</tbody></table></div>`;
      if (v.target > 1 && v.phase === "dealEnd") html += `<p class="muted">First to ${v.target} bad points is the goat.</p>`;
      html += isHost
        ? `<div class="row"><button type="button" class="btn" data-next="1">${v.phase === "gameOver" ? "Play again" : "Next deal"}</button>${v.phase === "gameOver" ? `<button type="button" class="btn ghost" data-leave="1">Leave</button>` : ""}</div>`
        : `<p class="muted">Waiting for the host to ${v.phase === "gameOver" ? "start a new game" : "deal"}…</p>`;
    }
    if (html === null) { ov.hidden = true; return; }
    m.innerHTML = html; ov.hidden = false;
  }
  $("modal").addEventListener("click", e => {
    const p = e.target.closest("[data-pick]"); if (p) { act({ type: "pick", option: p.dataset.pick }); return; }
    if (e.target.closest("[data-next]")) { act({ type: "next" }); return; }
    if (e.target.closest("[data-leave]")) leave();
  });

  window.addEventListener("beforeunload", e => {
    if (app.role === "host" && app.state && app.state.phase !== "gameOver") { e.preventDefault(); e.returnValue = ""; }
  });

  // test hook
  window.__kozel = app;
})();
