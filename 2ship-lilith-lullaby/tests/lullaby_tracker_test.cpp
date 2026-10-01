// Host-side unit test for mm/2s2h/Enhancements/Songs/LilithsLullabyTracker.h (not part of the repo, it has no unit test setup).
//   g++ -std=c++20 -Wall -Wextra -I mm/2s2h/Enhancements/Songs -o /tmp/lullaby_test /tmp/lullaby_test.cpp && /tmp/lullaby_test
//
// Staff behaviour (AudioOcarina_CheckSongsWithoutMusicStaff in mm/src/audio/code_8019AF00.c): `pos` is 0 right after the ocarina
// opens, becomes 1 on the first note, increments per note and wraps from 8 back to 1.
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>
#include "LilithsLullabyTracker.h"

using namespace LilithsLullaby;

static int sFailures = 0;
#define CHECK(cond, msg)                                           \
    do {                                                           \
        if (!(cond)) {                                             \
            std::printf("FAIL: %s (line %d)\n", msg, __LINE__);    \
            sFailures++;                                           \
        }                                                          \
    } while (0)

// Plays notes one per game frame, with idle frames (staff unchanged) in between like a real player. Returns the 1-based index of the
// note at which the melody was recognised, or 0. `startPos` is the staff position before the first note.
static int Play(Tracker& t, const std::vector<uint8_t>& notes, int startPos = 0) {
    int pos = startPos, hit = 0;
    for (size_t i = 0; i < notes.size(); i++) {
        pos = (pos % 8) + 1;
        if (t.Feed(pos, notes[i], 0xFE) && !hit) {
            hit = static_cast<int>(i) + 1;
        }
        for (int idle = 0; idle < 2; idle++) {
            t.Feed(pos, notes[i], 0xFE);
        }
    }
    return hit;
}

static std::vector<uint8_t> Melody() { return std::vector<uint8_t>(MELODY, MELODY + MELODY_LENGTH); }

static uint8_t Btn(char c) {
    switch (c) { case 'A': return NOTE_A; case 'D': return NOTE_C_DOWN; case 'R': return NOTE_C_RIGHT; case 'L': return NOTE_C_LEFT; default: return NOTE_C_UP; }
}

// Parsed from gOcarinaSongButtons in this repo (mm/src/audio/code_8019AF00.c). A=A D=C-Down R=C-Right L=C-Left U=C-Up
struct Vanilla { const char* name; const char* pattern; };
static const Vanilla sVanilla[] = {
    { "OCARINA_SONG_SONATA", "ULULARA" },
    { "OCARINA_SONG_GORON_LULLABY", "ARLARLRA" },
    { "OCARINA_SONG_NEW_WAVE", "LULRDLR" },
    { "OCARINA_SONG_ELEGY", "RLRDRUL" },
    { "OCARINA_SONG_OATH", "RDADRU" },
    { "OCARINA_SONG_SARIAS", "DRLDRL" },
    { "OCARINA_SONG_TIME", "RADRAD" },
    { "OCARINA_SONG_HEALING", "LRDLRD" },
    { "OCARINA_SONG_EPONAS", "ULRULR" },
    { "OCARINA_SONG_SOARING", "DLUDLU" },
    { "OCARINA_SONG_STORMS", "ADUADU" },
    { "OCARINA_SONG_SUNS", "RDURDU" },
    { "OCARINA_SONG_INVERTED_TIME", "DARDAR" },
    { "OCARINA_SONG_DOUBLE_TIME", "RRAADD" },
    { "OCARINA_SONG_GORON_LULLABY_INTRO", "ARLARL" },
    { "OCARINA_SONG_WIND_FISH_HUMAN", "URLR" },
    { "OCARINA_SONG_WIND_FISH_GORON", "AAADAAAR" },
    { "OCARINA_SONG_WIND_FISH_ZORA", "URDAULRD" },
    { "OCARINA_SONG_WIND_FISH_DEKU", "RADLR" },
    { "OCARINA_SONG_EVAN_PART1", "RRDAADRA" },
    { "OCARINA_SONG_EVAN_PART2", "LLRDDRLD" },
    { "OCARINA_SONG_ZELDAS_LULLABY", "LURLUR" },
    { "OCARINA_SONG_SCARECROW_SPAWN", "AAAAAAAA" },
    { "OCARINA_SONG_TERMINA_WALL", "ADRLULRD" }
};

int main() {
    Tracker t;
    const int n = static_cast<int>(MELODY_LENGTH);

    // 1. the melody from a freshly opened ocarina is recognised on its last note
    t.Reset();
    CHECK(Play(t, Melody()) == n, "clean play is recognised on the last note");

    // 2. ...from every staff start position (the 8 note window may wrap part way through)
    for (int start = 0; start < 8; start++) {
        t.Reset();
        CHECK(Play(t, Melody(), start) == n, "recognised from every staff start position");
    }

    // 3. unrelated notes first, then the melody: recognised when it completes (rolling history)
    for (int start = 0; start < 8; start++) {
        std::vector<uint8_t> seq = { NOTE_A, NOTE_C_DOWN, NOTE_A, NOTE_C_UP, NOTE_C_RIGHT };
        for (uint8_t b : MELODY) seq.push_back(b);
        t.Reset();
        CHECK(Play(t, seq, start) == static_cast<int>(seq.size()), "melody after unrelated notes is recognised");
    }

    // 4. one wrong note inside the melody: not recognised
    { auto seq = Melody(); seq[3] = NOTE_A; t.Reset(); CHECK(Play(t, seq) == 0, "a wrong note breaks the melody"); }

    // 5. a truncated melody is not recognised
    { auto seq = Melody(); seq.pop_back(); t.Reset(); CHECK(Play(t, seq) == 0, "six notes are not enough"); }

    // 6. after a recognition the game side resets the tracker, and a second play is recognised again
    t.Reset();
    CHECK(Play(t, Melody()) == n, "first play");
    t.Reset();
    CHECK(Play(t, Melody()) == n, "second play after a reset");

    // 7. when the game recognises one of its own songs part way through, the history is discarded
    t.Reset();
    {
        int pos = 0;
        for (int i = 0; i < 4; i++) { pos = (pos % 8) + 1; t.Feed(pos, MELODY[i], 0xFE); }
        t.Feed(pos, MELODY[3], 0x06 /* a vanilla song index */);
        for (int i = 4; i < n; i++) { pos = (pos % 8) + 1; CHECK(!t.Feed(pos, MELODY[i], 0xFE), "the remaining notes alone must not match"); }
    }

    // 8. a note that went by unseen (staff position skipped ahead) invalidates the history.
    //    Played: U L R L (x) U L D, where x was an extra note never sampled. Seen without the gap logic it would look like the melody.
    t.Reset();
    {
        const uint8_t seen[] = { NOTE_C_UP, NOTE_C_LEFT, NOTE_C_RIGHT, NOTE_C_LEFT, NOTE_C_UP, NOTE_C_LEFT, NOTE_C_DOWN };
        const int pos[] = { 1, 2, 3, 4, 6, 7, 8 }; // position 5 never seen
        bool hit = false;
        for (int i = 0; i < n; i++) { hit |= t.Feed(pos[i], seen[i], 0xFE); }
        CHECK(!hit, "a skipped staff position breaks the melody");
    }
    //    ...and the same notes at consecutive positions do match (control for the test above)
    t.Reset();
    { const int pos[] = { 1, 2, 3, 4, 5, 6, 7 }; bool hit = false; for (int i = 0; i < n; i++) { hit |= t.Feed(pos[i], MELODY[i], 0xFE); } CHECK(hit, "control: consecutive positions match"); }

    // 9. opening the ocarina again (pos back to 0) clears everything: half a melody, a reset, the other half must not match
    t.Reset();
    {
        int pos = 0;
        for (int i = 0; i < 4; i++) { pos = (pos % 8) + 1; t.Feed(pos, MELODY[i], 0xFE); }
        t.Feed(0, 0, 0xFE);
        pos = 0;
        for (int i = 4; i < n; i++) { pos = (pos % 8) + 1; CHECK(!t.Feed(pos, MELODY[i], 0xFE), "second half after a pos 0 reset must not match"); }
        t.Feed(0, 0, 0xFE);
        CHECK(Play(t, Melody()) == n, "a full melody after a pos 0 reset is recognised");
    }

    // 9b. when the ocarina is reopened the staff still reports the LAST button of the previous session (buttonIndex is never cleared).
    //     That stale button must not count as a note: stale C-Up + only six real notes (L R L U L D) must not be taken for the melody.
    t.Reset();
    {
        t.Feed(1, NOTE_A, 0xFE); // previous session: two unrelated notes, so the tracker is holding state (lastPos != 0)
        t.Feed(2, NOTE_C_DOWN, 0xFE);
        t.Feed(0, NOTE_C_UP, 0xFE); // reopened: pos is 0 and the staff reports the stale last button
        int pos = 0; bool hit = false;
        for (int i = 1; i < n; i++) { pos = (pos % 8) + 1; hit |= t.Feed(pos, MELODY[i], 0xFE); }
        CHECK(!hit, "a stale button from the previous session must not count as the first note");
    }

    // 10. invalid button values (garbage, or the game's C-Right-or-C-Left marker 5) are never recorded and break a melody in progress
    for (uint8_t bad : { uint8_t(0x3F), uint8_t(5), uint8_t(0xFF) }) {
        t.Reset();
        CHECK(!t.Feed(1, bad, 0xFE), "an invalid button never matches");
        // the melody right after the garbage note (positions 2..8) is still recognised: garbage did not poison the tracker
        int pos = 1; bool hit = false;
        for (int i = 0; i < n; i++) { pos = (pos % 8) + 1; hit |= t.Feed(pos, MELODY[i], 0xFE); }
        CHECK(hit, "melody after a garbage note is recognised");
        // garbage in the middle breaks the melody
        t.Reset(); pos = 0; hit = false;
        for (int i = 0; i < n; i++) { pos = (pos % 8) + 1; hit |= t.Feed(pos, i == 3 ? bad : MELODY[i], 0xFE); }
        CHECK(!hit, "garbage in the middle breaks the melody");
    }

    // 11. no vanilla song triggers the melody; the melody contains no vanilla song and no vanilla song contains the melody.
    for (const Vanilla& v : sVanilla) {
        std::vector<uint8_t> seq;
        for (const char* c = v.pattern; *c; c++) { seq.push_back(Btn(*c)); }
        t.Reset();
        CHECK(Play(t, seq) == 0, v.name);
    }
    {
        std::string melody;
        for (uint8_t b : MELODY) { melody += "ADRLU"[b]; }
        for (const Vanilla& v : sVanilla) {
            CHECK(melody.find(v.pattern) == std::string::npos, "the melody must not contain a vanilla song");
            CHECK(std::string(v.pattern).find(melody) == std::string::npos, "no vanilla song may contain the melody");
        }
        std::printf("melody under test: %s   (%zu vanilla songs checked, parsed from this repo)\n", melody.c_str(), sizeof(sVanilla) / sizeof(sVanilla[0]));
        CHECK(melody == "ULRLULD", "the melody must be C-Up, C-Left, C-Right, C-Left, C-Up, C-Left, C-Down");
    }

    if (sFailures == 0) { std::printf("lullaby_test: all checks passed\n"); return 0; }
    std::printf("lullaby_test: %d FAILED\n", sFailures);
    return 1;
}
