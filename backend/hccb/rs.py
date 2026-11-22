"""Generic Reed-Solomon codec over GF(2^m).

Conventions (used consistently in this module):
  * Polynomials are lists of coefficients, LOWEST degree first: p[k] is the
    coefficient of x^k.
  * A codeword c of length n is a polynomial c(x) = sum c[k] x^k.
  * The generator is g(x) = prod_{j=0}^{nsym-1} (x - alpha^(fcr+j)).
  * Systematic encoding: c(x) = msg(x) * x^nsym + (msg(x) * x^nsym mod g(x)),
    i.e. c[0:nsym] are parity symbols and c[nsym:] are the message symbols.
  * Shortened codes are supported implicitly: any n <= 2^m - 1 works.

The decoder implements errors-and-erasures Berlekamp-Massey, Chien search and
Forney's algorithm and corrects any pattern with 2*errors + erasures <= nsym.
It never returns a "corrected" word unless all syndromes of the result are 0.
"""
from __future__ import annotations

from dataclasses import dataclass, field


class GaloisField:
    def __init__(self, m: int, prim_poly: int):
        self.m = m
        self.size = 1 << m
        self.n = self.size - 1
        self.prim_poly = prim_poly
        exp = [0] * (2 * self.n)
        log = [0] * self.size
        x = 1
        for i in range(self.n):
            exp[i] = x
            log[x] = i
            x <<= 1
            if x & self.size:
                x ^= prim_poly
        if x != 1:
            raise ValueError("polynomial is not primitive")
        for i in range(self.n, 2 * self.n):
            exp[i] = exp[i - self.n]
        self.exp = exp
        self.log = log

    def mul(self, a: int, b: int) -> int:
        if a == 0 or b == 0:
            return 0
        return self.exp[self.log[a] + self.log[b]]

    def div(self, a: int, b: int) -> int:
        if b == 0:
            raise ZeroDivisionError
        if a == 0:
            return 0
        return self.exp[(self.log[a] - self.log[b]) % self.n]

    def inv(self, a: int) -> int:
        return self.div(1, a)

    def alpha_pow(self, k: int) -> int:
        return self.exp[k % self.n]

    # --- polynomial helpers (lowest degree first) ---
    def poly_eval(self, p: list[int], x: int) -> int:
        y = 0
        for c in reversed(p):  # Horner
            y = self.mul(y, x) ^ c
        return y

    def poly_mul(self, a: list[int], b: list[int]) -> list[int]:
        out = [0] * (len(a) + len(b) - 1)
        for i, av in enumerate(a):
            if av:
                for j, bv in enumerate(b):
                    if bv:
                        out[i + j] ^= self.mul(av, bv)
        return out

    def poly_add(self, a: list[int], b: list[int]) -> list[int]:
        out = [0] * max(len(a), len(b))
        for i, v in enumerate(a):
            out[i] ^= v
        for i, v in enumerate(b):
            out[i] ^= v
        return out

    def poly_scale(self, p: list[int], s: int) -> list[int]:
        return [self.mul(c, s) for c in p]


@dataclass
class RSResult:
    ok: bool
    codeword: list[int]
    error_positions: list[int] = field(default_factory=list)
    erasure_positions: list[int] = field(default_factory=list)
    reason: str = ""


class ReedSolomon:
    def __init__(self, gf: GaloisField, nsym: int, fcr: int = 1):
        self.gf = gf
        self.nsym = nsym
        self.fcr = fcr
        g = [1]
        for j in range(nsym):
            g = gf.poly_mul(g, [gf.alpha_pow(fcr + j), 1])
        self.generator = g  # lowest first, monic (g[-1] == 1)

    def parity(self, msg: list[int]) -> list[int]:
        """Return the nsym parity symbols (coefficients of x^0..x^(nsym-1))."""
        gf = self.gf
        # Long division of msg(x)*x^nsym by monic g(x), highest degree first.
        rem = [0] * self.nsym  # rem[k] coefficient of x^k
        for coef in reversed(msg):
            feedback = coef ^ rem[-1]
            # shift up
            for k in range(self.nsym - 1, 0, -1):
                rem[k] = rem[k - 1] ^ gf.mul(feedback, self.generator[k])
            rem[0] = gf.mul(feedback, self.generator[0])
        return rem

    def encode(self, msg: list[int]) -> list[int]:
        return self.parity(msg) + list(msg)

    def syndromes(self, cw: list[int]) -> list[int]:
        return [self.gf.poly_eval(cw, self.gf.alpha_pow(self.fcr + j)) for j in range(self.nsym)]

    def decode(self, cw: list[int], erasures: list[int] | None = None) -> RSResult:
        gf = self.gf
        n = len(cw)
        erasures = sorted(set(erasures or []))
        if n > gf.n:
            return RSResult(False, list(cw), reason="codeword longer than field allows")
        if len(erasures) > self.nsym:
            return RSResult(False, list(cw), reason="too many erasures")
        S = self.syndromes(cw)
        if not any(S):
            return RSResult(True, list(cw), [], [])

        # Erasure locator Gamma(x) = prod (1 - X_k x)
        gamma = [1]
        for p in erasures:
            gamma = gf.poly_mul(gamma, [1, gf.alpha_pow(p)])
        e = len(erasures)

        # Errors-and-erasures Berlekamp-Massey
        C = list(gamma)
        B = list(gamma)
        L = e
        m = 1
        b = 1
        for r in range(e, self.nsym):
            d = S[r]
            for i in range(1, L + 1):
                if i < len(C):
                    d ^= gf.mul(C[i], S[r - i])
            if d == 0:
                m += 1
                continue
            coef = gf.div(d, b)
            shifted = [0] * m + gf.poly_scale(B, coef)
            T = list(C)
            C = gf.poly_add(C, shifted)
            if 2 * L <= r + e:
                L = r + 1 + e - L
                B = T
                b = d
                m = 1
            else:
                m += 1
        while len(C) > 1 and C[-1] == 0:
            C.pop()
        Lambda = C
        deg = len(Lambda) - 1
        if 2 * (deg - e) + e > self.nsym:
            return RSResult(False, list(cw), reason="too many errors")

        # Chien search over valid positions only (shortened code)
        positions = []
        for p in range(n):
            if gf.poly_eval(Lambda, gf.alpha_pow(-p)) == 0:
                positions.append(p)
        if len(positions) != deg:
            return RSResult(False, list(cw), reason=f"locator degree {deg} but {len(positions)} roots in range: uncorrectable")

        # Forney
        Sx = list(S)
        Omega = gf.poly_mul(Sx, Lambda)[: self.nsym]
        dLambda = [Lambda[i] if i % 2 == 1 else 0 for i in range(1, len(Lambda))]
        out = list(cw)
        for p in positions:
            Xinv = gf.alpha_pow(-p)
            num = gf.poly_eval(Omega, Xinv)
            den = gf.poly_eval(dLambda, Xinv)
            if den == 0:
                return RSResult(False, list(cw), reason="Forney denominator zero")
            mag = gf.div(num, den)
            # X^(1-fcr)
            mag = gf.mul(mag, gf.alpha_pow(p * (1 - self.fcr)))
            out[p] ^= mag
        if any(self.syndromes(out)):
            return RSResult(False, list(cw), reason="correction did not yield a codeword")
        errs = [p for p in positions if p not in erasures and out[p] != cw[p]]
        return RSResult(True, out, errs, erasures)
