/*
 * Host test for the integer-only float helpers in include/glacio_float.h.
 *
 * The helpers exist because mod code may not contain a single float operation: the soft-float ABI
 * the N64 toolchain uses turns every float op into a libgcc call, and the base game exports none of
 * those symbols, so the mod would fail to load. That makes the helpers load bearing for far more
 * than convenience -- a wrong scale or a wrong teleport coordinate is a gameplay bug, and a
 * regression here is silent. So this file compiles the *same source* the MIPS build uses (via
 * GLACIO_FLOAT_HOST_TEST) and checks it against real float arithmetic on the host.
 *
 * Run it with `make test`.
 */

#define GLACIO_FLOAT_HOST_TEST 1

#include <math.h>
#include <stdint.h>
#include <stdio.h>

#include "glacio_float.h"

/* Two floats are "close" for our purposes if they are within `maxUlps` representable steps of each
 * other. Comparing the bit patterns as ordered integers gives exactly that. */
static int32_t ordered_bits(float value) {
    union {
        float f;
        int32_t i;
    } bits;
    bits.f = value;
    return bits.i >= 0 ? bits.i : 0x80000000 - (bits.i & 0x7FFFFFFF);
}

static int ulp_close(float got, float want, int maxUlps) {
    if (isnan(got) || isnan(want)) {
        return isnan(got) && isnan(want);
    }
    int64_t diff = (int64_t)ordered_bits(got) - (int64_t)ordered_bits(want);
    if (diff < 0) {
        diff = -diff;
    }
    return diff <= maxUlps;
}

static int failures;

#define CHECK(cond, ...)                                                                                       \
    do {                                                                                                       \
        if (!(cond)) {                                                                                         \
            if (failures < 20) {                                                                               \
                printf("FAIL " __VA_ARGS__);                                                                   \
                printf("\n");                                                                                  \
            }                                                                                                  \
            failures++;                                                                                        \
        }                                                                                                      \
    } while (0)

/* Glacio_F32ToS32 must truncate toward zero, exactly like (s32)f. */
static void test_to_integer(void) {
    long v;
    int checked = 0;

    for (v = -65536; v <= 65536; v++) {
        float f = (float)v;
        CHECK(Glacio_F32ToS32(f) == (int32_t)f, "F32ToS32(%ld) = %d, want %ld", (long)f,
              (int)Glacio_F32ToS32(f), (long)(int32_t)f);
        checked++;
    }
    /* Sixteenths, the representation mm positions actually use. */
    for (v = -32768 * 16; v <= 32767 * 16; v += 7) {
        float f = (float)v / 16.0f;
        CHECK(Glacio_F32ToS32(f) == (int32_t)f, "F32ToS32(%g) = %d, want %ld", (double)f,
              (int)Glacio_F32ToS32(f), (long)(int32_t)f);
        checked++;
    }
    /* Negative zero, values that overflow the mantissa shift, and non-finite inputs: documented as
     * returning 0 rather than trapping, which is what keeps a stray value from corrupting a spawn. */
    CHECK(Glacio_F32ToS32(-0.0f) == 0, "F32ToS32(-0.0) must be 0");
    CHECK(Glacio_F32ToS32(INFINITY) == 0, "F32ToS32(+inf) must be 0");
    CHECK(Glacio_F32ToS32(-INFINITY) == 0, "F32ToS32(-inf) must be 0");
    CHECK(Glacio_F32ToS32((float)NAN) == 0, "F32ToS32(nan) must be 0");
    CHECK(Glacio_F32ToS32(1.0f / 16.0f) == 0, "F32ToS32(0.0625) must truncate to 0");
    printf("  F32ToS32: %d cases\n", checked);
}

/* Glacio_S32ToF32Scaled(v, n) == (float)v / 2^n, correctly rounded when the result is exact and
 * within one ulp otherwise (the helper rounds half up, the hardware rounds half to even). */
static void test_from_integer_scaled(void) {
    static const int fracs[] = { 0, 4, 14, 16, 23 };
    long v;
    size_t i;
    int checked = 0;

    for (i = 0; i < sizeof(fracs) / sizeof(fracs[0]); i++) {
        int frac = fracs[i];
        double divisor = ldexp(1.0, frac);
        for (v = -200000; v <= 200000; v += 13) {
            float want = (float)((double)v / divisor);
            float got = Glacio_S32ToF32Scaled((int32_t)v, frac);
            /* Exact when the quotient has an exact binary representation. */
            int exact = fabs(((double)v / divisor) - (double)want) == 0.0;
            CHECK(ulp_close(got, want, exact ? 0 : 1),
                  "S32ToF32Scaled(%ld, %d) = %.9g, want %.9g%s", v, frac, (double)got, (double)want,
                  exact ? " (must be exact)" : "");
            checked++;
        }
    }
    /* The wide field: s32 values that need mantissa rounding (topBit >= 23), which is where a
     * scale percent or a large coordinate can land, and where an off by one shift hides. */
    for (i = 0; i < 2; i++) {
        int frac = fracs[i] + 14;
        double divisor = ldexp(1.0, frac);
        for (v = -(1 << 25); v <= (1 << 25); v += 9973) {
            float want = (float)((double)v / divisor);
            float got = Glacio_S32ToF32Scaled((int32_t)v, frac);
            CHECK(ulp_close(got, want, 1), "S32ToF32Scaled(%ld, %d) = %.9g, want %.9g", (long)v,
                  frac, (double)got, (double)want);
            checked++;
        }
    }
    /* Every power of two, in both directions, is representable exactly at any fraction. */
    for (v = 0; v < 31; v++) {
        for (i = 0; i < 5; i++) {
            int frac = fracs[i];
            float want = ldexpf(1.0f, (int)v - frac);
            float got = Glacio_S32ToF32Scaled(1 << v, frac);
            CHECK(got == want, "S32ToF32Scaled(1<<%ld, %d) = %.9g, want exact %.9g", (long)v, frac,
                  (double)got, (double)want);
            checked++;
        }
    }
    /* The extremes: zero, the largest and smallest s32, and powers of two. */
    CHECK(Glacio_S32ToF32Scaled(0, 16) == 0.0f, "S32ToF32Scaled(0,16) must be +0.0");
    CHECK(ulp_close(Glacio_S32ToF32Scaled(2147483647, 0), 2147483647.0f, 1), "S32ToF32Scaled(INT32_MAX)");
    CHECK(ulp_close(Glacio_S32ToF32Scaled(-2147483647 - 1, 0), -2147483648.0f, 1), "S32ToF32Scaled(INT32_MIN)");
    printf("  S32ToF32Scaled: %d cases\n", checked);
}

/* Glacio_F32Mul must agree with a/b to within one ulp, and be exact for every product the target
 * format can hold -- scale multipliers like 0.017 * 1.3 come straight from config options. */
static void test_multiply(void) {
    unsigned seed = 12345;
    int i;
    int checked = 0;
    static const float nice[] = { 0.0f,     1.0f,   0.017f,  1.3f,   0.5f,   255.0f,  1.0f / 3.0f,
                                  123.456f, -3.75f, 0.001f,  65536.0f, -1.0f, 0.125f, 7.0f,
                                  1.0f / 65536.0f, 3.4028235e+38f };

    for (i = 0; i < (int)(sizeof(nice) / sizeof(nice[0])); i++) {
        for (size_t j = 0; j < sizeof(nice) / sizeof(nice[0]); j++) {
            float a = nice[i];
            float b = nice[j];
            float want = a * b;
            float got = Glacio_F32Mul(a, b);
            CHECK(ulp_close(got, want, isinf(want) ? 0 : 1), "F32Mul(%g, %g) = %g, want %g",
                  (double)a, (double)b, (double)got, (double)want);
            CHECK((got < 0) == (want < 0) || got == 0.0f || want == 0.0f,
                  "F32Mul(%g, %g) sign flip: %g vs %g", (double)a, (double)b, (double)got,
                  (double)want);
            checked++;
        }
    }
    /* Pseudo random sweep over the range a scale factor can realistically take. */
    for (i = 0; i < 400000; i++) {
        union {
            uint32_t u;
            float f;
        } bits;
        float a, b, want, got;
        seed = seed * 1103515245u + 12345u;
        bits.u = 0x30000000u + (seed & 0x00400000u) + (i & 0x3FFFF); /* exponent ~2^-30..2^15ish */
        a = bits.f;
        seed = seed * 1103515245u + 12345u;
        b = (float)(1.0 + (double)(seed % 4000) / 1000.0); /* 1.000 .. 5.000, i.e. a percentage */
        want = a * b;
        got = Glacio_F32Mul(a, b);
        CHECK(ulp_close(got, want, 1), "F32Mul(%g, %g) = %g, want %g", (double)a, (double)b,
              (double)got, (double)want);
        checked++;
    }
    printf("  F32Mul: %d cases\n", checked);
}

/* Glacio_Near is the interaction gate, so it must never reject a player standing on the crystal and
 * must reject the far side of a town. Its truncation slack is part of the contract. */
static void test_near(void) {
    int radius;
    int checked = 0;

    for (radius = 20; radius <= 2000; radius += 60) {
        CHECK(Glacio_Near(0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, radius) == 1, "Near(0,0) radius %d",
              radius);
        CHECK(Glacio_Near(0.0f, 0.0f, 0.0f, (float)radius, 0.0f, 0.0f, radius) == 1,
              "Near on the boundary radius %d must pass", radius);
        CHECK(Glacio_Near(0.0f, 0.0f, 0.0f, (float)(radius * 4), 0.0f, 0.0f, radius) == 0,
              "Near far away radius %d must fail", radius);
        CHECK(Glacio_Near(0.0f, 0.0f, 0.0f, 0.0f, (float)(radius * 4), 0.0f, radius) == 0,
              "Near far above radius %d must fail", radius);
        /* Symmetry, because the caller cannot control which side ends up as "a". */
        for (int d = -radius; d <= radius; d += 37) {
            float f = (float)d;
            CHECK(Glacio_Near(f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, radius) ==
                      Glacio_Near(0.0f, 0.0f, 0.0f, f, 0.0f, 0.0f, radius),
                  "Near not symmetric at %d radius %d", d, radius);
            checked++;
        }
        checked += 4;
    }
    printf("  Near: %d cases\n", checked);
}

/* The rules that keep the mod loadable are stated in terms of the helpers, so restate them here as
 * an executable note: everything the helpers touch must stay integral in the MIPS build. That is
 * enforced by tools/test_float_helpers.py, which links the object and rejects libgcc symbols. */
int main(void) {
    printf("glacio_float.h vs host float arithmetic:\n");
    test_to_integer();
    test_from_integer_scaled();
    test_multiply();
    test_near();
    if (failures) {
        printf("\n%d FAILURE(S)\n", failures);
        return 1;
    }
    printf("\nall float helper checks passed\n");
    return 0;
}
