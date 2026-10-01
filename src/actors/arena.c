/**
 * Wave arenas and hazards.
 *
 * An arena controller sits in the middle of a room. When the player walks in it spawns waves of enemies (as its
 * children) and, once the last wave is dead, sets the switch flag that opens the next gate.
 * Hazards are the projectiles / ground spikes used by the enemies and the bosses.
 */

#include "lil_actor.h"

static InitChainEntry sArenaInitChain[] = {
    ICHAIN_F32(cullingVolumeDistance, 4500, ICHAIN_STOP),
};

/* ==================================================================================================================
 * Arena controller
 * ================================================================================================================ */
typedef struct LilWaveSpawn {
    s16 slot; // LilActorSlot
    s16 dx;   // offset from the arena centre
    s16 dz;
} LilWaveSpawn;

typedef struct LilWave {
    const LilWaveSpawn* spawns;
    s16 count;
} LilWave;

typedef struct LilArenaDef {
    f32 triggerRadius;
    u8 flag;
    const LilWave* waves;
    s16 numWaves;
} LilArenaDef;

// Arena 0: the Petal Gallery
static const LilWaveSpawn sGalleryWave0[] = {
    { LIL_ACT_PETAL_WISP, -250, -380 },
    { LIL_ACT_PETAL_WISP, 250, -380 },
    { LIL_ACT_PETAL_WISP, 0, -440 },
};
static const LilWaveSpawn sGalleryWave1[] = {
    { LIL_ACT_THORNLING, -240, -420 },
    { LIL_ACT_THORNLING, 240, -420 },
    { LIL_ACT_PETAL_WISP, -150, -300 },
    { LIL_ACT_PETAL_WISP, 150, -300 },
};
static const LilWave sGalleryWaves[] = {
    { sGalleryWave0, ARRAY_COUNT(sGalleryWave0) },
    { sGalleryWave1, ARRAY_COUNT(sGalleryWave1) },
};

// Arena 1: the Sentinel Hall (Rose Knights)
static const LilWaveSpawn sSentinelWave0[] = {
    { LIL_ACT_ROSE_KNIGHT, -300, -400 },
    { LIL_ACT_ROSE_KNIGHT, 300, -400 },
};
static const LilWaveSpawn sSentinelWave1[] = {
    { LIL_ACT_ROSE_KNIGHT, -320, -380 },
    { LIL_ACT_ROSE_KNIGHT, 320, -380 },
    { LIL_ACT_THORNLING, 0, -440 },
};
static const LilWave sSentinelWaves[] = {
    { sSentinelWave0, ARRAY_COUNT(sSentinelWave0) },
    { sSentinelWave1, ARRAY_COUNT(sSentinelWave1) },
};

static const LilArenaDef sArenas[] = {
    { 560.0f, LIL_FLAG_GALLERY_CLEAR, sGalleryWaves, ARRAY_COUNT(sGalleryWaves) },
    { 620.0f, LIL_FLAG_KNIGHTS_CLEAR, sSentinelWaves, ARRAY_COUNT(sSentinelWaves) },
};

enum { ARENA_IDLE, ARENA_SPAWN_DELAY, ARENA_FIGHTING, ARENA_DONE };

static s32 EnLilArena_CountAlive(EnLilArena* this, PlayState* play) {
    Actor* actor = play->actorCtx.actorLists[ACTORCAT_ENEMY].first;
    s32 count = 0;

    while (actor != NULL) {
        if ((actor->parent == &this->actor) && (actor->update != NULL)) {
            count++;
        }
        actor = actor->next;
    }
    return count;
}

static void EnLilArena_SpawnWave(EnLilArena* this, PlayState* play, const LilArenaDef* def) {
    const LilWave* wave = &def->waves[this->wave];
    s32 i;

    for (i = 0; i < wave->count; i++) {
        const LilWaveSpawn* spawn = &wave->spawns[i];
        f32 x = this->actor.home.pos.x + spawn->dx;
        f32 z = this->actor.home.pos.z + spawn->dz;
        f32 y = this->actor.home.pos.y + ((spawn->slot == LIL_ACT_PETAL_WISP) ? 90.0f : 0.0f);
        Vec3f spawnPos;
        s16 yaw;

        spawnPos.x = x;
        spawnPos.y = y;
        spawnPos.z = z;
        yaw = Math_Vec3f_Yaw(&spawnPos, &this->actor.home.pos);

        if (Lil_SpawnActor(play, &this->actor, spawn->slot, x, y, z, 0, yaw, 0, LIL_ENEMY_PARAM_AWAKE) != NULL) {
            Vec3f pos;

            pos.x = x;
            pos.y = y + 20.0f;
            pos.z = z;
            Lil_Puff(play, &pos, 120.0f);
        }
    }
    this->wave++;
}

void EnLilArena_Init(Actor* thisx, PlayState* play) {
    EnLilArena* this = (EnLilArena*)thisx;

    Actor_ProcessInitChain(&this->actor, sArenaInitChain);
    Actor_SetScale(&this->actor, 1.0f);
    this->arenaId = this->actor.params & 0xFF;
    if (this->arenaId >= ARRAY_COUNT(sArenas)) {
        Actor_Kill(&this->actor);
        return;
    }
    this->state = Flags_GetSwitch(play, sArenas[this->arenaId].flag) ? ARENA_DONE : ARENA_IDLE;
}

void EnLilArena_Destroy(Actor* thisx, PlayState* play) {
}

void EnLilArena_Update(Actor* thisx, PlayState* play) {
    EnLilArena* this = (EnLilArena*)thisx;
    const LilArenaDef* def = &sArenas[this->arenaId];

    switch (this->state) {
        case ARENA_IDLE:
            if (this->actor.xzDistToPlayer < def->triggerRadius) {
                this->state = ARENA_SPAWN_DELAY;
                this->timer = 30;
                Audio_PlaySfx(NA_SE_SY_ERROR);
            }
            break;

        case ARENA_SPAWN_DELAY:
            if (this->timer > 0) {
                this->timer--;
            } else {
                EnLilArena_SpawnWave(this, play, def);
                this->state = ARENA_FIGHTING;
                this->timer = 10;
            }
            break;

        case ARENA_FIGHTING:
            if (this->timer > 0) {
                this->timer--; // give freshly spawned enemies a moment to exist before counting
                break;
            }
            this->alive = EnLilArena_CountAlive(this, play);
            if (this->alive == 0) {
                if (this->wave < def->numWaves) {
                    this->state = ARENA_SPAWN_DELAY;
                    this->timer = 25;
                } else {
                    this->state = ARENA_DONE;
                    Flags_SetSwitch(play, def->flag);
                    Audio_PlaySfx(NA_SE_SY_CORRECT_CHIME);
                }
            }
            break;

        default:
            break;
    }
}

void EnLilArena_Draw(Actor* thisx, PlayState* play) {
}

ActorProfile LilArena_Profile = {
    /**/ 0,
    /**/ ACTORCAT_PROP,
    /**/ ACTOR_FLAG_UPDATE_CULLING_DISABLED,
    /**/ GAMEPLAY_KEEP,
    /**/ sizeof(EnLilArena),
    /**/ EnLilArena_Init,
    /**/ EnLilArena_Destroy,
    /**/ EnLilArena_Update,
    /**/ EnLilArena_Draw,
};

/* ==================================================================================================================
 * Hazards: petal shots and thorn spikes
 * params: type (bits 0-3) | speed (bits 4-7, petal shots only)
 * ================================================================================================================ */
#define HAZARD_SPIKE_HEIGHT 90.0f
#define HAZARD_SPIKE_TELEGRAPH 18
#define HAZARD_SPIKE_ERUPT 14
#define HAZARD_SPIKE_LINGER 14
#define HAZARD_SPIKE_RETRACT 14
#define HAZARD_PETAL_LIFETIME 70

typedef struct EnLilHazard {
    /* 0x000 */ Actor actor;
    /* 0x144 */ ColliderCylinder collider;
    /* 0x190 */ s16 timer;
    /* 0x192 */ s16 type;
    /* 0x194 */ s16 spin;
    /* 0x196 */ s16 pad;
    /* 0x198 */ f32 height;
} EnLilHazard;

static ColliderCylinderInit sHazardCylinderInit = {
    {
        COL_MATERIAL_HIT0,
        AT_ON | AT_TYPE_ENEMY,
        AC_NONE,
        OC1_NONE,
        OC2_NONE,
        COLSHAPE_CYLINDER,
    },
    {
        ELEM_MATERIAL_UNK0,
        { 0xF7CFFFFF, 0x00, 0x08 },
        { 0x00000000, 0x00, 0x00 },
        ATELEM_ON | ATELEM_SFX_NORMAL,
        ACELEM_NONE,
        OCELEM_NONE,
    },
    { 14, 28, 0, { 0, 0, 0 } },
};

Actor* Lil_SpawnHazard(PlayState* play, s32 type, f32 x, f32 y, f32 z, s16 yaw, s32 speed) {
    return Lil_SpawnActor(play, NULL, LIL_ACT_HAZARD, x, y, z, 0, yaw, 0, (type & 0xF) | ((speed & 0xF) << 4));
}

void EnLilHazard_Init(Actor* thisx, PlayState* play) {
    EnLilHazard* this = (EnLilHazard*)thisx;

    Actor_ProcessInitChain(&this->actor, sArenaInitChain);
    Actor_SetScale(&this->actor, 1.0f);
    this->type = this->actor.params & 0xF;
    Collider_InitCylinder(play, &this->collider);
    Collider_SetCylinder(play, &this->collider, &this->actor, &sHazardCylinderInit);

    if (this->type == LIL_HAZARD_PETAL) {
        this->actor.speed = (this->actor.params >> 4) & 0xF;
        if (this->actor.speed < 2.0f) {
            this->actor.speed = 5.0f;
        }
        this->timer = HAZARD_PETAL_LIFETIME;
    } else {
        this->collider.dim.radius = 20;
        this->collider.elem.atDmgInfo.damage = 0x10; // a thorn through the foot hurts more than a petal (1 heart vs 1/2)
        this->timer = 0;
        this->height = 0.0f;
        this->collider.base.atFlags &= ~AT_ON;
    }
    Collider_UpdateCylinder(&this->actor, &this->collider);
}

void EnLilHazard_Destroy(Actor* thisx, PlayState* play) {
    EnLilHazard* this = (EnLilHazard*)thisx;

    Collider_DestroyCylinder(play, &this->collider);
}

void EnLilHazard_Update(Actor* thisx, PlayState* play) {
    EnLilHazard* this = (EnLilHazard*)thisx;

    if (this->type == LIL_HAZARD_PETAL) {
        this->spin += 0x700;
        this->timer--;
        Actor_MoveWithoutGravity(&this->actor);
        Actor_UpdateBgCheckInfo(play, &this->actor, 10.0f, 10.0f, 10.0f, UPDBGCHECKINFO_FLAG_1);
        if ((this->timer <= 0) || (this->collider.base.atFlags & AT_HIT) || (this->actor.bgCheckFlags & BGCHECKFLAG_WALL)) {
            Vec3f pos = this->actor.world.pos;

            Lil_Puff(play, &pos, 40.0f);
            Actor_Kill(&this->actor);
            return;
        }
        Collider_UpdateCylinder(&this->actor, &this->collider);
        CollisionCheck_SetAT(play, &play->colChkCtx, &this->collider.base);
        return;
    }

    // thorn spike
    this->timer++;
    if (this->timer < HAZARD_SPIKE_TELEGRAPH) {
        this->height = 10.0f + 14.0f * ((f32)this->timer / HAZARD_SPIKE_TELEGRAPH);
    } else if (this->timer < (HAZARD_SPIKE_TELEGRAPH + HAZARD_SPIKE_ERUPT)) {
        if (this->timer == HAZARD_SPIKE_TELEGRAPH) {
            Actor_PlaySfx(&this->actor, NA_SE_EV_BLOCK_BOUND);
            this->collider.base.atFlags |= AT_ON;
        }
        this->height += (HAZARD_SPIKE_HEIGHT - this->height) * 0.45f;
    } else if (this->timer < (HAZARD_SPIKE_TELEGRAPH + HAZARD_SPIKE_ERUPT + HAZARD_SPIKE_LINGER)) {
        this->height = HAZARD_SPIKE_HEIGHT;
    } else if (this->timer < (HAZARD_SPIKE_TELEGRAPH + HAZARD_SPIKE_ERUPT + HAZARD_SPIKE_LINGER + HAZARD_SPIKE_RETRACT)) {
        this->collider.base.atFlags &= ~AT_ON;
        this->height *= 0.7f;
    } else {
        Actor_Kill(&this->actor);
        return;
    }
    this->collider.dim.height = (s16)this->height;
    Collider_UpdateCylinder(&this->actor, &this->collider);
    if (this->collider.base.atFlags & AT_ON) {
        CollisionCheck_SetAT(play, &play->colChkCtx, &this->collider.base);
    }
}

void EnLilHazard_Draw(Actor* thisx, PlayState* play) {
    EnLilHazard* this = (EnLilHazard*)thisx;

    Lil_SetupLitOpa(play);
    if (this->type == LIL_HAZARD_PETAL) {
        Lil_DrawPart(play, gLilPetalShot_PetalDL, 0, 12, 0, 0, 0, this->spin, 1.0f, 1.0f, 1.0f, false);
    } else {
        Lil_DrawPart(play, gLilThornSpike_SpikeDL, 0, this->height - HAZARD_SPIKE_HEIGHT, 0, 0, 0, 0, 1.0f, 1.0f, 1.0f, false);
    }
}

ActorProfile LilHazard_Profile = {
    /**/ 0,
    /**/ ACTORCAT_MISC,
    /**/ ACTOR_FLAG_UPDATE_CULLING_DISABLED | ACTOR_FLAG_DRAW_CULLING_DISABLED,
    /**/ GAMEPLAY_KEEP,
    /**/ sizeof(EnLilHazard),
    /**/ EnLilHazard_Init,
    /**/ EnLilHazard_Destroy,
    /**/ EnLilHazard_Update,
    /**/ EnLilHazard_Draw,
};
