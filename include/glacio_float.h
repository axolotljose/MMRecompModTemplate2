#ifndef GLACIO_FLOAT_H
#define GLACIO_FLOAT_H

/*
 * Exact float helpers written with integer arithmetic only.
 *
 * Mod code is live recompiled by the host, which resolves undefined symbols against the base
 * game's exported symbol table. The N64 toolchain targets soft float, so a single `+`, `/`, `(int)`
 * or `(float)` on a float becomes a libgcc call (`__addsf3`, `__fixsfsi`, `__floatsisf`, ...) and
 * the base game exports none of them -- the mod then fails to load with "unknown symbol" and, on
 * the Android port, simply does not appear to work at all. Keeping the arithmetic integral is the
 * fix, so these helpers do the IEEE-754 work by hand.
 *
 * They are exact for the ranges this mod uses (positions are 16 bit coordinates, scales and
 * percentages are small integers) and are cross-checked against real float arithmetic for every
 * input the mod can produce by `make test`.
 */

#ifdef GLACIO_FLOAT_HOST_TEST
/* Host build of the same source, used by tests/glacio_float_test.c. */
# include <stdint.h>
typedef float    f32;
typedef int      bool;
# define false   0
# define true    1
typedef int32_t  s32;
typedef uint32_t u32;
typedef uint64_t u64;
#endif

typedef union {
    f32 value;
    u32 bits;
} GlacioFloatBits; /* bit-punning, so no conversion instruction is ever generated */

/** Truncate a float to an integer. Values outside s32 range and denormals become 0. */
static s32 Glacio_F32ToS32(f32 value) {
    GlacioFloatBits u;
    u32 mantissa;
    s32 exponent;
    s32 result;

    u.value = value;

    exponent = (s32)((u.bits >> 23) & 0xFF);
    if (exponent == 0 || exponent > 157) {
        return 0;
    }

    mantissa = (u.bits & 0x7FFFFF) | 0x800000; /* restore the implicit leading one */
    exponent -= 150;                           /* value = mantissa * 2^(exponent - 150) */

    if (exponent >= 0) {
        result = (s32)(mantissa << exponent);
    } else {
        result = (s32)(mantissa >> -exponent);
    }
    return (u.bits >> 31) ? -result : result;
}

/** Convert an integer scaled by 2^-fracBits into a float, rounding the mantissa to nearest. */
static f32 Glacio_S32ToF32Scaled(s32 value, s32 fracBits) {
    GlacioFloatBits u;
    u32 magnitude;
    u32 mantissa;
    s32 topBit;
    s32 exponent;
    u32 sign;

    if (value == 0) {
        u.bits = 0;
        return u.value;
    }

    /* Negate in unsigned arithmetic: -(int32)INT32_MIN would be signed overflow. */
    sign = 0;
    if (value < 0) {
        sign = 0x80000000U;
        magnitude = 0U - (u32)value;
    } else {
        magnitude = (u32)value;
    }

    /* Find the index of the highest set bit. */
    topBit = 0;
    while ((magnitude >> (topBit + 1)) != 0) {
        topBit++;
    }

    /* Normalise so that the mantissa holds 24 bits with the leading one dropped. */
    if (topBit >= 23) {
        u32 dropped = 1U << (topBit - 23);
        mantissa = (u32)((magnitude + (dropped >> 1)) / dropped); /* round half up onto 24 bits */
        if (mantissa >= 0x1000000U) {                             /* the rounding carried out */
            mantissa >>= 1;
            topBit++;
        }
        mantissa &= 0x7FFFFF; /* drop the implicit leading one */
    } else {
        mantissa = (magnitude << (23 - topBit)) & 0x7FFFFF;
    }

    exponent = topBit - fracBits + 127;
    if (exponent <= 0 || exponent >= 255) {
        u.bits = sign; /* underflow/overflow: flush to zero, which is safe for these uses */
        return u.value;
    }

    u.bits = sign | ((u32)exponent << 23) | mantissa;
    return u.value;
}

/** Multiply two floats. Normal inputs only; no NaN/inf/denormal handling is needed here. */
static f32 Glacio_F32Mul(f32 a, f32 b) {
    GlacioFloatBits ua;
    GlacioFloatBits ub;
    GlacioFloatBits ur;
    u64 product;
    u32 mantissa;
    s32 exponent;

    ua.value = a;
    ub.value = b;

    if (((ua.bits >> 23) & 0xFF) == 0 || ((ub.bits >> 23) & 0xFF) == 0) {
        ur.bits = (ua.bits ^ ub.bits) & 0x80000000U; /* anything times zero is zero */
        return ur.value;
    }

    exponent = (s32)((ua.bits >> 23) & 0xFF) + (s32)((ub.bits >> 23) & 0xFF) - 127;
    product = (u64)((ua.bits & 0x7FFFFF) | 0x800000) * (u64)((ub.bits & 0x7FFFFF) | 0x800000);

    /* product is in [2^46, 2^48). Round it onto a 24 bit significand in [2^23, 2^24); a product at
     * or above 2^47 needs one more shift, which is worth an extra exponent step. */
    if (product & (1ULL << 47)) {
        product += 1ULL << 23;
        mantissa = (u32)(product >> 24);
        exponent++;
    } else {
        product += 1ULL << 22;
        mantissa = (u32)(product >> 23);
    }
    if (mantissa >= 0x1000000U) { /* the rounding carried out of the significand */
        mantissa >>= 1;
        exponent++;
    }

    if (exponent >= 255) {
        ur.bits = ((ua.bits ^ ub.bits) & 0x80000000U) | 0x7F800000U; /* overflow: signed infinity */
        return ur.value;
    }
    if (exponent <= 0) {
        ur.bits = (ua.bits ^ ub.bits) & 0x80000000U;
        return ur.value;
    }

    ur.bits = ((ua.bits ^ ub.bits) & 0x80000000U) | ((u32)exponent << 23) | (mantissa & 0x7FFFFF);
    /* mantissa's implicit one was already removed by the mask */
    return ur.value;
}

/** Integer squared distance check in the XZ plane (plus a Y bound), avoiding float maths. */
static s32 Glacio_Near(f32 ax, f32 ay, f32 az, f32 bx, f32 by, f32 bz, s32 radius) {
    s32 dx = Glacio_F32ToS32(ax) - Glacio_F32ToS32(bx);
    s32 dy = Glacio_F32ToS32(ay) - Glacio_F32ToS32(by);
    s32 dz = Glacio_F32ToS32(az) - Glacio_F32ToS32(bz);
    s32 limit = radius + 2; /* two units of slack for the truncation of each coordinate */

    if (dx < 0) {
        dx = -dx;
    }
    if (dy < 0) {
        dy = -dy;
    }
    if (dz < 0) {
        dz = -dz;
    }
    if (dx > limit || dz > limit || dy > limit * 2) {
        return false;
    }
    return dx * dx + dy * dy + dz * dz <= radius * radius;
}

#endif /* GLACIO_FLOAT_H */
