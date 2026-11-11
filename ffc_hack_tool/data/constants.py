"""UI labels for Fossil Fighters: Champions data."""

# DCL Digsite enum (creature_defs sortOrderDigsite / kaseki_defs site field)
DIGSITE_NAMES = {
    "none": "None",
    "bonusDataAndDebugs": "Bonus Data / Debug",
    "zongazongaRematch": "Zongazonga Rematch",
    "lolaFight": "Lola Fight",
    "lesterFight": "Lester Fight",
    "coleFight": "Cole Fight",
    "robinsonFight": "Robinson Fight",
    "sideMission": "Side Mission",
    "superRevival": "Super Revival",
    "donationPointsVivosaur": "Donation Points",
    "seabedCavern": "Seabed Cavern",
    "bbBrigadeBase": "BB Brigade Base",
    "unused": "Unused",
    "bonehemoth": "Bonehemoth",
    "icegripPlateau": "Icegrip Plateau",
    "hotSpringHeights": "Hot Spring Heights",
    "dustyDunes": "Dusty Dunes",
    "rainbowCanyon": "Rainbow Canyon",
    "mtKrakanak": "Mt. Krakanak",
    "petrifiedWoods": "Petrified Woods",
    "stonePyramid": "Stone Pyramid",
    "jungleLabyrinth": "Jungle Labyrinth",
    "treasureLake": "Treasure Lake",
}

# kaseki_defs numeric site ids -> label (same order as the enum above)
KASEKI_SITE_NAMES = {i: label for i, label in enumerate(DIGSITE_NAMES.values())}

FOSSIL_PART_NAMES = {1: "Head", 2: "Body", 3: "Arms", 4: "Legs"}

ELEMENTS = ["fire", "water", "air", "earth", "neutral", "legendary", "none"]
RANGES = ["close", "mid", "long", "none"]
