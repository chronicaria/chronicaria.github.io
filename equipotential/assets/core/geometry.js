/* geometry.js — the level-set kernel, in closed form.
 *
 * A port of the solver's figure definitions, written fresh for the browser.
 * Two families, both equipotentials of a point-mass effective potential with
 * the polar radius fixed at exactly 1:
 *
 *   Roche oblate   phi = 1 - 1/r - (1/2) q rho^2
 *   Tidal Roche    phi = C - 1/r - mu/r_c - (1/2) Om2 ((x-xcm)^2 + y^2)
 *
 * Because phi IS the effective potential, ||grad phi|| on the surface is the
 * local effective gravity. Nothing here is measured; every value on this page
 * that comes out of this file is computed live from these closed forms.
 *
 * Reference values this file is held to live in tests/golden.html.
 */

export const Q_BREAK = 8 / 27;          // (2/3)^3 = 0.296296…, point-mass break-up
export const R_BREAK = 1.5;             // where the two equatorial roots collide

/* ── Roche oblate ─────────────────────────────────────────────────────── */

export function phiOb(x, y, z, q) {
  const r = Math.sqrt(x * x + y * y + z * z);
  if (r <= 1e-300) return -Infinity;
  return 1.0 - 1.0 / r - 0.5 * q * (x * x + y * y);
}

/** grad phi for the oblate figure, written into `out` (or a fresh array). */
export function gradOb(x, y, z, q, out) {
  const o = out || [0, 0, 0];
  const r2 = x * x + y * y + z * z;
  const r = Math.sqrt(r2);
  if (r <= 1e-300) { o[0] = 0; o[1] = 0; o[2] = 1; return o; }
  const invr3 = 1.0 / (r2 * r);
  o[0] = x * invr3 - q * x;
  o[1] = y * invr3 - q * y;
  o[2] = z * invr3;
  return o;
}

/**
 * Equatorial radius: the inner root of 1 - 1/R - (1/2) q R^2 = 0.
 *
 * That is the depressed cubic R^3 - (2/q) R + 2/q = 0, so the middle
 * trigonometric root is exact — no iteration, and no bracket to lose near
 * break-up, where the exact form returns 1.5 on the nose.
 */
export function equatorialRadius(q) {
  if (q <= 1e-6) return 1 + 0.5 * q + 0.75 * q * q;   // series; error O(q^3)
  if (q > Q_BREAK) return NaN;                        // no root past break-up
  const a = -1.5 * Math.sqrt(1.5 * q);                // exactly -1 at q = 8/27
  return 2 * Math.sqrt(2 / (3 * q)) *
         Math.cos((1 / 3) * Math.acos(a < -1 ? -1 : a) - 2 * Math.PI / 3);
}

/** Geometric flattening 1 - R_pole/R_eq, with R_pole = 1. */
export const flattening = (q) => 1 - 1 / equatorialRadius(q);

/**
 * Surface radius along the direction (sin t cos p, sin t sin p, cos t).
 * Substituting rho^2 = (r sin t)^2 turns the level-set equation into the same
 * cubic with q -> q sin^2 t, so the exact root serves every latitude.
 */
export const radiusOb = (sinTheta, q) => equatorialRadius(q * sinTheta * sinTheta);

/** The break-up curve: q admitted by an equatorial radius R. Peaks at R = 3/2. */
export const qOfR = (R) => 2 / (R * R) - 2 / (R * R * R);

/** The two equatorial roots of qOfR(R) = q; they annihilate at R = 3/2. */
export function breakupRoots(q) {
  if (q > Q_BREAK) return null;
  const inner = equatorialRadius(q);
  // Outer root: bisect on [3/2, huge] where qOfR decreases monotonically.
  let lo = R_BREAK, hi = 1e6;
  for (let i = 0; i < 200; i++) {
    const mid = 0.5 * (lo + hi);
    if (qOfR(mid) >= q) lo = mid; else hi = mid;
  }
  return { inner, outer: 0.5 * (lo + hi) };
}

/* ── Tidal Roche ──────────────────────────────────────────────────────── */

/**
 * The synchronous-Roche figure of a primary (polar radius 1) with a companion
 * of mass ratio mu at separation D, co-rotating at Om2 = (1+mu)/D^3.
 *
 * At mu = 0 this reduces to the oblate figure at q = 1/D^3 — and it does so
 * bit-exactly, which tests/golden.html asserts rather than assumes. D3 is
 * spelled D*D*D on both sides so the two q values are the same double.
 */
export function tidal(mu, D) {
  const D3 = D * D * D;
  const Om2 = (1.0 + mu) / D3;
  const xcm = mu * D / (1.0 + mu);
  const rcPole = Math.sqrt(D * D + 1.0);
  const C = 1.0 + mu / rcPole + 0.5 * Om2 * xcm * xcm;
  return { mu, D, Om2, xcm, C };
}

export function phiTd(x, y, z, ls) {
  const r = Math.sqrt(x * x + y * y + z * z);
  if (r <= 1e-300) return -Infinity;
  const dx = x - ls.D;
  const rc = Math.sqrt(dx * dx + y * y + z * z);
  if (rc <= 1e-300) return -Infinity;
  const dc = x - ls.xcm;
  return ls.C - 1.0 / r - ls.mu / rc - 0.5 * ls.Om2 * (dc * dc + y * y);
}

export function gradTd(x, y, z, ls, out) {
  const o = out || [0, 0, 0];
  const r2 = x * x + y * y + z * z;
  const r = Math.sqrt(r2);
  if (r <= 1e-300) { o[0] = 0; o[1] = 0; o[2] = 1; return o; }
  const invr3 = 1.0 / (r2 * r);
  const dx = x - ls.D;
  const rc2 = dx * dx + y * y + z * z;
  const rc = Math.sqrt(rc2);
  const invrc3 = rc <= 1e-300 ? 0.0 : 1.0 / (rc2 * rc);
  o[0] = x * invr3 + ls.mu * dx * invrc3 - ls.Om2 * (x - ls.xcm);
  o[1] = y * invr3 + ls.mu * y * invrc3 - ls.Om2 * y;
  o[2] = z * invr3 + ls.mu * z * invrc3;
  return o;
}

/**
 * Surface radius along a unit direction. Newton from t = 1 on g(t) = phi(t*u),
 * with g'(t) = grad phi . u; bisection on [1e-3, 3] whenever a step leaves the
 * bracket or the derivative vanishes.
 */
export function radiusTd(ux, uy, uz, ls) {
  const g = [0, 0, 0];
  let t = 1.0;
  for (let it = 0; it < 40; it++) {
    const f = phiTd(t * ux, t * uy, t * uz, ls);
    if (Math.abs(f) <= 1e-13) return t;
    gradTd(t * ux, t * uy, t * uz, ls, g);
    const d = g[0] * ux + g[1] * uy + g[2] * uz;
    const tn = t - f / d;
    if (!isFinite(tn) || tn <= 1e-3 || tn >= 3) break;
    if (Math.abs(tn - t) < 1e-14) return tn;
    t = tn;
  }
  // Bracket and bisect: phi > 0 inside, phi < 0 outside the sub-companion lobe.
  let lo = 1e-3, hi = 3.0;
  if (phiTd(lo * ux, lo * uy, lo * uz, ls) * phiTd(hi * ux, hi * uy, hi * uz, ls) > 0) return NaN;
  for (let i = 0; i < 80; i++) {
    const mid = 0.5 * (lo + hi);
    if (phiTd(lo * ux, lo * uy, lo * uz, ls) * phiTd(mid * ux, mid * uy, mid * uz, ls) <= 0) hi = mid;
    else lo = mid;
  }
  return 0.5 * (lo + hi);
}

/**
 * g_pole for a figure that is no longer axisymmetric: the operational
 * definition is the mean of ||grad phi|| at the two spin-axis piercings, and
 * the figure's z -> -z symmetry makes the two identical.
 */
export function gPoleTidal(ls) {
  const s = Math.pow(ls.D * ls.D + 1.0, 1.5);
  return Math.hypot(ls.Om2 * ls.xcm - ls.mu * ls.D / s, 1.0 + ls.mu / s);
}

/** Inner Lagrange point: the root in (0, D) of 1/x^2 - mu/(D-x)^2 - Om2 (x - xcm). */
export function xL1(mu, D) {
  const Om2 = (1.0 + mu) / (D * D * D);
  const xcm = mu * D / (1.0 + mu);
  const f = (x) => 1.0 / (x * x) - mu / ((D - x) * (D - x)) - Om2 * (x - xcm);
  let lo = 1e-9 * D, hi = D * (1.0 - 1e-9);
  for (let i = 0; i < 200; i++) {
    const mid = 0.5 * (lo + hi);
    if (f(mid) > 0.0) lo = mid; else hi = mid;
  }
  return 0.5 * (lo + hi);
}

/**
 * L1 distance, the sub-companion surface radius, and the fill fraction
 * x_sub / x_L1. `overflow` is phi(L1) < 0: the figure has burst its lobe.
 */
export function tidalGeometry(ls) {
  const L1 = xL1(ls.mu, ls.D);
  const phiL1 = phiTd(L1, 0, 0, ls);
  const overflow = phiL1 < 0.0;
  if (overflow) return { xL1: L1, phiL1, xSub: NaN, fill: NaN, overflow };
  let lo = 1e-6, hi = L1 * (1.0 - 1e-9);
  const g = (x) => phiTd(x, 0, 0, ls);
  if (g(lo) * g(hi) > 0.0) return { xL1: L1, phiL1, xSub: NaN, fill: NaN, overflow };
  for (let i = 0; i < 200; i++) {
    const mid = 0.5 * (lo + hi);
    if (g(lo) * g(mid) <= 0.0) hi = mid; else lo = mid;
  }
  const xSub = 0.5 * (lo + hi);
  return { xL1: L1, phiL1, xSub, fill: xSub / L1, overflow };
}

/* ── Shared surface accessors ─────────────────────────────────────────── */

/** Per-point gravity darkening, before area renormalization. */
export const darkening = (geff, gpole, beta) => Math.pow(geff / gpole, beta);

/**
 * One object per figure, so the widgets never branch on family. `radius` takes
 * a unit direction; `grad` writes into a scratch array; `gPole` is the
 * normalizing effective gravity at the spin-axis piercing.
 */
export function figure(kind, p) {
  if (kind === 'oblate') {
    const q = p.q;
    return {
      kind, q,
      radius: (ux, uy, uz) => radiusOb(Math.hypot(ux, uy), q),
      phi: (x, y, z) => phiOb(x, y, z, q),
      grad: (x, y, z, out) => gradOb(x, y, z, q, out),
      gPole: 1.0,                       // exactly 1 for this figure, at any q
      extent: equatorialRadius(q)
    };
  }
  const ls = tidal(p.mu, p.D);
  const gp = gPoleTidal(ls);
  return {
    kind, ls, mu: p.mu, D: p.D,
    radius: (ux, uy, uz) => radiusTd(ux, uy, uz, ls),
    phi: (x, y, z) => phiTd(x, y, z, ls),
    grad: (x, y, z, out) => gradTd(x, y, z, ls, out),
    gPole: gp,
    extent: tidalGeometry(ls).xSub || 1.4
  };
}
