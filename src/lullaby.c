/**
 * Lilith's Lullaby - song detection and warping.
 *
 * How it works
 * ------------
 * The vanilla ocarina code only recognises the 24 songs it has tables for, and only lets you play a song if the matching
 * quest item bit is set in your save file. Rather than hijack one of those slots (which would mean mutating the save), we
 * watch the notes the player is playing ourselves and look for our own melody:
 *
 *   C-Up, C-Left, C-Right, C-Left, C-Up, C-Left, C-Down       (see tools/check_melody.py, it does not clash with any
 *                                                              vanilla song, in either direction)
 *
 * When the melody is completed the ocarina session is closed the same way the game closes it when you press B, and then
 * one of three things happens:
 *   1. An actor nearby wants the song (for example the gate statue, or a puzzle): it consumes the song.
 *   2. We are outside our scenes: a *real* Song of Soaring warp is started (the feather / wind capsule cutscene, played by
 *      the vanilla EnTest7 actor). EnTest7 picks the destination during the actor update and the game only reads it at the
 *      start of the next frame, so once it has chosen we swap the destination for the White Rose Sanctuary.
 *   3. We are inside our scenes: the vanilla "warp back to the entrance" path is used (the same one the game uses when you
 *      play the Song of Soaring inside a dungeon) with the respawn data replaced by the exact spot the player left from.
 *
 * Nothing is patched, so this coexists with other mods.
 *
 * Why there are almost no hooks: every game function a mod hooks has to be regenerated from the ROM when the mod is loaded, and
 * if one of them cannot be regenerated the whole mod fails to load ("code mod loading internal error", with no mod id). The only
 * game functions this mod hooks are Play_InitScene and Room_RequestNewRoom (scene_loader.c), the same two the Scene API mod
 * hooks. Everything else runs from events the game raises itself (recomp_on_play_init, recomp_after_play_update and the
 * autosave events), which cost nothing at load time. tools/inspect_nrm.py lists what a built mod asks the game to regenerate.
 */

#include "lil_actor.h"
#include "lil_song_tracker.h"

#define LIL_MAX_LISTENERS 12

typedef enum LilWarpKind {
    LIL_WARP_NONE,
    LIL_WARP_TO_SANCTUARY, // destination is overridden once EnTest7 has picked one (Lil_RedirectOwlWarp)
    LIL_WARP_HOME,         // vanilla OCARINA_MODE_WARP_TO_ENTRANCE, using the saved origin
    LIL_WARP_HOME_FALLBACK // origin unknown: vanilla Clock Town owl statue destination
} LilWarpKind;

typedef struct LilListener {
    Actor* actor;
    LilLullabyHandler handler;
} LilListener;

static LilSongTracker sLilTracker;

static LilListener sLilListeners[LIL_MAX_LISTENERS];

static u8 sLilWarpKind;
static RespawnData sLilOrigin;
static u16 sLilOriginSaveEntrance;
static u8 sLilOriginValid;

static u16 sLilSavedEntranceForAutosave;
static u8 sLilAutosaveAdjusted;

u8 gLilWarpBlocked;

/* ------------------------------------------------------------------------------------------------------------------
 * Listener registry
 * ---------------------------------------------------------------------------------------------------------------- */
void Lil_RegisterLullabyListener(Actor* actor, LilLullabyHandler handler) {
    s32 i;

    for (i = 0; i < LIL_MAX_LISTENERS; i++) {
        if (sLilListeners[i].actor == actor) {
            sLilListeners[i].handler = handler;
            return;
        }
    }
    for (i = 0; i < LIL_MAX_LISTENERS; i++) {
        if (sLilListeners[i].actor == NULL) {
            sLilListeners[i].actor = actor;
            sLilListeners[i].handler = handler;
            return;
        }
    }
}

void Lil_UnregisterLullabyListener(Actor* actor) {
    s32 i;

    for (i = 0; i < LIL_MAX_LISTENERS; i++) {
        if (sLilListeners[i].actor == actor) {
            sLilListeners[i].actor = NULL;
            sLilListeners[i].handler = NULL;
        }
    }
}

static void Lil_ClearListeners(void) {
    s32 i;

    for (i = 0; i < LIL_MAX_LISTENERS; i++) {
        sLilListeners[i].actor = NULL;
        sLilListeners[i].handler = NULL;
    }
}

/* ------------------------------------------------------------------------------------------------------------------
 * Note tracking (the logic lives in lil_song_tracker.h so it can be unit tested off-game)
 * ---------------------------------------------------------------------------------------------------------------- */
_Static_assert(OCARINA_BTN_A == LIL_NOTE_A && OCARINA_BTN_C_DOWN == LIL_NOTE_C_DOWN && OCARINA_BTN_C_RIGHT == LIL_NOTE_C_RIGHT &&
                   OCARINA_BTN_C_LEFT == LIL_NOTE_C_LEFT && OCARINA_BTN_C_UP == LIL_NOTE_C_UP,
               "song tracker button values must match the game's OcarinaButtonIndex");

/* ------------------------------------------------------------------------------------------------------------------
 * Closing the ocarina
 * ---------------------------------------------------------------------------------------------------------------- */
// Same sequence the vanilla message code runs when B is pressed while playing, with a different resulting ocarina mode.
static void Lil_CloseOcarina(PlayState* play, s32 ocarinaMode) {
    AudioOcarina_SetInstrument(OCARINA_INSTRUMENT_OFF);
    play->msgCtx.ocarinaMode = ocarinaMode;
    Message_CloseTextbox(play);
}

static s32 Lil_CanWarp(PlayState* play) {
    if (gLilWarpBlocked != 0) {
        return false;
    }
    if (play->interfaceCtx.restrictions.songOfSoaring != 0) {
        return false;
    }
    if ((play->transitionTrigger != TRANS_TRIGGER_OFF) || (play->transitionMode != TRANS_MODE_OFF)) {
        return false;
    }
    return true;
}

static void Lil_StartWarpToSanctuary(PlayState* play) {
    Player* player = GET_PLAYER(play);
    RespawnData savedTop = gSaveContext.respawn[RESPAWN_MODE_TOP];

    // Remember exactly where the player is standing so that the song can bring them back to the same spot. The game's own
    // helper fills in the respawn record (scene, room, position, yaw, temporary flags); it writes into the "top" slot, so
    // the slot's previous contents are put back straight away and the game's own data is left untouched.
    Play_SetRespawnData(play, RESPAWN_MODE_TOP, gSaveContext.save.entrance, play->roomCtx.curRoom.num,
                        PLAYER_PARAMS(0xFF, PLAYER_START_MODE_D), &player->actor.world.pos, player->actor.shape.rot.y);
    sLilOrigin = gSaveContext.respawn[RESPAWN_MODE_TOP];
    gSaveContext.respawn[RESPAWN_MODE_TOP] = savedTop;
    sLilOriginSaveEntrance = gSaveContext.save.entrance;
    sLilOriginValid = true;

    sLilWarpKind = LIL_WARP_TO_SANCTUARY;
    // Any of the owl warp modes works, the destination is swapped for ours in Lil_RedirectOwlWarp.
    Lil_CloseOcarina(play, OCARINA_MODE_WARP_TO_SOUTH_CLOCK_TOWN);
}

static void Lil_StartWarpHome(PlayState* play) {
    if (sLilOriginValid) {
        gSaveContext.respawn[RESPAWN_MODE_TOP] = sLilOrigin;
        sLilWarpKind = LIL_WARP_HOME;
        Lil_CloseOcarina(play, OCARINA_MODE_WARP_TO_ENTRANCE);
    } else {
        // We have no record of where the player came from (for example the game was restarted in between).
        sLilWarpKind = LIL_WARP_HOME_FALLBACK;
        Lil_CloseOcarina(play, OCARINA_MODE_WARP_TO_SOUTH_CLOCK_TOWN);
    }
}

// Returns the player to where they came from with a plain fade (used by the rose circles, which are not part of an
// ocarina session). Mirrors what the vanilla soaring warp does for "return to entrance".
void Lil_FadeHome(PlayState* play) {
    if (sLilOriginValid) {
        gSaveContext.respawn[RESPAWN_MODE_TOP] = sLilOrigin;
        func_80169F78(play);
        gSaveContext.respawn[RESPAWN_MODE_TOP].playerParams =
            PLAYER_PARAMS(gSaveContext.respawn[RESPAWN_MODE_TOP].playerParams, PLAYER_START_MODE_OWL);
        gSaveContext.respawnFlag = -6;
    } else {
        play->nextEntrance = ENTRANCE(SOUTH_CLOCK_TOWN, 0);
        play->transitionTrigger = TRANS_TRIGGER_START;
        play->transitionType = TRANS_TYPE_FADE_BLACK;
    }
}

static void Lil_OnMelodyPlayed(PlayState* play) {
    s32 consumed = false;
    s32 i;

    // The lullaby soothes hostile things. If anything awake is around, it is lulled to sleep instead of the song
    // taking you away: you cannot leave the Crypt with monsters on your heels (play it again once they sleep).
    if (LIL_IS_CUSTOM_SCENE(play->sceneId) && (Lil_SleepPulse(play, 950.0f, 10 * LIL_FRAMES_PER_SECOND) > 0)) {
        consumed = true;
    }

    for (i = 0; i < LIL_MAX_LISTENERS; i++) {
        LilListener* listener = &sLilListeners[i];

        if ((listener->actor != NULL) && (listener->handler != NULL)) {
            if (listener->handler(listener->actor, play)) {
                consumed = true;
            }
        }
    }

    if (consumed) {
        Audio_PlaySfx(NA_SE_SY_CORRECT_CHIME);
        Lil_CloseOcarina(play, OCARINA_MODE_END);
        return;
    }

    if (!Lil_CanWarp(play) || (sLilWarpKind != LIL_WARP_NONE)) {
        // Same feedback the game gives for a song that cannot be used here. The ocarina stays open.
        Audio_PlaySfx(NA_SE_SY_OCARINA_ERROR);
        return;
    }

    Audio_PlaySfx(NA_SE_SY_CORRECT_CHIME);
    if (LIL_IS_CUSTOM_SCENE(play->sceneId)) {
        Lil_StartWarpHome(play);
    } else {
        Lil_StartWarpToSanctuary(play);
    }
}

/* ------------------------------------------------------------------------------------------------------------------
 * Per-frame work (events raised by the game itself, nothing is hooked)
 * ---------------------------------------------------------------------------------------------------------------- */

// Watches the notes of a free-play ocarina session for our melody.
static void Lil_PollOcarina(PlayState* play) {
    MessageContext* msgCtx = &play->msgCtx;
    OcarinaStaff* staff;

    if ((msgCtx->msgMode != MSGMODE_OCARINA_PLAYING) || (msgCtx->ocarinaAction != OCARINA_ACTION_FREE_PLAY)) {
        LilSong_Reset(&sLilTracker);
        return;
    }

    staff = AudioOcarina_GetPlayingStaff();
    if (LilSong_Feed(&sLilTracker, staff->pos, staff->buttonIndex, staff->state)) {
        LilSong_Reset(&sLilTracker);
        Lil_OnMelodyPlayed(play);
    }
}

// The vanilla owl warp cutscene (EnTest7) picks the destination from a table by ocarina mode and starts the fade in a single
// call during the actor update (EnTest7_WarpCsWarp). Play_UpdateMain only reads the destination at the start of the next
// frame, so changing it here, right after Play_Update, is in time. Only the exact destination the vanilla code chose for the
// mode we asked for is replaced, so no other transition can be redirected by mistake.
static void Lil_RedirectOwlWarp(PlayState* play) {
    s32 isVanillaDestination;

    if ((sLilWarpKind != LIL_WARP_TO_SANCTUARY) || (play->transitionTrigger != TRANS_TRIGGER_START)) {
        return;
    }

    isVanillaDestination =
        (play->nextEntrance == ENTRANCE(SOUTH_CLOCK_TOWN, 9)) || // sOwlWarpEntrances[OWL_WARP_CLOCK_TOWN]
        ((play->sceneId == SCENE_SECOM) && (play->nextEntrance == ENTRANCE(IKANA_CANYON, 6))); // vanilla special case in the Secret Shrine

    if (isVanillaDestination) {
        play->nextEntrance = LIL_ENTRANCE_SANCTUARY(LIL_SPAWN_SANCTUARY_WARP);
    }
}

// Raised by the game right after Play_Update, once per frame.
RECOMP_CALLBACK("*", recomp_after_play_update) void Lil_AfterPlayUpdate(PlayState* play) {
    Lil_PollOcarina(play);
    Lil_RedirectOwlWarp(play);
}

// Raised by the game as the very first thing Play_Init does (a new scene is starting). Make sure our tables are in place before
// the game looks anything up.
RECOMP_CALLBACK("*", recomp_on_play_init) void Lil_OnPlayInit(PlayState* play) {
    Lil_RegisterTables();
    Lil_RegisterActors();
    Lil_ClearListeners();
    LilSong_Reset(&sLilTracker);
    sLilWarpKind = LIL_WARP_NONE;
    gLilWarpBlocked = 0;
}

/* ------------------------------------------------------------------------------------------------------------------
 * Autosave protection. If the game saved while inside one of our scenes the save would contain an entrance that only
 * exists while this mod is loaded. Swap in the place the player came from for the duration of the autosave.
 * ---------------------------------------------------------------------------------------------------------------- */
RECOMP_CALLBACK("*", recomp_on_autosave) void Lil_BeforeAutosave(PlayState* play) {
    sLilSavedEntranceForAutosave = gSaveContext.save.entrance;
    sLilAutosaveAdjusted = false;

    if (LIL_IS_CUSTOM_SCENE(play->sceneId)) {
        // Switch / chest / collectible flags live in the actor context until a scene is left: flush them so the save
        // contains the progress made so far in the Crypt.
        Play_SaveCycleSceneFlags(play);
        gSaveContext.save.entrance = sLilOriginValid ? sLilOriginSaveEntrance : ENTRANCE(SOUTH_CLOCK_TOWN, 0);
        sLilAutosaveAdjusted = true;
    }
}

RECOMP_CALLBACK("*", recomp_after_autosave) void Lil_AfterAutosave(PlayState* play) {
    if (sLilAutosaveAdjusted) {
        gSaveContext.save.entrance = sLilSavedEntranceForAutosave;
        sLilAutosaveAdjusted = false;
    }
}
