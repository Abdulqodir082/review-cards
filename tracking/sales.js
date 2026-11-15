/* Shared sales + review maths for dashboard.html, partner.html and report.html.
 * Plain script (no modules) so it works on GitHub Pages without a build step. */
var OtvizSales = (function () {
  var PRODUCTS = {
    stand:   { cards: 1, price: 25,  uz: 'Stend',            ru: 'Стенд',            en: 'Stand' },
    sticker: { cards: 1, price: 25,  uz: 'Stiker',           ru: 'Стикер',           en: 'Sticker' },
    both:    { cards: 2, price: 40,  uz: 'Stend + stiker',   ru: 'Стенд + стикер',   en: 'Stand + sticker' },
    extra:   { cards: 1, price: 12,  uz: 'Qoʻshimcha karta', ru: 'Доп. карта',   en: 'Extra card' },
    pack6:   { cards: 6, price: 100, uz: '6 ta stend',       ru: '6 стендов',        en: 'Table pack (6)' }
  };
  var DEFAULT_FEE_CARD = 5, DEFAULT_FEE_PACK = 20;

  function num(v, fallback) { var n = Number(v); return (v === '' || v == null || isNaN(n)) ? fallback : n; }
  function isPaid(b) { var p = String(b && b.plan || '').toLowerCase(); return p === 'paid' || p === 'active'; }
  function cardsOf(b) { return num(b.cards, (PRODUCTS[b.product] || {}).cards || 1); }
  function priceOf(b) {
    var base = (PRODUCTS[b.product] || {}).price || 0;
    if (b.product === 'extra') base = base * cardsOf(b);   // extra cards are priced per card
    return num(b.price_usd, base);
  }
  function productLabel(b, lang) { var p = PRODUCTS[b.product]; return p ? (p[lang] || p.en) : '—'; }

  /* What a partner earns on one sale. Only paid sales earn a fee. */
  function feeOf(b, partner) {
    if (!b.partner || !partner || !isPaid(b)) return 0;
    if (b.product === 'pack6') return num(partner.fee_pack, DEFAULT_FEE_PACK);
    return num(partner.fee_card, DEFAULT_FEE_CARD) * cardsOf(b);
  }

  /* Review numbers for one card: first snapshot = before, latest = now. */
  function stats(history, cardId) {
    var snaps = (history || []).filter(function (r) { return r.card_id === cardId && typeof r.review_count === 'number'; })
      .sort(function (a, b) { return a.date < b.date ? -1 : a.date > b.date ? 1 : 0; });
    if (!snaps.length) return { snaps: [], before: null, after: null, growth: 0, rating: null, firstDate: null, lastDate: null };
    var first = snaps[0], last = snaps[snaps.length - 1], rating = null;
    for (var i = snaps.length - 1; i >= 0; i--) { if (typeof snaps[i].rating === 'number') { rating = snaps[i].rating; break; } }
    return { snaps: snaps, before: first.review_count, after: last.review_count, growth: last.review_count - first.review_count,
             rating: rating, firstDate: first.date, lastDate: last.date };
  }

  /* Totals for the owner dashboard, plus a per-partner breakdown. */
  function summary(businesses, partners) {
    var byCode = {};
    (partners || []).forEach(function (p) { byCode[p.code] = { partner: p, clients: 0, trials: 0, cards: 0, earned: 0 }; });
    var out = { cards: 0, clients: 0, trials: 0, revenue: 0, fees: 0, byPartner: byCode };
    (businesses || []).forEach(function (b) {
      var slot = b.partner ? byCode[b.partner] : null;
      if (!isPaid(b)) { if (String(b.plan || '').toLowerCase() === 'trial') { out.trials++; if (slot) slot.trials++; } return; }
      var fee = feeOf(b, slot && slot.partner);
      out.cards += cardsOf(b); out.clients++; out.revenue += priceOf(b); out.fees += fee;
      if (slot) { slot.clients++; slot.cards += cardsOf(b); slot.earned += fee; }
    });
    Object.keys(byCode).forEach(function (k) { var s = byCode[k]; s.paid = num(s.partner.paid_usd, 0); s.owed = Math.max(0, s.earned - s.paid); });
    out.owed = Object.keys(byCode).reduce(function (a, k) { return a + byCode[k].owed; }, 0);
    return out;
  }

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }

  async function loadAll() {
    var bust = '?t=' + Date.now();
    async function get(url, fallback) {
      try { var r = await fetch(url + bust, { cache: 'no-store' }); return r.ok ? await r.json() : fallback; } catch (e) { return fallback; }
    }
    var res = await Promise.all([get('tracking-history.json', []), get('tracking/businesses.json', {}), get('tracking/partners.json', {})]);
    return { history: Array.isArray(res[0]) ? res[0] : [], businesses: (res[1] && res[1].businesses) || [], partners: (res[2] && res[2].partners) || [] };
  }

  return { PRODUCTS: PRODUCTS, isPaid: isPaid, cardsOf: cardsOf, priceOf: priceOf, productLabel: productLabel,
           feeOf: feeOf, stats: stats, summary: summary, esc: esc, loadAll: loadAll };
})();
if (typeof module !== 'undefined') module.exports = OtvizSales;
