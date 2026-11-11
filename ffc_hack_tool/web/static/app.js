let currentProject = "";
let currentCreature = null;
let fossilSites = [];
let currentSiteRecords = null;
let battleList = [];
let currentBattle = null;
let vivoNames = new Map(); // index -> name
let vivoIndexByName = new Map(); // lowercase name -> index (base form wins)

const PART_NAMES = { 1: "Head", 2: "Body", 3: "Arms", 4: "Legs" };

function project() {
  return document.getElementById("project-select").value || currentProject;
}

/* ------------------------------------------------------------- ui utils */

function toast(msg, type = "ok", ms = 4500) {
  const root = document.getElementById("toast-root");
  const el = document.createElement("div");
  el.className = `toast ${type === "error" ? "error" : ""}`;
  el.textContent = msg;
  root.appendChild(el);
  setTimeout(() => el.remove(), ms);
}

function setStatus(msg, type = "ok") {
  if (msg) toast(msg, type);
}

function overlay(msg) {
  const el = document.getElementById("overlay");
  if (msg) {
    document.getElementById("overlay-msg").textContent = msg;
    el.classList.remove("hidden");
  } else {
    el.classList.add("hidden");
  }
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

/* ---------------------------------------------------------- navigation */

function showTab(name) {
  document.querySelectorAll(".side-nav button").forEach((b) =>
    b.classList.toggle("active", b.dataset.tab === name)
  );
  document.querySelectorAll(".tab-content").forEach((t) =>
    t.classList.toggle("active", t.id === `tab-${name}`)
  );
}

document.querySelectorAll(".side-nav button").forEach((btn) => {
  btn.addEventListener("click", () => showTab(btn.dataset.tab));
});

function setNavEnabled(enabled) {
  document.querySelectorAll(".side-nav button").forEach((b) => {
    if (b.dataset.tab !== "home") b.disabled = !enabled;
  });
}

/* ------------------------------------------------------------- projects */

document.getElementById("create-project").addEventListener("click", async () => {
  const name = document.getElementById("project-name").value.trim();
  const rom = document.getElementById("rom-path").value.trim().replace(/^"|"$/g, "");
  if (!name || !rom) return toast("Enter a project name and the path to your ROM.", "error");
  try {
    overlay(`Extracting the ROM into project “${name}”…`);
    await api("/api/projects", { method: "POST", body: JSON.stringify({ name, rom }) });
    const sel = document.getElementById("project-select");
    if (![...sel.options].some((o) => o.value === name)) {
      const opt = document.createElement("option");
      opt.value = opt.textContent = name;
      sel.appendChild(opt);
    }
    sel.value = name;
    currentProject = name;
    toast(`Project “${name}” created. Your workspace is ready — start editing!`);
    await loadAll();
  } catch (e) {
    toast(e.message, "error", 9000);
  } finally {
    overlay(null);
  }
});

document.getElementById("project-select").addEventListener("change", async (e) => {
  currentProject = e.target.value;
  if (!currentProject) {
    setNavEnabled(false);
    document.getElementById("project-overview").classList.add("hidden");
    return;
  }
  overlay(`Loading project “${currentProject}”…`);
  try {
    await loadAll();
    toast(`Project “${currentProject}” loaded — picking up right where you left off.`);
  } catch (err) {
    toast(err.message, "error");
  } finally {
    overlay(null);
  }
});

async function loadAll() {
  const problems = [];
  for (const [label, fn] of [
    ["vivosaurs", loadVivoNames],
    ["vivosaur list", loadCreatures],
    ["moves", loadMoves],
    ["dig sites", loadFossils],
    ["battles", loadBattles],
    ["text archives", loadTexts],
    ["settings", loadSettings],
    ["project info", loadMeta],
  ]) {
    try {
      await fn();
    } catch (e) {
      problems.push(`${label}: ${e.message}`);
    }
  }
  setNavEnabled(true);
  localStorage.setItem("ffc-last-project", project());
  if (problems.length) {
    toast(
      `Some project data could not be loaded — ${problems[0]}` +
        (problems.length > 1 ? ` (+${problems.length - 1} more)` : ""),
      "error",
      9000
    );
  }
}

/* ----------------------------------------------------- overview + notes */

async function loadMeta() {
  const meta = await api(`/api/projects/${project()}/meta`);
  document.getElementById("project-overview").classList.remove("hidden");
  document.getElementById("overview-title").textContent = `Project: ${meta.name}`;
  document.getElementById("overview-created").textContent = (meta.created_at || "").slice(0, 10) || "—";
  document.getElementById("overview-rom").textContent = meta.source_rom || "—";
  document.getElementById("overview-workspace").textContent = meta.workspace || "—";
  document.getElementById("project-notes").value = meta.notes || "";
  document.getElementById("base-rom").value = meta.base_rom || "";
  document.getElementById("hack-title").value = meta.hack_title || "";
  document.getElementById("hack-author").value = meta.author || "";
}

let notesTimer = null;
document.getElementById("project-notes").addEventListener("input", () => {
  const status = document.getElementById("notes-status");
  status.textContent = "Saving…";
  clearTimeout(notesTimer);
  notesTimer = setTimeout(async () => {
    try {
      await api(`/api/projects/${project()}/settings`, {
        method: "PUT",
        body: JSON.stringify({ notes: document.getElementById("project-notes").value }),
      });
      status.textContent = "Notes saved ✓";
    } catch (e) {
      status.textContent = `Could not save notes: ${e.message}`;
    }
  }, 600);
});

document.getElementById("save-identity").addEventListener("click", async () => {
  try {
    await api(`/api/projects/${project()}/settings`, {
      method: "PUT",
      body: JSON.stringify({
        hack_title: document.getElementById("hack-title").value,
        author: document.getElementById("hack-author").value,
      }),
    });
    toast("Hack title and author saved.");
  } catch (e) {
    toast(e.message, "error");
  }
});

/* ------------------------------------------------------ vivosaur names */

async function loadVivoNames() {
  const p = project();
  if (!p) return;
  const list = await api(`/api/projects/${p}/vivosaur-names`);
  vivoNames = new Map();
  vivoIndexByName = new Map();
  const datalist = document.getElementById("vivo-datalist");
  datalist.innerHTML = "";
  for (const v of list) {
    vivoNames.set(v.index, v.name);
    const key = v.name.toLowerCase();
    if (!vivoIndexByName.has(key)) vivoIndexByName.set(key, v.index); // base form wins
    const opt = document.createElement("option");
    opt.value = v.name;
    datalist.appendChild(opt);
  }
}

function resolveVivoName(raw) {
  const text = raw.trim().toLowerCase();
  if (!text) return 0; // empty slot
  if (vivoIndexByName.has(text)) return vivoIndexByName.get(text);
  const asNumber = Number(text.replace(/^#/, ""));
  if (Number.isInteger(asNumber) && vivoNames.has(asNumber)) return asNumber;
  return null;
}

/* ------------------------------------------------------------ creatures */

async function loadCreatures() {
  const p = project();
  if (!p) return;
  const list = document.getElementById("creature-list");
  list.innerHTML = "";
  const creatures = await api(`/api/projects/${p}/creatures`);
  creatures.forEach((c) => {
    const btn = document.createElement("button");
    btn.textContent = `#${c.id} ${c.name}`;
    btn.addEventListener("click", () => selectCreature(c, btn));
    list.appendChild(btn);
  });
}

const SUPPORT_STATS = ["attack", "defense", "accuracy", "speed"];

function setSupportFields(side, effects) {
  const on = document.getElementById(`c-sup-${side}-on`);
  on.checked = !!effects;
  for (const stat of SUPPORT_STATS) {
    const input = document.getElementById(`c-sup-${side}-${stat}`);
    input.value = effects?.[stat] ?? 0;
    input.disabled = !effects;
  }
}

function readSupportFields(side) {
  if (!document.getElementById(`c-sup-${side}-on`).checked) return null;
  const effects = {};
  for (const stat of SUPPORT_STATS) {
    const value = Number(document.getElementById(`c-sup-${side}-${stat}`).value) || 0;
    effects[stat] = Math.max(-100, Math.min(100, Math.round(value)));
  }
  return effects;
}

for (const side of ["ally", "enemy"]) {
  document.getElementById(`c-sup-${side}-on`).addEventListener("change", (e) => {
    for (const stat of SUPPORT_STATS) {
      document.getElementById(`c-sup-${side}-${stat}`).disabled = !e.target.checked;
    }
  });
}

function selectCreature(c, btn) {
  currentCreature = c;
  document.querySelectorAll("#creature-list button").forEach((b) => b.classList.remove("active"));
  btn.classList.add("active");
  document.getElementById("creature-editor").classList.remove("hidden");
  document.getElementById("creature-title").textContent = c.name;
  document.getElementById("c-element").value = c.element || "none";
  document.getElementById("c-range").value = c.range || "none";
  document.getElementById("c-digsite").value = c.digsite || "none";
  document.getElementById("c-atk20").value = c.stats?.attack?.rank20Value ?? 0;
  document.getElementById("c-def20").value = c.stats?.defense?.rank20Value ?? 0;
  document.getElementById("c-acc20").value = c.stats?.accuracy?.rank20Value ?? 0;
  document.getElementById("c-spd20").value = c.stats?.speed?.rank20Value ?? 0;
  document.getElementById("c-hp20").value = c.healthAtEachRank?.[19] ?? 0;
  setSupportFields("ally", c.raw?.supportEffectsForAlly ?? null);
  setSupportFields("enemy", c.raw?.supportEffectsForEnemy ?? null);
  document.getElementById("c-skills").value = (c.skills || []).join(", ");
}

document.getElementById("save-creature").addEventListener("click", async () => {
  if (!currentCreature) return;
  const raw = structuredClone(currentCreature.raw);
  raw.element = document.getElementById("c-element").value;
  raw.range = document.getElementById("c-range").value;
  raw.sortOrderDigsite = document.getElementById("c-digsite").value;
  raw.stat1Attack.rank20Value = Number(document.getElementById("c-atk20").value);
  raw.stat2Defense.rank20Value = Number(document.getElementById("c-def20").value);
  raw.stat3Accuracy.rank20Value = Number(document.getElementById("c-acc20").value);
  raw.stat4Speed.rank20Value = Number(document.getElementById("c-spd20").value);
  if (raw.healthAtEachRank?.length >= 20) {
    raw.healthAtEachRank[19] = Number(document.getElementById("c-hp20").value);
  }
  const ally = readSupportFields("ally");
  if (ally) raw.supportEffectsForAlly = ally;
  else delete raw.supportEffectsForAlly;
  const enemy = readSupportFields("enemy");
  if (enemy) raw.supportEffectsForEnemy = enemy;
  else delete raw.supportEffectsForEnemy;
  raw.skillIDs = document.getElementById("c-skills").value.split(",").map((x) => Number(x.trim())).filter(Boolean);
  try {
    await api(`/api/projects/${project()}/creatures/${currentCreature.index}`, {
      method: "PUT",
      body: JSON.stringify({ raw }),
    });
    toast(`Saved ${currentCreature.name}.`);
    await loadCreatures();
  } catch (e) {
    toast(e.message, "error");
  }
});

/* -------------------------------------------------- fossils: site list */

async function loadFossils() {
  const p = project();
  if (!p) return;
  try {
    fossilSites = await api(`/api/projects/${p}/fossils`);
    renderFossilSiteList();
  } catch (e) {
    toast(e.message, "error");
  }
}

document.getElementById("load-fossils").addEventListener("click", loadFossils);
document.getElementById("fossil-filter").addEventListener("input", renderFossilSiteList);

function renderFossilSiteList() {
  const root = document.getElementById("fossil-site-list");
  const filter = document.getElementById("fossil-filter").value.trim().toLowerCase();
  root.innerHTML = "";
  fossilSites
    .filter(
      (site) =>
        !filter ||
        site.map_id.includes(filter) ||
        site.pool.some((s) => s.name.toLowerCase().includes(filter))
    )
    .forEach((site) => {
      const btn = document.createElement("button");
      btn.textContent = `Map ${site.map_id} — ${site.pool.length} species`;
      btn.addEventListener("click", () => {
        document.querySelectorAll("#fossil-site-list button").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        loadSiteRecords(site.map_id);
      });
      root.appendChild(btn);
    });
}

/* -------------------------------------------- fossils: record editor */

async function loadSiteRecords(mapId) {
  const root = document.getElementById("fossil-records");
  root.innerHTML = "<p class='muted'>Loading records…</p>";
  try {
    currentSiteRecords = await api(`/api/projects/${project()}/fossils/${mapId}/records`);
    renderSiteRecords();
  } catch (e) {
    root.innerHTML = "";
    toast(e.message, "error");
  }
}

function speciesStats(records, total) {
  const stats = new Map(); // name -> {count, parts: Map(part -> count)}
  for (const r of records) {
    if (r.special) continue;
    const s = stats.get(r.name) || { count: 0, parts: new Map() };
    s.count += 1;
    s.parts.set(r.part, (s.parts.get(r.part) || 0) + 1);
    stats.set(r.name, s);
  }
  return [...stats.entries()]
    .sort((a, b) => b[1].count - a[1].count)
    .map(([name, s]) => {
      const parts = [1, 2, 3, 4]
        .filter((p) => s.parts.has(p))
        .map((p) => `${PART_NAMES[p][0]} ${((s.parts.get(p) / total) * 100).toFixed(1)}%`)
        .join(", ");
      return `${name} ${((s.count / total) * 100).toFixed(1)}% (${parts})`;
    });
}

function renderSiteRecords() {
  const site = currentSiteRecords;
  const root = document.getElementById("fossil-records");
  root.innerHTML = "";

  const heading = document.createElement("h3");
  heading.textContent = `Map ${site.mapId} — ${site.records.length} records (${site.speciesRecords} species rocks)`;
  root.appendChild(heading);

  const summary = document.createElement("div");
  summary.className = "chip-row";
  for (const line of speciesStats(site.records, site.speciesRecords)) {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.textContent = line;
    summary.appendChild(chip);
  }
  root.appendChild(summary);

  // group records by zone code
  const zones = new Map();
  for (const r of site.records) {
    const key = `${r.zone[0]}-${r.zone[1]}`;
    if (!zones.has(key)) zones.set(key, []);
    zones.get(key).push(r);
  }

  for (const [zone, records] of [...zones.entries()].sort()) {
    const card = document.createElement("div");
    card.className = "spawn-card";
    card.innerHTML = `<h4>Zone ${zone} — ${records.length} records</h4>`;

    const table = document.createElement("table");
    table.className = "rec-table";
    table.innerHTML =
      "<thead><tr><th>offset</th><th>weights</th><th>vivosaur</th><th>part</th><th>share</th></tr></thead>";
    const tbody = document.createElement("tbody");

    for (const r of records) {
      const tr = document.createElement("tr");
      const share = ((1 / site.speciesRecords) * 100).toFixed(2);
      if (r.special) {
        tr.innerHTML =
          `<td>0x${r.offset.toString(16)}</td><td>${r.paramA}/${r.paramB}</td>` +
          `<td colspan="2" class="muted">special rock #${r.kasekiId} (jewel / dropping / dark fossil)</td><td>—</td>`;
      } else {
        tr.innerHTML = `<td>0x${r.offset.toString(16)}</td><td>${r.paramA}/${r.paramB}</td>`;
        const tdVivo = document.createElement("td");
        const input = document.createElement("input");
        input.setAttribute("list", "vivo-datalist");
        input.value = r.name;
        input.dataset.offset = r.offset;
        input.dataset.origVivo = r.vivo;
        input.className = "rec-vivo";
        tdVivo.appendChild(input);
        tr.appendChild(tdVivo);

        const tdPart = document.createElement("td");
        const sel = document.createElement("select");
        sel.className = "rec-part";
        for (const [num, label] of Object.entries(PART_NAMES)) {
          const opt = document.createElement("option");
          opt.value = num;
          opt.textContent = label;
          if (Number(num) === r.part) opt.selected = true;
          sel.appendChild(opt);
        }
        sel.dataset.origPart = r.part;
        tdPart.appendChild(sel);
        tr.appendChild(tdPart);

        const tdShare = document.createElement("td");
        tdShare.textContent = `${share}%`;
        tr.appendChild(tdShare);
      }
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    card.appendChild(table);
    root.appendChild(card);
  }

  const save = document.createElement("button");
  save.className = "primary";
  save.textContent = "Save changed records";
  save.addEventListener("click", saveSiteRecords);
  root.appendChild(save);
}

async function saveSiteRecords() {
  const site = currentSiteRecords;
  const changes = [];
  const problems = [];
  document.querySelectorAll("#fossil-records tbody tr").forEach((tr) => {
    const input = tr.querySelector("input.rec-vivo");
    if (!input) return;
    const sel = tr.querySelector("select.rec-part");
    const vivo = resolveVivoName(input.value);
    const part = Number(sel.value);
    if (vivo === null) {
      problems.push(`"${input.value}" is not a vivosaur`);
      return;
    }
    if (vivo === 0) {
      problems.push("a dig record cannot be empty — pick a vivosaur");
      return;
    }
    if (vivo !== Number(input.dataset.origVivo) || part !== Number(sel.dataset.origPart)) {
      changes.push({ offset: Number(input.dataset.offset), vivo, part });
    }
  });
  if (problems.length) return toast(problems.join("; "), "error");
  if (!changes.length) return toast("No record changes to save.");
  try {
    const result = await api(`/api/projects/${project()}/fossils/${site.mapId}/records`, {
      method: "PUT",
      body: JSON.stringify({ changes }),
    });
    toast(
      `Map ${site.mapId}: ${result.changed} records updated.` +
        (result.errors.length ? ` Errors: ${result.errors.join("; ")}` : ""),
      result.errors.length ? "error" : "ok"
    );
    await loadSiteRecords(site.mapId);
    await loadFossils();
  } catch (e) {
    toast(e.message, "error");
  }
}

/* --------------------------------------------------------------- battles */

async function loadBattles() {
  const p = project();
  if (!p) return;
  try {
    battleList = await api(`/api/projects/${p}/battles`);
    renderBattleList();
  } catch (e) {
    toast(e.message, "error");
  }
}

document.getElementById("load-battles").addEventListener("click", loadBattles);
document.getElementById("battle-filter").addEventListener("input", renderBattleList);

function renderBattleList() {
  const root = document.getElementById("battle-list");
  const filter = document.getElementById("battle-filter").value.trim().toLowerCase();
  root.innerHTML = "";
  battleList
    .filter(
      (b) =>
        !filter ||
        String(b.id) === filter ||
        b.summary.toLowerCase().includes(filter) ||
        (b.trainer || "").toLowerCase().includes(filter) ||
        (b.location || "").toLowerCase().includes(filter)
    )
    .forEach((b) => {
      const btn = document.createElement("button");
      const where = b.location ? ` @ ${b.location}` : "";
      btn.textContent = `#${b.id}  ${b.trainer}${where} — ${b.summary || "(no enemy data)"}`;
      btn.addEventListener("click", () => {
        document.querySelectorAll("#battle-list button").forEach((x) => x.classList.remove("active"));
        btn.classList.add("active");
        loadBattleDetail(b.id);
      });
      root.appendChild(btn);
    });
}

async function loadBattleDetail(id) {
  const root = document.getElementById("battle-editor");
  root.innerHTML = "<p class='muted'>Loading battle…</p>";
  try {
    currentBattle = await api(`/api/projects/${project()}/battles/${id}`);
    renderBattleEditor();
  } catch (e) {
    root.innerHTML = "";
    toast(e.message, "error");
  }
}

function renderBattleEditor() {
  const battle = currentBattle;
  const root = document.getElementById("battle-editor");
  root.innerHTML = "";

  // Headline the battle by its toughest enemy vivosaur (no trainer-name
  // field exists in the battle data), same as the site docs.
  let lead = null;
  for (const entry of battle.entries) {
    if (entry.isPlayer) continue;
    for (const slot of entry.slots) {
      if (slot.vivo && (!lead || slot.rank > lead.rank)) lead = slot;
    }
  }
  const heading = document.createElement("h3");
  heading.textContent = lead ? `${lead.name} — Battle ${battle.id}` : `Battle ${battle.id}`;
  root.appendChild(heading);

  // Secondary header: curated trainer name; and a location line below it.
  const sub = document.createElement("p");
  sub.className = battle.named ? "battle-trainer" : "battle-trainer muted";
  sub.textContent = battle.trainer || "Fossil Fighter";
  root.appendChild(sub);
  if (battle.location) {
    const loc = document.createElement("p");
    loc.className = "battle-location";
    loc.textContent = `📍 ${battle.location}`;
    root.appendChild(loc);
  }

  battle.entries.forEach((entry, ei) => {
    const card = document.createElement("div");
    card.className = "spawn-card";
    card.dataset.entry = ei;
    card.innerHTML = `<h4>${entry.isPlayer ? "PLAYER side" : "ENEMY side"}${
      entry.preBattleMsg ? ` <span class="muted">(pre-battle msg ${entry.preBattleMsg})</span>` : ""
    }</h4>`;

    const table = document.createElement("table");
    table.className = "rec-table";
    table.innerHTML =
      "<thead><tr><th>slot</th><th>vivosaur</th><th>rank</th><th>stat ×</th><th>tactic</th></tr></thead>";
    const tbody = document.createElement("tbody");

    entry.slots.forEach((slot, si) => {
      const tr = document.createElement("tr");
      tr.dataset.slot = si;
      tr.innerHTML = `<td>${si + 1}</td>`;

      const tdVivo = document.createElement("td");
      const input = document.createElement("input");
      input.setAttribute("list", "vivo-datalist");
      input.value = slot.vivo ? slot.name : "";
      input.placeholder = "(empty)";
      input.className = "slot-vivo";
      tdVivo.appendChild(input);
      tr.appendChild(tdVivo);

      const tdRank = document.createElement("td");
      const rank = document.createElement("input");
      rank.type = "number";
      rank.min = 1;
      rank.max = 20;
      rank.value = slot.rank;
      rank.className = "slot-rank num";
      tdRank.appendChild(rank);
      tr.appendChild(tdRank);

      const tdMult = document.createElement("td");
      const mult = document.createElement("input");
      mult.type = "number";
      mult.min = 0.05;
      mult.max = 8;
      mult.step = 0.01;
      mult.value = slot.mult;
      mult.disabled = !slot.hasMult;
      mult.className = "slot-mult num";
      tdMult.appendChild(mult);
      tr.appendChild(tdMult);

      const tdTac = document.createElement("td");
      const tac = document.createElement("input");
      tac.type = "number";
      tac.min = 1;
      tac.max = 4;
      tac.value = slot.tactic;
      tac.disabled = !slot.hasTactic;
      tac.className = "slot-tactic num";
      tdTac.appendChild(tac);
      tr.appendChild(tdTac);

      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    card.appendChild(table);

    if (entry.ai.length) {
      const aiRow = document.createElement("div");
      aiRow.className = "ai-row";
      aiRow.innerHTML = "<span class='muted'>AI tactic ids:</span>";
      entry.ai.forEach((value) => {
        const input = document.createElement("input");
        input.type = "number";
        input.min = 1;
        input.max = 17;
        input.value = value;
        input.className = "slot-ai num";
        aiRow.appendChild(input);
      });
      card.appendChild(aiRow);
    }
    root.appendChild(card);
  });

  const save = document.createElement("button");
  save.className = "primary";
  save.textContent = "Save battle";
  save.addEventListener("click", saveBattle);
  root.appendChild(save);
}

async function saveBattle() {
  const battle = currentBattle;
  const payload = { entries: [] };
  const problems = [];

  document.querySelectorAll("#battle-editor .spawn-card").forEach((card) => {
    const ei = Number(card.dataset.entry);
    const source = battle.entries[ei];
    const entry = { slots: [] };
    card.querySelectorAll("tbody tr").forEach((tr) => {
      const raw = tr.querySelector(".slot-vivo").value;
      const vivo = resolveVivoName(raw);
      if (vivo === null) problems.push(`"${raw}" is not a vivosaur`);
      entry.slots.push({
        vivo: vivo ?? 0,
        rank: Number(tr.querySelector(".slot-rank").value),
        mult: Number(tr.querySelector(".slot-mult").value),
        tactic: Number(tr.querySelector(".slot-tactic").value),
      });
    });
    const aiInputs = card.querySelectorAll(".slot-ai");
    if (aiInputs.length) entry.ai = [...aiInputs].map((i) => Number(i.value));
    else if (source.ai.length) entry.ai = source.ai;
    payload.entries.push(entry);
  });

  if (problems.length) return toast(problems.join("; "), "error");
  try {
    await api(`/api/projects/${project()}/battles/${battle.id}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    toast(`Battle ${battle.id} saved.`);
    await loadBattleDetail(battle.id);
    await loadBattles();
  } catch (e) {
    toast(`Battle ${battle.id}: ${e.message}`, "error");
  }
}

/* ----------------------------------------------------------------- moves */

let moveList = [];
let currentMove = null;

async function loadMoves() {
  const p = project();
  if (!p) return;
  try {
    moveList = await api(`/api/projects/${p}/moves`);
    renderMoveList();
  } catch (e) {
    toast(e.message, "error");
  }
}

document.getElementById("load-moves").addEventListener("click", loadMoves);
document.getElementById("move-filter").addEventListener("input", renderMoveList);

function moveOwnerText(m) {
  return m.owners.map((o) => o.name).join(", ");
}

function renderMoveList() {
  const root = document.getElementById("move-list");
  const filter = document.getElementById("move-filter").value.trim().toLowerCase();
  root.innerHTML = "";
  moveList
    .filter(
      (m) =>
        !filter ||
        m.name.toLowerCase().includes(filter) ||
        String(m.id) === filter ||
        m.owners.some((o) => o.name.toLowerCase().includes(filter))
    )
    .forEach((m) => {
      const btn = document.createElement("button");
      const owners = moveOwnerText(m);
      btn.textContent = `#${m.id} ${m.name} — FP ${m.total?.fp ?? "?"} / dmg ${m.total?.damage ?? "?"}${owners ? ` (${owners})` : ""}`;
      btn.addEventListener("click", () => {
        document.querySelectorAll("#move-list button").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        selectMove(m);
      });
      root.appendChild(btn);
    });
}

function selectMove(m) {
  currentMove = m;
  const root = document.getElementById("move-editor");
  root.innerHTML = "";

  const heading = document.createElement("h3");
  heading.textContent = `#${m.id} ${m.name}`;
  root.appendChild(heading);

  if (m.info) {
    const info = document.createElement("p");
    info.className = "muted";
    info.textContent = m.info.replace("%s", m.total?.damage ?? "?");
    root.appendChild(info);
  }
  if (m.owners.length) {
    const owners = document.createElement("div");
    owners.className = "chip-row";
    for (const o of m.owners) {
      const chip = document.createElement("span");
      chip.className = "chip";
      chip.textContent = `${o.name} · ${o.element}`;
      owners.appendChild(chip);
    }
    root.appendChild(owners);
    const note = document.createElement("p");
    note.className = "muted";
    note.textContent =
      "A move always uses its vivosaur's element — change that in the Vivosaurs tab.";
    root.appendChild(note);
  }

  const table = document.createElement("table");
  table.className = "rec-table";
  table.innerHTML = "<thead><tr><th>hit</th><th>FP cost</th><th>damage</th></tr></thead>";
  const tbody = document.createElement("tbody");
  m.hits.forEach((hit, i) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${m.hits.length > 1 ? i + 1 : "—"}</td>`;
    for (const key of ["fp", "damage"]) {
      const td = document.createElement("td");
      const input = document.createElement("input");
      input.type = "number";
      input.min = 0;
      input.max = 999;
      input.value = hit[key];
      input.className = `move-${key} num`;
      input.addEventListener("input", updateMoveTotal);
      td.appendChild(input);
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  root.appendChild(table);

  const totalRow = document.createElement("p");
  totalRow.id = "move-total";
  root.appendChild(totalRow);

  if (m.effectId > 1) {
    const label = document.createElement("label");
    label.textContent = "Status effect chance % ";
    const input = document.createElement("input");
    input.type = "number";
    input.min = 0;
    input.max = 100;
    input.value = m.effectChance;
    input.id = "move-chance";
    input.className = "num";
    label.appendChild(input);
    root.appendChild(label);
  }

  const save = document.createElement("button");
  save.className = "primary";
  save.textContent = "Save move";
  save.addEventListener("click", saveMove);
  root.appendChild(save);
  updateMoveTotal();
}

function readMoveHits() {
  const fps = [...document.querySelectorAll("#move-editor .move-fp")].map((i) => Number(i.value));
  const dmgs = [...document.querySelectorAll("#move-editor .move-damage")].map((i) => Number(i.value));
  return fps.map((fp, i) => ({ fp, damage: dmgs[i] }));
}

function updateMoveTotal() {
  const hits = readMoveHits();
  const fp = hits.reduce((s, h) => s + h.fp, 0);
  const damage = hits.reduce((s, h) => s + h.damage, 0);
  const el = document.getElementById("move-total");
  if (el) el.innerHTML = `<b>Total (shown in game):</b> FP ${fp} · damage ${damage}`;
}

async function saveMove() {
  if (!currentMove) return;
  const body = { hits: readMoveHits() };
  const chance = document.getElementById("move-chance");
  if (chance) body.effectChance = Number(chance.value);
  try {
    await api(`/api/projects/${project()}/moves/${currentMove.id}`, {
      method: "PUT",
      body: JSON.stringify(body),
    });
    toast(`Saved ${currentMove.name}.`);
    await loadMoves();
  } catch (e) {
    toast(e.message, "error");
  }
}

/* ------------------------------------------------------------------ text */

let textFiles = [];
let currentTextFile = null;
let textEntryFilter = "";

async function loadTexts() {
  const p = project();
  if (!p) return;
  try {
    textFiles = await api(`/api/projects/${p}/texts`);
    renderTextFileList();
  } catch (e) {
    toast(e.message, "error");
  }
}

document.getElementById("load-texts").addEventListener("click", loadTexts);
document.getElementById("text-file-filter").addEventListener("input", renderTextFileList);

function renderTextFileList() {
  const root = document.getElementById("text-file-list");
  const filter = document.getElementById("text-file-filter").value.trim().toLowerCase();
  root.innerHTML = "";
  textFiles
    .filter((f) => !filter || f.file.toLowerCase().includes(filter))
    .forEach((f) => {
      const btn = document.createElement("button");
      btn.textContent = `${f.file} — ${f.count} strings`;
      btn.addEventListener("click", () => {
        document.querySelectorAll("#text-file-list button").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        loadTextFile(f.file);
      });
      root.appendChild(btn);
    });
}

async function loadTextFile(rel, highlightIndex = null) {
  const root = document.getElementById("text-editor");
  root.innerHTML = "<p class='muted'>Loading strings…</p>";
  try {
    currentTextFile = await api(
      `/api/projects/${project()}/texts/entries?file=${encodeURIComponent(rel)}`
    );
    textEntryFilter = "";
    renderTextEditor(highlightIndex);
  } catch (e) {
    root.innerHTML = "";
    toast(e.message, "error");
  }
}

const TEXT_PAGE_LIMIT = 250;

function renderTextEditor(highlightIndex = null) {
  const tf = currentTextFile;
  const root = document.getElementById("text-editor");
  root.innerHTML = "";

  const heading = document.createElement("h3");
  heading.textContent = `${tf.file} — ${tf.entries.length} strings`;
  root.appendChild(heading);

  const filterLabel = document.createElement("label");
  filterLabel.textContent = "Filter strings ";
  const filterInput = document.createElement("input");
  filterInput.value = textEntryFilter;
  filterInput.placeholder = "substring or #index";
  filterInput.addEventListener("input", () => {
    textEntryFilter = filterInput.value;
    renderRows();
  });
  filterLabel.appendChild(filterInput);
  root.appendChild(filterLabel);

  const rows = document.createElement("div");
  rows.id = "text-rows";
  root.appendChild(rows);

  const edited = new Map(); // index -> new string

  function renderRows() {
    rows.innerHTML = "";
    const filter = textEntryFilter.trim().toLowerCase();
    const wantIndex = filter.startsWith("#") ? Number(filter.slice(1)) : null;
    let shown = 0;
    for (const e of tf.entries) {
      const value = edited.has(e.index) ? edited.get(e.index) : e.string;
      if (filter) {
        if (wantIndex !== null) {
          if (e.index !== wantIndex) continue;
        } else if (!value.toLowerCase().includes(filter)) continue;
      }
      if (shown >= TEXT_PAGE_LIMIT) {
        const more = document.createElement("p");
        more.className = "muted";
        more.textContent = `…more strings match — narrow the filter to see them.`;
        rows.appendChild(more);
        break;
      }
      shown += 1;
      const row = document.createElement("div");
      row.className = "text-row";
      const label = document.createElement("span");
      label.className = "mono muted";
      label.textContent = `#${e.index}`;
      row.appendChild(label);
      const area = document.createElement("textarea");
      area.value = value;
      area.rows = Math.min(6, Math.max(1, value.split("\n").length));
      area.addEventListener("input", () => {
        edited.set(e.index, area.value);
        area.classList.toggle("changed", area.value !== e.string);
      });
      if (highlightIndex !== null && e.index === highlightIndex) {
        area.classList.add("highlight");
        setTimeout(() => area.scrollIntoView({ block: "center" }), 50);
      }
      row.appendChild(area);
      rows.appendChild(row);
    }
    if (!shown) {
      rows.innerHTML = "<p class='muted'>No strings match this filter.</p>";
    }
  }
  renderRows();

  const save = document.createElement("button");
  save.className = "primary";
  save.textContent = "Save changed strings";
  save.addEventListener("click", async () => {
    const entries = tf.entries.map((e) => ({
      index: e.index,
      string: edited.has(e.index) ? edited.get(e.index) : e.string,
    }));
    try {
      const result = await api(`/api/projects/${project()}/texts/entries`, {
        method: "PUT",
        body: JSON.stringify({ file: tf.file, entries }),
      });
      toast(`${tf.file}: ${result.changed} strings updated.`);
      await loadTextFile(tf.file);
    } catch (e) {
      toast(e.message, "error");
    }
  });
  root.appendChild(save);
}

let textSearchTimer = null;
document.getElementById("text-search").addEventListener("input", () => {
  clearTimeout(textSearchTimer);
  textSearchTimer = setTimeout(runTextSearch, 400);
});

async function runTextSearch() {
  const q = document.getElementById("text-search").value.trim();
  const box = document.getElementById("text-search-results");
  if (q.length < 2) {
    box.classList.add("hidden");
    box.innerHTML = "";
    return;
  }
  try {
    const hits = await api(`/api/projects/${project()}/texts/search?q=${encodeURIComponent(q)}`);
    box.classList.remove("hidden");
    box.innerHTML = `<p class="muted">${hits.length} matches${hits.length >= 300 ? " (first 300)" : ""}</p>`;
    for (const hit of hits.slice(0, 60)) {
      const row = document.createElement("button");
      row.className = "text-hit";
      const oneLine = hit.string.replace(/\n/g, " ⏎ ");
      row.textContent = `${hit.file} #${hit.index}: ${oneLine.length > 110 ? oneLine.slice(0, 110) + "…" : oneLine}`;
      row.addEventListener("click", () => {
        box.classList.add("hidden");
        loadTextFile(hit.file, hit.index).then(() => {
          textEntryFilter = `#${hit.index}`;
          renderTextEditor(hit.index);
        });
      });
      box.appendChild(row);
    }
    if (hits.length > 60) {
      const more = document.createElement("p");
      more.className = "muted";
      more.textContent = "…more matches not shown — refine the search.";
      box.appendChild(more);
    }
  } catch (e) {
    toast(e.message, "error");
  }
}

/* -------------------------------------------------------------- settings */

async function loadSettings() {
  const settings = await api(`/api/projects/${project()}/settings`);
  const r = settings.randomizer || {};
  document.getElementById("rand-enabled").checked = !!r.enabled;
  document.getElementById("rand-seed").value = r.seed || 0;
  document.getElementById("rand-fossils").checked = r.randomize_fossil_locations !== false;
  document.getElementById("rand-battles").checked = r.randomize_battles !== false;
  document.getElementById("rand-mono").checked = !!r.mono_spawn;
  document.getElementById("hard-mode").checked = !!settings.hard_mode;
  document.getElementById("element-fix").checked = !!settings.element_fix;
}

document.getElementById("save-randomizer").addEventListener("click", async () => {
  try {
    const settings = await api(`/api/projects/${project()}/settings`);
    settings.randomizer = {
      enabled: document.getElementById("rand-enabled").checked,
      seed: Number(document.getElementById("rand-seed").value),
      randomize_fossil_locations: document.getElementById("rand-fossils").checked,
      randomize_battles: document.getElementById("rand-battles").checked,
      mono_spawn: document.getElementById("rand-mono").checked,
    };
    await api(`/api/projects/${project()}/settings`, { method: "PUT", body: JSON.stringify(settings) });
    toast("Randomizer settings saved — they apply the next time you build.");
  } catch (e) {
    toast(e.message, "error");
  }
});

document.getElementById("save-hardmode").addEventListener("click", async () => {
  try {
    const settings = await api(`/api/projects/${project()}/settings`);
    settings.hard_mode = document.getElementById("hard-mode").checked;
    await api(`/api/projects/${project()}/settings`, { method: "PUT", body: JSON.stringify(settings) });
    toast("Hard mode setting saved — it applies the next time you build.");
  } catch (e) {
    toast(e.message, "error");
  }
});

document.getElementById("save-elementfix").addEventListener("click", async () => {
  try {
    const settings = await api(`/api/projects/${project()}/settings`);
    settings.element_fix = document.getElementById("element-fix").checked;
    await api(`/api/projects/${project()}/settings`, { method: "PUT", body: JSON.stringify(settings) });
    toast("Elemental resistance fix saved — it applies the next time you build.");
  } catch (e) {
    toast(e.message, "error");
  }
});

/* ----------------------------------------------------------- build/patch */

function showResult(id, html, isError = false) {
  const el = document.getElementById(id);
  el.classList.remove("hidden");
  el.classList.toggle("error", isError);
  el.innerHTML = html;
}

function esc(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;");
}

document.getElementById("build-rom").addEventListener("click", async () => {
  try {
    overlay("Building your ROM… this can take a few minutes.");
    const result = await api(`/api/projects/${project()}/build`, { method: "POST" });
    showResult(
      "build-result",
      `<b>✅ ROM built!</b><br>Saved to: <span class="mono">${esc(result.output)}</span><br>` +
        `Open it in an emulator like melonDS to test your changes. Remember: don’t share this file.`
    );
    toast("ROM built successfully.");
  } catch (e) {
    showResult("build-result", `<b>❌ Build failed</b><br>${esc(e.message)}`, true);
    toast("Build failed — see details in the panel.", "error");
  } finally {
    overlay(null);
  }
});

document.getElementById("make-patch").addEventListener("click", async () => {
  const base = document.getElementById("base-rom").value.trim().replace(/^"|"$/g, "");
  try {
    overlay("Building the ROM and creating your patch… this can take a few minutes.");
    const m = await api(`/api/projects/${project()}/patch`, {
      method: "POST",
      body: JSON.stringify({ base_rom: base }),
    });
    const mb = (m.patchSize / 1048576).toFixed(1);
    showResult(
      "patch-result",
      `<b>🎉 Patch created and verified!</b><br>` +
        `Patch file: <span class="mono">${esc(m.patchFile)}</span> (${mb} MB)<br>` +
        `Patch CRC32: <span class="mono">${m.patchCrc32}</span><br>` +
        `Base ROM MD5 (tell players to check theirs matches): <span class="mono">${m.base.md5}</span><br><br>` +
        `This <code>.bps</code> file is what you upload/share. Players apply it to their own ` +
        `copy of the game with any BPS patcher. The patch was decoded back and byte-compared ` +
        `against your hack ROM, so it’s guaranteed to reproduce it exactly.`
    );
    toast("Patch created and self-verified. Ready to share!");
  } catch (e) {
    showResult("patch-result", `<b>❌ Patch failed</b><br>${esc(e.message)}`, true);
    toast("Patch creation failed — see details in the panel.", "error");
  } finally {
    overlay(null);
  }
});

/* ---------------------------------------------------------------- init */

setNavEnabled(false);
(function init() {
  const sel = document.getElementById("project-select");
  const last = localStorage.getItem("ffc-last-project");
  if (last && [...sel.options].some((o) => o.value === last)) sel.value = last;
  if (sel.value) {
    currentProject = sel.value;
    loadAll().catch((e) => toast(e.message, "error"));
  }
})();
