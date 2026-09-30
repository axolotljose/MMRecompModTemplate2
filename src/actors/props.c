/**
 * Props and puzzle pieces of the Sanctuary and the Crypt:
 *   - Lilith's statue (hears the song and unseals the crypt gate)
 *   - the rose circles (portals)
 *   - thorn walls / white rose gate (dynamic collision, open on a switch flag)
 *   - pressure plate
 *   - the Petal Path (repeat the pattern the pads show you)
 *   - brambles (burn or blast them away)
 */

#include "lil_actor.h"

static InitChainEntry sPropInitChain[] = {
    ICHAIN_F32(cullingVolumeDistance, 4500, ICHAIN_STOP),
};

#define PROP_FLAGS (ACTOR_FLAG_UPDATE_CULLING_DISABLED | ACTOR_FLAG_DRAW_CULLING_DISABLED)

/* ==================================================================================================================
 * Lilith's statue
 * ================================================================================================================ */
#define STATUE_LISTEN_RANGE 520.0f

typedef struct EnLilStatue {
    /* 0x000 */ Actor actor;
    /* 0x144 */ s16 flag;
    /* 0x146 */ s16 pulse;
} EnLilStatue;

static s32 EnLilStatue_OnLullaby(Actor* thisx, PlayState* play) {
    EnLilStatue* this = (EnLilStatue*)thisx;
    Player* player = GET_PLAYER(play);

    if (Actor_WorldDistXZToActor(&this->actor, &player->actor) > STATUE_LISTEN_RANGE) {
        return false;
    }
    if (Flags_GetSwitch(play, this->flag)) {
        return false; // already unsealed: the song takes you home as usual
    }
    Flags_SetSwitch(play, this->flag);
    return true;
}

void EnLilStatue_Init(Actor* thisx, PlayState* play) {
    EnLilStatue* this = (EnLilStatue*)thisx;

    Actor_ProcessInitChain(&this->actor, sPropInitChain);
    Actor_SetScale(&this->actor, 1.0f);
    this->flag = this->actor.params & 0x7F;
    Lil_RegisterLullabyListener(&this->actor, EnLilStatue_OnLullaby);
}

void EnLilStatue_Destroy(Actor* thisx, PlayState* play) {
    Lil_UnregisterLullabyListener(thisx);
}

void EnLilStatue_Update(Actor* thisx, PlayState* play) {
    EnLilStatue* this = (EnLilStatue*)thisx;

    this->pulse += 0x180;
}

void EnLilStatue_Draw(Actor* thisx, PlayState* play) {
    EnLilStatue* this = (EnLilStatue*)thisx;
    s16 halo = this->pulse;
    f32 bob = Math_SinS(this->pulse) * 4.0f;

    Lil_SetupLitOpa(play);
    Lil_DrawPart(play, gLilLilithStatue_RobeDL, 0, 0, 0, 0, 0, 0, 1.0f, 1.0f, 1.0f, false);
    Lil_DrawPart(play, gLilLilithStatue_HeadDL, 0, 0, 0, 0, 0, 0, 1.0f, 1.0f, 1.0f, false);
    Lil_DrawPart(play, gLilLilithStatue_ArmsDL, 0, 0, 0, 0, 0, 0, 1.0f, 1.0f, 1.0f, false);
    Lil_DrawPart(play, gLilLilithStatue_RoseDL, 0, 0, 0, 0, 0, 0, 1.0f, 1.0f, 1.0f, false);
    Lil_DrawPart(play, gLilLilithStatue_LeafDL, 0, 0, 0, 0, 0, 0, 1.0f, 1.0f, 1.0f, false);
    Lil_DrawPart(play, gLilLilithStatue_HaloDL, 0, bob, 0, 0, halo, 0, 1.0f, 1.0f, 1.0f, false);
}

ActorProfile LilStatue_Profile = {
    /**/ 0,
    /**/ ACTORCAT_PROP,
    /**/ PROP_FLAGS,
    /**/ GAMEPLAY_KEEP,
    /**/ sizeof(EnLilStatue),
    /**/ EnLilStatue_Init,
    /**/ EnLilStatue_Destroy,
    /**/ EnLilStatue_Update,
    /**/ EnLilStatue_Draw,
};

/* ==================================================================================================================
 * Rose circle (portal)
 * ================================================================================================================ */
typedef struct EnLilPortal {
    /* 0x000 */ Actor actor;
    /* 0x144 */ s16 spin;
    /* 0x146 */ s16 variant;
    /* 0x148 */ u8 armed;
    /* 0x149 */ u8 triggered;
} EnLilPortal;

void EnLilPortal_Init(Actor* thisx, PlayState* play) {
    EnLilPortal* this = (EnLilPortal*)thisx;

    Actor_ProcessInitChain(&this->actor, sPropInitChain);
    Actor_SetScale(&this->actor, 1.0f);
    this->variant = this->actor.params & 0xF;
    // The circle only arms once the player has stepped away from it, so arriving on top of one never bounces you back.
    this->armed = false;
    this->triggered = false;
}

void EnLilPortal_Destroy(Actor* thisx, PlayState* play) {
}

void EnLilPortal_Update(Actor* thisx, PlayState* play) {
    EnLilPortal* this = (EnLilPortal*)thisx;
    Player* player = GET_PLAYER(play);

    this->spin += 0x200;

    if (!this->armed) {
        if (this->actor.xzDistToPlayer > 90.0f) {
            this->armed = true;
        }
        return;
    }
    if (this->triggered) {
        return;
    }
    if ((this->actor.xzDistToPlayer < 40.0f) && (fabsf(player->actor.world.pos.y - this->actor.world.pos.y) < 50.0f) &&
        (play->transitionTrigger == TRANS_TRIGGER_OFF) && (play->transitionMode == TRANS_MODE_OFF) &&
        (play->msgCtx.msgMode == MSGMODE_NONE)) {
        this->triggered = true;
        Actor_PlaySfx(&this->actor, NA_SE_EV_STONE_STATUE_OPEN);

        switch (this->variant) {
            case LIL_PORTAL_TO_CRYPT:
                play->nextEntrance = LIL_ENTRANCE_CRYPT(LIL_SPAWN_CRYPT_ENTRY);
                play->transitionTrigger = TRANS_TRIGGER_START;
                play->transitionType = TRANS_TYPE_FADE_BLACK;
                break;
            case LIL_PORTAL_TO_SANCTUARY:
                play->nextEntrance = LIL_ENTRANCE_SANCTUARY(LIL_SPAWN_SANCTUARY_CRYPT);
                play->transitionTrigger = TRANS_TRIGGER_START;
                play->transitionType = TRANS_TYPE_FADE_BLACK;
                break;
            default:
                Lil_FadeHome(play);
                break;
        }
    }
}

void EnLilPortal_Draw(Actor* thisx, PlayState* play) {
    EnLilPortal* this = (EnLilPortal*)thisx;
    f32 pulse = 0.5f + 0.5f * Math_SinS(this->spin * 2);
    u8 alpha = (u8)(150 + (s32)(pulse * 80.0f));

    Lil_SetupLitXlu(play, alpha);
    Lil_DrawPart(play, gLilPortal_RingDL, 0, 6, 0, 0, this->spin, 0, 1.0f, 1.0f, 1.0f, true);
    Lil_DrawPart(play, gLilPortal_GlowDL, 0, 4, 0, 0, 0, 0, 1.0f + pulse * 0.2f, 1.0f, 1.0f + pulse * 0.2f, true);
    Lil_DrawPart(play, gLilPortal_RingDL, 0, 12, 0, 0, -this->spin, 0, 0.6f, 1.0f, 0.6f, true);
}

ActorProfile LilPortal_Profile = {
    /**/ 0,
    /**/ ACTORCAT_PROP,
    /**/ PROP_FLAGS,
    /**/ GAMEPLAY_KEEP,
    /**/ sizeof(EnLilPortal),
    /**/ EnLilPortal_Init,
    /**/ EnLilPortal_Destroy,
    /**/ EnLilPortal_Update,
    /**/ EnLilPortal_Draw,
};

/* ==================================================================================================================
 * Thorn wall / white rose gate
 * params: (variant << 8) | switchFlag
 * ================================================================================================================ */
typedef struct EnLilBarrier {
    /* 0x000 */ DynaPolyActor dyna;
    /* 0x15C */ f32 sink;
    /* 0x160 */ s16 flag;
    /* 0x162 */ u8 variant;
    /* 0x163 */ u8 open;
} EnLilBarrier;

#define BARRIER_SINK_DEPTH 310.0f

void EnLilBarrier_Init(Actor* thisx, PlayState* play) {
    EnLilBarrier* this = (EnLilBarrier*)thisx;
    CollisionHeader* colHeader = NULL;

    Actor_ProcessInitChain(&this->dyna.actor, sPropInitChain);
    Actor_SetScale(&this->dyna.actor, 1.0f);
    this->flag = this->dyna.actor.params & 0x7F;
    this->variant = (this->dyna.actor.params >> 8) & 0xF;

    DynaPolyActor_Init(&this->dyna, 0);
    CollisionHeader_GetVirtual(&gLilBarrierCol, &colHeader);
    DynaPolyActor_LoadMesh(play, &this->dyna, colHeader);

    if (Flags_GetSwitch(play, this->flag)) {
        this->sink = BARRIER_SINK_DEPTH;
        this->open = true;
        this->dyna.actor.world.pos.y = this->dyna.actor.home.pos.y - this->sink;
        DynaPoly_DisableCollision(play, &play->colCtx.dyna, this->dyna.bgId);
    }
}

void EnLilBarrier_Destroy(Actor* thisx, PlayState* play) {
    EnLilBarrier* this = (EnLilBarrier*)thisx;

    DynaPoly_DeleteBgActor(play, &play->colCtx.dyna, this->dyna.bgId);
}

void EnLilBarrier_Update(Actor* thisx, PlayState* play) {
    EnLilBarrier* this = (EnLilBarrier*)thisx;

    if (this->open) {
        return;
    }
    if (Flags_GetSwitch(play, this->flag)) {
        if (this->sink == 0.0f) {
            Actor_PlaySfx(&this->dyna.actor, NA_SE_EV_STONEDOOR_OPEN_S);
        }
        if (Math_StepToF(&this->sink, BARRIER_SINK_DEPTH, 6.0f)) {
            this->open = true;
            DynaPoly_DisableCollision(play, &play->colCtx.dyna, this->dyna.bgId);
        }
        this->dyna.actor.world.pos.y = this->dyna.actor.home.pos.y - this->sink;
    }
}

void EnLilBarrier_Draw(Actor* thisx, PlayState* play) {
    EnLilBarrier* this = (EnLilBarrier*)thisx;

    if (this->open) {
        return;
    }
    Lil_SetupLitOpa(play);
    if (this->variant == LIL_BARRIER_SANCTUARY) {
        Lil_DrawPart(play, gLilBarrier1_PostsDL, 0, 0, 0, 0, 0, 0, 1.0f, 1.0f, 1.0f, false);
        Lil_DrawPart(play, gLilBarrier1_RosesDL, 0, 0, 0, 0, 0, 0, 1.0f, 1.0f, 1.0f, false);
        Lil_DrawPart(play, gLilBarrier1_BudsDL, 0, 0, 0, 0, 0, 0, 1.0f, 1.0f, 1.0f, false);
        Lil_DrawPart(play, gLilBarrier1_ArchDL, 0, 0, 0, 0, 0, 0, 1.0f, 1.0f, 1.0f, false);
    } else {
        Lil_DrawPart(play, gLilBarrier0_PostsDL, 0, 0, 0, 0, 0, 0, 1.0f, 1.0f, 1.0f, false);
        Lil_DrawPart(play, gLilBarrier0_ThornsDL, 0, 0, 0, 0, 0, 0, 1.0f, 1.0f, 1.0f, false);
        Lil_DrawPart(play, gLilBarrier0_BarsDL, 0, 0, 0, 0, 0, 0, 1.0f, 1.0f, 1.0f, false);
    }
}

ActorProfile LilBarrier_Profile = {
    /**/ 0,
    /**/ ACTORCAT_BG,
    /**/ PROP_FLAGS,
    /**/ GAMEPLAY_KEEP,
    /**/ sizeof(EnLilBarrier),
    /**/ EnLilBarrier_Init,
    /**/ EnLilBarrier_Destroy,
    /**/ EnLilBarrier_Update,
    /**/ EnLilBarrier_Draw,
};

/* ==================================================================================================================
 * Pressure plate
 * params: (unused << 8) | switchFlag
 * ================================================================================================================ */
typedef struct EnLilPlate {
    /* 0x000 */ Actor actor;
    /* 0x144 */ f32 depth;
    /* 0x148 */ s16 flag;
    /* 0x14A */ u8 pressed;
} EnLilPlate;

void EnLilPlate_Init(Actor* thisx, PlayState* play) {
    EnLilPlate* this = (EnLilPlate*)thisx;

    Actor_ProcessInitChain(&this->actor, sPropInitChain);
    Actor_SetScale(&this->actor, 1.0f);
    this->flag = this->actor.params & 0x7F;
    if (Flags_GetSwitch(play, this->flag)) {
        this->pressed = true;
        this->depth = 5.0f;
    }
}

void EnLilPlate_Destroy(Actor* thisx, PlayState* play) {
}

void EnLilPlate_Update(Actor* thisx, PlayState* play) {
    EnLilPlate* this = (EnLilPlate*)thisx;
    Player* player = GET_PLAYER(play);

    if (!this->pressed) {
        if ((this->actor.xzDistToPlayer < 42.0f) && (fabsf(player->actor.world.pos.y - this->actor.world.pos.y) < 24.0f) &&
            (player->actor.bgCheckFlags & BGCHECKFLAG_GROUND)) {
            this->pressed = true;
            Flags_SetSwitch(play, this->flag);
            Actor_PlaySfx(&this->actor, NA_SE_EV_BLOCK_BOUND);
        }
    }
    Math_StepToF(&this->depth, this->pressed ? 5.0f : 0.0f, 1.0f);
}

void EnLilPlate_Draw(Actor* thisx, PlayState* play) {
    EnLilPlate* this = (EnLilPlate*)thisx;

    Lil_SetupLitOpa(play);
    Lil_DrawPart(play, gLilPlate_BaseDL, 0, 0, 0, 0, 0, 0, 1.0f, 1.0f, 1.0f, false);
    Lil_DrawPart(play, gLilPlate_TopDL, 0, -this->depth, 0, 0, 0, 0, 1.0f, 1.0f, 1.0f, false);
}

ActorProfile LilPlate_Profile = {
    /**/ 0,
    /**/ ACTORCAT_PROP,
    /**/ PROP_FLAGS,
    /**/ GAMEPLAY_KEEP,
    /**/ sizeof(EnLilPlate),
    /**/ EnLilPlate_Init,
    /**/ EnLilPlate_Destroy,
    /**/ EnLilPlate_Update,
    /**/ EnLilPlate_Draw,
};

/* ==================================================================================================================
 * The Petal Path: four pads in a cross. They light up in a pattern, and you step on them in the same order.
 * The pattern is the start of Lilith's Lullaby: C-Up, C-Left, C-Right, C-Left, C-Up  ->  N, W, E, W, N.
 * params: switchFlag (set when solved)
 * ================================================================================================================ */
#define PATH_PADS 4
#define PATH_PAD_DIST 130.0f
#define PATH_PAD_RADIUS 38.0f
#define PATH_SEQ_LEN 5
#define PATH_STEP_FRAMES 18
#define PATH_GAP_FRAMES 6

enum { PATH_IDLE, PATH_DEMO, PATH_INPUT, PATH_SOLVED, PATH_FAIL };
enum { PAD_N, PAD_E, PAD_S, PAD_W };

static const u8 sPathSequence[PATH_SEQ_LEN] = { PAD_N, PAD_W, PAD_E, PAD_W, PAD_N };
static const f32 sPadOffsetX[PATH_PADS] = { 0.0f, PATH_PAD_DIST, 0.0f, -PATH_PAD_DIST };
static const f32 sPadOffsetZ[PATH_PADS] = { -PATH_PAD_DIST, 0.0f, PATH_PAD_DIST, 0.0f };
static const u8 sPadColors[PATH_PADS][3] = { { 255, 235, 120 }, { 255, 130, 160 }, { 120, 255, 170 }, { 130, 170, 255 } };

typedef struct EnLilPath {
    /* 0x000 */ Actor actor;
    /* 0x144 */ s16 flag;
    /* 0x146 */ s16 timer;
    /* 0x148 */ s16 glow[PATH_PADS];
    /* 0x150 */ u8 state;
    /* 0x151 */ u8 index;
    /* 0x152 */ s8 lastPad;
    /* 0x153 */ u8 failFlash;
} EnLilPath;

static s32 EnLilPath_PadUnderPlayer(EnLilPath* this, PlayState* play) {
    Player* player = GET_PLAYER(play);
    s32 i;

    if (!(player->actor.bgCheckFlags & BGCHECKFLAG_GROUND)) {
        return -1;
    }
    for (i = 0; i < PATH_PADS; i++) {
        f32 dx = player->actor.world.pos.x - (this->actor.world.pos.x + sPadOffsetX[i]);
        f32 dz = player->actor.world.pos.z - (this->actor.world.pos.z + sPadOffsetZ[i]);

        if ((SQ(dx) + SQ(dz)) < SQ(PATH_PAD_RADIUS)) {
            return i;
        }
    }
    return -1;
}

void EnLilPath_Init(Actor* thisx, PlayState* play) {
    EnLilPath* this = (EnLilPath*)thisx;

    Actor_ProcessInitChain(&this->actor, sPropInitChain);
    Actor_SetScale(&this->actor, 1.0f);
    this->flag = this->actor.params & 0x7F;
    this->lastPad = -1;
    if (Flags_GetSwitch(play, this->flag)) {
        this->state = PATH_SOLVED;
        this->glow[0] = this->glow[1] = this->glow[2] = this->glow[3] = 40;
    } else {
        this->state = PATH_IDLE;
    }
}

void EnLilPath_Destroy(Actor* thisx, PlayState* play) {
}

void EnLilPath_Update(Actor* thisx, PlayState* play) {
    EnLilPath* this = (EnLilPath*)thisx;
    s32 i;
    s32 pad;

    for (i = 0; i < PATH_PADS; i++) {
        if (this->glow[i] > 0 && this->state != PATH_SOLVED) {
            this->glow[i]--;
        }
    }
    if (this->failFlash > 0) {
        this->failFlash--;
    }

    switch (this->state) {
        case PATH_IDLE:
            if (this->actor.xzDistToPlayer < 480.0f) {
                this->state = PATH_DEMO;
                this->index = 0;
                this->timer = 30;
            }
            break;

        case PATH_DEMO:
            if (this->timer > 0) {
                this->timer--;
                break;
            }
            if (this->index >= PATH_SEQ_LEN) {
                this->state = PATH_INPUT;
                this->index = 0;
                this->lastPad = EnLilPath_PadUnderPlayer(this, play);
                break;
            }
            this->glow[sPathSequence[this->index]] = PATH_STEP_FRAMES;
            Audio_PlaySfx_AtPos(&this->actor.world.pos, NA_SE_SY_DECIDE);
            this->index++;
            this->timer = PATH_STEP_FRAMES + PATH_GAP_FRAMES;
            break;

        case PATH_INPUT:
            pad = EnLilPath_PadUnderPlayer(this, play);
            if ((pad >= 0) && (pad != this->lastPad)) {
                if (pad == sPathSequence[this->index]) {
                    this->glow[pad] = 30;
                    Audio_PlaySfx_AtPos(&this->actor.world.pos, NA_SE_SY_DECIDE);
                    this->index++;
                    if (this->index >= PATH_SEQ_LEN) {
                        this->state = PATH_SOLVED;
                        Flags_SetSwitch(play, this->flag);
                        Audio_PlaySfx(NA_SE_SY_CORRECT_CHIME);
                        this->glow[0] = this->glow[1] = this->glow[2] = this->glow[3] = 40;
                    }
                } else {
                    this->state = PATH_FAIL;
                    this->timer = 40;
                    this->failFlash = 30;
                    Audio_PlaySfx(NA_SE_SY_ERROR);
                }
            }
            this->lastPad = pad;
            break;

        case PATH_FAIL:
            if (this->timer > 0) {
                this->timer--;
            } else {
                this->state = PATH_DEMO;
                this->index = 0;
                this->timer = 30;
            }
            break;

        default:
            break;
    }
}

void EnLilPath_Draw(Actor* thisx, PlayState* play) {
    EnLilPath* this = (EnLilPath*)thisx;
    s32 i;

    OPEN_DISPS(play->state.gfxCtx);

    Lil_SetupLitOpaTint(play);
    for (i = 0; i < PATH_PADS; i++) {
        f32 glow = (f32)this->glow[i] / 20.0f;
        s32 r = 70;
        s32 g = 70;
        s32 b = 90;

        if (glow > 1.0f) {
            glow = 1.0f;
        }
        if (this->failFlash != 0) {
            r = 255;
            g = 40;
            b = 40;
        } else {
            r += (s32)((sPadColors[i][0] - 70) * glow);
            g += (s32)((sPadColors[i][1] - 70) * glow);
            b += (s32)((sPadColors[i][2] - 70) * glow);
        }
        gDPSetEnvColor(POLY_OPA_DISP++, r, g, b, 255);
        Lil_DrawPart(play, gLilPathPad_PadDL, sPadOffsetX[i], 0, sPadOffsetZ[i], 0, 0, 0, 1.0f, 1.0f, 1.0f, false);
    }

    CLOSE_DISPS(play->state.gfxCtx);
}

ActorProfile LilPath_Profile = {
    /**/ 0,
    /**/ ACTORCAT_PROP,
    /**/ PROP_FLAGS,
    /**/ GAMEPLAY_KEEP,
    /**/ sizeof(EnLilPath),
    /**/ EnLilPath_Init,
    /**/ EnLilPath_Destroy,
    /**/ EnLilPath_Update,
    /**/ EnLilPath_Draw,
};

/* ==================================================================================================================
 * Brambles: a wall of thorny vines. Fire (fire arrows, burning sticks) or explosions clear them.
 * ================================================================================================================ */
typedef struct EnLilBramble {
    /* 0x000 */ DynaPolyActor dyna;
    /* 0x15C */ ColliderCylinder collider;
    /* 0x1A8 */ s16 burnTimer;
    /* 0x1AA */ u8 burning;
} EnLilBramble;

static ColliderCylinderInit sBrambleCylinderInit = {
    {
        COL_MATERIAL_HIT0,
        AT_NONE,
        AC_ON | AC_TYPE_PLAYER,
        OC1_NONE,
        OC2_NONE,
        COLSHAPE_CYLINDER,
    },
    {
        ELEM_MATERIAL_UNK0,
        { 0x00000000, 0x00, 0x00 },
        { DMG_EXPLOSIVES | DMG_FIRE_ARROW | DMG_DEKU_STICK, 0x00, 0x00 },
        ATELEM_NONE | ATELEM_SFX_NORMAL,
        ACELEM_ON,
        OCELEM_NONE,
    },
    { 115, 210, 0, { 0, 0, 0 } },
};

void EnLilBramble_Init(Actor* thisx, PlayState* play) {
    EnLilBramble* this = (EnLilBramble*)thisx;
    CollisionHeader* colHeader = NULL;

    Actor_ProcessInitChain(&this->dyna.actor, sPropInitChain);
    Actor_SetScale(&this->dyna.actor, 1.0f);
    DynaPolyActor_Init(&this->dyna, 0);
    CollisionHeader_GetVirtual(&gLilBrambleCol, &colHeader);
    DynaPolyActor_LoadMesh(play, &this->dyna, colHeader);

    Collider_InitCylinder(play, &this->collider);
    Collider_SetCylinder(play, &this->collider, &this->dyna.actor, &sBrambleCylinderInit);
    Collider_UpdateCylinder(&this->dyna.actor, &this->collider);
}

void EnLilBramble_Destroy(Actor* thisx, PlayState* play) {
    EnLilBramble* this = (EnLilBramble*)thisx;

    DynaPoly_DeleteBgActor(play, &play->colCtx.dyna, this->dyna.bgId);
    Collider_DestroyCylinder(play, &this->collider);
}

void EnLilBramble_Update(Actor* thisx, PlayState* play) {
    EnLilBramble* this = (EnLilBramble*)thisx;

    if (!this->burning) {
        if (this->collider.base.acFlags & AC_HIT) {
            this->collider.base.acFlags &= ~AC_HIT;
            this->burning = true;
            this->burnTimer = 28;
            Actor_PlaySfx(&this->dyna.actor, NA_SE_EV_FIRE_PILLAR);
            // The passage opens as soon as the brambles catch.
            DynaPoly_DisableCollision(play, &play->colCtx.dyna, this->dyna.bgId);
        } else {
            CollisionCheck_SetAC(play, &play->colChkCtx, &this->collider.base);
        }
        return;
    }

    if (this->burnTimer > 0) {
        Vec3f pos;

        pos.x = this->dyna.actor.world.pos.x + Rand_CenteredFloat(200.0f);
        pos.y = this->dyna.actor.world.pos.y + Rand_ZeroFloat(180.0f);
        pos.z = this->dyna.actor.world.pos.z + Rand_CenteredFloat(30.0f);
        Lil_Puff(play, &pos, 60.0f);
        this->burnTimer--;
    } else {
        Actor_Kill(&this->dyna.actor);
    }
}

void EnLilBramble_Draw(Actor* thisx, PlayState* play) {
    EnLilBramble* this = (EnLilBramble*)thisx;
    f32 burn = this->burning ? (1.0f - (f32)this->burnTimer / 28.0f) : 0.0f;
    f32 squash = 1.0f - burn * 0.85f;
    s32 r = 255 - (s32)(burn * 160.0f);
    s32 g = 255 - (s32)(burn * 170.0f);
    s32 b = 255 - (s32)(burn * 200.0f);

    OPEN_DISPS(play->state.gfxCtx);

    Lil_SetupLitOpaTint(play);
    gDPSetEnvColor(POLY_OPA_DISP++, r, g, b, 255);
    Lil_DrawPart(play, gLilBramble_VinesDL, 0, 0, 0, 0, 0, 0, 1.0f, squash, 1.0f, false);
    Lil_DrawPart(play, gLilBramble_ThornsDL, 0, 0, 0, 0, 0, 0, 1.0f, squash, 1.0f, false);

    CLOSE_DISPS(play->state.gfxCtx);
}

ActorProfile LilBramble_Profile = {
    /**/ 0,
    /**/ ACTORCAT_BG,
    /**/ PROP_FLAGS,
    /**/ GAMEPLAY_KEEP,
    /**/ sizeof(EnLilBramble),
    /**/ EnLilBramble_Init,
    /**/ EnLilBramble_Destroy,
    /**/ EnLilBramble_Update,
    /**/ EnLilBramble_Draw,
};
