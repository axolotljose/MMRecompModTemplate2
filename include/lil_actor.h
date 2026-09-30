#ifndef LIL_ACTOR_H
#define LIL_ACTOR_H

/**
 * Shared helpers for the mod's custom actors.
 *
 * All custom models come from tools/gen_world.py (src/gen/lil_models.c). They are lit by vertex normals, drawn in the
 * actor's own local space, with `PRIMITIVE * SHADE` colour (each part sets its own primitive colour).
 * Actors use an actor scale of 1.0 because the models are authored in game units.
 */

#include "lilith.h"
#include "lil_gen.h"

#define LIL_FRAMES_PER_SECOND 20 // the game's update rate

/* ---------------------------------------------------------------------------------------------------------------
 * Enemies
 * ------------------------------------------------------------------------------------------------------------- */
typedef struct LilEnemyBase {
    /* 0x000 */ Actor actor;
    /* 0x144 */ s16 sleepTimer; // > 0: lulled to sleep by Lilith's Lullaby
    /* 0x146 */ s16 hurtTimer;  // short visual squash after being hit
} LilEnemyBase;

// Puts every awake custom enemy within `radius` of the player to sleep for `frames` updates.
// Returns how many were put to sleep (0 if there was nothing awake nearby).
s32 Lil_SleepPulse(PlayState* play, f32 radius, s16 frames);
s32 Lil_IsLilEnemyId(s16 actorId);

/* ---------------------------------------------------------------------------------------------------------------
 * Arena controller (arena.c)
 * ------------------------------------------------------------------------------------------------------------- */
typedef struct EnLilArena {
    /* 0x000 */ Actor actor;
    /* 0x144 */ s16 alive;    // enemies spawned by this arena that are still alive
    /* 0x146 */ s16 wave;     // next wave to spawn
    /* 0x148 */ s16 timer;
    /* 0x14A */ u8 state;
    /* 0x14B */ u8 arenaId;
} EnLilArena;

// Enemies spawned by an arena have it as their parent; the arena counts its living children to know when a wave is over.
#define LIL_ENEMY_PARAM_AWAKE 0x0001 // enemies spawned by an arena start out awake and hostile

/* ---------------------------------------------------------------------------------------------------------------
 * Hazards (arena.c): petal shots, thorn spikes
 * ------------------------------------------------------------------------------------------------------------- */
#define LIL_HAZARD_PETAL 0 // flies straight along its heading
#define LIL_HAZARD_SPIKE 1 // telegraphs, erupts, retracts

// `speed` is in units per update (petal shots only). Returns the new actor (or NULL).
Actor* Lil_SpawnHazard(PlayState* play, s32 type, f32 x, f32 y, f32 z, s16 yaw, s32 speed);

/* ---------------------------------------------------------------------------------------------------------------
 * Drawing helpers (actor_common.c)
 * ------------------------------------------------------------------------------------------------------------- */
// Call once before drawing opaque generated models.
void Lil_SetupLitOpa(PlayState* play);
// Like Lil_SetupLitOpa, but the colour is multiplied by the environment colour (gDPSetEnvColor) so parts can be tinted.
void Lil_SetupLitOpaTint(PlayState* play);
// Call once before drawing translucent generated models; `alpha` is 0-255.
void Lil_SetupLitXlu(PlayState* play, u8 alpha);
// Draws one model part relative to the current (actor) matrix. Rotations are applied Y, X, Z.
void Lil_DrawPart(PlayState* play, Gfx* dl, f32 x, f32 y, f32 z, s16 rotX, s16 rotY, s16 rotZ, f32 scaleX, f32 scaleY,
                  f32 scaleZ, s32 xlu);

/* ---------------------------------------------------------------------------------------------------------------
 * Misc helpers
 * ------------------------------------------------------------------------------------------------------------- */
void Lil_Puff(PlayState* play, Vec3f* pos, f32 scale);
// Number of enemies of the mod that are alive (used by boss fights).
s32 Lil_CountLilEnemies(PlayState* play);

/* Actor profiles (defined in the actor source files). */
extern ActorProfile LilStatue_Profile;
extern ActorProfile LilPortal_Profile;
extern ActorProfile LilBarrier_Profile;
extern ActorProfile LilPlate_Profile;
extern ActorProfile LilPath_Profile;
extern ActorProfile LilBramble_Profile;
extern ActorProfile LilArena_Profile;
extern ActorProfile LilThornling_Profile;
extern ActorProfile LilWisp_Profile;
extern ActorProfile LilKnight_Profile;
extern ActorProfile LilHazard_Profile;
extern ActorProfile LilWarden_Profile;
extern ActorProfile LilQueen_Profile;

/* Warp helper used by the "go home" portal (lullaby.c). */
void Lil_FadeHome(PlayState* play);

#endif /* LIL_ACTOR_H */
