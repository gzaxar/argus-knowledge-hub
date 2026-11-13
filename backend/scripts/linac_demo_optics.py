"""Linear optics and a small matcher for the Valmora linac demo (synthetic, acceleration ignored)."""
import math
import random


def _mat(k, L):
    if abs(k) < 1e-9:
        return (1.0, L, 0.0, 1.0)
    r = math.sqrt(abs(k))
    if k > 0:
        return (math.cos(r * L), math.sin(r * L) / r, -r * math.sin(r * L), math.cos(r * L))
    return (math.cosh(r * L), math.sinh(r * L) / r, r * math.sinh(r * L), math.cosh(r * L))


def _prop(m, b, a):
    m11, m12, m21, m22 = m
    g = (1 + a * a) / b
    return (m11 * m11 * b - 2 * m11 * m12 * a + m12 * m12 * g,
            -m11 * m21 * b + (m11 * m22 + m12 * m21) * a - m12 * m22 * g)


def twiss(elements, k1, b0=5.0, a0=0.0):
    """elements: [(id, s, length)] in order. Returns ({id: optics at entry}, largest beta seen, sampled inside)."""
    out, bx, ax, by, ay, s_prev, worst = {}, b0, a0, b0, a0, 0.0, b0
    for el, s, L in elements:
        gap = s - s_prev
        for frac in (0.5, 1.0):                       # sample half way along a long drift too
            pbx, _ = _prop(_mat(0, gap * frac), bx, ax)
            pby, _ = _prop(_mat(0, gap * frac), by, ay)
            worst = max(worst, pbx, pby)
        bx, ax = _prop(_mat(0, gap), bx, ax)
        by, ay = _prop(_mat(0, gap), by, ay)
        out[el] = {"betx": round(bx, 3), "alfx": round(ax, 3), "bety": round(by, 3), "alfy": round(ay, 3)}
        k = k1.get(el, 0.0)
        for frac in (0.5, 1.0):
            pbx, _ = _prop(_mat(k, L * frac), bx, ax)
            pby, _ = _prop(_mat(-k, L * frac), by, ay)
            worst = max(worst, pbx, pby)
        bx, ax = _prop(_mat(k, L), bx, ax)
        by, ay = _prop(_mat(-k, L), by, ay)
        s_prev = s + L
    return out, worst


def match(elements, quads, cost, seed=7, starts=60, kmax=60.0):
    rnd = random.Random(seed)
    best, best_c = None, float("inf")
    for _ in range(starts):
        k = {q: rnd.uniform(-kmax, kmax) for q in quads}
        c, step = cost(k), kmax / 4
        while step > 1e-3:
            moved = False
            for q in quads:
                for d in (step, -step):
                    t = {**k, q: max(-kmax, min(kmax, k[q] + d))}
                    ct = cost(t)
                    if ct < c:
                        k, c, moved = t, ct, True
            if not moved:
                step /= 2
        if c < best_c:
            best, best_c = k, c
    return best, best_c
