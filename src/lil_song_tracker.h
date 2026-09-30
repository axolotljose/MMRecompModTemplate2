#ifndef LIL_SONG_TRACKER_H
#define LIL_SONG_TRACKER_H

/**
 * Recognises Lilith's Lullaby from the stream of notes the player plays.
 *
 * This header deliberately depends on nothing but plain C so the exact same code is unit tested on the host
 * (tools/tests/test_song.c). The game side (lullaby.c) feeds it the ocarina staff each frame.
 *
 * Buttons use the game's OcarinaButtonIndex values: A = 0, C-Down = 1, C-Right = 2, C-Left = 3, C-Up = 4.
 */

#define LIL_LULLABY_LENGTH 7
#define LIL_NOTE_A 0
#define LIL_NOTE_C_DOWN 1
#define LIL_NOTE_C_RIGHT 2
#define LIL_NOTE_C_LEFT 3
#define LIL_NOTE_C_UP 4

// The melody: C-Up, C-Left, C-Right, C-Left, C-Up, C-Left, C-Down.
static const unsigned char sLilLullabyNotes[LIL_LULLABY_LENGTH] = {
    LIL_NOTE_C_UP, LIL_NOTE_C_LEFT, LIL_NOTE_C_RIGHT, LIL_NOTE_C_LEFT, LIL_NOTE_C_UP, LIL_NOTE_C_LEFT, LIL_NOTE_C_DOWN,
};

typedef struct LilSongTracker {
    unsigned char history[LIL_LULLABY_LENGTH];
    unsigned char count;
    unsigned char lastPos;
} LilSongTracker;

static inline void LilSong_Reset(LilSongTracker* t) {
    t->count = 0;
    t->lastPos = 0;
}

static inline int LilSong_Matches(const LilSongTracker* t) {
    int i;

    if (t->count < LIL_LULLABY_LENGTH) {
        return 0;
    }
    for (i = 0; i < LIL_LULLABY_LENGTH; i++) {
        if (t->history[i] != sLilLullabyNotes[i]) {
            return 0;
        }
    }
    return 1;
}

static inline void LilSong_Push(LilSongTracker* t, unsigned char button) {
    int i;

    if (t->count < LIL_LULLABY_LENGTH) {
        t->history[t->count++] = button;
    } else {
        for (i = 0; i < LIL_LULLABY_LENGTH - 1; i++) {
            t->history[i] = t->history[i + 1];
        }
        t->history[LIL_LULLABY_LENGTH - 1] = button;
    }
}

/**
 * Feeds one staff update. Returns 1 when the last LIL_LULLABY_LENGTH notes are the melody.
 *   pos         number of notes played in the current 8 note window (wraps 8 -> 1), 0 when the ocarina was just opened
 *   button      last button played
 *   vanillaState 0xFE while the game has not recognised one of its own songs, < 0xFE when it has
 */
static inline int LilSong_Feed(LilSongTracker* t, unsigned char pos, unsigned char button, unsigned char vanillaState) {
    unsigned char expectedPos;

    if (vanillaState < 0xFE) {
        LilSong_Reset(t); // the game recognised one of its own songs, never treat that as ours
        return 0;
    }
    if (pos == 0) {
        LilSong_Reset(t);
        return 0;
    }
    if (pos == t->lastPos) {
        return 0;
    }
    if (t->lastPos != 0) {
        expectedPos = (unsigned char)((t->lastPos % 8) + 1);
        if (pos != expectedPos) {
            t->count = 0; // notes went by unseen, the history can no longer be trusted
        }
    }
    t->lastPos = pos;
    if (button > LIL_NOTE_C_UP) {
        t->count = 0;
        return 0;
    }
    LilSong_Push(t, button);
    return LilSong_Matches(t);
}

#endif /* LIL_SONG_TRACKER_H */
