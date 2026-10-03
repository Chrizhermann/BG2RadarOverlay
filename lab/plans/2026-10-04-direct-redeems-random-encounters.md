# Direct Twitch redeems & random encounter tiers - design draft

- **Status:** draft for discussion (Chriz <-> Claude first, then Yuna via upstream issues)
- **Date:** 2026-10-04
- **Fork:** `Chrizhermann/BG2RadarOverlay`, based on upstream `tapahob/BG2RadarOverlay` @ `aee5f65`
- **Target game for the lab:** Chriz's EET install (EET v14, EEex v0.11.0-alpha + LuaJIT, SCS v35.21,
  EEex Remote Console installed)

## 0. Decisions so far

| Date | Decision (Chriz) |
|---|---|
| 2026-10-04 | We're in the **design phase**: plan and design everything (design + board) before building and testing. No rush to a first live test. |
| 2026-10-04 | Chriz's stream doesn't need the extension panel. Yuna's extension/token path stays available; a **local mode switch** picks direct redeems or the extension path - simple config on the streamer's PC that nothing from outside can flip. |
| 2026-10-04 | Phase 1 triggers: **native Channel Points redeems + Bits** (custom Power-ups / cheers). Donations (StreamElements tips, Streamer.bot) later. |
| 2026-10-04 | A **hold/stop control** for redeems is required. Redemptions arriving while offline: hold or refund - decided during design. |
| 2026-10-04 | **No spawns in cities** and in areas Chriz blocks. |
| 2026-10-04 | `lab` branch may be committed and pushed to the fork. No issue to Yuna until the wording is agreed. |

## 1. Goal

1. A viewer spawns an encounter in the streamer's game with **one native Twitch action** - a
   Channel Points reward or a cheer. No extension panel, no token balance, no allowlist.
2. **Random factor.** Encounters come in danger tiers (start: 1-10, tier 10 = something like a
   lich). Viewers either pick a danger band or gamble on a random tier. Later 40-60 encounters.
3. **Progression aware.** Party level gates what can spawn (v1); chapter / campaign phase later.
4. **Encounter sets outside the app:** JSON files with import/export, several sets, shareable
   (file or URL), still edited in a UI.
5. **Creature search** in the editor instead of typing ResRefs from memory.

Non-goals for v1: replacing Yuna's token/extension flow (it stays and keeps working), chat
commands, follow/sub triggers.

## 2. What exists upstream today (verified in code, 2026-10-04)

**Game side** (`EEexMod/M_BG2RDR.lua`, mailbox layout v4): the overlay finds a 0x88-byte mailbox
in the game heap by magic, writes ResRef + amount (max 20) + viewer message (max 95 chars) and sets
a flag. Lua polls ~10x/s from a per-frame menu tick (works while paused), clears the flag, then
calls `C:CreateCreature(resref)` once per creature - spawns at the screen centre. **No result goes
back:** the overlay can't tell whether anything spawned.

**Overlay** (`GameSpawnBridge.cs`, `TwitchIntegration/SpawnPack.cs`, `TwitchRelayClient.cs`):
queue of max 32 spawns fed into the mailbox one at a time. Packs = name + level band + cost in
tokens + fixed creature list, stored as one flat line in `config.cfg`. Level = protagonist's class
level read from memory. One WebSocket to the relay: party snapshot + pack list up every 2 s,
`summon` commands down.

**Relay** (`TwitchIntegration/Relay`, net8, multi-tenant, public HTTPS on 443): EventSub
*webhooks* for `channel.channel_points_custom_reward_redemption.add` and `.update` (app token,
scope `channel:read:redemptions`). Exactly one manually created reward - matched by title - credits
**summon tokens**; cancellations claw them back. Bits only via Extension Bits products (receipts),
also crediting tokens. Viewers spend tokens on packs in the panel -> relay -> overlay. No cooldowns,
no cheers, no reward management, no acknowledgement from the game.

**Extension:** video component polling the relay every 5 s; while in Local/Hosted Test only
allowlisted accounts see it, public use needs Twitch review.

**Gap vs. goal:** no path where a redemption itself spawns something; no randomness; packs live only
in `config.cfg`; no creature search - although `ResourceManager` + `CREReader` + TLK exist (note:
its CRE index only covers chitin.key/BIFs; CREs that exist only in `override/`, e.g. SCS's
`DW#LICH1`, are readable but not listed).

Findings worth reporting upstream:

1. **Presets die with every update.** `Configuration.loadConfig()` deletes `config.cfg` whenever
   the stored version differs from the assembly version (`Configuration.cs` ~L256-262), i.e. on
   every release - `SpawnPacks` and the Twitch settings go with it. Separate preset files fix it
   for our data; upstream should migrate the file instead of deleting it.
2. **Mod creatures can't be spawned.** ResRef validation allows only `A-Z 0-9 _`
   (`GameSpawnBridge.cs:318`, `SpawnPack.cs:357`). In Chriz's install that rejects 472 of 9,611
   creatures - every `#`/`!` mod prefix, including SCS's lich `DW#LICH1`. The charset needs
   widening (at least `#` and `!`), while still excluding quotes/brackets/spaces so a ResRef can
   never break out of a Lua/BCS string - imported sets are untrusted input.
3. Docs: upstream `CLAUDE.md` (section "Summon tokens") still says a refunded redemption is not
   clawed back - the relay handles `.update` -> `canceled` since the hardening merge
   (`Program.cs` ~L602-621, `RedemptionRefundTests`).

## 3. Proposed architecture

```
Twitch EventSub ─┐
Local trigger ───┼─> Trigger source ─> EncounterDirector ─> Game bridge ─> Lua in the game
Relay command ───┤        ^                 |    ^                            |
Test button ─────┘        |                 |    └── EncounterSet / ChannelProfile
                          └── fulfill / refund <──── result + game context ───┘
```

The director doesn't care where it runs or which bridge carries the spawn - see 3.1 for the two
candidate hosts.

1. **EncounterDirector** (transport-agnostic, unit-testable): takes a trigger request
   `{source, viewer, tier range, roll mode, message, redemptionId?}`, gates it (game ready? level
   cap? cooldown? queue?), rolls tier -> variant -> counts, hands a spawn plan to the bridge, waits
   for the result and reports `spawned | refused(reason) | failed(reason)` back to the trigger.
2. **Trigger sources**, all producing the same request:
   - **Native EventSub** (phase 1): the encounter system itself talks to Twitch - no server, no
     extra tool. Channel Points + Bits.
   - **Local trigger API** (later): `POST` on `127.0.0.1` with a shared secret. Streamer.bot,
     SAMMI, Mix It Up and Firebot can all fire HTTP requests - the way in for donations
     (StreamElements tips) and anything else Chriz's Streamer.bot setup (local API on
     `127.0.0.1:8080`) already sees.
   - **Relay route** (optional, Yuna's extension/token path): kept available behind the mode
     switch; the relay forwards summons as today.
   - **Manual**: "Test roll" button / hotkey in the control panel - the lab's main test tool.
3. **Game bridge** with one contract: `context()` (screen, area, chapter, party levels, dialogue /
   cutscene state) and `spawn(plan) -> result` (request id, spawned count or error). Two possible
   carriers - Yuna's mailbox (needs a v5 with results + context) or Chriz's EEex Remote Console
   (has request ids and JSON results already).
4. **Encounter sets + channel profile** as JSON files (section 6).
5. **Creature catalog/search** backed by KEY + override + TLK (section 7).
6. **Control panel:** hold / stop / resume, connection + game status, queue, sets, creature search.

The Twitch route is decided (section 0): native redeems first. Via Yuna's relay it would need a
public relay, broadcaster -> overlay routing (missing today), the manage scope, rewards created by
the relay's client id and an ack path - not worth it for direct redeems.

### 3.1 Host: inside Yuna's overlay, or a standalone service? (open - decision 0)

What the overlay does for spawning today is three things: write into the game (mailbox), edit packs
(WPF tab), talk to the relay. None of them requires the radar overlay itself, so the encounter
system can live inside it **or** next to it.

| | A: inside Yuna's overlay (C#) | B: standalone service (Rust) on the EEex Remote Console |
|---|---|---|
| Toolchain | core is an old-style .NET Framework 4.8 project (`packages.config`); needs the 4.8 Developer Pack + NuGet CLI on this machine; UI project is net8 | Rust (cargo 1.97 installed), one binary, `cargo test` |
| Game bridge | mailbox v4 is fire-and-forget -> needs a v5 layout change in Yuna's Lua + C# | Remote Console protocol v1.1 already has request ids, JSON results, ready handshake, 22 in-game smoke tests; commands wait during forced dialogue (a natural hold) |
| Tests | none for the overlay side today | unit tests for rolls, fakes for Twitch and the console, in-game smoke via the console |
| Config / presets | flat `config.cfg`, wiped on each update (bug) | own files; secrets in the Windows credential store |
| Twitch client | core has no JSON library; would go into the net8 project - Yuna's call | EventSub + Helix in Rust (crates to be verified) |
| UI | existing WPF pack editor can be extended | new, small local web panel on 127.0.0.1 - also usable as an OBS browser dock |
| Collaboration | everything lands upstream, each change needs Yuna's review | set format, fixes and ideas go upstream; her overlay/relay can later trigger the director through an adapter |
| Risk | slow coordination on a legacy core | second tool next to the overlay; the console runs arbitrary Lua, so the director only calls a small fixed Lua module, never viewer text as code |

**Claude's recommendation: B.** The bridge Chriz already owns does what mailbox v5 would have to
add, Rust is testable and fits Chriz's direction, and nothing about spawning needs the radar
overlay. Yuna's work stays useful: the radar overlay is unaffected, her extension path stays
available (mode switch), and bug fixes plus the set format go upstream. With B, the .NET 4.8
Developer Pack is only needed for PRs into her C# code.

What speaks for A: one tool for streamers who already run the overlay, and the feature reaching
Yuna's users without a second install.

## 4. Random encounter model

### Data model (encounter set)

- **Tier** 1..N: label, optional `minPartyLevel`, weighted **variants**.
- **Variant:** name, weight, flavour text, creatures `{resref, min, max}`, optional gates
  (`minPartyLevel`, `maxPartyLevel`, later `chapters` / campaign phase), spawn placement.

### Trigger -> roll

1. Request carries a tier range `[a, b]` and a roll mode: `uniform`, or `weighted` with a falloff
   (P(t) ~ falloff^(t-a), so high tiers are rare - that's the "gamble").
2. Clamp `b` to the **level cap** (party level -> max tier). If `a` is above the cap: policy
   `downgrade` (roll at the cap) or `refund`.
3. Roll tier, then variant (by weight, gates applied), then counts (uniform min..max, total per
   request capped by the bridge limits).
4. Announce in game: `[Twitch] <viewer>: Tier 7 "Regenerators" - 2x Troll` (+ viewer message).
5. Every roll uses a logged seed -> reproducible bugs, deterministic unit tests.

### Reward shapes (channel profile, examples)

| Reward | Roll | Cost (pts, placeholder) |
|---|---|---|
| Random Encounter | weighted, tiers 1-10, falloff 0.6 | 1000 |
| Encounter: Easy | uniform 1-3 | 300 |
| Encounter: Hard | uniform 4-6 | 1500 |
| Encounter: Deadly | uniform 7-9 | 5000 |
| Encounter: Legendary | tier 10 | 20000 |

**Bits** - two native options, both via EventSub `channel.bits.use` (scope `bits:read`):

- **Custom Power-ups** (generally available since 2026-05-19) are exactly the "Bits redeem": the
  streamer defines them in the dashboard and prices them in Bits, streamer keeps 100%, optional
  viewer input. Limits: live only, and the API is read-only - no create, pause, fulfil or
  refund. So a failed spawn can't be refunded; the request has to wait until the game
  is ready.
- **Cheers:** amount thresholds -> encounter (e.g. 100 / 500 / 1000 / 2500 Bits).

Policy (section 12): Bits may trigger stream content - Twitch's own example is changing a game
character's speed - but must not be a bet/wager or buy something of monetary value. A random spawn
with no prize for the viewer is most likely fine, but **a fixed mapping (one Power-up = one
known encounter) is the safe design**. Randomness therefore belongs to Channel Points first.

### Level / chapter scaling

- **v1:** level caps table (party level -> max tier) plus per-variant gates. Party level = average
  of the party read from memory (today only the protagonist's level is used).
- **v2:** campaign bands x tiers (e.g. BG1 early / BG1 late / SoD / SoA / ToB x 10 tiers = 50
  encounters - matches the "40, 50, 60 encounters" idea). Chapter comes from the bridge context
  (`CHAPTER` global via EEex). EET's chapter numbering across BG1/SoD/BG2 still has to be verified
  in game before relying on it.

### Draft starter ladder (resrefs verified in the main EET install, 2026-10-04)

Checked with `lab/tools/cre_catalog.py`: all hostile (EA 255), no dialog. Counts are first guesses
for playtesting, not balance.

| Tier | Label | Variants |
|---|---|---|
| 1 | Nuisance | `GIBBER01` Gibberling x3-5 / `XVART01` Xvart x4-6 / `KOBARC01` Kobold archer x3-4 |
| 2 | Skirmish | `GNOLL01` Gnoll x2-3 / `SKELET02` Skeleton x3-4 |
| 3 | Pack | `WOLF01` Wolf x3-4 / `GHOUL01` Ghoul x2 (paralysis) |
| 4 | Brutes | `OGRE03` Ogre x2 |
| 5 | Regenerators | `TROLL03` Troll x2 (fire/acid) |
| 6 | Ambush | `ANKHEG01` Ankheg x2 / `WYVERN01` Wyvern x2 (poison) |
| 7 | Mind-bender | `UMBHUL01` Umber Hulk x2 / `GOLEMF` Flesh Golem x2 |
| 8 | Stone | `BASGRT01` Greater Basilisk (petrification) / `DSTONE1` Stone Golem |
| 9 | Horror | `BEHOLD01` Beholder / `MINDFL01` Mind Flayer x2 / `UMBHUL02` Umber Hulk Elder |
| 10 | Legendary | `DW#LICH1` Lich (SCS, L25) / `DRAGRED` Red Dragon |

Findings that shaped this: vanilla `LICH01` in this install is an empty dummy (L1, 1 HP, no name),
the usable lich is SCS's `DW#LICH1` - a set must declare which mods it needs, and Yuna's overlay
rejects its `#` today (finding 2 in section 2), so tier 10 depends on that fix. Several BG2
creatures carry script names (death variables) quest scripts may check; generic ones were preferred.

### Where and when spawns may happen

- **No-spawn zones.** Every area file carries type flags (ARE header `0x48`, bit 3 = City). Checked
  in the main install: Athkatla's districts, Trademeet and BG1's Baldur's Gate are flagged City,
  Irenicus' dungeon is Dungeon, Umar Hills is Forest. Proposal: City areas blocked by default, plus
  Chriz's own block list and an allow list for exceptions (the Graveyard District is flagged City
  too). Interiors (neither Outdoor nor Dungeon: shops, taverns, homes) blocked by default as well.
- **Game state:** no spawns in dialogue, cutscenes, on the world map or in the main menu. The
  request waits a configurable time, then falls back to the offline/stop policy.
- **Controls** (control panel + hotkey; a Streamer.bot deck button can call the same thing):
  - **Hold** - redemptions keep arriving but queue; nothing spawns until released.
  - **Pause** - our Channel Points rewards are paused on Twitch, nobody can redeem. Power-ups can't
    be paused through the API, so they queue.
  - **Stop** - clear the queue: Channel Points get refunded. Bits can't be refunded through the API
    at all, so Bits requests stay queued for the next safe moment (or get announced and dropped -
    decision).
- **Redemptions while offline** (Channel Points work offline): hold for the next stream, or refund
  automatically - open decision, Chriz leans towards deciding by what's more fun.

### Safety (hardcore, no-reload runs)

- Tiers 8-10 contain run-enders (petrification, disintegration, lich). Level caps are on by default.
- Native reward cooldowns + per-stream / per-user limits, plus our own queue limit and a cap on
  living spawned creatures.
- Spawn XP: killing a tier-9 Beholder gives 14,000 XP. Decide: keep / scale / none (section 10).

## 5. Twitch side - native EventSub source

Facts checked against the official docs on 2026-10-04 (sources in section 12).

- **Auth:** Device Code Grant Flow with a *public* client - Twitch's recommendation for desktop
  apps. No secret ships with the app; the streamer approves once at twitch.tv/activate. Scopes
  `channel:manage:redemptions` + `bits:read`. Refresh tokens are single-use and expire after 30
  days (idle), so after a month without streaming the streamer logs in again. Validate the token
  at startup and hourly; store the refresh token encrypted (DPAPI), not in `config.cfg`.
- **Connection:** one WebSocket to `wss://eventsub.wss.twitch.tv/ws`. Subscribe within 10 s of
  the welcome message, reconnect when keepalives stop, follow `session_reconnect` within 30 s.
  Delivery is at-least-once -> dedupe on `message_id`. Events during a real disconnect are **not
  replayed**: Channel Points can be recovered via `GET .../redemptions?status=UNFULFILLED`, Bits
  cannot - so the connection state must be visible in the UI.
- **Subscriptions** (condition `broadcaster_user_id`; user-authorized ones cost nothing):
  `channel.channel_points_custom_reward_redemption.add` v1,
  `channel.bits.use` v1 (`type` = `cheer` / `power_up` / `custom_power_up`; excludes Extension
  Bits), and `channel.custom_power_up_redemption.add` v1 if a Power-up's viewer input is needed.
- **Rewards:** created by the app from the channel profile - max 50 per channel, unique title
  of max 45 characters, cooldown at least 1 s, optional per-stream / per-user limits;
  Affiliate/Partner only. Only the client id that created a reward may update it or its
  redemptions, so hand-made rewards could be read but never refunded.
- **Lifecycle:** `should_redemptions_skip_request_queue = false`, because only `UNFULFILLED`
  redemptions can still change. Event -> director -> bridge result -> `FULFILLED` on spawn,
  `CANCELED` (= refund) on refusal or failure.
- **Pause rather than refund:** Channel Points can be redeemed while offline. The app pauses
  its rewards whenever the game isn't ready and on exit, unpauses when it is. After a crash it
  finds leftovers via the `UNFULFILLED` query at startup and refunds them.
- **Code location:** depends on 3.1. A: the overlay core is .NET Framework 4.8 with no JSON
  library, WPFFrontend is net8.0-windows (System.Text.Json built in) - Yuna's call. B: Rust.
- **Housekeeping:** legacy PubSub was shut down on 2025-04-14; EventSub is the only live path.

## 6. Encounter sets & channel profile (presets)

- **Encounter set** = content (tiers, variants, creatures). Shareable, game/mod specific.
- **Channel profile** = streamer config (rewards, costs, cooldowns, cheer thresholds, level caps,
  over-cap policy, active set). Personal.
- Both JSON with `schemaVersion`, kept in the app's own data folder (never in Yuna's `config.cfg`,
  which is wiped on updates). Import from file or URL (e.g. raw GitHub), export, several sets, one
  active.
- On load: validate every ResRef against the install's creature catalog; mark missing ones (a set
  built for SCS lists `DW#LICH1`, which a non-SCS install doesn't have).
- Existing `SpawnPacks` stay untouched for the token/panel flow; optional one-click export to a set.
- Sharing: a curated sets folder or repo (per game + mod list) that Chriz and Yuna grow over time.

## 7. Creature search

- Index = chitin.key CRE entries **plus** `override/*.cre` (mod-added creatures only live there).
- Columns: name (TLK), ResRef, level, XP value, max HP, hostile, script name, dialog.
- Filters: hostile only, hide creatures with dialog/script name (quest-risk), sort by XP/level.
- Picking a result adds it to the variant being edited. Prototype: `lab/tools/cre_catalog.py`
  (9,611 creatures in the main install, ~2 s).
- Material is not the bottleneck: ~1,600 hostile, dialog-free, XP-giving CREs (~750 distinct
  names) spread over all level bands. But the same filter also returns story bosses (Abazigal,
  Aec'Letec, ...), so the search has to flag likely-unique creatures and curation stays manual.

## 8. Lab setup

- **Repo:** fork cloned to `C:\src\private\BG2RadarOverlay`, `origin` = fork (pushes as
  Chrizhermann), `upstream` = Yuna. Branch model in `lab/README.md`.
- **Build machine:** relay + extension tests green; nuget.org restored as package source
  (2026-10-04). Building Yuna's overlay still needs the .NET Framework 4.8 Developer Pack + NuGet CLI
  - only required for option A or PRs into her C# code. Rust toolchain present (cargo 1.97).
- **Game:** a dedicated copy of the EET install for testing (the main install stays the stream
  install), EEex + EEex Remote Console (+ Yuna's spawn bridge for option A). Test saves at roughly
  party level 1, 8, 15, plus one in a City area and one in an interior for the no-spawn rules.
- **In-game assertions:** EEex Remote Console as harness - after a test roll, list the area's
  creatures and check ResRefs/counts. That gives an end-to-end smoke test without Twitch.
- **Twitch without real points:** Twitch CLI (v1.1.24) - `twitch event websocket start-server`
  is a mock EventSub WebSocket, and `twitch event trigger ... -T websocket` fires reward
  redemptions (`-i` reward id, `--cost`) and cheers; `twitch mock-api` covers custom rewards and
  redemption status. It can't trigger `channel.bits.use` or custom Power-up events - those need
  hand-built payloads in our own tests. Both CLI servers and Streamer.bot's local API default to
  port 8080 -> move the CLI with `-p`.
- **Live:** app-created Channel Points rewards at cost 1, paused outside tests; custom Power-ups
  can be tested on the own channel for 0 Bits.

## 9. Phases

### Design phase (now)

| # | Deliverable |
|---|---|
| D1 | Host decision (3.1) |
| D2 | Formats: encounter set + channel profile schema; the starter ladder as a real set file |
| D3 | Rules: roll algorithm, level caps, no-spawn zones, hold / pause / stop, offline policy, XP, Bits |
| D4 | Interfaces: trigger request, game-bridge contract (context / spawn / result), Twitch reward lifecycle, mode switch |
| D5 | Control panel UX: hold / pause / stop, status, queue, sets, creature search |
| D6 | Test strategy: unit tests, Twitch mocks, in-game smoke tests via the Remote Console |
| D7 | Board with the work packages; wording of the issue for Yuna |

### Build phase (after the design is signed off)

| # | Deliverable | Upstream? |
|---|---|---|
| B0 | Bugfix PR: ResRef charset (`#`/`!`), so SCS creatures spawn | yes - first, smallest PR (needs the .NET 4.8 Developer Pack) |
| B1 | Director core: sets, rolls, rules, unit tests, test-roll trigger | A: yes / B: own repo |
| B2 | Game bridge + context + placement modes + in-game smoke tests | A: mailbox v5, needs Yuna's OK / B: small Lua executor on the Remote Console |
| B3 | Native EventSub: device-code login, reward provisioning, redemption lifecycle, Bits / Power-ups, pause | A: yes / B: own repo |
| B4 | Control panel, creature search, set validation | A: yes / B: own repo |
| B5 | Campaign bands (chapter), 40-60 encounters, shared sets; local trigger API for donations; optional adapter for Yuna's relay | partly |

## 10. Open decisions (Chriz)

0. **Host:** inside Yuna's overlay (A) or standalone Rust on the EEex Remote Console (B,
   recommended)? See 3.1.
1. **Board:** where should it live (GitHub Project, a markdown board in `lab/`, ...)?
2. **Tier model:** absolute tiers + level caps now, campaign bands later (recommended) - or bands
   from the start?
3. **Over the cap:** downgrade to the highest allowed tier, or refund?
4. **Run-enders:** allow tier 10 at all in a no-reload run, and from which party level?
5. **XP from spawns:** keep / scale down / none?
6. **Bits:** custom Power-ups with a fixed, announced encounter each (recommended, policy-safe),
   cheers by amount, or both? And may Bits pick a random encounter within a band - most likely
   allowed (no prize for the viewer), but not explicitly covered by Twitch's wording.
7. **Where shared sets live:** folder in the fork, or a separate repo?
8. **Offline redemptions:** hold until the next stream, or refund automatically?
9. **Stop with Bits in the queue:** keep them for the next safe moment, or announce and drop?
10. **No-spawn defaults:** City areas and interiors blocked by default - OK?

## 11. Upstream collaboration (Yuna agreed to issues + fork PRs)

Nothing is posted to Yuna until Chriz and Claude have agreed on the wording (decision 2026-10-04).
Drafts stay local in `lab/issues/` and are not pushed. Candidate issues for `tapahob/BG2RadarOverlay`:

1. Direct redeems + random encounter tiers - the umbrella proposal; content depends on decision 0.
2. Bug: ResRef validation rejects `#`/`!` mod prefixes (SCS creatures unspawnable) - small,
   self-contained first PR.
3. Bug: `config.cfg` (incl. packs + Twitch settings) is deleted on every version update.
4. Encounter sets as JSON (import/export) - shareable format, useful whichever host we pick.
5. Spawn bridge v5 (only for option A): request ids, results, game context, placement modes.
6. Creature search in the pack editor (KEY + override index).
7. Docs: `CLAUDE.md` refund paragraph is stale.

## 12. Twitch platform facts (sources)

Checked 2026-10-04. "Inferred" = our reading, not stated by Twitch.

| Topic | Fact | Source |
|---|---|---|
| EventSub WebSocket | welcome -> subscribe within 10 s (else close 4003); keepalive 10-600 s; `session_reconnect` within 30 s, subscriptions carry over; no replay after a real disconnect; at-least-once delivery | https://dev.twitch.tv/docs/eventsub/handling-websocket-events/ |
| Limits | per client id + user: 3 connections, 300 subscriptions each, `max_total_cost` 10; user-authorized subscriptions cost 0; since 2026-04-17 a duplicate returns 409 with the existing id | https://dev.twitch.tv/docs/eventsub/manage-subscriptions/ |
| Token | WebSocket needs a user access token; validate at startup and hourly | https://dev.twitch.tv/docs/authentication/validate-tokens/ |
| Device code flow | public client, no secret; refresh tokens single-use, 30-day expiry (docs say "inactive" in one place, "after generation" in another) | https://dev.twitch.tv/docs/authentication/getting-tokens-oauth/ · https://dev.twitch.tv/docs/authentication/refresh-tokens/ |
| Subscription types | redemption `.add`/`.update` v1 (`channel:read:redemptions` or `channel:manage:redemptions`); `channel.cheer` v1 and `channel.bits.use` v1 (`bits:read`; types cheer / power_up / custom_power_up, no Extension Bits; Combos removed 2026-04-02); `channel.custom_power_up_redemption.add` v1 (GA 2026-05-19) | https://dev.twitch.tv/docs/eventsub/eventsub-subscription-types/ · https://dev.twitch.tv/docs/change-log/ |
| Custom Power-ups | streamer-defined, priced in Bits, streamer keeps 100%, live only, testable for 0 Bits on own channel; API read-only (no create/pause/refund) | https://help.twitch.tv/s/article/power-ups · https://discuss.dev.twitch.com/t/introducing-api-and-eventsub-support-for-custom-power-ups/64708 |
| Custom rewards | max 50/channel; title unique, max 45 chars; cooldown min 1 s; only the creating client id may manage reward + redemptions; status change only from `UNFULFILLED`, `CANCELED` refunds; max 50 ids per call; 403 for non-Affiliates | https://dev.twitch.tv/docs/api/reference/#create-custom-rewards · https://dev.twitch.tv/docs/api/reference/#update-redemption-status |
| Channel Points | redeemable while offline; gambling-like redemptions not allowed | https://help.twitch.tv/s/article/channel-points-guide · https://legal.twitch.com/en/legal/channel-points-acceptable-use-policy/ |
| Bits policy | triggering content is a permitted use (example: changing a game character's speed); not a bet/wager, not for goods/services of monetary value. Random spawn without prize: most likely fine (inferred); "loot box" framing risky; fixed mapping safest. Bits AUP updated 2026-05-04 | https://legal.twitch.com/en/legal/bits-acceptable-use/ · https://legal.twitch.com/en/legal/monetized-streamer-agreement/ |
| Extensions | Local/Hosted Test: allowlisted accounts only; public use needs review; Extension guidelines 6.2.3-6.2.6 ban gambling, chance-based loot boxes, sweepstakes, wagering | https://dev.twitch.tv/docs/extensions/life-cycle/ · https://dev.twitch.tv/docs/extensions/guidelines-and-policies/ |
| Rate limits | Helix token bucket per client id + user per minute, 429 + `Ratelimit-*` headers (800 appears only as an example) | https://dev.twitch.tv/docs/api/guide/#twitch-rate-limits |
| Twitch CLI | v1.1.24: WebSocket mock + triggers for redemptions and cheers; no `channel.bits.use` / Power-up triggers; `mock-api` has custom rewards + redemptions | https://dev.twitch.tv/docs/cli/websocket-event-command/ · https://github.com/twitchdev/twitch-cli/blob/main/docs/event.md |
| Streamer.bot | triggers Reward Redemption, Cheer, Power Up Redemption (custom Power-ups since v1.0.7, 2026-08-06); can Fetch URL, run programs, execute C# | https://docs.streamer.bot/api/sub-actions/core · https://docs.streamer.bot/changelogs/v1.0.7 |
| PubSub | shut down 2025-04-14 | https://dev.twitch.tv/docs/change-log/ |
