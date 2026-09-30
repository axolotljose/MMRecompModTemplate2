/**
 * The three new enemies of the Thornbound Crypt.
 *
 *   Thornling    a bramble ball that lies dormant until you get close, then rolls after you and lunges.
 *   Petal Wisp   a floating wisp ringed with petals: it circles, pelts you with petals and dive-bombs.
 *   Rose Knight  an armoured guardian with a shield. The shield blocks normal attacks from the front: hit it from behind,
 *                use something heavy (bombs, spin attack), or play Lilith's Lullaby to put it to sleep and strike freely.
 *
 * All of them can be lulled to sleep by the song (see Lil_SleepPulse). Sleeping enemies do not attack and take double
 * damage.
 */

#include "lil_actor.h"

#define ENEMY_FLAGS (ACTOR_FLAG_ATTENTION_ENABLED | ACTOR_FLAG_HOSTILE)
#define SLEEP_DAMAGE_MULTIPLIER 2

/* Damage tables (per damage type, see the vanilla enemies). All effects are "none". */
#define DT(dmg) DMG_ENTRY(dmg, 0)
static DamageTable sStdDamageTable = {
    /* Deku Nut       */ DT(0), /* Deku Stick     */ DT(1), /* Horse trample  */ DT(1), /* Explosives     */ DT(2),
    /* Zora boomerang */ DT(1), /* Normal arrow   */ DT(1), /* UNK_DMG_0x06   */ DT(0), /* Hookshot       */ DT(1),
    /* Goron punch    */ DT(2), /* Sword          */ DT(1), /* Goron pound    */ DT(2), /* Fire arrow     */ DT(2),
    /* Ice arrow      */ DT(2), /* Light arrow    */ DT(2), /* Goron spikes   */ DT(1), /* Deku spin      */ DT(1),
    /* Deku bubble    */ DT(1), /* Deku launch    */ DT(2), /* UNK_DMG_0x12   */ DT(0), /* Zora barrier   */ DT(0),
    /* Normal shield  */ DT(0), /* Light ray      */ DT(0), /* Thrown object  */ DT(1), /* Zora punch     */ DT(1),
    /* Spin attack    */ DT(2), /* Sword beam     */ DT(1), /* Normal Roll    */ DT(0), /* UNK_DMG_0x1B   */ DT(0),
    /* UNK_DMG_0x1C   */ DT(0), /* Unblockable    */ DT(0), /* UNK_DMG_0x1E   */ DT(0), /* Powder Keg     */ DT(3),
};

// The Rose Knight's shield soaks up ordinary hits (1 damage), so everything that gets through is worth more.
static DamageTable sKnightDamageTable = {
    /* Deku Nut       */ DT(0), /* Deku Stick     */ DT(1), /* Horse trample  */ DT(1), /* Explosives     */ DT(3),
    /* Zora boomerang */ DT(1), /* Normal arrow   */ DT(1), /* UNK_DMG_0x06   */ DT(0), /* Hookshot       */ DT(0),
    /* Goron punch    */ DT(3), /* Sword          */ DT(1), /* Goron pound    */ DT(3), /* Fire arrow     */ DT(2),
    /* Ice arrow      */ DT(2), /* Light arrow    */ DT(2), /* Goron spikes   */ DT(2), /* Deku spin      */ DT(1),
    /* Deku bubble    */ DT(1), /* Deku launch    */ DT(2), /* UNK_DMG_0x12   */ DT(0), /* Zora barrier   */ DT(0),
    /* Normal shield  */ DT(0), /* Light ray      */ DT(0), /* Thrown object  */ DT(1), /* Zora punch     */ DT(1),
    /* Spin attack    */ DT(2), /* Sword beam     */ DT(1), /* Normal Roll    */ DT(0), /* UNK_DMG_0x1B   */ DT(0),
    /* UNK_DMG_0x1C   */ DT(0), /* Unblockable    */ DT(0), /* UNK_DMG_0x1E   */ DT(0), /* Powder Keg     */ DT(3),
};

static InitChainEntry sGroundInitChain[] = {
    ICHAIN_F32(cullingVolumeDistance, 2600, ICHAIN_CONTINUE),
    ICHAIN_F32_DIV1000(gravity, -3000, ICHAIN_STOP),
};

static InitChainEntry sAirInitChain[] = {
    ICHAIN_F32(cullingVolumeDistance, 2600, ICHAIN_STOP),
};

static s32 Enemy_IsAsleep(LilEnemyBase* this) {
    return this->sleepTimer > 0;
}

// Applies the damage the collision system worked out. Returns true if the enemy has died.
static s32 Enemy_TakeHit(LilEnemyBase* this, PlayState* play) {
    s32 i;
    s32 times = Enemy_IsAsleep(this) ? SLEEP_DAMAGE_MULTIPLIER : 1;

    for (i = 0; i < times; i++) {
        Actor_ApplyDamage(&this->actor);
    }
    this->hurtTimer = 6;
    if (this->actor.colChkInfo.health <= 0) {
        this->actor.flags &= ~ACTOR_FLAG_ATTENTION_ENABLED;
        Enemy_StartFinishingBlow(play, &this->actor);
        return true;
    }
    Actor_PlaySfx(&this->actor, NA_SE_EN_STALKID_ATTACK);
    return false;
}

static void Enemy_Drop(LilEnemyBase* this, PlayState* play) {
    Item_DropCollectibleRandom(play, &this->actor, &this->actor.world.pos, 0x80);
}

/* ==================================================================================================================
 * Thornling
 * ================================================================================================================ */
enum { THORN_DORMANT, THORN_EMERGE, THORN_CHASE, THORN_WINDUP, THORN_LUNGE, THORN_RECOVER, THORN_HURT, THORN_DYING };

typedef struct EnLilThornling {
    /* 0x000 */ LilEnemyBase base;
    /* 0x148 */ ColliderCylinder collider;
    /* 0x194 */ s16 timer;
    /* 0x196 */ s16 state;
    /* 0x198 */ f32 growth;
} EnLilThornling;

static ColliderCylinderInit sThornlingCylinderInit = {
    {
        COL_MATERIAL_HIT6,
        AT_ON | AT_TYPE_ENEMY,
        AC_ON | AC_TYPE_PLAYER,
        OC1_ON | OC1_TYPE_ALL,
        OC2_TYPE_1,
        COLSHAPE_CYLINDER,
    },
    {
        ELEM_MATERIAL_UNK0,
        { 0xF7CFFFFF, 0x00, 0x08 },
        { 0xF7CFFFFF, 0x00, 0x00 },
        ATELEM_ON | ATELEM_SFX_NORMAL,
        ACELEM_ON,
        OCELEM_ON,
    },
    { 24, 44, 0, { 0, 0, 0 } },
};

static CollisionCheckInfoInit sThornlingColChkInfoInit = { 3, 24, 44, 40 };

static void EnLilThornling_SetState(EnLilThornling* this, s16 state, s16 timer) {
    this->state = state;
    this->timer = timer;
}

void EnLilThornling_Init(Actor* thisx, PlayState* play) {
    EnLilThornling* this = (EnLilThornling*)thisx;

    Actor_ProcessInitChain(&this->base.actor, sGroundInitChain);
    Actor_SetScale(&this->base.actor, 1.0f);
    ActorShape_Init(&this->base.actor.shape, 0.0f, ActorShadow_DrawCircle, 26.0f);
    Collider_InitCylinder(play, &this->collider);
    Collider_SetCylinder(play, &this->collider, &this->base.actor, &sThornlingCylinderInit);
    CollisionCheck_SetInfo(&this->base.actor.colChkInfo, &sStdDamageTable, &sThornlingColChkInfoInit);

    if (this->base.actor.params & LIL_ENEMY_PARAM_AWAKE) {
        this->growth = 1.0f;
        EnLilThornling_SetState(this, THORN_CHASE, 0);
    } else {
        this->growth = 0.45f;
        this->collider.base.acFlags &= ~AC_ON;
        this->base.actor.flags &= ~ACTOR_FLAG_ATTENTION_ENABLED;
        EnLilThornling_SetState(this, THORN_DORMANT, 0);
    }
    this->collider.base.atFlags &= ~AT_ON;
}

void EnLilThornling_Destroy(Actor* thisx, PlayState* play) {
    EnLilThornling* this = (EnLilThornling*)thisx;

    Collider_DestroyCylinder(play, &this->collider);
}

void EnLilThornling_Update(Actor* thisx, PlayState* play) {
    EnLilThornling* this = (EnLilThornling*)thisx;
    Actor* actor = &this->base.actor;
    s32 dying = (this->state == THORN_DYING);

    if (this->base.hurtTimer > 0) {
        this->base.hurtTimer--;
    }

    // damage
    if ((this->collider.base.acFlags & AC_HIT) && !dying) {
        this->collider.base.acFlags &= ~AC_HIT;
        if (Enemy_TakeHit(&this->base, play)) {
            this->collider.base.atFlags &= ~AT_ON;
            this->collider.base.acFlags &= ~AC_ON;
            actor->speed = 0.0f;
            Actor_PlaySfx(actor, NA_SE_EN_EXTINCT);
            EnLilThornling_SetState(this, THORN_DYING, 16);
        } else if (this->state != THORN_DORMANT) {
            actor->speed = -5.0f;
            actor->world.rot.y = actor->yawTowardsPlayer;
            this->collider.base.atFlags &= ~AT_ON;
            EnLilThornling_SetState(this, THORN_HURT, 8);
        }
    }

    if (Enemy_IsAsleep(&this->base) && !dying) {
        this->base.sleepTimer--;
        this->collider.base.atFlags &= ~AT_ON;
        Math_StepToF(&actor->speed, 0.0f, 1.0f);
        if ((this->state == THORN_LUNGE) || (this->state == THORN_WINDUP)) {
            EnLilThornling_SetState(this, THORN_RECOVER, 10);
        }
    } else {
        switch (this->state) {
            case THORN_DORMANT:
                if (actor->xzDistToPlayer < 260.0f) {
                    Actor_PlaySfx(actor, NA_SE_EN_KAICHO_CRY);
                    this->collider.base.acFlags |= AC_ON;
                    actor->flags |= ACTOR_FLAG_ATTENTION_ENABLED;
                    EnLilThornling_SetState(this, THORN_EMERGE, 0);
                }
                break;

            case THORN_EMERGE:
                if (Math_StepToF(&this->growth, 1.0f, 0.04f)) {
                    EnLilThornling_SetState(this, THORN_CHASE, 0);
                }
                break;

            case THORN_CHASE:
                Math_SmoothStepToS(&actor->shape.rot.y, actor->yawTowardsPlayer, 4, 0x700, 0x80);
                actor->world.rot.y = actor->shape.rot.y;
                Math_StepToF(&actor->speed, 3.2f, 0.5f);
                if (actor->xzDistToPlayer < 125.0f) {
                    actor->speed = 0.0f;
                    EnLilThornling_SetState(this, THORN_WINDUP, 14);
                }
                break;

            case THORN_WINDUP:
                Math_SmoothStepToS(&actor->shape.rot.y, actor->yawTowardsPlayer, 3, 0x900, 0x80);
                actor->world.rot.y = actor->shape.rot.y;
                if (--this->timer <= 0) {
                    actor->speed = 10.0f;
                    this->collider.base.atFlags |= AT_ON;
                    Actor_PlaySfx(actor, NA_SE_EN_BUBLE_BITE);
                    EnLilThornling_SetState(this, THORN_LUNGE, 16);
                }
                break;

            case THORN_LUNGE:
                this->timer--;
                if ((this->timer <= 0) || (this->collider.base.atFlags & AT_HIT) || (actor->bgCheckFlags & BGCHECKFLAG_WALL)) {
                    this->collider.base.atFlags &= ~(AT_HIT | AT_ON);
                    actor->speed = 0.0f;
                    EnLilThornling_SetState(this, THORN_RECOVER, 30);
                }
                break;

            case THORN_RECOVER:
                Math_StepToF(&actor->speed, 0.0f, 1.5f);
                if (--this->timer <= 0) {
                    EnLilThornling_SetState(this, THORN_CHASE, 0);
                }
                break;

            case THORN_HURT:
                Math_StepToF(&actor->speed, 0.0f, 1.0f);
                if (--this->timer <= 0) {
                    EnLilThornling_SetState(this, THORN_CHASE, 0);
                }
                break;

            case THORN_DYING:
                this->growth -= 1.0f / 16.0f;
                if (this->growth <= 0.05f || --this->timer <= 0) {
                    Enemy_Drop(&this->base, play);
                    Actor_Kill(actor);
                    return;
                }
                break;

            default:
                break;
        }
    }

    Actor_MoveWithGravity(actor);
    Actor_UpdateBgCheckInfo(play, actor, 18.0f, 24.0f, 40.0f, UPDBGCHECKINFO_FLAG_1 | UPDBGCHECKINFO_FLAG_2 | UPDBGCHECKINFO_FLAG_4);
    Collider_UpdateCylinder(actor, &this->collider);
    if (this->collider.base.atFlags & AT_ON) {
        CollisionCheck_SetAT(play, &play->colChkCtx, &this->collider.base);
    }
    if (this->collider.base.acFlags & AC_ON) {
        CollisionCheck_SetAC(play, &play->colChkCtx, &this->collider.base);
    }
    if (this->state != THORN_DYING) {
        CollisionCheck_SetOC(play, &play->colChkCtx, &this->collider.base);
    }
    Actor_SetFocus(actor, 26.0f);
}

void EnLilThornling_Draw(Actor* thisx, PlayState* play) {
    EnLilThornling* this = (EnLilThornling*)thisx;
    s32 asleep = Enemy_IsAsleep(&this->base);
    f32 squash = (this->base.hurtTimer > 0) ? 0.78f : 1.0f;
    f32 wind = (this->state == THORN_WINDUP) ? 0.72f : 1.0f;
    f32 s = this->growth;
    s16 tilt = asleep ? 0x1600 : 0;

    Lil_SetupLitOpa(play);
    Lil_DrawPart(play, gLilThornling_BodyDL, 0, asleep ? -6.0f : -4.0f, 0, tilt, 0, 0, s, s * squash * wind, s, false);
    Lil_DrawPart(play, gLilThornling_ThornsDL, 0, asleep ? -6.0f : -4.0f, 0, tilt, 0, 0, s, s * squash * wind, s, false);
    if (!asleep && (this->state != THORN_DORMANT)) {
        Lil_DrawPart(play, gLilThornling_EyesDL, 0, -4.0f, 0, 0, 0, 0, s, s * squash * wind, s, false);
    }
}

ActorProfile LilThornling_Profile = {
    /**/ 0,
    /**/ ACTORCAT_ENEMY,
    /**/ ENEMY_FLAGS,
    /**/ GAMEPLAY_KEEP,
    /**/ sizeof(EnLilThornling),
    /**/ EnLilThornling_Init,
    /**/ EnLilThornling_Destroy,
    /**/ EnLilThornling_Update,
    /**/ EnLilThornling_Draw,
};

/* ==================================================================================================================
 * Petal Wisp
 * ================================================================================================================ */
enum { WISP_HOVER, WISP_DIVE, WISP_RETREAT, WISP_DYING };

typedef struct EnLilWisp {
    /* 0x000 */ LilEnemyBase base;
    /* 0x148 */ ColliderCylinder collider;
    /* 0x194 */ s16 timer;
    /* 0x196 */ s16 state;
    /* 0x198 */ s16 orbit;
    /* 0x19A */ s16 shotTimer;
    /* 0x19C */ s16 petalSpin;
    /* 0x19E */ s16 bob;
    /* 0x1A0 */ f32 scale;
} EnLilWisp;

static ColliderCylinderInit sWispCylinderInit = {
    {
        COL_MATERIAL_HIT3,
        AT_ON | AT_TYPE_ENEMY,
        AC_ON | AC_TYPE_PLAYER,
        OC1_ON | OC1_TYPE_ALL,
        OC2_TYPE_1,
        COLSHAPE_CYLINDER,
    },
    {
        ELEM_MATERIAL_UNK0,
        { 0xF7CFFFFF, 0x00, 0x08 },
        { 0xF7CFFFFF, 0x00, 0x00 },
        ATELEM_ON | ATELEM_SFX_NORMAL,
        ACELEM_ON,
        OCELEM_ON,
    },
    { 18, 34, -10, { 0, 0, 0 } },
};

static CollisionCheckInfoInit sWispColChkInfoInit = { 2, 18, 34, 20 };

void EnLilWisp_Init(Actor* thisx, PlayState* play) {
    EnLilWisp* this = (EnLilWisp*)thisx;

    Actor_ProcessInitChain(&this->base.actor, sAirInitChain);
    Actor_SetScale(&this->base.actor, 1.0f);
    ActorShape_Init(&this->base.actor.shape, 0.0f, ActorShadow_DrawCircle, 14.0f);
    Collider_InitCylinder(play, &this->collider);
    Collider_SetCylinder(play, &this->collider, &this->base.actor, &sWispCylinderInit);
    CollisionCheck_SetInfo(&this->base.actor.colChkInfo, &sStdDamageTable, &sWispColChkInfoInit);
    this->collider.base.atFlags &= ~AT_ON;
    this->scale = 1.0f;
    this->state = WISP_HOVER;
    this->timer = 50 + (s16)Rand_ZeroFloat(40.0f);
    this->orbit = (s16)Rand_ZeroFloat(65535.0f);
    this->shotTimer = 40 + (s16)Rand_ZeroFloat(40.0f);
    this->base.actor.world.pos.y = this->base.actor.home.pos.y + ((this->base.actor.params & LIL_ENEMY_PARAM_AWAKE) ? 0.0f : 80.0f);
}

void EnLilWisp_Destroy(Actor* thisx, PlayState* play) {
    EnLilWisp* this = (EnLilWisp*)thisx;

    Collider_DestroyCylinder(play, &this->collider);
}

void EnLilWisp_Update(Actor* thisx, PlayState* play) {
    EnLilWisp* this = (EnLilWisp*)thisx;
    Actor* actor = &this->base.actor;
    Player* player = GET_PLAYER(play);
    f32 targetX;
    f32 targetY;
    f32 targetZ;

    this->petalSpin += 0x500;
    this->bob += 0x280;
    if (this->base.hurtTimer > 0) {
        this->base.hurtTimer--;
    }

    if ((this->collider.base.acFlags & AC_HIT) && (this->state != WISP_DYING)) {
        this->collider.base.acFlags &= ~AC_HIT;
        if (Enemy_TakeHit(&this->base, play)) {
            this->collider.base.atFlags &= ~AT_ON;
            this->collider.base.acFlags &= ~AC_ON;
            Actor_PlaySfx(actor, NA_SE_EN_EXTINCT);
            this->state = WISP_DYING;
            this->timer = 14;
        } else {
            this->state = WISP_RETREAT;
            this->timer = 24;
            this->collider.base.atFlags &= ~AT_ON;
        }
    }

    if (Enemy_IsAsleep(&this->base) && (this->state != WISP_DYING)) {
        // A sleeping wisp drifts down and rests close to the ground where it can be hit.
        this->base.sleepTimer--;
        this->collider.base.atFlags &= ~AT_ON;
        this->state = WISP_HOVER;
        Math_ApproachF(&actor->world.pos.y, actor->floorHeight + 24.0f, 0.2f, 6.0f);
    } else {
        switch (this->state) {
            case WISP_HOVER:
                this->orbit += 0x140;
                targetX = actor->home.pos.x + Math_SinS(this->orbit) * 110.0f;
                targetZ = actor->home.pos.z + Math_CosS(this->orbit) * 110.0f;
                targetY = actor->home.pos.y + 70.0f + Math_SinS(this->bob) * 18.0f;
                Math_ApproachF(&actor->world.pos.x, targetX, 0.12f, 9.0f);
                Math_ApproachF(&actor->world.pos.y, targetY, 0.12f, 6.0f);
                Math_ApproachF(&actor->world.pos.z, targetZ, 0.12f, 9.0f);
                Math_SmoothStepToS(&actor->shape.rot.y, actor->yawTowardsPlayer, 4, 0x800, 0x80);

                if (this->shotTimer > 0) {
                    this->shotTimer--;
                } else if ((actor->xzDistToPlayer > 220.0f) && (actor->xzDistToPlayer < 700.0f)) {
                    Lil_SpawnHazard(play, LIL_HAZARD_PETAL, actor->world.pos.x, actor->world.pos.y + 8.0f, actor->world.pos.z,
                                    actor->yawTowardsPlayer, 6);
                    Actor_PlaySfx(actor, NA_SE_EN_KAICHO_ATTACK);
                    this->shotTimer = 60 + (s16)Rand_ZeroFloat(30.0f);
                }
                if (this->timer > 0) {
                    this->timer--;
                } else if (actor->xzDistToPlayer < 450.0f) {
                    this->state = WISP_DIVE;
                    this->timer = 26;
                    this->collider.base.atFlags |= AT_ON;
                    Actor_PlaySfx(actor, NA_SE_EN_KAICHO_CRY);
                }
                break;

            case WISP_DIVE: {
                f32 dx = player->actor.world.pos.x - actor->world.pos.x;
                f32 dy = (player->actor.world.pos.y + 30.0f) - actor->world.pos.y;
                f32 dz = player->actor.world.pos.z - actor->world.pos.z;
                f32 len = sqrtf(SQ(dx) + SQ(dy) + SQ(dz));

                if (len > 1.0f) {
                    actor->world.pos.x += dx / len * 9.0f;
                    actor->world.pos.y += dy / len * 9.0f;
                    actor->world.pos.z += dz / len * 9.0f;
                }
                actor->shape.rot.y = actor->yawTowardsPlayer;
                this->timer--;
                if ((this->timer <= 0) || (this->collider.base.atFlags & AT_HIT) || (len < 28.0f)) {
                    this->collider.base.atFlags &= ~(AT_HIT | AT_ON);
                    this->state = WISP_RETREAT;
                    this->timer = 30;
                }
                break;
            }

            case WISP_RETREAT:
                Math_ApproachF(&actor->world.pos.y, actor->home.pos.y + 110.0f, 0.15f, 7.0f);
                Math_ApproachF(&actor->world.pos.x, actor->home.pos.x, 0.05f, 5.0f);
                Math_ApproachF(&actor->world.pos.z, actor->home.pos.z, 0.05f, 5.0f);
                if (--this->timer <= 0) {
                    this->state = WISP_HOVER;
                    this->timer = 60 + (s16)Rand_ZeroFloat(50.0f);
                }
                break;

            case WISP_DYING:
                this->scale -= 1.0f / 14.0f;
                actor->world.pos.y += 2.0f;
                if ((this->scale <= 0.05f) || (--this->timer <= 0)) {
                    Enemy_Drop(&this->base, play);
                    Actor_Kill(actor);
                    return;
                }
                break;

            default:
                break;
        }
    }

    Actor_UpdateBgCheckInfo(play, actor, 12.0f, 14.0f, 20.0f, UPDBGCHECKINFO_FLAG_1 | UPDBGCHECKINFO_FLAG_4);
    Collider_UpdateCylinder(actor, &this->collider);
    if (this->collider.base.atFlags & AT_ON) {
        CollisionCheck_SetAT(play, &play->colChkCtx, &this->collider.base);
    }
    if (this->collider.base.acFlags & AC_ON) {
        CollisionCheck_SetAC(play, &play->colChkCtx, &this->collider.base);
    }
    if (this->state != WISP_DYING) {
        CollisionCheck_SetOC(play, &play->colChkCtx, &this->collider.base);
    }
    Actor_SetFocus(actor, 10.0f);
}

void EnLilWisp_Draw(Actor* thisx, PlayState* play) {
    EnLilWisp* this = (EnLilWisp*)thisx;
    f32 s = this->scale * ((this->base.hurtTimer > 0) ? 1.25f : 1.0f);
    s32 asleep = Enemy_IsAsleep(&this->base);

    Lil_SetupLitOpa(play);
    Lil_DrawPart(play, gLilPetalWisp_CoreDL, 0, 0, 0, 0, 0, 0, s, s, s, false);
    Lil_DrawPart(play, gLilPetalWisp_PetalsDL, 0, 0, 0, asleep ? 0x2000 : 0, asleep ? 0 : this->petalSpin, 0, s, s, s, false);
}

ActorProfile LilWisp_Profile = {
    /**/ 0,
    /**/ ACTORCAT_ENEMY,
    /**/ ENEMY_FLAGS,
    /**/ GAMEPLAY_KEEP,
    /**/ sizeof(EnLilWisp),
    /**/ EnLilWisp_Init,
    /**/ EnLilWisp_Destroy,
    /**/ EnLilWisp_Update,
    /**/ EnLilWisp_Draw,
};

/* ==================================================================================================================
 * Rose Knight
 * ================================================================================================================ */
enum { KNIGHT_IDLE, KNIGHT_WALK, KNIGHT_WINDUP, KNIGHT_SWING, KNIGHT_RECOVER, KNIGHT_STAGGER, KNIGHT_DYING };

typedef struct EnLilKnight {
    /* 0x000 */ LilEnemyBase base;
    /* 0x148 */ ColliderCylinder collider;
    /* 0x194 */ s16 timer;
    /* 0x196 */ s16 state;
    /* 0x198 */ s16 swordAngle;
    /* 0x19A */ s16 blockFlash;
    /* 0x19C */ f32 scale;
} EnLilKnight;

static ColliderCylinderInit sKnightCylinderInit = {
    {
        COL_MATERIAL_METAL,
        AT_ON | AT_TYPE_ENEMY,
        AC_ON | AC_HARD | AC_TYPE_PLAYER,
        OC1_ON | OC1_TYPE_ALL,
        OC2_TYPE_1,
        COLSHAPE_CYLINDER,
    },
    {
        ELEM_MATERIAL_UNK0,
        { 0xF7CFFFFF, 0x00, 0x10 },
        { 0xF7CFFFFF, 0x00, 0x00 },
        ATELEM_ON | ATELEM_SFX_NORMAL,
        ACELEM_ON,
        OCELEM_ON,
    },
    { 26, 92, 0, { 0, 0, 0 } },
};

static CollisionCheckInfoInit sKnightColChkInfoInit = { 6, 26, 92, 120 };

#define KNIGHT_BLOCK_ARC 0x3800 // ~79 degrees either side of the knight's facing

static s32 EnLilKnight_FacingAttacker(EnLilKnight* this) {
    s16 diff = this->base.actor.yawTowardsPlayer - this->base.actor.shape.rot.y;

    return ABS_ALT(diff) < KNIGHT_BLOCK_ARC;
}

void EnLilKnight_Init(Actor* thisx, PlayState* play) {
    EnLilKnight* this = (EnLilKnight*)thisx;

    Actor_ProcessInitChain(&this->base.actor, sGroundInitChain);
    Actor_SetScale(&this->base.actor, 1.0f);
    ActorShape_Init(&this->base.actor.shape, 0.0f, ActorShadow_DrawCircle, 30.0f);
    Collider_InitCylinder(play, &this->collider);
    Collider_SetCylinder(play, &this->collider, &this->base.actor, &sKnightCylinderInit);
    CollisionCheck_SetInfo(&this->base.actor.colChkInfo, &sKnightDamageTable, &sKnightColChkInfoInit);
    this->collider.base.atFlags &= ~AT_ON;
    this->scale = 1.0f;
    this->swordAngle = -0x1800;
    this->state = (this->base.actor.params & LIL_ENEMY_PARAM_AWAKE) ? KNIGHT_WALK : KNIGHT_IDLE;
}

void EnLilKnight_Destroy(Actor* thisx, PlayState* play) {
    EnLilKnight* this = (EnLilKnight*)thisx;

    Collider_DestroyCylinder(play, &this->collider);
}

void EnLilKnight_Update(Actor* thisx, PlayState* play) {
    EnLilKnight* this = (EnLilKnight*)thisx;
    Actor* actor = &this->base.actor;
    s32 asleep = Enemy_IsAsleep(&this->base);

    if (this->base.hurtTimer > 0) {
        this->base.hurtTimer--;
    }
    if (this->blockFlash > 0) {
        this->blockFlash--;
    }

    if ((this->collider.base.acFlags & AC_HIT) && (this->state != KNIGHT_DYING)) {
        s32 vulnerable = asleep || (this->state == KNIGHT_WINDUP) || (this->state == KNIGHT_SWING) ||
                         (this->state == KNIGHT_RECOVER) || (actor->colChkInfo.damage >= 2) || !EnLilKnight_FacingAttacker(this);

        this->collider.base.acFlags &= ~AC_HIT;
        if (!vulnerable) {
            // The shield takes it.
            Actor_PlaySfx(actor, NA_SE_IT_SHIELD_REFLECT_SW);
            this->blockFlash = 6;
        } else if (Enemy_TakeHit(&this->base, play)) {
            this->collider.base.atFlags &= ~AT_ON;
            this->collider.base.acFlags &= ~AC_ON;
            actor->speed = 0.0f;
            Actor_PlaySfx(actor, NA_SE_EN_STAL_DEAD);
            this->state = KNIGHT_DYING;
            this->timer = 24;
        } else if (!asleep) {
            this->collider.base.atFlags &= ~AT_ON;
            actor->speed = -4.0f;
            actor->world.rot.y = actor->yawTowardsPlayer;
            this->state = KNIGHT_STAGGER;
            this->timer = 10;
        }
    }

    if (asleep && (this->state != KNIGHT_DYING)) {
        this->base.sleepTimer--;
        this->collider.base.atFlags &= ~AT_ON;
        Math_StepToF(&actor->speed, 0.0f, 1.0f);
        this->collider.dim.radius = 26;
    } else {
        switch (this->state) {
            case KNIGHT_IDLE:
                if (actor->xzDistToPlayer < 420.0f) {
                    Actor_PlaySfx(actor, NA_SE_EN_STALKID_ATTACK);
                    this->state = KNIGHT_WALK;
                }
                break;

            case KNIGHT_WALK:
                Math_SmoothStepToS(&actor->shape.rot.y, actor->yawTowardsPlayer, 5, 0x500, 0x80);
                actor->world.rot.y = actor->shape.rot.y;
                Math_StepToF(&actor->speed, 2.3f, 0.4f);
                Math_SmoothStepToS(&this->swordAngle, -0x1800, 3, 0x600, 0x40);
                if (actor->xzDistToPlayer < 100.0f) {
                    actor->speed = 0.0f;
                    this->state = KNIGHT_WINDUP;
                    this->timer = 18;
                }
                break;

            case KNIGHT_WINDUP:
                Math_SmoothStepToS(&actor->shape.rot.y, actor->yawTowardsPlayer, 4, 0x600, 0x80);
                actor->world.rot.y = actor->shape.rot.y;
                Math_SmoothStepToS(&this->swordAngle, -0x3600, 2, 0x900, 0x40);
                if (--this->timer <= 0) {
                    this->state = KNIGHT_SWING;
                    this->timer = 7;
                    this->collider.base.atFlags |= AT_ON;
                    this->collider.dim.radius = 66;
                    Actor_PlaySfx(actor, NA_SE_IT_SWORD_STRIKE);
                }
                break;

            case KNIGHT_SWING:
                Math_SmoothStepToS(&this->swordAngle, 0x2800, 1, 0x1800, 0x100);
                if (--this->timer <= 0 || (this->collider.base.atFlags & AT_HIT)) {
                    this->collider.base.atFlags &= ~(AT_HIT | AT_ON);
                    this->collider.dim.radius = 26;
                    this->state = KNIGHT_RECOVER;
                    this->timer = 26;
                }
                break;

            case KNIGHT_RECOVER:
                Math_SmoothStepToS(&this->swordAngle, -0x1800, 4, 0x500, 0x40);
                if (--this->timer <= 0) {
                    this->state = KNIGHT_WALK;
                }
                break;

            case KNIGHT_STAGGER:
                Math_StepToF(&actor->speed, 0.0f, 1.0f);
                if (--this->timer <= 0) {
                    this->state = KNIGHT_WALK;
                }
                break;

            case KNIGHT_DYING:
                this->scale = this->timer / 24.0f;
                if (--this->timer <= 0) {
                    Enemy_Drop(&this->base, play);
                    Actor_Kill(actor);
                    return;
                }
                break;

            default:
                break;
        }
    }

    Actor_MoveWithGravity(actor);
    Actor_UpdateBgCheckInfo(play, actor, 26.0f, 26.0f, 60.0f, UPDBGCHECKINFO_FLAG_1 | UPDBGCHECKINFO_FLAG_2 | UPDBGCHECKINFO_FLAG_4);
    Collider_UpdateCylinder(actor, &this->collider);
    if (this->collider.base.atFlags & AT_ON) {
        CollisionCheck_SetAT(play, &play->colChkCtx, &this->collider.base);
    }
    if (this->collider.base.acFlags & AC_ON) {
        CollisionCheck_SetAC(play, &play->colChkCtx, &this->collider.base);
    }
    if (this->state != KNIGHT_DYING) {
        CollisionCheck_SetOC(play, &play->colChkCtx, &this->collider.base);
    }
    Actor_SetFocus(actor, 70.0f);
}

void EnLilKnight_Draw(Actor* thisx, PlayState* play) {
    EnLilKnight* this = (EnLilKnight*)thisx;
    s32 asleep = Enemy_IsAsleep(&this->base);
    f32 s = this->scale;
    f32 squash = (this->base.hurtTimer > 0) ? 0.94f : 1.0f;
    s16 slump = asleep ? 0x1400 : 0;
    f32 drop = asleep ? -12.0f : 0.0f;

    Lil_SetupLitOpa(play);
    Lil_DrawPart(play, gLilRoseKnight_BodyDL, 0, drop, 0, slump, 0, 0, s, s * squash, s, false);
    Lil_DrawPart(play, gLilRoseKnight_HeadDL, 0, drop, asleep ? 10.0f : 0.0f, slump, 0, 0, s, s * squash, s, false);
    Lil_DrawPart(play, gLilRoseKnight_PlumeDL, 0, drop, asleep ? 10.0f : 0.0f, slump, 0, 0, s, s * squash, s, false);
    Lil_DrawPart(play, gLilRoseKnight_ShieldDL, (this->blockFlash > 0) ? 4.0f : 0.0f, drop, 0, slump, 0, 0, s, s, s, false);
    Lil_DrawPart(play, gLilRoseKnight_SwordDL, -30.0f * s, (62.0f + drop) * s, 10.0f * s, this->swordAngle, 0, 0, s, s, s, false);
}

ActorProfile LilKnight_Profile = {
    /**/ 0,
    /**/ ACTORCAT_ENEMY,
    /**/ ENEMY_FLAGS,
    /**/ GAMEPLAY_KEEP,
    /**/ sizeof(EnLilKnight),
    /**/ EnLilKnight_Init,
    /**/ EnLilKnight_Destroy,
    /**/ EnLilKnight_Update,
    /**/ EnLilKnight_Draw,
};
