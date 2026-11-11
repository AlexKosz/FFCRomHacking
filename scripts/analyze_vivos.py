import json
from pathlib import Path

p = Path(r"c:\Users\Alexander\Desktop\FFCRomHacking\Fossil Fighters Champions (USA) (NDSi Enhanced)\etc\creature_defs.dcl.json")
data = json.loads(p.read_text(encoding="utf-8"))
rows = []
for e in data["vivosaurs"]:
    if not e or not e.get("isEntry"):
        continue
    hp = e["healthAtEachRank"][19] if e.get("healthAtEachRank") else 0
    atk = e["stat1Attack"]["rank20Value"]
    defn = e["stat2Defense"]["rank20Value"]
    acc = e["stat3Accuracy"]["rank20Value"]
    spd = e["stat4Speed"]["rank20Value"]
    score = hp * 0.4 + atk * 3.2 + defn * 2.8 + acc * 1.8 + spd * 3.5
    rows.append((score, e["_id"], e["_defaultName"], hp, atk, defn, spd))

rows.sort(reverse=True)
for r in rows:
    print(f"{r[1]:3d} {r[2]:20s} score={r[0]:.0f} hp={r[3]} atk={r[4]} def={r[5]} spd={r[6]}")
