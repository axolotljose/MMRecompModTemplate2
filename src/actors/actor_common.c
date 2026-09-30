/**
 * Custom actor registration and shared helpers.
 *
 * Registration: the game's actor table (gActorOverlayTable) has many unused entries. The vanilla spawn code already
 * supports entries without an overlay (vramStart == NULL): it simply uses the entry's profile. So a custom actor only
 * needs an unused entry to point at its ActorProfile; nothing has to be patched. The scene data refers to actors through
 * placeholder ids (LIL_ACTOR_ID) which are replaced with the real ids here.
 */

#include "lil_actor.h"

s16 gLilActorIds[LIL_ACT_COUNT];

LilActorDef gLilActorDefs[LIL_ACT_COUNT] = {
    [LIL_ACT_LILITH_STATUE] = { &LilStatue_Profile, "Lil_Statue" },
    [LIL_ACT_RETURN_PORTAL] = { &LilPortal_Profile, "Lil_Portal" },
    [LIL_ACT_BARRIER] = { &LilBarrier_Profile, "Lil_Barrier" },
    [LIL_ACT_PLATE] = { &LilPlate_Profile, "Lil_Plate" },
    [LIL_ACT_PATH_PUZZLE] = { &LilPath_Profile, "Lil_Path" },
    [LIL_ACT_BRAMBLE] = { &LilBramble_Profile, "Lil_Bramble" },
    [LIL_ACT_ARENA] = { &LilArena_Profile, "Lil_Arena" },
    [LIL_ACT_THORNLING] = { &LilThornling_Profile, "Lil_Thornling" },
    [LIL_ACT_PETAL_WISP] = { &LilWisp_Profile, "Lil_Wisp" },
    [LIL_ACT_ROSE_KNIGHT] = { &LilKnight_Profile, "Lil_Knight" },
    [LIL_ACT_HAZARD] = { &LilHazard_Profile, "Lil_Hazard" },
    [LIL_ACT_BOSS_WARDEN] = { &LilWarden_Profile, "Lil_Warden" },
    [LIL_ACT_BOSS_QUEEN] = { &LilQueen_Profile, "Lil_Queen" },
};

static s32 Lil_IsFreeOverlayEntry(ActorOverlay* e) {
    return (e->vramStart == NULL) && (e->vramEnd == NULL) && (e->profile == NULL) && (e->loadedRamAddr == NULL) &&
           (e->file.vromStart == 0) && (e->file.vromEnd == 0);
}

// Some unused table entry, used as the destination of placeholders that could not be registered: spawning an unused entry
// is a harmless no-op in the vanilla spawn code (its profile is NULL). Returns 0 if there is none.
static s16 Lil_FindEmptyActorId(void) {
    s32 id;

    for (id = 1; id < ACTOR_ID_MAX; id++) {
        if (Lil_IsFreeOverlayEntry(&gActorOverlayTable[id])) {
            return id;
        }
    }
    return 0;
}

// Replaces the placeholder ids used by the generated actor lists with the real (registered) ids.
static void Lil_RemapActorLists(void) {
    s16 emptyId = Lil_FindEmptyActorId();
    s32 i;
    s32 j;

    for (i = 0; i < gLilNumActorLists; i++) {
        ActorEntry* entries = gLilActorLists[i].entries;

        for (j = 0; j < gLilActorLists[i].count; j++) {
            s32 id = entries[j].id & 0x1FFF;

            if ((id >= LIL_ACTOR_PLACEHOLDER_BASE) && (id < (LIL_ACTOR_PLACEHOLDER_BASE + LIL_ACT_COUNT))) {
                s16 real = gLilActorIds[id - LIL_ACTOR_PLACEHOLDER_BASE];

                if (real == 0) {
                    real = emptyId; // not registered: make the entry spawn nothing rather than something wrong
                }
                if (real != 0) {
                    entries[j].id = (entries[j].id & ~0x1FFF) | real;
                }
            }
        }
    }
}

void Lil_RegisterActors(void) {
    s32 slot;
    s32 id;

    for (slot = 0; slot < LIL_ACT_COUNT; slot++) {
        ActorProfile* profile = gLilActorDefs[slot].profile;
        ActorOverlay* entry;

        if ((gLilActorIds[slot] != 0) && (gActorOverlayTable[gLilActorIds[slot]].profile == profile)) {
            continue; // already registered (this runs on every scene load)
        }

        // Scan from the end of the table so we stay out of the way of anything that scans from the start.
        for (id = ACTOR_ID_MAX - 1; id > 0; id--) {
            if (Lil_IsFreeOverlayEntry(&gActorOverlayTable[id])) {
                break;
            }
        }
        if (id <= 0) {
            recomp_printf("[lilith] no free actor table entry for %s\n", gLilActorDefs[slot].name);
            continue;
        }

        entry = &gActorOverlayTable[id];
        profile->id = id;
        entry->profile = profile;
        entry->vramStart = NULL;
        entry->vramEnd = NULL;
        entry->loadedRamAddr = NULL;
        entry->name = (char*)gLilActorDefs[slot].name;
        entry->allocType = ALLOCTYPE_NORMAL;
        entry->numLoaded = 0;
        gLilActorIds[slot] = id;
    }

    Lil_RemapActorLists();
}

/* ------------------------------------------------------------------------------------------------------------------
 * Drawing
 * ---------------------------------------------------------------------------------------------------------------- */
static Gfx sLilLitOpaSetupDL[] = {
    gsDPPipeSync(),
    gsSPTexture(0xFFFF, 0xFFFF, 0, G_TX_RENDERTILE, G_ON),
    gsDPSetCombineLERP(PRIMITIVE, 0, SHADE, 0, 0, 0, 0, PRIMITIVE, PRIMITIVE, 0, SHADE, 0, 0, 0, 0, PRIMITIVE),
    gsSPEndDisplayList(),
};

static Gfx sLilLitXluSetupDL[] = {
    gsDPPipeSync(),
    gsSPTexture(0xFFFF, 0xFFFF, 0, G_TX_RENDERTILE, G_ON),
    gsDPSetCombineLERP(PRIMITIVE, 0, SHADE, 0, 0, 0, 0, ENVIRONMENT, PRIMITIVE, 0, SHADE, 0, 0, 0, 0, ENVIRONMENT),
    gsSPEndDisplayList(),
};

// Same as above but the result is multiplied by the environment colour, so parts can be tinted (set with gDPSetEnvColor).
static Gfx sLilLitOpaTintSetupDL[] = {
    gsDPPipeSync(),
    gsSPTexture(0xFFFF, 0xFFFF, 0, G_TX_RENDERTILE, G_ON),
    gsDPSetCombineLERP(PRIMITIVE, 0, SHADE, 0, 0, 0, 0, PRIMITIVE, COMBINED, 0, ENVIRONMENT, 0, 0, 0, 0, COMBINED),
    gsSPEndDisplayList(),
};

void Lil_SetupLitOpaTint(PlayState* play) {
    OPEN_DISPS(play->state.gfxCtx);

    Gfx_SetupDL25_Opa(play->state.gfxCtx);
    gSPDisplayList(POLY_OPA_DISP++, sLilLitOpaTintSetupDL);

    CLOSE_DISPS(play->state.gfxCtx);
}

void Lil_SetupLitOpa(PlayState* play) {
    OPEN_DISPS(play->state.gfxCtx);

    Gfx_SetupDL25_Opa(play->state.gfxCtx);
    gSPDisplayList(POLY_OPA_DISP++, sLilLitOpaSetupDL);

    CLOSE_DISPS(play->state.gfxCtx);
}

void Lil_SetupLitXlu(PlayState* play, u8 alpha) {
    OPEN_DISPS(play->state.gfxCtx);

    Gfx_SetupDL25_Xlu(play->state.gfxCtx);
    gSPDisplayList(POLY_XLU_DISP++, sLilLitXluSetupDL);
    gDPSetEnvColor(POLY_XLU_DISP++, 0, 0, 0, alpha);

    CLOSE_DISPS(play->state.gfxCtx);
}

void Lil_DrawPart(PlayState* play, Gfx* dl, f32 x, f32 y, f32 z, s16 rotX, s16 rotY, s16 rotZ, f32 scaleX, f32 scaleY,
                  f32 scaleZ, s32 xlu) {
    OPEN_DISPS(play->state.gfxCtx);

    Matrix_Push();
    Matrix_Translate(x, y, z, MTXMODE_APPLY);
    Matrix_RotateYS(rotY, MTXMODE_APPLY);
    Matrix_RotateXS(rotX, MTXMODE_APPLY);
    Matrix_RotateZS(rotZ, MTXMODE_APPLY);
    Matrix_Scale(scaleX, scaleY, scaleZ, MTXMODE_APPLY);
    if (xlu) {
        MATRIX_FINALIZE_AND_LOAD(POLY_XLU_DISP++, play->state.gfxCtx);
        gSPDisplayList(POLY_XLU_DISP++, dl);
    } else {
        MATRIX_FINALIZE_AND_LOAD(POLY_OPA_DISP++, play->state.gfxCtx);
        gSPDisplayList(POLY_OPA_DISP++, dl);
    }
    Matrix_Pop();

    CLOSE_DISPS(play->state.gfxCtx);
}

void Lil_Puff(PlayState* play, Vec3f* pos, f32 scale) {
    func_800B3030(play, pos, &gZeroVec3f, &gZeroVec3f, (s16)scale, 0, 0);
}

/* ------------------------------------------------------------------------------------------------------------------
 * Enemies
 * ---------------------------------------------------------------------------------------------------------------- */
Actor* Lil_SpawnActor(PlayState* play, Actor* parent, LilActorSlot slot, f32 x, f32 y, f32 z, s16 rotX, s16 rotY, s16 rotZ,
                      s32 params) {
    s16 id = gLilActorIds[slot];

    if (id == 0) {
        return NULL; // 0 would be ACTOR_PLAYER
    }
    if (parent != NULL) {
        return Actor_SpawnAsChild(&play->actorCtx, parent, play, id, x, y, z, rotX, rotY, rotZ, params);
    }
    return Actor_Spawn(&play->actorCtx, play, id, x, y, z, rotX, rotY, rotZ, params);
}

s32 Lil_IsLilEnemyId(s16 actorId) {
    if (actorId == 0) {
        return false;
    }
    return (actorId == gLilActorIds[LIL_ACT_THORNLING]) || (actorId == gLilActorIds[LIL_ACT_PETAL_WISP]) ||
           (actorId == gLilActorIds[LIL_ACT_ROSE_KNIGHT]);
}

s32 Lil_SleepPulse(PlayState* play, f32 radius, s16 frames) {
    Player* player = GET_PLAYER(play);
    Actor* actor = play->actorCtx.actorLists[ACTORCAT_ENEMY].first;
    s32 count = 0;

    while (actor != NULL) {
        if (Lil_IsLilEnemyId(actor->id) && (Actor_WorldDistXZToActor(&player->actor, actor) < radius)) {
            LilEnemyBase* enemy = (LilEnemyBase*)actor;

            if (enemy->sleepTimer <= 0) {
                count++;
            }
            enemy->sleepTimer = frames;
        }
        actor = actor->next;
    }
    return count;
}

s32 Lil_CountLilEnemies(PlayState* play) {
    Actor* actor = play->actorCtx.actorLists[ACTORCAT_ENEMY].first;
    s32 count = 0;

    while (actor != NULL) {
        if (Lil_IsLilEnemyId(actor->id) && (actor->update != NULL)) {
            count++;
        }
        actor = actor->next;
    }
    return count;
}
