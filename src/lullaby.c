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
 *      the vanilla EnTest7 actor). When that cutscene is about to load the destination we swap the destination for the
 *      White Rose Sanctuary.
 *   3. We are inside our scenes: the vanilla "warp back to the entrance" path is used (the same one the game uses when you
 *      play the Song of Soaring inside a dungeon) with the respawn data replaced by the exact spot the player left from.
 *
 * Nothing is patched (only hooked), so this coexists with other mods.
 */

#include "lil_actor.h"

#define LIL_MAX_LISTENERS 12

typedef enum LilWarpKind {
    LIL_WARP_NONE,
    LIL_WARP_TO_SANCTUARY, // destination is overridden in EnTest7_WarpCsWarp
    LIL_WARP_HOME,         // vanilla OCARINA_MODE_WARP_TO_ENTRANCE, using the saved origin
    LIL_WARP_HOME_FALLBACK // origin unknown: vanilla Clock Town owl statue destination
} LilWarpKind;

typedef struct LilListener {
    Actor* actor;
    LilLullabyHandler handler;
} LilListener;

/* Notes of the melody. */
static const u8 sLilLullabyNotes[LIL_LULLABY_LENGTH] = {
    OCARINA_BTN_C_UP, OCARINA_BTN_C_LEFT, OCARINA_BTN_C_RIGHT, OCARINA_BTN_C_LEFT,
    OCARINA_BTN_C_UP, OCARINA_BTN_C_LEFT, OCARINA_BTN_C_DOWN,
};

static u8 sLilHistory[LIL_LULLABY_LENGTH];
static u8 sLilHistoryCount;
static u8 sLilLastStaffPos;

static LilListener sLilListeners[LIL_MAX_LISTENERS];

static u8 sLilWarpKind;
static RespawnData sLilOrigin;
static u16 sLilOriginSaveEntrance;
static u8 sLilOriginValid;

static u16 sLilSavedEntranceForAutosave;
static u8 sLilAutosaveAdjusted;

static PlayState* sLilPlayForWarpHook;

u32 gLilLullabyFrame;
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

s32 Lil_LullabyPlayedRecently(PlayState* play, u32 frames) {
    return (gLilLullabyFrame != 0) && ((play->gameplayFrames - gLilLullabyFrame) <= frames);
}

/* ------------------------------------------------------------------------------------------------------------------
 * Note tracking
 * ---------------------------------------------------------------------------------------------------------------- */
static void Lil_ResetTracker(void) {
    sLilHistoryCount = 0;
    sLilLastStaffPos = 0;
}

static void Lil_PushNote(u8 button) {
    s32 i;

    if (sLilHistoryCount < LIL_LULLABY_LENGTH) {
        sLilHistory[sLilHistoryCount++] = button;
    } else {
        for (i = 0; i < LIL_LULLABY_LENGTH - 1; i++) {
            sLilHistory[i] = sLilHistory[i + 1];
        }
        sLilHistory[LIL_LULLABY_LENGTH - 1] = button;
    }
}

static s32 Lil_HistoryMatchesMelody(void) {
    s32 i;

    if (sLilHistoryCount < LIL_LULLABY_LENGTH) {
        return false;
    }
    for (i = 0; i < LIL_LULLABY_LENGTH; i++) {
        if (sLilHistory[i] != sLilLullabyNotes[i]) {
            return false;
        }
    }
    return true;
}

/**
 * Feeds one staff update into the tracker. Returns true when the last LIL_LULLABY_LENGTH notes are the melody.
 * `pos` is the number of notes played in the current 8 note window (it wraps from 8 to 1, and is 0 when the ocarina was
 * just opened), `buttonIndex` is the last button played, `state` is 0xFE while no vanilla song has been recognised.
 */
static s32 Lil_FeedStaff(u8 pos, u8 buttonIndex, u8 state) {
    u8 expectedPos;

    if (state < 0xFE) {
        // The game recognised one of its own songs, never treat that as ours.
        Lil_ResetTracker();
        return false;
    }

    if (pos == 0) {
        Lil_ResetTracker();
        return false;
    }

    if (pos == sLilLastStaffPos) {
        return false;
    }

    if (sLilLastStaffPos != 0) {
        expectedPos = (sLilLastStaffPos % 8) + 1;
        if (pos != expectedPos) {
            // One or more notes went by unseen, the history is no longer trustworthy.
            sLilHistoryCount = 0;
        }
    }

    sLilLastStaffPos = pos;
    if (buttonIndex > OCARINA_BTN_C_UP) {
        sLilHistoryCount = 0;
        return false;
    }
    Lil_PushNote(buttonIndex);
    return Lil_HistoryMatchesMelody();
}

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

    // Remember exactly where the player is standing so that the song can bring them back to the same spot.
    Play_SetRespawnData(play, RESPAWN_MODE_TOP, gSaveContext.save.entrance, play->roomCtx.curRoom.num,
                        PLAYER_PARAMS(0xFF, PLAYER_START_MODE_D), &player->actor.world.pos, player->actor.shape.rot.y);
    sLilOrigin = gSaveContext.respawn[RESPAWN_MODE_TOP];
    sLilOriginSaveEntrance = gSaveContext.save.entrance;
    sLilOriginValid = true;

    sLilWarpKind = LIL_WARP_TO_SANCTUARY;
    // Any of the owl warp modes works, the destination is swapped for ours in EnTest7_WarpCsWarp.
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

void Lil_RequestWarpHome(PlayState* play) {
    if (Lil_CanWarp(play) && (sLilWarpKind == LIL_WARP_NONE)) {
        Lil_StartWarpHome(play);
    }
}

static void Lil_OnMelodyPlayed(PlayState* play) {
    s32 consumed = false;
    s32 i;

    gLilLullabyFrame = (play->gameplayFrames != 0) ? play->gameplayFrames : 1;

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
 * Hooks
 * ---------------------------------------------------------------------------------------------------------------- */
RECOMP_HOOK("Message_Update") void Lil_OnMessageUpdate(PlayState* play) {
    MessageContext* msgCtx = &play->msgCtx;
    OcarinaStaff* staff;

    if ((msgCtx->msgMode != MSGMODE_OCARINA_PLAYING) || (msgCtx->ocarinaAction != OCARINA_ACTION_FREE_PLAY)) {
        Lil_ResetTracker();
        return;
    }

    staff = AudioOcarina_GetPlayingStaff();
    if (Lil_FeedStaff(staff->pos, staff->buttonIndex, staff->state)) {
        Lil_ResetTracker();
        Lil_OnMelodyPlayed(play);
    }
}

RECOMP_HOOK("EnTest7_WarpCsWarp") void Lil_OnWarpCsWarp(Actor* thisx, PlayState* play) {
    sLilPlayForWarpHook = play;
}

// Runs after the vanilla code has picked the owl warp destination and started the transition.
RECOMP_HOOK_RETURN("EnTest7_WarpCsWarp") void Lil_AfterWarpCsWarp(void) {
    if ((sLilWarpKind == LIL_WARP_TO_SANCTUARY) && (sLilPlayForWarpHook != NULL)) {
        sLilPlayForWarpHook->nextEntrance = LIL_ENTRANCE_SANCTUARY(LIL_SPAWN_SANCTUARY_WARP);
    }
}

// A new scene (Play state) is starting. Make sure our tables are in place before the game looks anything up.
RECOMP_HOOK("Play_Init") void Lil_OnPlayInit(GameState* thisx) {
    Lil_RegisterTables();
    Lil_RegisterActors();
    Lil_ClearListeners();
    Lil_ResetTracker();
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
