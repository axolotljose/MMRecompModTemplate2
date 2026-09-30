/**
 * Loads the mod's own scenes.
 *
 * The game normally DMAs a scene file from the ROM into memory and every scene command refers to it through segment
 * addresses. Our scenes live in this mod's data instead, so:
 *   - each of our scenes owns an unused slot in gSceneTable / sSceneEntranceTable, filled in by Lil_RegisterTables();
 *   - the scene table entry points at a small real ROM file so that the game's DMA request for it stays valid, and we then
 *     replace the loaded scene segment with our own data in Play_InitScene;
 *   - room requests are answered with our room data instead of a DMA transfer.
 *
 * (The technique is the same one used by the Scene API mod by Keanine, CC0, which shares the same decomp commit. The
 * difference is that every scene here has a slot of its own, so no state is needed to know which scene is loading.)
 */

#include "lilith.h"

#define LIL_MAX_SPAWNS 4
#define LIL_ENTRANCE_LAYERS 16 // Entrance_GetTableEntry indexes by the scene layer too, so provide every layer.

// Private decomp tables. The declarations live in this mod because the decomp keeps them file-local.
extern SceneEntranceTableEntry sSceneEntranceTable[];

typedef struct LilPersistentCycleSceneFlags {
    /* 0x0 */ u32 switch0;
    /* 0x4 */ u32 switch1;
    /* 0x8 */ u32 chest;
    /* 0xC */ u32 collectible;
} LilPersistentCycleSceneFlags; // same layout as the decomp's PersistentCycleSceneFlags

extern LilPersistentCycleSceneFlags sPersistentCycleSceneFlags[SCENE_MAX];

// A small, real scene file. The scene table entry has to describe a valid DMA range even though we replace the data.
extern u8 _Z2_INSIDETOWERSegmentRomStart[1];
extern u8 _Z2_INSIDETOWERSegmentRomEnd[1];

static EntranceTableEntry sLilEntranceEntries[2][LIL_MAX_SPAWNS][LIL_ENTRANCE_LAYERS];
static EntranceTableEntry* sLilEntranceTables[2][LIL_MAX_SPAWNS];

const LilSceneDef* Lil_FindSceneDef(s32 sceneId) {
    s32 i;

    for (i = 0; i < gLilNumSceneDefs; i++) {
        if (gLilSceneDefs[i].sceneId == sceneId) {
            return &gLilSceneDefs[i];
        }
    }
    return NULL;
}

/**
 * Fills in every table entry that belongs to our scenes. Safe (and cheap) to call repeatedly, it is called whenever a
 * new Play state starts so the tables are in place before the game looks anything up, regardless of when the game's own
 * static data was initialised.
 */
void Lil_RegisterTables(void) {
    s32 i;
    s32 spawn;
    s32 layer;

    for (i = 0; i < gLilNumSceneDefs; i++) {
        const LilSceneDef* def = &gLilSceneDefs[i];
        SceneTableEntry* sceneEntry = &gSceneTable[def->sceneId];
        SceneEntranceTableEntry* entranceEntry = &sSceneEntranceTable[def->entranceSceneId];
        LilPersistentCycleSceneFlags* persistent = &sPersistentCycleSceneFlags[def->sceneId];

        sceneEntry->segment.vromStart = (uintptr_t)_Z2_INSIDETOWERSegmentRomStart;
        sceneEntry->segment.vromEnd = (uintptr_t)_Z2_INSIDETOWERSegmentRomEnd;
        sceneEntry->titleTextId = 0;
        sceneEntry->unk_A = 0;
        sceneEntry->drawConfig = SCENE_DRAW_CFG_DEFAULT;
        sceneEntry->unk_C = 0;
        sceneEntry->unk_D = 0;

        for (spawn = 0; spawn < LIL_MAX_SPAWNS; spawn++) {
            for (layer = 0; layer < LIL_ENTRANCE_LAYERS; layer++) {
                EntranceTableEntry* e = &sLilEntranceEntries[i][spawn][layer];

                e->sceneId = def->sceneId;
                e->spawnNum = (spawn < def->numSpawns) ? spawn : 0;
                e->flags = LIL_ENTRANCE_FLAGS(TRANS_TYPE_FADE_BLACK, TRANS_TYPE_FADE_BLACK);
            }
            sLilEntranceTables[i][spawn] = sLilEntranceEntries[i][spawn];
        }

        entranceEntry->tableCount = LIL_MAX_SPAWNS;
        entranceEntry->table = sLilEntranceTables[i];
        entranceEntry->name = (char*)def->name;

        // Progress made in the scenes (chests, switches, collectibles) survives the three day reset, like a real dungeon.
        persistent->switch0 = 0xFFFFFFFF;
        persistent->switch1 = 0xFFFFFFFF;
        persistent->chest = 0xFFFFFFFF;
        persistent->collectible = 0xFFFFFFFF;
    }
}

/* ------------------------------------------------------------------------------------------------------------------
 * Hooks
 * ---------------------------------------------------------------------------------------------------------------- */

// The scene is about to have its commands executed: replace what the game DMA'd with our scene header.
RECOMP_HOOK("Play_InitScene") void Lil_OnPlayInitScene(PlayState* play, s32 spawn) {
    const LilSceneDef* def = Lil_FindSceneDef(play->sceneId);

    if (def != NULL) {
        play->sceneSegment = def->header;
    }
}

// Answer room requests with our room data instead of a DMA transfer. The vanilla function does nothing once the request
// status has been set, so running before it is enough.
RECOMP_HOOK("Room_RequestNewRoom") void Lil_OnRoomRequest(PlayState* play, RoomContext* roomCtx, s32 index) {
    const LilSceneDef* def = Lil_FindSceneDef(play->sceneId);

    if ((def != NULL) && (roomCtx->status == 0) && (index >= 0) && (index < def->numRooms)) {
        roomCtx->prevRoom = roomCtx->curRoom;
        roomCtx->curRoom.num = index;
        roomCtx->curRoom.segment = NULL;
        roomCtx->status = 1;
        roomCtx->roomRequestAddr = def->rooms[index];
        roomCtx->activeBufPage ^= 1;

        osCreateMesgQueue(&roomCtx->loadQueue, roomCtx->loadMsg, ARRAY_COUNT(roomCtx->loadMsg));
        osSendMesg(&roomCtx->loadQueue, NULL, OS_MESG_NOBLOCK);
    }
}
