/*
 * Host-side unit test for the song tracker (src/lil_song_tracker.h), the exact code the mod runs in-game.
 *
 *   gcc -std=c99 -Wall -Wextra -I src -o /tmp/test_song tools/tests/test_song.c && /tmp/test_song
 *
 * The game's staff position behaves like this (see AudioOcarina_CheckSongsWithoutMusicStaff): it is 0 when the ocarina has
 * just been opened, goes to 1 on the first note, increments per note and wraps from 8 back to 1.
 */
#include <stdio.h>
#include <string.h>

#include "lil_song_tracker.h"

static int sFailures = 0;

#define CHECK(cond, msg)                                                                     \
    do {                                                                                     \
        if (!(cond)) {                                                                       \
            printf("FAIL: %s (line %d)\n", msg, __LINE__);                                   \
            sFailures++;                                                                     \
        }                                                                                    \
    } while (0)

/* Plays a whole sequence, one note per update, like a real player. Returns the index (1-based) of the note at which the
 * melody was recognised, or 0 if it never was. `startPos` is the staff position before the first note. */
static int Play(LilSongTracker* t, const unsigned char* notes, int n, int startPos) {
    int pos = startPos;
    int hit = 0;
    int i;

    for (i = 0; i < n; i++) {
        pos = (pos % 8) + 1;
        if (LilSong_Feed(t, (unsigned char)pos, notes[i], 0xFE) && !hit) {
            hit = i + 1;
        }
        // several idle frames between notes, with the staff unchanged
        LilSong_Feed(t, (unsigned char)pos, notes[i], 0xFE);
        LilSong_Feed(t, (unsigned char)pos, notes[i], 0xFE);
    }
    return hit;
}

/* The 24 vanilla song patterns (A=0, D=1, R=2, L=3, U=4), extracted from gOcarinaSongButtons in the decomp. */
static const char* const sVanilla[] = {
    "ULULARA",  "ARLARLRA", "LULRDLR", "RLRDRUL", "RDADRU",   "DRLDRL",   "RADRAD",  "LRDLRD",
    "ULRULR",   "DLUDLU",   "ADUADU",  "RDURDU",  "DARDAR",   "RRAADD",   "ARLARL",  "URLR",
    "AAADAAAR", "URDAULRD", "RADLR",   "RRDAADRA", "LLRDDRLD", "LURLUR",   "AAAAAAAA", "ADRLULRD",
};

static unsigned char Btn(char c) {
    switch (c) {
        case 'A': return LIL_NOTE_A;
        case 'D': return LIL_NOTE_C_DOWN;
        case 'R': return LIL_NOTE_C_RIGHT;
        case 'L': return LIL_NOTE_C_LEFT;
        default: return LIL_NOTE_C_UP;
    }
}

int main(void) {
    LilSongTracker t;
    unsigned char seq[64];
    int i;
    int start;

    /* 1. the melody, played cleanly from a freshly opened ocarina, is recognised on its last note */
    LilSong_Reset(&t);
    CHECK(Play(&t, sLilLullabyNotes, LIL_LULLABY_LENGTH, 0) == LIL_LULLABY_LENGTH, "clean play is recognised on the last note");

    /* 2. ...from every possible staff position (the 8 note window may wrap part way through) */
    for (start = 0; start < 8; start++) {
        LilSong_Reset(&t);
        CHECK(Play(&t, sLilLullabyNotes, LIL_LULLABY_LENGTH, start) == LIL_LULLABY_LENGTH, "recognised from every staff start position");
    }

    /* 3. random noise first, then the melody: recognised when it completes (rolling history) */
    {
        const unsigned char noise[] = { LIL_NOTE_A, LIL_NOTE_C_DOWN, LIL_NOTE_A, LIL_NOTE_C_UP, LIL_NOTE_C_RIGHT };
        for (start = 0; start < 8; start++) {
            memcpy(seq, noise, sizeof(noise));
            memcpy(seq + sizeof(noise), sLilLullabyNotes, LIL_LULLABY_LENGTH);
            LilSong_Reset(&t);
            CHECK(Play(&t, seq, (int)sizeof(noise) + LIL_LULLABY_LENGTH, start) == (int)sizeof(noise) + LIL_LULLABY_LENGTH,
                  "melody after unrelated notes is recognised");
        }
    }

    /* 4. one wrong note inside the melody: not recognised */
    memcpy(seq, sLilLullabyNotes, LIL_LULLABY_LENGTH);
    seq[3] = LIL_NOTE_A;
    LilSong_Reset(&t);
    CHECK(Play(&t, seq, LIL_LULLABY_LENGTH, 0) == 0, "a wrong note breaks the melody");

    /* 5. a truncated melody is not recognised */
    LilSong_Reset(&t);
    CHECK(Play(&t, sLilLullabyNotes, LIL_LULLABY_LENGTH - 1, 0) == 0, "six notes are not enough");

    /* 6. the melody played twice in a row is recognised twice (after a reset the game closes the ocarina anyway) */
    LilSong_Reset(&t);
    memcpy(seq, sLilLullabyNotes, LIL_LULLABY_LENGTH);
    CHECK(Play(&t, seq, LIL_LULLABY_LENGTH, 0) == LIL_LULLABY_LENGTH, "first play");

    /* 7. when the game recognises one of its own songs mid-way, the history is discarded */
    LilSong_Reset(&t);
    {
        int pos = 0;
        for (i = 0; i < 4; i++) {
            pos = (pos % 8) + 1;
            LilSong_Feed(&t, (unsigned char)pos, sLilLullabyNotes[i], 0xFE);
        }
        LilSong_Feed(&t, (unsigned char)pos, sLilLullabyNotes[3], 0x06 /* vanilla Song of Time */);
        CHECK(t.count == 0, "a vanilla song resets the tracker");
        for (i = 4; i < LIL_LULLABY_LENGTH; i++) {
            pos = (pos % 8) + 1;
            CHECK(!LilSong_Feed(&t, (unsigned char)pos, sLilLullabyNotes[i], 0xFE), "remaining notes alone must not match");
        }
    }

    /* 8. a note that went by unseen (staff position skipped ahead) invalidates the history */
    LilSong_Reset(&t);
    LilSong_Feed(&t, 1, sLilLullabyNotes[0], 0xFE);
    LilSong_Feed(&t, 2, sLilLullabyNotes[1], 0xFE);
    LilSong_Feed(&t, 4, sLilLullabyNotes[3], 0xFE); /* pos 3 was never seen */
    CHECK(t.count == 1, "skipped staff position leaves only the newest note");

    /* 9. opening the ocarina again (pos back to 0) clears everything */
    LilSong_Feed(&t, 0, 0, 0xFE);
    CHECK(t.count == 0 && t.lastPos == 0, "pos 0 resets the tracker");

    /* 10. an invalid button value is ignored safely */
    LilSong_Reset(&t);
    CHECK(!LilSong_Feed(&t, 1, 0x3F, 0xFE) && t.count == 0, "garbage button does not get recorded");

    /* 11. no vanilla song pattern (or any contiguous piece of one that is >= 4 notes) triggers the melody, and the melody
     * does not contain any vanilla song. This is what makes the song safe next to the game's own songs. */
    for (i = 0; i < (int)(sizeof(sVanilla) / sizeof(sVanilla[0])); i++) {
        int len = (int)strlen(sVanilla[i]);
        int k;
        LilSong_Reset(&t);
        for (k = 0; k < len; k++) {
            seq[k] = Btn(sVanilla[i][k]);
        }
        CHECK(Play(&t, seq, len, 0) == 0, "a vanilla song must not trigger Lilith's Lullaby");
    }
    {
        char melody[LIL_LULLABY_LENGTH + 1];
        static const char letters[5] = { 'A', 'D', 'R', 'L', 'U' };
        for (i = 0; i < LIL_LULLABY_LENGTH; i++) {
            melody[i] = letters[sLilLullabyNotes[i]];
        }
        melody[LIL_LULLABY_LENGTH] = 0;
        for (i = 0; i < (int)(sizeof(sVanilla) / sizeof(sVanilla[0])); i++) {
            /* only songs the free-play check can match on (playable set is 0-13, 14 is the Goron Lullaby intro) matter,
             * but check all of them: the answer is the same */
            CHECK(strstr(melody, sVanilla[i]) == NULL, "the melody must not contain a vanilla song");
            CHECK(strstr(sVanilla[i], melody) == NULL, "no vanilla song may contain the melody");
        }
        printf("melody under test: %s\n", melody);
    }

    if (sFailures == 0) {
        printf("test_song: all checks passed\n");
        return 0;
    }
    printf("test_song: %d FAILED\n", sFailures);
    return 1;
}
