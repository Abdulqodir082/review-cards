/* Kozel (Козёл) game engine. Pure state machine, no DOM.
 * Works in the browser (window.KozelEngine) and in Node (module.exports). */
(function (root) {
  "use strict";

  const SUITS = ["♠", "♥", "♦", "♣"];
  const RED = ["♥", "♦"];
  const RANKS = ["6", "7", "8", "9", "J", "Q", "K", "10", "A"]; // low → high
  const POINTS = { A: 11, "10": 10, K: 4, Q: 3, J: 2 };
  const HAND = 4;

  const rankOf = c => c.slice(0, -1);
  const suitOf = c => c.slice(-1);
  const power = c => RANKS.indexOf(rankOf(c));
  const pts = c => POINTS[rankOf(c)] || 0;
  const sum = cards => cards.reduce((a, c) => a + pts(c), 0);
  const colorOf = c => (RED.includes(suitOf(c)) ? "red" : "black");

  function newDeck() {
    const d = [];
    for (const s of SUITS) for (const r of RANKS) d.push(r + s);
    return d;
  }
  function shuffle(a, rng) {
    rng = rng || Math.random;
    for (let i = a.length - 1; i > 0; i--) {
      const j = Math.floor(rng() * (i + 1));
      [a[i], a[j]] = [a[j], a[i]];
    }
    return a;
  }

  /** Does card a beat target t, given the trump suit? */
  function beats(a, t, trump) {
    if (suitOf(a) === suitOf(t)) return power(a) > power(t);
    return suitOf(a) === trump;
  }

  function permutations(arr) {
    if (arr.length <= 1) return [arr.slice()];
    const out = [];
    arr.forEach((x, i) => {
      const rest = arr.slice(0, i).concat(arr.slice(i + 1));
      for (const p of permutations(rest)) out.push([x].concat(p));
    });
    return out;
  }

  /** Order `cards` so cards[i] beats targets[i]; null if impossible. */
  function findAssignment(cards, targets, trump) {
    if (cards.length !== targets.length) return null;
    for (const p of permutations(cards)) {
      if (p.every((c, i) => beats(c, targets[i], trump))) return p;
    }
    return null;
  }

  function combos(arr, k) {
    if (k === 0) return [[]];
    if (arr.length < k) return [];
    const [h, ...t] = arr;
    return combos(t, k - 1).map(c => [h].concat(c)).concat(combos(t, k));
  }

  /* ---------- state ---------- */

  /**
   * @param {object} cfg
   *   players: [{ name, bot }]  (2–4)
   *   teams: boolean (only for 4 players)
   *   target: 1 (one deal) | 6 | 12
   */
  function createGame(cfg) {
    const n = cfg.players.length;
    if (n < 2 || n > 4) throw new Error("2 to 4 players");
    const teams = n === 4 && !!cfg.teams;
    const sides = teams ? 2 : n;
    const s = {
      n, teams, sides,
      target: cfg.target || 12,
      players: cfg.players.map((p, i) => ({ name: p.name, bot: !!p.bot, hand: [] })),
      sideBad: Array(sides).fill(0),
      dealNo: 0,
      eggs: false,
      phase: "pick",
      pick: makePick(n, teams),
      log: [],
      results: [],
      firstLeader: null,
      lastWinner: null,
      goat: null
    };
    addLog(s, "New game. Pick a " + (s.pick.kind === "color" ? "colour" : "suit") + " to decide who goes first.");
    return s;
  }

  function sideOf(s, p) { return s.teams ? p % 2 : p; }
  function sideName(s, side) {
    if (s.teams) return "Team " + (side === 0 ? "A" : "B") + " (" + s.players[side].name + " & " + s.players[side + 2].name + ")";
    return s.players[side].name;
  }
  function next(s, p) { return (p + 1) % s.n; }
  function addLog(s, msg) { s.log.push(msg); if (s.log.length > 60) s.log.shift(); }

  function makePick(n, teams) {
    if (n === 2) return { kind: "color", options: ["red", "black"], pickers: [0, 1], choices: {}, idx: 0 };
    if (teams) return { kind: "color", options: ["red", "black"], pickers: [0, 1], choices: {}, idx: 0 };
    return { kind: "suit", options: SUITS.slice(), pickers: [...Array(n).keys()], choices: {}, idx: 0 };
  }

  function remainingOptions(pk) {
    const used = Object.values(pk.choices).flat();
    return pk.options.filter(o => !used.includes(o));
  }

  function pickChoice(s, p, option, rng) {
    if (s.phase !== "pick") throw new Error("Not picking now");
    const pk = s.pick;
    if (pk.pickers[pk.idx] !== p) throw new Error("Not your pick");
    if (!remainingOptions(pk).includes(option)) throw new Error("Already taken");
    pk.choices[p] = [option];
    addLog(s, s.players[p].name + " picks " + labelOption(option) + (s.teams ? " for their team" : "") + ".");
    pk.idx++;
    if (pk.idx === pk.pickers.length - 1) {
      const last = pk.pickers[pk.idx];
      pk.choices[last] = remainingOptions(pk);
      addLog(s, s.players[last].name + " gets " + pk.choices[last].map(labelOption).join(" and ") + ".");
      pk.idx++;
      const card = shuffle(newDeck(), rng)[0];
      const key = pk.kind === "color" ? colorOf(card) : suitOf(card);
      const winner = +Object.keys(pk.choices).find(k => pk.choices[k].includes(key));
      pk.card = card;
      pk.winner = winner;
      s.firstLeader = winner;
      s.phase = "picked";
      addLog(s, "The card is " + card + ". " + s.players[winner].name + " goes first.");
    }
    return s;
  }
  function labelOption(o) { return o === "red" ? "red" : o === "black" ? "black" : o; }

  function startDeal(s, rng) {
    if (!["picked", "dealEnd"].includes(s.phase)) throw new Error("Can't deal now");
    s.dealNo++;
    const deck = shuffle(newDeck(), rng);
    s.players.forEach(p => { p.hand = []; });
    for (let r = 0; r < HAND; r++) {
      for (let k = 0; k < s.n; k++) s.players[(s.firstLeader + k) % s.n].hand.push(deck.pop());
    }
    s.faceUp = deck.pop();
    s.hidden = deck.pop();
    s.stock = deck.concat([s.faceUp, s.hidden]); // drawn from the front; specials last
    s.hiddenRevealed = false;
    s.trump = suitOf(s.faceUp);
    s.piles = Array(s.sides).fill(null).map(() => []);
    s.took = Array(s.sides).fill(false);
    s.lastWinner = null;
    s.phase = "lead";
    s.turn = newTurn(s.firstLeader);
    addLog(s, "Deal " + s.dealNo + ". Face-up card " + s.faceUp + ": " + suitName(s.trump) + " are trump.");
    return s;
  }
  function newTurn(leader) { return { leader, plays: [], winning: null, toAct: leader, fourTrumps: false }; }
  function suitName(x) { return { "♠": "spades", "♥": "hearts", "♦": "diamonds", "♣": "clubs" }[x]; }

  function takeFromHand(hand, cards) {
    const copy = hand.slice();
    for (const c of cards) {
      const i = copy.indexOf(c);
      if (i < 0) throw new Error("You don't have " + c);
      copy.splice(i, 1);
    }
    if (new Set(cards).size !== cards.length) throw new Error("Duplicate card");
    return copy;
  }

  function validLead(s, cards) {
    if (!cards.length || cards.length > HAND) return "Lead 1 to 4 cards";
    if (!cards.every(c => suitOf(c) === suitOf(cards[0]))) return "All cards must be the same suit";
    return null;
  }

  function lead(s, p, cards) {
    if (s.phase !== "lead") throw new Error("Not time to lead");
    if (s.turn.leader !== p) throw new Error("Not your lead");
    const err = validLead(s, cards);
    if (err) throw new Error(err);
    s.players[p].hand = takeFromHand(s.players[p].hand, cards);
    s.turn.plays.push({ p, kind: "lead", cards: cards.slice() });
    s.turn.winning = { p, cards: cards.slice() };
    s.turn.toAct = next(s, p);
    s.phase = "answer";
    addLog(s, s.players[p].name + " leads " + cards.join(" "));
    return s;
  }

  function answer(s, p, cards, kind) {
    if (s.phase !== "answer") throw new Error("Not time to answer");
    if (s.turn.toAct !== p) throw new Error("Not your turn");
    const need = s.turn.plays[0].cards.length;
    if (cards.length !== need) throw new Error("Play exactly " + need + " card" + (need > 1 ? "s" : ""));
    const hand = takeFromHand(s.players[p].hand, cards);
    if (kind === "beat") {
      const ordered = findAssignment(cards, s.turn.winning.cards, s.trump);
      if (!ordered) throw new Error("These cards don't beat every card on the table");
      s.turn.plays.push({ p, kind: "beat", cards: ordered });
      s.turn.winning = { p, cards: ordered };
      addLog(s, s.players[p].name + " beats with " + ordered.join(" "));
    } else if (kind === "throw") {
      s.turn.plays.push({ p, kind: "throw", cards: cards.slice() });
      addLog(s, s.players[p].name + " throws " + need + " face down");
    } else throw new Error("Unknown answer");
    s.players[p].hand = hand;
    s.turn.toAct = next(s, p);
    if (s.turn.toAct === s.turn.leader) resolveTurn(s);
    return s;
  }

  function canFourTrumps(s, p) {
    if (!["lead", "answer"].includes(s.phase)) return false;
    const h = s.players[p].hand;
    if (h.length !== HAND || !h.every(c => suitOf(c) === s.trump)) return false;
    if (s.turn.plays.some(pl => pl.p === p)) return false;
    if (s.turn.fourTrumps) return false;
    return true;
  }

  function fourTrumps(s, p) {
    if (!canFourTrumps(s, p)) throw new Error("You can't play four trumps now");
    for (const pl of s.turn.plays) s.players[pl.p].hand.push(...pl.cards);
    const cards = s.players[p].hand.slice();
    s.turn = newTurn(p);
    s.turn.fourTrumps = true;
    s.players[p].hand = [];
    s.turn.plays.push({ p, kind: "lead", cards });
    s.turn.winning = { p, cards };
    s.turn.toAct = next(s, p);
    s.phase = "answer";
    addLog(s, s.players[p].name + " plays FOUR TRUMPS: " + cards.join(" ") + ". Cards on the table go back.");
    return s;
  }

  function resolveTurn(s) {
    const w = s.turn.winning.p, side = sideOf(s, w);
    const all = s.turn.plays.flatMap(pl => pl.cards);
    s.piles[side].push(...all);
    s.took[side] = true;
    s.lastWinner = w;
    s.lastTurn = { plays: s.turn.plays, winner: w, points: sum(all) };
    addLog(s, s.players[w].name + " takes " + all.length + " cards (" + sum(all) + " pts)");
    // draw back up to 4: winner first, then clockwise
    if (s.stock.length) {
      const need = HAND - s.players[w].hand.length;
      const per = Math.min(need, Math.floor(s.stock.length / s.n));
      for (let k = 0; k < s.n; k++) {
        const pi = (w + k) % s.n;
        for (let j = 0; j < per; j++) {
          const c = s.stock.shift();
          s.players[pi].hand.push(c);
          if (s.stock.length === 0 && c === s.hidden) {
            s.hiddenRevealed = true;
            const old = s.trump;
            s.trump = suitOf(c);
            addLog(s, s.players[pi].name + " draws the hidden card: " + c + ". " +
              (old === s.trump ? "Trump stays " + suitName(old) + "." : "Trump changes to " + suitName(s.trump) + "!"));
          }
        }
      }
    }
    if (s.players.every(p => p.hand.length === 0)) return endDeal(s);
    s.phase = "lead";
    s.turn = newTurn(w);
  }

  function thresholds(sides) {
    if (sides === 2) return { safe: 61, fourMax: 30 };
    if (sides === 3) return { safe: 40, fourMax: 19 };
    return { safe: 30, fourMax: 14 };
  }

  function endDeal(s) {
    s.turn = null;
    const points = s.piles.map(sum);
    const th = thresholds(s.sides);
    const isEggs = s.sides === 2 && points[0] === 60 && points[1] === 60;
    const mult = s.eggs ? 2 : 1;
    let bad = Array(s.sides).fill(0);
    if (!isEggs) {
      bad = points.map((pt, i) => {
        if (!s.took[i]) return 6 * mult;
        if (pt >= th.safe) return 0;
        if (pt <= th.fourMax) return 4 * mult;
        return 2 * mult;
      });
      s.eggs = false;
    } else {
      s.eggs = true;
    }
    bad.forEach((b, i) => { s.sideBad[i] += b; });
    const res = { deal: s.dealNo, points, bad, eggs: isEggs, doubled: mult === 2 && !isEggs, totals: s.sideBad.slice() };
    s.results.push(res);
    s.lastResult = res;
    s.firstLeader = s.lastWinner;
    addLog(s, "Deal " + s.dealNo + " over: " + points.map((p, i) => sideName(s, i) + " " + p).join(", ") +
      (isEggs ? ". Eggs! Next deal counts double." : ""));

    let over = false, goats = [];
    if (s.target === 1) {
      over = true;
      const max = Math.max(...s.sideBad);
      goats = max > 0 ? s.sideBad.map((b, i) => (b === max ? i : -1)).filter(i => i >= 0) : [];
    } else if (s.sideBad.some(b => b >= s.target)) {
      over = true;
      const max = Math.max(...s.sideBad);
      goats = s.sideBad.map((b, i) => (b === max ? i : -1)).filter(i => i >= 0);
    }
    if (over) {
      s.phase = "gameOver";
      s.goat = goats;
      addLog(s, goats.length ? goats.map(g => sideName(s, g)).join(" & ") + (goats.length > 1 || s.teams ? " are" : " is") + " the goat!" : "No goat this time.");
    } else {
      s.phase = "dealEnd";
    }
    return s;
  }

  /* ---------- views (hide secret info per player) ---------- */
  function viewFor(s, me) {
    const v = {
      me, n: s.n, teams: s.teams, sides: s.sides, target: s.target, phase: s.phase,
      dealNo: s.dealNo, eggs: s.eggs, sideBad: s.sideBad.slice(), log: s.log.slice(-14),
      players: s.players.map((p, i) => ({ name: p.name, bot: p.bot, count: p.hand.length, side: sideOf(s, i) })),
      sideNames: [...Array(s.sides).keys()].map(i => sideName(s, i)),
      pick: s.pick && { kind: s.pick.kind, options: s.pick.options, remaining: remainingOptions(s.pick), choices: s.pick.choices,
        current: s.pick.pickers[s.pick.idx], card: s.pick.card || null, winner: s.pick.winner },
      results: s.results, lastResult: s.lastResult || null, goat: s.goat
    };
    if (s.dealNo > 0) {
      v.hand = sortHand(s.players[me].hand.slice(), s.trump);
      v.trump = s.trump;
      v.stockCount = s.stock.length;
      v.faceUp = s.stock.length >= 2 ? s.faceUp : null;
      v.hiddenInStock = s.stock.length >= 1;
      v.hiddenCard = s.hiddenRevealed ? s.hidden : null;
      v.firstFaceUp = s.faceUp;
      v.pileCounts = s.piles.map(p => p.length);
      v.mySide = sideOf(s, me);
      const hide = pl => ({ p: pl.p, kind: pl.kind, cards: pl.kind === "throw" && pl.p !== me ? pl.cards.map(() => "back") : pl.cards });
      v.turn = s.turn && { leader: s.turn.leader, toAct: s.turn.toAct, fourTrumps: s.turn.fourTrumps,
        winning: s.turn.winning && s.turn.winning.p, plays: s.turn.plays.map(hide) };
      v.lastTurn = s.lastTurn && { winner: s.lastTurn.winner, points: s.lastTurn.points, plays: s.lastTurn.plays.map(hide) };
      v.canFour = canFourTrumps(s, me);
      if (["dealEnd", "gameOver"].includes(s.phase)) v.piles = s.piles.map(sum);
    }
    return v;
  }

  function sortHand(h, trump) {
    const order = c => (suitOf(c) === trump ? 100 : SUITS.indexOf(suitOf(c)) * 10) + power(c);
    return h.sort((a, b) => order(a) - order(b));
  }

  /* ---------- simple bot ---------- */
  function cost(c, trump) { return (suitOf(c) === trump ? 30 : 0) + power(c) + pts(c); }

  function botAction(s, p) {
    if (s.phase === "pick" && s.pick.pickers[s.pick.idx] === p) {
      const r = remainingOptions(s.pick);
      return { type: "pick", option: r[Math.floor(Math.random() * r.length)] };
    }
    if (canFourTrumps(s, p) && s.phase === "answer") return { type: "four" };
    const hand = s.players[p].hand, trump = s.trump;
    if (s.phase === "lead" && s.turn.leader === p) {
      if (canFourTrumps(s, p)) return { type: "four" };
      const plain = hand.filter(c => suitOf(c) !== trump);
      const pool = plain.length ? plain : hand;
      // lead the cheapest card; sometimes a pair of zero-point cards of one suit
      const sorted = pool.slice().sort((a, b) => cost(a, trump) - cost(b, trump));
      const c = sorted[0];
      const mates = sorted.filter(x => x !== c && suitOf(x) === suitOf(c) && pts(x) === 0 && pts(c) === 0);
      return { type: "lead", cards: mates.length && Math.random() < 0.4 ? [c, mates[0]] : [c] };
    }
    if (s.phase === "answer" && s.turn.toAct === p) {
      const k = s.turn.plays[0].cards.length;
      const tablePts = s.turn.plays.reduce((a, pl) => a + sum(pl.cards), 0);
      const partnerWinning = s.teams && sideOf(s, s.turn.winning.p) === sideOf(s, p);
      if (partnerWinning) {
        const give = hand.slice().sort((a, b) => (suitOf(a) === trump) - (suitOf(b) === trump) || pts(b) - pts(a)).slice(0, k);
        return { type: "throw", cards: give };
      }
      let best = null, bestCost = Infinity;
      for (const combo of combos(hand, k)) {
        if (!findAssignment(combo, s.turn.winning.cards, trump)) continue;
        const cst = combo.reduce((a, c) => a + cost(c, trump), 0);
        if (cst < bestCost) { best = combo; bestCost = cst; }
      }
      const usesTrump = best && best.some(c => suitOf(c) === trump);
      if (best && (!usesTrump || tablePts >= 10 || s.stock.length === 0)) return { type: "beat", cards: best };
      const dump = hand.slice().sort((a, b) => cost(a, trump) - cost(b, trump)).slice(0, k);
      return { type: "throw", cards: dump };
    }
    return null;
  }

  /** Apply an action object from player p. Throws on invalid moves. */
  function apply(s, p, a, rng) {
    switch (a.type) {
      case "pick": return pickChoice(s, p, a.option, rng);
      case "lead": return lead(s, p, a.cards);
      case "beat": return answer(s, p, a.cards, "beat");
      case "throw": return answer(s, p, a.cards, "throw");
      case "four": return fourTrumps(s, p);
      default: throw new Error("Unknown action");
    }
  }

  /** Whose input is the game waiting for? (array of player indexes) */
  function waitingOn(s) {
    if (s.phase === "pick") return [s.pick.pickers[s.pick.idx]];
    if (s.phase === "lead") return [s.turn.leader];
    if (s.phase === "answer") return [s.turn.toAct];
    return [];
  }

  const api = {
    SUITS, RANKS, POINTS, HAND, rankOf, suitOf, power, pts, sum, beats, findAssignment, combos,
    newDeck, shuffle, createGame, startDeal, apply, viewFor, botAction, waitingOn, canFourTrumps,
    validLead, sideOf, thresholds, suitName, endDeal
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.KozelEngine = api;
})(typeof window !== "undefined" ? window : globalThis);
