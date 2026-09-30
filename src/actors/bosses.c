/**
 * The two bosses of the Thornbound Crypt.
 *
 *   Thorn Warden       (mid boss)  an armoured plant-knight. Slams his mace (shockwave of petals and thorn spikes at your
 *                                  feet), summons a line of thorns, then is left exhausted: that is your window. Playing
 *                                  Lilith's Lullaby also exhausts him.
 *   Queen of Thorns    (final boss) floats over the arena. Phase 1 and 2: dodge the petal spirals and thorn rings, hit her
 *                                  while she rests. Phase 3: she is only vulnerable while she sleeps, and she only sleeps
 *                                  when she hears Lilith's Lullaby.
 *
 * Both respect the switch flag given in their params: once set (they are dead) they do not come back.
 */

#include "lil_actor.h"

#define DT(dmg) DMG_ENTRY(dmg, 0)
static DamageTable sBossDamageTable = {
    /* Deku Nut       */ DT(0), /* Deku Stick     */ DT(1), /* Horse trample  */ DT(0), /* Explosives     */ DT(3),
    /* Zora boomerang */ DT(1), /* Normal arrow   */ DT(1), /* UNK_DMG_0x06   */ DT(0), /* Hookshot       */ DT(0),
    /* Goron punch    */ DT(2), /* Sword          */ DT(1), /* Goron pound    */ DT(3), /* Fire arrow     */ DT(2),
    /* Ice arrow      */ DT(2), /* Light arrow    */ DT(3), /* Goron spikes   */ DT(2), /* Deku spin      */ DT(1),
    /* Deku bubble    */ DT(1), /* Deku launch    */ DT(2), /* UNK_DMG_0x12   */ DT(0), /* Zora barrier   */ DT(0),
    /* Normal shield  */ DT(0), /* Light ray      */ DT(0), /* Thrown object  */ DT(1), /* Zora punch     */ DT(1),
    /* Spin attack    */ DT(2), /* Sword beam     */ DT(1), /* Normal Roll    */ DT(0), /* UNK_DMG_0x1B   */ DT(0),
    /* UNK_DMG_0x1C   */ DT(0), /* Unblockable    */ DT(0), /* UNK_DMG_0x1E   */ DT(0), /* Powder Keg     */ DT(4),
};

static InitChainEntry sBossInitChain[] = {
    ICHAIN_F32(cullingVolumeDistance, 6000, ICHAIN_CONTINUE),
    ICHAIN_F32_DIV1000(gravity, -3000, ICHAIN_STOP),
};

// Shoots `count` petals outwards in a ring.
static void Boss_PetalRing(PlayState* play, f32 x, f32 y, f32 z, s32 count, s16 startAngle, s32 speed) {
    s32 i;

    for (i = 0; i < count; i++) {
        Lil_SpawnHazard(play, LIL_HAZARD_PETAL, x, y, z, startAngle + (s16)((i * 0x10000) / count), speed);
    }
}

static void Boss_SpawnSpike(PlayState* play, f32 x, f32 y, f32 z) {
    Lil_SpawnHazard(play, LIL_HAZARD_SPIKE, x, y, z, 0, 0);
}

/* ==================================================================================================================
 * Thorn Warden
 * ================================================================================================================ */
enum {
    WARDEN_DORMANT,
    WARDEN_INTRO,
    WARDEN_WALK,
    WARDEN_SLAM_WINDUP,
    WARDEN_SLAM,
    WARDEN_ROOTS,
    WARDEN_EXHAUSTED,
    WARDEN_DYING
};

typedef struct BossLilWarden {
    /* 0x000 */ Actor actor;
    /* 0x144 */ ColliderCylinder collider;
    /* 0x190 */ s16 timer;
    /* 0x192 */ s16 state;
    /* 0x194 */ s16 flag;
    /* 0x196 */ s16 attackCount;
    /* 0x198 */ s16 hurtTimer;
    /* 0x19A */ s16 maceAngle;
    /* 0x19C */ s16 rootsSpawned;
    /* 0x19E */ s16 rootYaw;
    /* 0x1A0 */ f32 scale;
} BossLilWarden;

#define WARDEN_HEALTH 18
#define WARDEN_ARENA_TRIGGER 620.0f

static ColliderCylinderInit sWardenCylinderInit = {
    {
        COL_MATERIAL_HARD,
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
    { 50, 210, 0, { 0, 0, 0 } },
};

static CollisionCheckInfoInit sWardenColChkInfoInit = { WARDEN_HEALTH, 50, 210, 250 };

static void BossLilWarden_SetState(BossLilWarden* this, s16 state, s16 timer) {
    this->state = state;
    this->timer = timer;
}

static s32 BossLilWarden_OnLullaby(Actor* thisx, PlayState* play) {
    BossLilWarden* this = (BossLilWarden*)thisx;

    if ((this->state == WARDEN_DORMANT) || (this->state == WARDEN_INTRO) || (this->state == WARDEN_DYING)) {
        return false;
    }
    this->collider.base.atFlags &= ~AT_ON;
    BossLilWarden_SetState(this, WARDEN_EXHAUSTED, 110);
    return true;
}

void BossLilWarden_Init(Actor* thisx, PlayState* play) {
    BossLilWarden* this = (BossLilWarden*)thisx;

    this->flag = this->actor.params & 0x7F;
    if (Flags_GetSwitch(play, this->flag)) {
        Actor_Kill(&this->actor);
        return;
    }
    Actor_ProcessInitChain(&this->actor, sBossInitChain);
    Actor_SetScale(&this->actor, 1.0f);
    ActorShape_Init(&this->actor.shape, 0.0f, ActorShadow_DrawCircle, 60.0f);
    Collider_InitCylinder(play, &this->collider);
    Collider_SetCylinder(play, &this->collider, &this->actor, &sWardenCylinderInit);
    CollisionCheck_SetInfo(&this->actor.colChkInfo, &sBossDamageTable, &sWardenColChkInfoInit);
    this->collider.base.atFlags &= ~AT_ON;
    this->scale = 1.0f;
    this->maceAngle = 0;
    this->actor.flags &= ~ACTOR_FLAG_ATTENTION_ENABLED;
    BossLilWarden_SetState(this, WARDEN_DORMANT, 0);
    Lil_RegisterLullabyListener(&this->actor, BossLilWarden_OnLullaby);
}

void BossLilWarden_Destroy(Actor* thisx, PlayState* play) {
    BossLilWarden* this = (BossLilWarden*)thisx;

    Lil_UnregisterLullabyListener(&this->actor);
    Collider_DestroyCylinder(play, &this->collider);
}

static void BossLilWarden_StartWalk(BossLilWarden* this) {
    this->collider.base.atFlags &= ~AT_ON;
    BossLilWarden_SetState(this, WARDEN_WALK, 45 + (s16)Rand_ZeroFloat(35.0f));
}

void BossLilWarden_Update(Actor* thisx, PlayState* play) {
    BossLilWarden* this = (BossLilWarden*)thisx;
    Actor* actor = &this->actor;
    Player* player = GET_PLAYER(play);
    s32 i;

    if (this->hurtTimer > 0) {
        this->hurtTimer--;
    }

    if ((this->collider.base.acFlags & AC_HIT) && (this->state != WARDEN_DYING)) {
        s32 vulnerable = (this->state == WARDEN_EXHAUSTED);

        this->collider.base.acFlags &= ~AC_HIT;
        if (!vulnerable) {
            Actor_PlaySfx(actor, NA_SE_IT_SHIELD_REFLECT_SW); // his bark-armour turns the blow aside
        } else {
            s32 times = 2;

            while (times-- > 0) {
                Actor_ApplyDamage(actor);
            }
            this->hurtTimer = 8;
            Actor_PlaySfx(actor, NA_SE_EN_STALKID_ATTACK);
            if (actor->colChkInfo.health <= 0) {
                actor->flags &= ~ACTOR_FLAG_ATTENTION_ENABLED;
                this->collider.base.atFlags &= ~AT_ON;
                this->collider.base.acFlags &= ~AC_ON;
                Enemy_StartFinishingBlow(play, actor);
                BossLilWarden_SetState(this, WARDEN_DYING, 60);
            }
        }
    }

    switch (this->state) {
        case WARDEN_DORMANT:
            if (actor->xzDistToPlayer < WARDEN_ARENA_TRIGGER) {
                gLilWarpBlocked = 1;
                Audio_PlayBgm_StorePrevBgm(NA_BGM_MINI_BOSS);
                Actor_PlaySfx(actor, NA_SE_EN_STALKID_ATTACK);
                BossLilWarden_SetState(this, WARDEN_INTRO, 50);
            }
            break;

        case WARDEN_INTRO:
            this->maceAngle = -(s16)(0x3000 * Math_SinS(this->timer * 0x500));
            Math_SmoothStepToS(&actor->shape.rot.y, actor->yawTowardsPlayer, 5, 0x400, 0x80);
            if (--this->timer <= 0) {
                actor->flags |= ACTOR_FLAG_ATTENTION_ENABLED;
                BossLilWarden_StartWalk(this);
            }
            break;

        case WARDEN_WALK:
            Math_SmoothStepToS(&actor->shape.rot.y, actor->yawTowardsPlayer, 5, 0x380, 0x80);
            actor->world.rot.y = actor->shape.rot.y;
            Math_StepToF(&actor->speed, 2.4f, 0.3f);
            Math_SmoothStepToS(&this->maceAngle, 0, 3, 0x400, 0x40);
            this->timer--;
            if ((actor->xzDistToPlayer < 170.0f) || (this->timer <= 0)) {
                actor->speed = 0.0f;
                this->attackCount++;
                if ((this->attackCount % 3) == 0) {
                    this->rootsSpawned = 0;
                    this->rootYaw = actor->yawTowardsPlayer;
                    BossLilWarden_SetState(this, WARDEN_ROOTS, 46);
                } else {
                    BossLilWarden_SetState(this, WARDEN_SLAM_WINDUP, 22);
                }
            }
            break;

        case WARDEN_SLAM_WINDUP:
            Math_SmoothStepToS(&actor->shape.rot.y, actor->yawTowardsPlayer, 4, 0x500, 0x80);
            Math_SmoothStepToS(&this->maceAngle, -0x7C00, 2, 0x1400, 0x80);
            if (--this->timer <= 0) {
                BossLilWarden_SetState(this, WARDEN_SLAM, 8);
            }
            break;

        case WARDEN_SLAM:
            if (this->timer == 8) {
                Vec3f maceTip;
                s16 yaw = actor->shape.rot.y;

                maceTip.x = actor->world.pos.x + Math_SinS(yaw) * 120.0f;
                maceTip.y = actor->world.pos.y + 4.0f;
                maceTip.z = actor->world.pos.z + Math_CosS(yaw) * 120.0f;
                Actor_PlaySfx(actor, NA_SE_IT_HAMMER_HIT);
                Boss_PetalRing(play, maceTip.x, maceTip.y + 8.0f, maceTip.z, 12, yaw, 8);
                Boss_SpawnSpike(play, player->actor.world.pos.x, actor->world.pos.y, player->actor.world.pos.z);
                Boss_SpawnSpike(play, player->actor.world.pos.x + 110.0f, actor->world.pos.y, player->actor.world.pos.z);
                Boss_SpawnSpike(play, player->actor.world.pos.x - 110.0f, actor->world.pos.y, player->actor.world.pos.z);
                Lil_Puff(play, &maceTip, 180.0f);
            }
            Math_SmoothStepToS(&this->maceAngle, -0x2000, 1, 0x2800, 0x100);
            if (--this->timer <= 0) {
                BossLilWarden_SetState(this, WARDEN_EXHAUSTED, 70);
            }
            break;

        case WARDEN_ROOTS:
            Math_SmoothStepToS(&this->maceAngle, -0x5000, 3, 0x600, 0x40);
            // a line of thorns sweeps out towards where the player was when the attack began
            if ((this->timer < 40) && ((this->timer & 3) == 0) && (this->rootsSpawned < 7)) {
                f32 dist = 130.0f + this->rootsSpawned * 95.0f;

                Boss_SpawnSpike(play, actor->world.pos.x + Math_SinS(this->rootYaw) * dist, actor->world.pos.y,
                                actor->world.pos.z + Math_CosS(this->rootYaw) * dist);
                this->rootsSpawned++;
            }
            if (--this->timer <= 0) {
                BossLilWarden_StartWalk(this);
            }
            break;

        case WARDEN_EXHAUSTED:
            actor->speed = 0.0f;
            Math_SmoothStepToS(&this->maceAngle, 0x1000, 3, 0x500, 0x40);
            if (--this->timer <= 0) {
                BossLilWarden_StartWalk(this);
            }
            break;

        case WARDEN_DYING:
            actor->speed = 0.0f;
            this->scale = 0.35f + 0.65f * ((f32)this->timer / 60.0f);
            if ((this->timer % 6) == 0) {
                Vec3f pos;

                pos.x = actor->world.pos.x + Rand_CenteredFloat(120.0f);
                pos.y = actor->world.pos.y + Rand_ZeroFloat(200.0f);
                pos.z = actor->world.pos.z + Rand_CenteredFloat(120.0f);
                Lil_Puff(play, &pos, 120.0f);
            }
            if (--this->timer <= 0) {
                Vec3f pos = actor->world.pos;

                Flags_SetSwitch(play, this->flag);
                Item_DropCollectible(play, &pos, ITEM00_HEART_PIECE);
                Audio_PlaySfx(NA_SE_SY_CORRECT_CHIME);
                Audio_RestorePrevBgm();
                gLilWarpBlocked = 0;
                Actor_Kill(actor);
                return;
            }
            break;

        default:
            break;
    }

    // While he swings, the swing itself hurts.
    if ((this->state == WARDEN_SLAM) && (this->timer > 4)) {
        this->collider.base.atFlags |= AT_ON;
        this->collider.dim.radius = 120;
    } else {
        this->collider.base.atFlags &= ~AT_ON;
        this->collider.dim.radius = 50;
    }

    Actor_MoveWithGravity(actor);
    Actor_UpdateBgCheckInfo(play, actor, 40.0f, 50.0f, 120.0f, UPDBGCHECKINFO_FLAG_1 | UPDBGCHECKINFO_FLAG_2 | UPDBGCHECKINFO_FLAG_4);
    Collider_UpdateCylinder(actor, &this->collider);
    if (this->collider.base.atFlags & AT_ON) {
        CollisionCheck_SetAT(play, &play->colChkCtx, &this->collider.base);
    }
    if (this->collider.base.acFlags & AC_ON) {
        CollisionCheck_SetAC(play, &play->colChkCtx, &this->collider.base);
    }
    if (this->state != WARDEN_DYING) {
        CollisionCheck_SetOC(play, &play->colChkCtx, &this->collider.base);
    }
    Actor_SetFocus(actor, 150.0f);
}

void BossLilWarden_Draw(Actor* thisx, PlayState* play) {
    BossLilWarden* this = (BossLilWarden*)thisx;
    f32 s = this->scale;
    s32 exhausted = (this->state == WARDEN_EXHAUSTED);
    s16 slump = exhausted ? 0x0E00 : 0;
    f32 flash = (this->hurtTimer > 0) ? 1.06f : 1.0f;

    Lil_SetupLitOpa(play);
    Lil_DrawPart(play, gLilWarden_BodyDL, 0, 0, 0, slump, 0, 0, s * flash, s, s * flash, false);
    Lil_DrawPart(play, gLilWarden_HeadDL, 0, exhausted ? -14.0f : 0.0f, exhausted ? 20.0f : 0.0f, slump, 0, 0, s, s, s, false);
    Lil_DrawPart(play, gLilWarden_CrownDL, 0, exhausted ? -14.0f : 0.0f, exhausted ? 20.0f : 0.0f, slump, 0, 0, s, s, s, false);
    Lil_DrawPart(play, gLilWarden_ArmsDL, 0, 0, 0, slump, 0, 0, s, s, s, false);
    Lil_DrawPart(play, gLilWarden_MaceDL, 74.0f * s, 150.0f * s, 0, this->maceAngle, 0, 0, s, s, s, false);
    Lil_DrawPart(play, gLilWarden_RootsDL, 0, 0, 0, 0, 0, 0, s, s, s, false);
}

ActorProfile LilWarden_Profile = {
    /**/ 0,
    /**/ ACTORCAT_BOSS,
    /**/ ACTOR_FLAG_ATTENTION_ENABLED | ACTOR_FLAG_HOSTILE,
    /**/ GAMEPLAY_KEEP,
    /**/ sizeof(BossLilWarden),
    /**/ BossLilWarden_Init,
    /**/ BossLilWarden_Destroy,
    /**/ BossLilWarden_Update,
    /**/ BossLilWarden_Draw,
};

/* ==================================================================================================================
 * Queen of Thorns
 * ================================================================================================================ */
enum {
    QUEEN_DORMANT,
    QUEEN_INTRO,
    QUEEN_FLOAT,
    QUEEN_SPIRAL,
    QUEEN_RINGS,
    QUEEN_SUMMON,
    QUEEN_REST,     // descended and vulnerable (phases 1 and 2)
    QUEEN_DAZED,    // the song stuns her (phases 1 and 2)
    QUEEN_ASLEEP,   // the song puts her to sleep: vulnerable, double damage (all phases, required for phase 3)
    QUEEN_TRANSITION,
    QUEEN_DYING
};

typedef struct BossLilQueen {
    /* 0x000 */ Actor actor;
    /* 0x144 */ ColliderCylinder collider;
    /* 0x190 */ s16 timer;
    /* 0x192 */ s16 state;
    /* 0x194 */ s16 flag;
    /* 0x196 */ s16 attackIndex;
    /* 0x198 */ s16 hurtTimer;
    /* 0x19A */ s16 spin;
    /* 0x19C */ s16 fireAngle;
    /* 0x19E */ s16 phase; // 1..3
    /* 0x1A0 */ s16 ringStep;
    /* 0x1A2 */ s16 bob;
    /* 0x1A4 */ f32 hover; // height above the arena floor
    /* 0x1A8 */ f32 scale;
    /* 0x1AC */ Vec3f center;
} BossLilQueen;

#define QUEEN_HEALTH 36
#define QUEEN_HOVER_HEIGHT 120.0f
#define QUEEN_TRIGGER 760.0f
#define QUEEN_LISTEN_RANGE 1500.0f

static ColliderCylinderInit sQueenCylinderInit = {
    {
        COL_MATERIAL_HIT3,
        AT_NONE,
        AC_ON | AC_TYPE_PLAYER,
        OC1_ON | OC1_TYPE_ALL,
        OC2_TYPE_1,
        COLSHAPE_CYLINDER,
    },
    {
        ELEM_MATERIAL_UNK0,
        { 0x00000000, 0x00, 0x00 },
        { 0xF7CFFFFF, 0x00, 0x00 },
        ATELEM_NONE | ATELEM_SFX_NORMAL,
        ACELEM_ON,
        OCELEM_ON,
    },
    { 46, 220, 0, { 0, 0, 0 } },
};

static CollisionCheckInfoInit sQueenColChkInfoInit = { QUEEN_HEALTH, 46, 220, 0xFF };

static void BossLilQueen_SetState(BossLilQueen* this, s16 state, s16 timer) {
    this->state = state;
    this->timer = timer;
}

static s16 BossLilQueen_PhaseForHealth(s32 health) {
    if (health > 24) {
        return 1;
    }
    if (health > 12) {
        return 2;
    }
    return 3;
}

static s32 BossLilQueen_IsVulnerable(BossLilQueen* this) {
    return (this->state == QUEEN_REST) || (this->state == QUEEN_DAZED) || (this->state == QUEEN_ASLEEP);
}

static s32 BossLilQueen_OnLullaby(Actor* thisx, PlayState* play) {
    BossLilQueen* this = (BossLilQueen*)thisx;
    Player* player = GET_PLAYER(play);

    if ((this->state == QUEEN_DORMANT) || (this->state == QUEEN_INTRO) || (this->state == QUEEN_DYING) ||
        (this->state == QUEEN_TRANSITION)) {
        return false;
    }
    if (Actor_WorldDistXZToActor(&this->actor, &player->actor) > QUEEN_LISTEN_RANGE) {
        return false;
    }
    if (this->phase >= 3) {
        BossLilQueen_SetState(this, QUEEN_ASLEEP, 170);
    } else {
        BossLilQueen_SetState(this, QUEEN_DAZED, 80);
    }
    return true;
}

static void BossLilQueen_NextAttack(BossLilQueen* this) {
    s16 pick = this->attackIndex++;

    if ((this->phase < 3) && ((pick % 4) == 3)) {
        BossLilQueen_SetState(this, QUEEN_REST, 110);
        return;
    }
    switch (pick % 3) {
        case 0:
            BossLilQueen_SetState(this, QUEEN_SPIRAL, 76);
            break;
        case 1:
            this->ringStep = 0;
            BossLilQueen_SetState(this, QUEEN_RINGS, 80);
            break;
        default:
            if (this->phase >= 2) {
                BossLilQueen_SetState(this, QUEEN_SUMMON, 50);
            } else {
                BossLilQueen_SetState(this, QUEEN_SPIRAL, 76);
            }
            break;
    }
}

void BossLilQueen_Init(Actor* thisx, PlayState* play) {
    BossLilQueen* this = (BossLilQueen*)thisx;

    this->flag = this->actor.params & 0x7F;
    if (Flags_GetSwitch(play, this->flag)) {
        // Already defeated: leave the way home open.
        Actor_Spawn(&play->actorCtx, play, gLilActorIds[LIL_ACT_RETURN_PORTAL], this->actor.home.pos.x,
                    this->actor.home.pos.y, this->actor.home.pos.z + 260.0f, 0, 0, 0, LIL_PORTAL_HOME);
        Actor_Kill(&this->actor);
        return;
    }
    Actor_ProcessInitChain(&this->actor, sBossInitChain);
    Actor_SetScale(&this->actor, 1.0f);
    this->actor.gravity = 0.0f;
    ActorShape_Init(&this->actor.shape, 0.0f, ActorShadow_DrawCircle, 70.0f);
    Collider_InitCylinder(play, &this->collider);
    Collider_SetCylinder(play, &this->collider, &this->actor, &sQueenCylinderInit);
    CollisionCheck_SetInfo(&this->actor.colChkInfo, &sBossDamageTable, &sQueenColChkInfoInit);
    this->center = this->actor.home.pos;
    this->scale = 1.0f;
    this->phase = 1;
    this->hover = 0.0f;
    this->actor.flags &= ~ACTOR_FLAG_ATTENTION_ENABLED;
    BossLilQueen_SetState(this, QUEEN_DORMANT, 0);
    Lil_RegisterLullabyListener(&this->actor, BossLilQueen_OnLullaby);
}

void BossLilQueen_Destroy(Actor* thisx, PlayState* play) {
    BossLilQueen* this = (BossLilQueen*)thisx;

    Lil_UnregisterLullabyListener(&this->actor);
    Collider_DestroyCylinder(play, &this->collider);
}

void BossLilQueen_Update(Actor* thisx, PlayState* play) {
    BossLilQueen* this = (BossLilQueen*)thisx;
    Actor* actor = &this->actor;
    Player* player = GET_PLAYER(play);
    f32 targetHover = QUEEN_HOVER_HEIGHT;
    s32 i;

    this->spin += 0x180;
    this->bob += 0x200;
    if (this->hurtTimer > 0) {
        this->hurtTimer--;
    }

    // taking damage
    if ((this->collider.base.acFlags & AC_HIT) && (this->state != QUEEN_DYING) && (this->state != QUEEN_DORMANT) &&
        (this->state != QUEEN_INTRO) && (this->state != QUEEN_TRANSITION)) {
        this->collider.base.acFlags &= ~AC_HIT;
        if (!BossLilQueen_IsVulnerable(this)) {
            Actor_PlaySfx(actor, NA_SE_IT_SHIELD_REFLECT_SW); // thorns turn the blow aside
        } else {
            s32 times = (this->state == QUEEN_ASLEEP) ? 2 : 1;
            s16 newPhase;

            while (times-- > 0) {
                Actor_ApplyDamage(actor);
            }
            this->hurtTimer = 8;
            Actor_PlaySfx(actor, NA_SE_EN_STALKID_ATTACK);
            if (actor->colChkInfo.health <= 0) {
                actor->flags &= ~ACTOR_FLAG_ATTENTION_ENABLED;
                this->collider.base.acFlags &= ~AC_ON;
                Enemy_StartFinishingBlow(play, actor);
                BossLilQueen_SetState(this, QUEEN_DYING, 70);
            } else {
                newPhase = BossLilQueen_PhaseForHealth(actor->colChkInfo.health);
                if (newPhase != this->phase) {
                    this->phase = newPhase;
                    Audio_PlaySfx(NA_SE_EN_KAICHO_CRY);
                    BossLilQueen_SetState(this, QUEEN_TRANSITION, 50);
                }
            }
        }
    }

    switch (this->state) {
        case QUEEN_DORMANT:
            if (actor->xzDistToPlayer < QUEEN_TRIGGER) {
                gLilWarpBlocked = 1;
                Audio_PlayBgm_StorePrevBgm(NA_BGM_BOSS);
                BossLilQueen_SetState(this, QUEEN_INTRO, 70);
            }
            targetHover = 0.0f;
            break;

        case QUEEN_INTRO:
            targetHover = QUEEN_HOVER_HEIGHT * (1.0f - (f32)this->timer / 70.0f);
            if ((this->timer % 12) == 0) {
                Boss_PetalRing(play, actor->world.pos.x, actor->world.pos.y + 30.0f, actor->world.pos.z, 8, this->spin, 4);
            }
            if (--this->timer <= 0) {
                actor->flags |= ACTOR_FLAG_ATTENTION_ENABLED;
                BossLilQueen_SetState(this, QUEEN_FLOAT, 50);
            }
            break;

        case QUEEN_FLOAT:
            if (--this->timer <= 0) {
                BossLilQueen_NextAttack(this);
            }
            break;

        case QUEEN_SPIRAL: {
            s32 streams = this->phase;

            this->fireAngle += 0x0C00;
            if ((this->timer % 3) == 0) {
                for (i = 0; i < streams; i++) {
                    Lil_SpawnHazard(play, LIL_HAZARD_PETAL, actor->world.pos.x, actor->world.pos.y + 40.0f, actor->world.pos.z,
                                    this->fireAngle + (s16)((i * 0x10000) / streams), 6);
                }
            }
            if (--this->timer <= 0) {
                BossLilQueen_SetState(this, QUEEN_FLOAT, 36);
            }
            break;
        }

        case QUEEN_RINGS:
            // expanding rings of thorns around the arena centre, each with a gap facing the player
            if (((this->timer % 22) == 0) && (this->ringStep < 3)) {
                s32 count = 8 + this->ringStep * 4;
                f32 radius = 190.0f + this->ringStep * 150.0f;
                s16 gapYaw = Math_Vec3f_Yaw(&this->center, &player->actor.world.pos);

                for (i = 0; i < count; i++) {
                    s16 a = (s16)((i * 0x10000) / count);
                    s16 diff = a - gapYaw;

                    if (ABS_ALT(diff) < 0x1600) {
                        continue;
                    }
                    Boss_SpawnSpike(play, this->center.x + Math_SinS(a) * radius, this->center.y, this->center.z + Math_CosS(a) * radius);
                }
                this->ringStep++;
            }
            if (--this->timer <= 0) {
                BossLilQueen_SetState(this, QUEEN_FLOAT, 36);
            }
            break;

        case QUEEN_SUMMON:
            if (this->timer == 25) {
                if (Lil_CountLilEnemies(play) < 4) {
                    for (i = 0; i < 2; i++) {
                        f32 sx = (i == 0) ? -240.0f : 240.0f;

                        if (Actor_SpawnAsChild(&play->actorCtx, actor, play, gLilActorIds[LIL_ACT_PETAL_WISP], this->center.x + sx,
                                               this->center.y + 90.0f, this->center.z + 120.0f, 0, 0, 0, LIL_ENEMY_PARAM_AWAKE) != NULL) {
                            Vec3f pos;

                            pos.x = this->center.x + sx;
                            pos.y = this->center.y + 100.0f;
                            pos.z = this->center.z + 120.0f;
                            Lil_Puff(play, &pos, 140.0f);
                        }
                    }
                }
            }
            if (--this->timer <= 0) {
                BossLilQueen_SetState(this, QUEEN_FLOAT, 36);
            }
            break;

        case QUEEN_REST:
        case QUEEN_DAZED:
            targetHover = 30.0f;
            if (--this->timer <= 0) {
                BossLilQueen_SetState(this, QUEEN_FLOAT, 30);
            }
            break;

        case QUEEN_ASLEEP:
            targetHover = 10.0f;
            if (--this->timer <= 0) {
                BossLilQueen_SetState(this, QUEEN_FLOAT, 40);
            }
            break;

        case QUEEN_TRANSITION:
            // the phase change: a burst of petals in every direction, then back to business
            if ((this->timer % 10) == 0) {
                Boss_PetalRing(play, actor->world.pos.x, actor->world.pos.y + 40.0f, actor->world.pos.z, 14, this->spin, 5);
            }
            if (--this->timer <= 0) {
                BossLilQueen_SetState(this, QUEEN_FLOAT, 30);
            }
            break;

        case QUEEN_DYING:
            targetHover = QUEEN_HOVER_HEIGHT + 60.0f * (1.0f - (f32)this->timer / 70.0f);
            this->scale = 0.3f + 0.7f * ((f32)this->timer / 70.0f);
            this->spin += 0x500;
            if ((this->timer % 5) == 0) {
                Vec3f pos;

                pos.x = actor->world.pos.x + Rand_CenteredFloat(140.0f);
                pos.y = actor->world.pos.y + Rand_ZeroFloat(240.0f);
                pos.z = actor->world.pos.z + Rand_CenteredFloat(140.0f);
                Lil_Puff(play, &pos, 140.0f);
            }
            if (--this->timer <= 0) {
                Vec3f rewardPos = this->center;

                rewardPos.y += 20.0f;
                Flags_SetSwitch(play, this->flag);
                Item_DropCollectible(play, &rewardPos, ITEM00_HEART_CONTAINER);
                Actor_Spawn(&play->actorCtx, play, gLilActorIds[LIL_ACT_RETURN_PORTAL], this->center.x, this->center.y,
                            this->center.z + 260.0f, 0, 0, 0, LIL_PORTAL_HOME);
                Audio_PlaySfx(NA_SE_SY_CORRECT_CHIME);
                Audio_RestorePrevBgm();
                gLilWarpBlocked = 0;
                Actor_Kill(actor);
                return;
            }
            break;

        default:
            break;
    }

    // hovering and facing
    Math_ApproachF(&this->hover, targetHover + ((this->state == QUEEN_FLOAT || this->state == QUEEN_SPIRAL) ? Math_SinS(this->bob) * 10.0f : 0.0f), 0.12f, 6.0f);
    actor->world.pos.y = this->center.y + this->hover;
    if ((this->state != QUEEN_DORMANT) && (this->state != QUEEN_ASLEEP) && (this->state != QUEEN_DYING)) {
        Math_SmoothStepToS(&actor->shape.rot.y, actor->yawTowardsPlayer, 5, 0x400, 0x80);
    }

    Actor_UpdateBgCheckInfo(play, actor, 20.0f, 30.0f, 40.0f, UPDBGCHECKINFO_FLAG_4);
    Collider_UpdateCylinder(actor, &this->collider);
    if (this->collider.base.acFlags & AC_ON) {
        CollisionCheck_SetAC(play, &play->colChkCtx, &this->collider.base);
    }
    if (this->state != QUEEN_DYING) {
        CollisionCheck_SetOC(play, &play->colChkCtx, &this->collider.base);
    }
    Actor_SetFocus(actor, 150.0f);
}

void BossLilQueen_Draw(Actor* thisx, PlayState* play) {
    BossLilQueen* this = (BossLilQueen*)thisx;
    f32 s = this->scale * ((this->hurtTimer > 0) ? 1.05f : 1.0f);
    s32 asleep = (this->state == QUEEN_ASLEEP);
    s16 slump = asleep ? 0x1200 : 0;

    Lil_SetupLitOpa(play);
    Lil_DrawPart(play, gLilQueen_GownDL, 0, 0, 0, 0, 0, 0, s, s, s, false);
    Lil_DrawPart(play, gLilQueen_BustDL, 0, 0, 0, slump, 0, 0, s, s, s, false);
    Lil_DrawPart(play, gLilQueen_HeadDL, 0, asleep ? -24.0f : 0.0f, asleep ? 30.0f : 0.0f, slump, 0, 0, s, s, s, false);
    Lil_DrawPart(play, gLilQueen_CrownDL, 0, asleep ? -24.0f : 0.0f, asleep ? 30.0f : 0.0f, slump, 0, 0, s, s, s, false);
    Lil_DrawPart(play, gLilQueen_ArmsDL, 0, 0, 0, asleep ? 0x1800 : 0, 0, 0, s, s, s, false);
    Lil_DrawPart(play, gLilQueen_PetalsDL, 0, 0, 0, 0, asleep ? 0 : this->spin, 0, s, s, s, false);
}

ActorProfile LilQueen_Profile = {
    /**/ 0,
    /**/ ACTORCAT_BOSS,
    /**/ ACTOR_FLAG_ATTENTION_ENABLED | ACTOR_FLAG_HOSTILE,
    /**/ GAMEPLAY_KEEP,
    /**/ sizeof(BossLilQueen),
    /**/ BossLilQueen_Init,
    /**/ BossLilQueen_Destroy,
    /**/ BossLilQueen_Update,
    /**/ BossLilQueen_Draw,
};
