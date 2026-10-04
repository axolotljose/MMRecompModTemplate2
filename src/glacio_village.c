/**
 * Glacio Village - The Ice Crystal of the Last Day
 * ------------------------------------------------
 *
 * A self-contained Majora's Mask: Recompiled mod:
 *
 *   1. On the final day (Day 3 by default) a huge ice crystal crystallises in South Clock Town,
 *      right where Link arrived. Standing next to it and pressing A pulls him inside it.
 *   2. The crystal spits him out in Glacio Village - the snowbound Mountain Village, home of the
 *      sorceress Diana. There, a large crystal opens the door into Diana's castle and a small one
 *      leads back to wherever Link came from.
 *   3. Diana's castle is the throne room of Ikana Castle, so the ice door drops Link straight in
 *      front of her. Diana is Igos du Ikana, the frost-bound ghost king: this mod buffs him (more
 *      health, larger, colder) and leaves his behaviour, attacks and moonlight weakness vanilla,
 *      which keeps the fight fair and completely free of custom actor code. Putting her to rest
 *      pays out a reward and freezes the waygate shut for the rest of the 3-day cycle.
 *
 * Why the mod is written this way (Android / cross-platform stability):
 *   - Only RECOMP_HOOK is used, never RECOMP_PATCH or RECOMP_FORCE_PATCH. Hooking cannot conflict
 *     with the base recompilation's own patches (the mobile port patches a number of functions,
 *     and patching one of those from a mod makes the mod fail to load) and it composes with other
 *     mods that hook the same function.
 *   - Every actor this mod spawns lives in `gameplay_keep`, the object that is loaded in every
 *     scene, so no dynamic object loading is required and nothing can be missing at runtime.
 *     `Actor_Spawn` failing (NULL) is handled: the waygate simply does not appear.
 *   - Mod state is never cached as an Actor pointer across frames; the actor lists are rescanned,
 *     so a scene or room change can never leave a dangling pointer behind.
 *   - No UI calls (recompui), no file IO, no native libraries, no RT64-specific features. The
 *     result is a plain .nrm that loads on PC and on the Android port with identical behaviour.
 *   - The only save data touched is rupees (the reward), which is written through the normal
 *     in-game field and clamped. Everything else, including the "quest complete" state, is
 *     per-session and vanishes with the 3-day cycle.
 */

#include "modding.h"
#include "global.h"
#include "recomputils.h"
#include "recompconfig.h"

/** Written into Actor.textId of every crystal this mod places, so the mod can recognise its own
 *  waygates again (and never treats a vanilla ice block as a door). Slot index is added to it. */
#define GLACIO_MARKER 0x4741

/** Ice block params: low byte is the mesh scale in percent, high byte is the "melted" switch
 *  flag; 0xFF means "no switch flag", so a scene switch can never delete a waygate. */
#define GLACIO_ICE_PARAMS(scale) (((s32)0xFF << 8) | ((s32)(scale) & 0xFF))

/** How many frames Diana has to be missing from the room before the fight counts as won. */
#define GLACIO_DIANA_GONE_FRAMES 30

/** `EnKnight` actor params of the Igos instance (the two "others" use 35, the head uses 100). */
#define GLACIO_IGOS_PARAMS_IGOS 0

#define GLACIO_SLOT_TOWN 0   /* Clock Town -> Glacio Village   */
#define GLACIO_SLOT_DOOR 1   /* Glacio Village -> Diana's castle */
#define GLACIO_SLOT_HOME 2   /* Glacio Village -> where you came from */
#define GLACIO_SLOT_FLEE 3   /* Diana's castle -> Glacio Village  */
#define GLACIO_SLOT_COUNT 4

typedef struct {
    /* Cached config. Refreshed once per scene entry, because the per-frame path must not make
     * import calls (config access goes through the host on every call). */
    u8 enabled;
    u8 frostSfx;
    u8 requireDay;
    s32 triggerRadius;   /* proximity radius in game units */
    s16 offsetX;
    s16 offsetZ;
    u8 portalScale;
    u8 returnScale;
    s8 dianaBonusHealth;
    s16 dianaScalePercent;
    s32 victoryRupees;
    u16 glacioEntrance;
    u16 lairEntrance;

    /* Session state. Deliberately never persisted. */
    s16 lastSceneId;
    u16 originEntrance;
    u8 haveOrigin;
    u8 placedMask;
    u8 dianaPresent;
    u8 dianaBuffed;
    u8 dianaDefeated;
    u8 dianaGoneFrames;
    u8 dianaHealthSeen;
    u16 resetCount;
} GlacioState;

static GlacioState sGlacio;

/* ----------------------------------------------------------------- config -- */

/**
 * Read a config option as an integer.
 *
 * Only `recomp_get_config_u32` is used on purpose: Number options are stored as doubles by the
 * host, but the base API truncates them to an integer for u32 reads, which lets this mod avoid
 * double-precision arithmetic entirely. That matters a lot for portability - the MIPS I FPU has no
 * 64-bit float support, so a `(f32)some_double` cast turns into a libgcc call (`__truncdfsf2`) and
 * the mod tool cannot resolve a symbol that the base game does not export, which would make the
 * mod fail to load on every platform.
 */
static s32 Glacio_ConfigInt(const char* key, s32 min, s32 max, s32 fallback) {
    s32 value = (s32)recomp_get_config_u32(key);

    if (value < min || value > max) {
        return fallback;
    }
    return value;
}

static void Glacio_ReadConfig(void) {
    s32 day;

    /* Enum options report the index of the selected entry; "Yes"/"On" are the first entries. */
    sGlacio.enabled = recomp_get_config_u32("enabled") == 0;
    sGlacio.frostSfx = recomp_get_config_u32("frost_sfx") == 0;

    day = Glacio_ConfigInt("crystal_day", 1, 4, 3);
    sGlacio.requireDay = (u8)day;

    sGlacio.triggerRadius = Glacio_ConfigInt("trigger_radius", 20, 2000, 160);

    sGlacio.offsetX = (s16)Glacio_ConfigInt("crystal_offset_x", -600, 600, 150);
    sGlacio.offsetZ = (s16)Glacio_ConfigInt("crystal_offset_z", -600, 600, 150);

    sGlacio.portalScale = (u8)Glacio_ConfigInt("crystal_scale_portal", 10, 255, 150);
    sGlacio.returnScale = (u8)Glacio_ConfigInt("crystal_scale_return", 10, 255, 70);

    sGlacio.dianaBonusHealth = (s8)Glacio_ConfigInt("diana_bonus_health", 0, 200, 20);
    sGlacio.dianaScalePercent = (s16)Glacio_ConfigInt("diana_scale_percent", 10, 400, 130);

    sGlacio.victoryRupees = Glacio_ConfigInt("victory_rupees", 0, 999, 300);

    /* Advanced overrides: 0 keeps the destination that is compiled into the mod. */
    sGlacio.glacioEntrance = (u16)recomp_get_config_u32("glacio_entrance_override");
    sGlacio.lairEntrance = (u16)recomp_get_config_u32("lair_entrance_override");
}

/* ------------------------------------------------------- float-free helpers --
 *
 * Only single precision IEEE-754 work is needed here, and it is done with integer arithmetic on
 * purpose. The MIPS I FPU in the N64 has no double-precision support, and a toolchain configured
 * for -msoft-float (which is what a freestanding MIPS target usually defaults to) lowers *every*
 * float operation, and every int<->float conversion, into a libgcc call: __mulsf3, __addsf3,
 * __fixsfsi, __truncdfsf2 and friends. The base game does not export any of those symbols, so a
 * mod that needs them cannot be linked and fails to load. Keeping the arithmetic in integer form
 * makes the mod compile identically with -msoft-float and -mhard-float, i.e. with clang, zig cc or
 * a mips-elf GCC, and it removes the dependency on a compiler runtime library entirely.
 *
 * All three helpers are exact for the ranges this mod uses (coordinates are 16 bit, percentages
 * are small integers); `tools/test_float_helpers.py` re-implements them and cross-checks them
 * against real float arithmetic.
 */

/*
 * Float work is done by integer-only helpers in include/glacio_float.h, because the soft-float
 * ABI would turn any float operation into a call to a libgcc symbol the base game does not export.
 */
#include "glacio_float.h"


/* --------------------------------------------------------------- utilities -- */

/** True when nothing else is grabbing the screen, so starting a warp is safe. */
static s32 Glacio_CanWarp(PlayState* play) {
    if (gSaveContext.gameMode != GAMEMODE_NORMAL) {
        return false;
    }
    if (play->transitionTrigger != TRANS_TRIGGER_OFF) {
        return false;
    }
    if (play->csCtx.state != CS_STATE_IDLE) {
        return false;
    }
    if (play->actorCtx.totalLoadedActors >= 250) {
        /* Actor_Spawn refuses to work close to the actor limit, so keep out of the way. */
        return false;
    }
    return true;
}

/** Start a white fade into `entrance`, following the game's own warp idiom (see e.g. the tourist
 *  information's gate actor): the entrance index is consumed while the transition runs. */
static void Glacio_Warp(PlayState* play, u16 entrance) {
    play->nextEntrance = entrance;
    play->transitionTrigger = TRANS_TRIGGER_START;
    play->transitionType = TRANS_TYPE_FADE_WHITE;
    /* 0xFFF0 asks the scene loader to derive the destination's day/night state from the entrance
     * instead of forcing one, which is what keeps Clock Town's festival state intact. */
    gSaveContext.nextCutsceneIndex = 0xFFF0;
    gSaveContext.nextTransitionType = TRANS_TYPE_FADE_WHITE;
}

/** Find the mod's crystal for `slot` in the current room, or NULL. The actor lists are rescanned
 *  every time on purpose: actors are freed on room and scene changes, so caching them is unsafe. */
static Actor* Glacio_FindCrystal(PlayState* play, s32 slot) {
    Actor* actor = play->actorCtx.actorLists[ACTORCAT_ITEMACTION].first;
    u16 marker = GLACIO_MARKER + slot;

    while (actor != NULL) {
        if (actor->id == ACTOR_OBJ_ICE_POLY && actor->textId == marker) {
            return actor;
        }
        actor = actor->next;
    }
    return NULL;
}

/** Place one waygate crystal next to the spot Link entered this room at, so it always stands on
 *  ground he can reach and never inside a wall. Returns NULL if the game refused to spawn it. */
static Actor* Glacio_SpawnCrystal(PlayState* play, s32 slot, s16 dx, s16 dz, s32 scale) {
    Actor* playerActor;
    Actor* crystal;
    s32 baseX;
    s32 baseY;
    s32 baseZ;

    if (play->actorCtx.actorLists[ACTORCAT_PLAYER].first == NULL) {
        return NULL;
    }
    playerActor = play->actorCtx.actorLists[ACTORCAT_PLAYER].first;

    /* Actor.home is a float position, so it is pulled into integer space with the truncating
     * helper, offset there, and turned back into floats; no int<->float conversion is emitted. */
    baseX = Glacio_F32ToS32(playerActor->home.pos.x);
    baseY = Glacio_F32ToS32(playerActor->home.pos.y);
    baseZ = Glacio_F32ToS32(playerActor->home.pos.z);

    crystal = Actor_Spawn(&play->actorCtx, play, ACTOR_OBJ_ICE_POLY,
                          Glacio_S32ToF32Scaled(baseX + dx, 0), Glacio_S32ToF32Scaled(baseY, 0),
                          Glacio_S32ToF32Scaled(baseZ + dz, 0), 0, 0, 0, GLACIO_ICE_PARAMS(scale));
    if (crystal == NULL) {
        return NULL;
    }

    crystal->textId = (u16)(GLACIO_MARKER + slot);
    crystal->flags |= ACTOR_FLAG_UPDATE_CULLING_DISABLED;
    return crystal;
}

/** True when Link is close enough to `crystal` and pressed A on this frame. */
static s32 Glacio_CrystalActivated(PlayState* play, Actor* crystal) {
    Vec3f playerPos;
    Vec3f crystalPos;
    s32 radius = sGlacio.triggerRadius;

    if (crystal == NULL) {
        return false;
    }
    if (play->actorCtx.actorLists[ACTORCAT_PLAYER].first == NULL) {
        return false;
    }

    playerPos = GET_PLAYER(play)->actor.world.pos;
    crystalPos = crystal->world.pos;

    if (!Glacio_Near(playerPos.x, playerPos.y, playerPos.z, crystalPos.x, crystalPos.y, crystalPos.z,
                     radius)) {
        return false;
    }

    return (play->state.input[0].press.button & A_BUTTON) != 0;
}

/** Diana herself, if this room contains her. She is placed by the scene, never spawned here, so
 *  the whole fight (music, curtains, moonlight, his death) stays vanilla. */
static Actor* Glacio_FindDiana(PlayState* play) {
    Actor* actor = play->actorCtx.actorLists[ACTORCAT_BOSS].first;

    while (actor != NULL) {
        if (actor->id == ACTOR_EN_KNIGHT && actor->params == GLACIO_IGOS_PARAMS_IGOS) {
            return actor;
        }
        actor = actor->next;
    }
    return NULL;
}

/* ------------------------------------------------------------ scene set-up -- */

static void Glacio_PlaceWaygates(PlayState* play, s32 sceneId) {
    sGlacio.placedMask = 0;
    sGlacio.dianaPresent = false;
    sGlacio.dianaBuffed = false;
    sGlacio.dianaGoneFrames = 0;

    if (!sGlacio.enabled || CURRENT_DAY != sGlacio.requireDay) {
        return;
    }

    switch (sceneId) {
        case SCENE_TOWN:
            /* South Clock Town: the only way in, and the origin the return crystal uses. */
            if (Glacio_SpawnCrystal(play, GLACIO_SLOT_TOWN, sGlacio.offsetX, sGlacio.offsetZ,
                                    sGlacio.portalScale) != NULL) {
                sGlacio.placedMask |= 1 << GLACIO_SLOT_TOWN;
                sGlacio.originEntrance = (u16)gSaveContext.save.entrance;
                sGlacio.haveOrigin = true;
                if (!sGlacio.dianaDefeated) {
                    recomp_printf("[glacio] An ice crystal has formed in the town square.\n");
                }
            }
            break;

        case SCENE_10YUKIYAMANOMURA:
            /* Glacio Village: the door to the castle, and a way back out. */
            if (!sGlacio.dianaDefeated) {
                if (Glacio_SpawnCrystal(play, GLACIO_SLOT_DOOR, sGlacio.offsetX, -sGlacio.offsetZ,
                                        sGlacio.portalScale) != NULL) {
                    sGlacio.placedMask |= 1 << GLACIO_SLOT_DOOR;
                }
            }
            if (sGlacio.haveOrigin) {
                if (Glacio_SpawnCrystal(play, GLACIO_SLOT_HOME, -sGlacio.offsetX, sGlacio.offsetZ,
                                        sGlacio.returnScale) != NULL) {
                    sGlacio.placedMask |= 1 << GLACIO_SLOT_HOME;
                }
            }
            recomp_printf("[glacio] Glacio Village. Diana's castle lies beyond the large crystal.\n");
            break;

        case SCENE_IKNINSIDE:
            /* Diana's throne room: always leave the player a way out of the fight. */
            if (Glacio_SpawnCrystal(play, GLACIO_SLOT_FLEE, -sGlacio.offsetX, -sGlacio.offsetZ,
                                    sGlacio.returnScale) != NULL) {
                sGlacio.placedMask |= 1 << GLACIO_SLOT_FLEE;
            }
            break;

        default:
            break;
    }
}

/* -------------------------------------------------------------- the boss -- */

static void Glacio_UpdateDiana(PlayState* play) {
    Actor* diana = Glacio_FindDiana(play);

    if (diana == NULL) {
        if (sGlacio.dianaPresent && !sGlacio.dianaDefeated) {
            sGlacio.dianaGoneFrames++;
            if (sGlacio.dianaGoneFrames >= GLACIO_DIANA_GONE_FRAMES) {
                /* She has left the world: the sorceress of Glacio has been put to rest. */
                sGlacio.dianaDefeated = true;
                sGlacio.dianaPresent = false;
                if (sGlacio.victoryRupees > 0) {
                    s32 rupees = gSaveContext.save.saveInfo.playerData.rupees + sGlacio.victoryRupees;
                    if (rupees > 999) {
                        rupees = 999;
                    }
                    gSaveContext.save.saveInfo.playerData.rupees = (s16)rupees;
                }
                if (sGlacio.frostSfx) {
                    Audio_PlaySfx(NA_SE_EN_COMMON_FREEZE);
                }
                recomp_printf("[glacio] Diana is gone. The waygate to her castle has frozen shut.\n");
            }
        }
        return;
    }

    sGlacio.dianaGoneFrames = 0;

    if (!sGlacio.dianaPresent) {
        sGlacio.dianaPresent = true;
        sGlacio.dianaHealthSeen = diana->colChkInfo.health;
        if (sGlacio.frostSfx) {
            Audio_PlaySfx(NA_SE_EN_WIZ_VOICE);
        }
        recomp_printf("[glacio] Diana, sorceress of Glacio, bars the way out.\n");
    }

    if (sGlacio.dianaBuffed) {
        return;
    }
    sGlacio.dianaBuffed = true;

    if (sGlacio.dianaBonusHealth > 0) {
        /* colChkInfo.health is a u8, so clamp instead of wrapping around to a trivial fight. */
        s32 health = diana->colChkInfo.health + sGlacio.dianaBonusHealth;
        diana->colChkInfo.health = health > 255 ? 255 : (u8)health;
    }

    /* Igos' skeleton is authored oversized and the game shrinks it with a tiny scale factor, so
     * grow him relative to whatever the game chose rather than overwriting it. */
    Actor_SetScale(diana, Glacio_F32Mul(diana->scale.x,
                                        Glacio_S32ToF32Scaled(sGlacio.dianaScalePercent * 65536 / 100,
                                                              16)));
}

/* ---------------------------------------------------------------- the hook -- */

/**
 * The driving hook: Player_Update runs once per frame while Link is in the world. This mod
 * deliberately hooks it instead of replacing it, which keeps it compatible with the base
 * recompilation's own patch of the same function and with any other mod hooking it too.
 */
RECOMP_HOOK("Player_Update")
void Glacio_OnPlayerUpdate(Actor* playerActor, PlayState* play) {
    s32 sceneId;
    u16 resetCount;
    Actor* crystal;

    if (play == NULL || playerActor == NULL) {
        return;
    }

    resetCount = gSaveContext.save.saveInfo.playerData.threeDayResetCount;
    if (resetCount != sGlacio.resetCount) {
        /* A new 3-day cycle began: everything has to form again. */
        sGlacio.resetCount = resetCount;
        sGlacio.placedMask = 0;
        sGlacio.haveOrigin = false;
        sGlacio.originEntrance = 0;
        sGlacio.dianaPresent = false;
        sGlacio.dianaBuffed = false;
        sGlacio.dianaDefeated = false;
        sGlacio.lastSceneId = -1;
    }

    sceneId = play->sceneId;
    if (sceneId != sGlacio.lastSceneId) {
        sGlacio.lastSceneId = (s16)sceneId;
        Glacio_ReadConfig();
        Glacio_PlaceWaygates(play, sceneId);
    }

    if (!sGlacio.enabled) {
        return;
    }

    if (CURRENT_DAY != sGlacio.requireDay) {
        return;
    }

    if (sceneId == SCENE_IKNINSIDE) {
        Glacio_UpdateDiana(play);
    }

    if (!Glacio_CanWarp(play)) {
        return;
    }

    if (sceneId == SCENE_TOWN) {
        if ((sGlacio.placedMask & (1 << GLACIO_SLOT_TOWN)) && !sGlacio.dianaDefeated) {
            if (Glacio_CrystalActivated(play, Glacio_FindCrystal(play, GLACIO_SLOT_TOWN))) {
                if (sGlacio.frostSfx) {
                    Audio_PlaySfx(NA_SE_EN_COMMON_FREEZE);
                }
                Glacio_Warp(play, sGlacio.glacioEntrance != 0 ? sGlacio.glacioEntrance
                                                              : ENTRANCE(MOUNTAIN_VILLAGE_WINTER, 0));
            }
        }
    } else if (sceneId == SCENE_10YUKIYAMANOMURA) {
        crystal = Glacio_FindCrystal(play, GLACIO_SLOT_DOOR);
        if ((sGlacio.placedMask & (1 << GLACIO_SLOT_DOOR)) &&
            Glacio_CrystalActivated(play, crystal)) {
            if (sGlacio.frostSfx) {
                Audio_PlaySfx(NA_SE_EN_COMMON_FREEZE);
            }
            Glacio_Warp(play, sGlacio.lairEntrance != 0 ? sGlacio.lairEntrance
                                                        : ENTRANCE(IGOS_DU_IKANAS_LAIR, 0));
        } else if ((sGlacio.placedMask & (1 << GLACIO_SLOT_HOME)) && sGlacio.haveOrigin &&
                   Glacio_CrystalActivated(play, Glacio_FindCrystal(play, GLACIO_SLOT_HOME))) {
            Glacio_Warp(play, sGlacio.originEntrance);
        }
    } else if (sceneId == SCENE_IKNINSIDE) {
        if ((sGlacio.placedMask & (1 << GLACIO_SLOT_FLEE)) &&
            Glacio_CrystalActivated(play, Glacio_FindCrystal(play, GLACIO_SLOT_FLEE))) {
            Glacio_Warp(play, sGlacio.glacioEntrance != 0 ? sGlacio.glacioEntrance
                                                          : ENTRANCE(MOUNTAIN_VILLAGE_WINTER, 0));
        }
    }
}
