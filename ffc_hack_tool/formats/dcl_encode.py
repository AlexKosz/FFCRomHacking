"""Encode carbonizer's creature_defs.dcl.json back into DCL_FFC binary.

A faithful Python port of carbonizer's DCL_FFC.Packed init (see
tools/carbonizer-src/Sources/Carbonizer/files/ffc/DCL_FFC.swift), so the
studio can rebuild creature_defs without carbonizer's fragile full repack.
Correctness is proven by encode(unpacked json) == original binary; call
verify_roundtrip() before trusting an encode.
"""

from __future__ import annotations

import struct
from typing import Any

DCL_MAGIC = b"DCL\x00"
FIXED_HEADER = 0xBC

# enum orders from DCL_FFC.swift (raw value = position)
ELEMENTS = ["none", "fire", "air", "earth", "water", "neutral", "legendary"]
DIETS = ["none", "carnivore", "herbivore", "omnivore", "unknown"]
ERAS = [
    "none", "noTimePeriod", "cenozoicQuaternary", "cenozoicNeogene", "cenozoicPaleogene",
    "mesozoicCreataceous", "mesozoicJurassic", "mesozoicTriassic", "paleozoicPermian",
    "paleozoicCarboniferous", "paleozoicDevonian", "paleozoicOrdovician", "paleozoicCambrian",
]
DIGSITES = [
    "none", "bonusDataAndDebugs", "zongazongaRematch", "lolaFight", "lesterFight", "coleFight",
    "robinsonFight", "sideMission", "superRevival", "donationPointsVivosaur", "seabedCavern",
    "bbBrigadeBase", "unused", "bonehemoth", "icegripPlateau", "hotSpringHeights", "dustyDunes",
    "rainbowCanyon", "mtKrakanak", "petrifiedWoods", "stonePyramid", "jungleLabyrinth",
    "treasureLake",
]
BLUE_ABILITIES = [
    "none", "nothing", "japaneseForViewEnemyDetailsDuringBattle",
    "japaneseForDinosaurPlacementRandomization", "fpPlus", "partingBlow", "autoLPRecovery",
    "autoCounter", "japaneseForStatusEffectAbilityChangeDisabled",
    "japaneseForSupportAttackRateUp", "japaneseForMakesItEasierToObtainCertainKindsOfRocks",
    "japaneseForIncreasedMovementSpeed", "japaneseForCanOvercomeObstacles", "elementalBoost",
    "positionLock", "fpAbsorb", "soloPower", "berserker", "startWithAStatus",
    "japaneseForIncreasedDamageAgainstSpecificAttributes", "resurrect",
]
RANGES = ["none", "close", "mid", "long"]
# Team JSON raw string -> bit index (allCases order)
TEAM_BITS = {
    name: bit
    for bit, name in enumerate(
        [
            "fire-type (1)", "air-type (2)", "earth-type (3)", "water-type (4)",
            "neutral-type (5)", "violent (6)", "group7", "group8", "group9", "group10",
            "group11", "group12", "group13", "group14", "group15", "japanese (16)",
            "group17", "group18", "group19", "cenozoic (20)", "group21", "boney (22)",
            "zombie (23)", "poisonous (24)", "rotate (25)", "group26", "group27",
            "group28", "group29", "dinaurians (30)", "feathered (31)", "unusedGroup32",
        ]
    )
}


def _round_up(value: int, alignment: int) -> int:
    return value if value % alignment == 0 else value + (alignment - value % alignment)


def _fixed2012(value: float) -> int:
    return int(value * 4096)  # Swift FixedWidthInteger(Double) truncates toward zero


def _enum(table: list[str], value: str, what: str) -> int:
    try:
        return table.index(value)
    except ValueError:
        raise ValueError(f"unknown {what}: {value!r}")


def _position(v: dict) -> bytes:
    return struct.pack("<3i", _fixed2012(v["y"]), _fixed2012(v["rotation"]), _fixed2012(v["z"]))


def _encode_vivosaur(v: dict[str, Any] | None) -> bytes:
    if v is None or not v.get("isEntry"):
        # DCL_FFC.Packed.Vivosaur.null: all zero except the three 0xBC offsets
        blob = bytearray(FIXED_HEADER)
        struct.pack_into("<I", blob, 0x98, FIXED_HEADER)  # movesOffset
        struct.pack_into("<I", blob, 0xA0, FIXED_HEADER)  # moveLearningLevelsOffset
        struct.pack_into("<I", blob, 0xB0, FIXED_HEADER)  # moveListOrderOffset
        struct.pack_into("<I", blob, 0xB8, FIXED_HEADER)  # healthAtEachRankOffset
        return bytes(blob)

    moves = v.get("skillIDs", [])
    learn = v.get("skillLearningLevels", [])
    ally = v.get("supportEffectsForAlly")
    enemy = v.get("supportEffectsForEnemy")
    order = v.get("skillListOrder", [])
    health = v.get("healthAtEachRank", [])

    moves_off = FIXED_HEADER
    learn_off = moves_off + _round_up(len(moves) * 2, 4)
    learn_end = learn_off + _round_up(len(learn) * 2, 4)
    ally_off = 0 if ally is None else learn_end
    ally_end = 0 if ally is None else ally_off + 4
    enemy_off = 0 if enemy is None else max(learn_end, ally_end)
    enemy_end = 0 if enemy is None else enemy_off + 4
    order_off = max(learn_end, ally_end, enemy_end)
    health_off = order_off + _round_up(len(order), 4)
    size = health_off + len(health) * 2

    blob = bytearray(size)
    teams = 0
    for team in v.get("teamGroups", []):
        bit = TEAM_BITS.get(team)
        if bit is None:
            raise ValueError(f"unknown team group: {team!r}")
        teams |= 1 << bit

    struct.pack_into(
        "<2B", blob, 0x00, 1, _enum(ELEMENTS, v["element"], "element")
    )
    for off, key in ((0x02, "stat1Attack"), (0x06, "stat2Defense"), (0x0A, "stat3Accuracy"), (0x0E, "stat4Speed")):
        s = v[key]
        struct.pack_into("<4B", blob, off, s["growthRate"], s["rank10Value"], s["rank01Value"], s["rank20Value"])
    struct.pack_into(
        "<9B", blob, 0x12,
        v["critRate"], v["critRateForTypeAdvantage"], v["linkChance"],
        _enum(DIETS, v["sortOrderDiet"], "diet"),
        _enum(ERAS, v["sortOrderEra"], "era"),
        v["sortOrderLP"],
        _enum(DIGSITES, v["sortOrderDigsite"], "dig site"),
        _enum(BLUE_ABILITIES, v["staticBlueAbility"], "blue ability"),
        _enum(RANGES, v["range"], "range"),
    )
    struct.pack_into(
        "<8B", blob, 0x1B,
        *(v[f"rangeMultiplier{i}"] for i in range(1, 9)),
    )
    struct.pack_into(
        "<8B", blob, 0x23,
        *(1 if v[k] else 0 for k in (
            "immunityToPoison", "immunityToSleep", "immunityToScare", "immunityToEnrage",
            "immunityToConfusion", "immunityToExcite", "immunityToInfection", "immunityToInstantKO",
        )),
    )
    struct.pack_into("<B", blob, 0x2B, v["unknown02"])
    struct.pack_into(
        "<18H", blob, 0x2C,
        v["unknown03"], v["unknown04"], v["defaultNameID"], v["unknown05"],
        v["_id"], v["superEvolvesIntoID"], v["superEvolvesFromID"], v["modelID"],
        v["unknown06"], v["unknown07"], v["spriteIDs"], v["animationPackID"],
        v["unknown08"], v["colorPaletteForHead"], v["colorPaletteForBody"],
        v["colorPaletteForArms"], v["colorPaletteForLegs"], v["teamSkillID"],
    )
    struct.pack_into(
        "<5H", blob, 0x50,
        v["linkMoveID"], v["unknown09"], v["abilityArgument"], v["sortOrderName"], v["unknown10"],
    )
    struct.pack_into("<H", blob, 0x5A, v["unknown11"])
    struct.pack_into("<I", blob, 0x5C, teams)
    blob[0x60:0x6C] = _position(v["positionInFormationScreen"])
    blob[0x6C:0x78] = _position(v["positionInStatsScreen"])
    blob[0x78:0x84] = _position(v["positionInFossilary"])
    blob[0x84:0x90] = _position(v["positionInRevivalScreen"])
    struct.pack_into("<i", blob, 0x90, _fixed2012(v["shadowSize"]))
    struct.pack_into(
        "<10I", blob, 0x94,
        len(moves), moves_off, len(learn), learn_off, ally_off, enemy_off,
        len(order), order_off, len(health), health_off,
    )

    struct.pack_into(f"<{len(moves)}H", blob, moves_off, *moves)
    struct.pack_into(f"<{len(learn)}H", blob, learn_off, *learn)
    if ally is not None:
        struct.pack_into("<4b", blob, ally_off, ally["attack"], ally["defense"], ally["accuracy"], ally["speed"])
    if enemy is not None:
        struct.pack_into("<4b", blob, enemy_off, enemy["attack"], enemy["defense"], enemy["accuracy"], enemy["speed"])
    struct.pack_into(f"<{len(order)}B", blob, order_off, *order)
    struct.pack_into(f"<{len(health)}H", blob, health_off, *health)
    return bytes(blob)


def encode_dcl(data: dict[str, Any]) -> bytes:
    """creature_defs.dcl.json dict -> DCL_FFC binary."""
    vivosaurs = data.get("vivosaurs", [])
    blobs = [_encode_vivosaur(v) for v in vivosaurs]

    out = bytearray(DCL_MAGIC)
    out += struct.pack("<14h", *(data[f"unknown{i:02d}"] for i in range(1, 15)))
    out += struct.pack("<2I", len(blobs), 0x28)

    # makeOffsets(start=0x28 + count*4, sizes, alignedTo: 4)
    offsets = []
    pos = 0x28 + len(blobs) * 4
    for blob in blobs:
        offsets.append(pos)
        pos = _round_up(pos + len(blob), 4)
    out += struct.pack(f"<{len(offsets)}I", *offsets)

    for offset, blob in zip(offsets, blobs):
        out += bytes(offset - len(out))  # inter-blob alignment padding
        out += blob
    return bytes(out)


def verify_roundtrip(pristine_json: dict[str, Any], pristine_binary: bytes) -> None:
    """Prove the encoder reproduces the original binary byte-for-byte."""
    encoded = encode_dcl(pristine_json)
    if encoded != pristine_binary:
        n = min(len(encoded), len(pristine_binary))
        diff = next((i for i in range(n) if encoded[i] != pristine_binary[i]), n)
        raise ValueError(
            f"DCL encoder self-check failed: first difference at offset {diff:#x} "
            f"(encoded {len(encoded)} bytes, original {len(pristine_binary)})"
        )
