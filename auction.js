/* SMP League auction rules, as one pure function. The site runs it in the browser on the published bid sheet;
   tools/test_auction.mjs runs the same file in node.

   Rules: every bid is public and binding. A bid is a salary in whole $M and a length of 1-5 years, compared on
   score = salary x (1 + 0.25 x (years - 1)). To take the lead a bid must beat the current best score (or reach the
   player's opening price if nobody has bid). A team's leading bids can never add up to more than the budget minus
   $1M for each roster spot still open, and it can lead at most `roster` players. Everything closes at one deadline:
   a bid stamped before it counts, one stamped at or after it does not. */
(function (root) {
  const mult = (y) => 1 + 0.25 * (y - 1);

  function run(cfg, bids) {
    const lots = new Map(cfg.lots.map((l) => [l.id, { ...l, lead: null, history: [] }]));
    const teams = Object.fromEntries(cfg.teams.map((t) => [t, { leads: new Set(), bids: 0, rejected: 0 }]));
    const spent = (t, except) => [...teams[t].leads].reduce((a, id) => a + (id === except ? 0 : lots.get(id).lead.sal), 0);
    const log = [];
    for (const b of [...bids].sort((x, y) => x.t - y.t)) {
      const L = lots.get(b.pid), T = teams[b.team];
      const no = (why) => { log.push({ ...b, ok: false, why }); if (T) T.rejected++; };
      if (!T) { no('Unknown team'); continue; }
      T.bids++;
      if (!L) { no('Player is not in the auction'); continue; }
      if (!(b.t >= cfg.start)) { no('Before the auction opened'); continue; }
      if (!(b.t < cfg.close)) { no('After the deadline'); continue; }
      if (!Number.isInteger(b.sal) || b.sal < 1 || (cfg.max && b.sal > cfg.max)) { no(cfg.max ? `Salary must be a whole number from $1M to $${cfg.max}M` : 'Salary must be a whole number of millions, $1M or more'); continue; }   // no cap unless cfg.max is set; the budget rule below still applies
      if (!Number.isInteger(b.yrs) || b.yrs < 1 || b.yrs > 5) { no('Length must be 1 to 5 years'); continue; }
      const score = b.sal * mult(b.yrs);
      if (L.lead ? score <= L.lead.score : score < L.open) { no(L.lead ? `Does not beat $${L.lead.sal}M x ${L.lead.yrs}` : `Below the $${L.open}M opening price`); continue; }
      const mine = !!L.lead && L.lead.team === b.team, n = T.leads.size + (mine ? 0 : 1);
      if (n > cfg.roster) { no(`Already leading ${cfg.roster} players`); continue; }
      const room = cfg.budget - (cfg.roster - n) - spent(b.team, b.pid);
      if (b.sal > room) { no(`Over budget: at most $${Math.max(0, room)}M available here`); continue; }
      if (L.lead && !mine) teams[L.lead.team].leads.delete(b.pid);
      L.lead = { team: b.team, sal: b.sal, yrs: b.yrs, score, t: b.t };
      L.history.push(L.lead); T.leads.add(b.pid);
      log.push({ ...b, ok: true });
    }
    const summary = Object.fromEntries(cfg.teams.map((t) => {
      const s = spent(t), n = teams[t].leads.size;
      return [t, { players: [...teams[t].leads], n, spent: s, left: cfg.budget - s, maxBid: Math.max(0, cfg.budget - s - Math.max(0, cfg.roster - n - 1)), bids: teams[t].bids, rejected: teams[t].rejected }];
    }));
    return { lots, teams: summary, log };
  }

  /* After the deadline, a team short of a full roster takes the best-ranked unsold players at their opening price
     for one year while it can afford them (keeping $1M per spot still open), otherwise at $1M. Neediest team first. */
  function fill(cfg, state) {
    const out = [], unsold = cfg.lots.filter((l) => !state.lots.get(l.id).lead).sort((a, b) => a.rk - b.rk);
    const T = Object.fromEntries(cfg.teams.map((t) => [t, { n: state.teams[t].n, spent: state.teams[t].spent }]));
    for (;;) {
      const t = cfg.teams.filter((x) => T[x].n < cfg.roster).sort((a, b) => T[a].n - T[b].n || T[a].spent - T[b].spent)[0];
      if (!t || !unsold.length) break;
      const room = cfg.budget - T[t].spent - (cfg.roster - T[t].n - 1), i = unsold.findIndex((l) => l.open <= room), l = unsold.splice(i < 0 ? 0 : i, 1)[0];
      const sal = i < 0 ? 1 : l.open;
      T[t].n++; T[t].spent += sal; out.push({ team: t, pid: l.id, sal, yrs: 1 });
    }
    return out;
  }

  const api = { run, fill, mult };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.SMPAuction = api;
})(typeof window !== 'undefined' ? window : globalThis);
