# Lab: direct Twitch redeems & random encounters

Working area for Chriz's experiments on top of Yuna's (tapahob) BG Radar Overlay. Lives on the
`lab` branch of the fork only - nothing under `lab/` is meant to go upstream.

- Plan: [plans/2026-10-04-direct-redeems-random-encounters.md](plans/2026-10-04-direct-redeems-random-encounters.md)
- Upstream: https://github.com/tapahob/BG2RadarOverlay (remote `upstream`)
- Fork: https://github.com/Chrizhermann/BG2RadarOverlay (remote `origin`). Pushes always go out as
  `Chrizhermann`, whichever gh account is active: `.git/config` resets the credential helpers for
  github.com and uses `gh auth token --user Chrizhermann` instead. gh's own helper only ever hands
  out the *active* account's token, so without this a push would fail (or, without the username
  pin, go out as the work account).
- `gh` calls for the fork or upstream (issues, PRs) run per command as the private account instead
  of switching the machine-wide active account, which other sessions rely on:
  `GH_TOKEN=$(gh auth token --user Chrizhermann) gh issue list -R tapahob/BG2RadarOverlay`

## Branches

| Branch | Purpose |
|---|---|
| `master` | Mirror of `upstream/master`. Never commit here; sync with `git pull upstream master`. |
| `lab` | This folder: plans, tools, notes. Rebased on `master` when upstream moves. |
| `feat/*` | One upstreamable change each, branched from `master`, offered to Yuna as a PR after an issue. |

## Build & test status (2026-10-04, this machine)

| Check | Command | Result |
|---|---|---|
| Relay tests (net8.0) | `dotnet test TwitchIntegration/Relay.Tests` | 86/86 passed |
| Extension receipt tests | `node TwitchIntegration/Extension/tests/pending-receipts.test.js` | 13/13 passed |
| Overlay build | `dotnet build BGOverlay.sln -c Debug` | **blocked**: `MSB3644`, .NET Framework 4.8 reference assemblies missing |

Machine setup:

1. Fixed 2026-10-04: the user-level `%APPDATA%\NuGet\NuGet.Config` had an empty
   `<packageSources>` (file dated 2026-02-12, cause unknown), so every restore failed with
   `NU1100`. nuget.org is registered again.
2. Still open, only needed to build Yuna's overlay (host option A or PRs into her C# code):
   `BGOverlay.csproj` is an old-style .NET Framework 4.8 project. It needs the .NET Framework 4.8
   Developer Pack (targeting pack) and a `packages.config` restore (NLog 5.0.1, SharpZipLib 1.3.3
   into `packages\`), which the dotnet CLI cannot do - that needs `nuget.exe` or Visual Studio
   Build Tools.

## Tools

`tools/cre_catalog.py` - dumps every CRE an install can spawn (override wins over BIFs) to CSV:
resref, name, level, XP value, max HP, hostility, script name (death variable), dialog.
Used to pick encounter creatures that actually exist in the install, and the prototype for the
overlay's creature search.

```
python lab/tools/cre_catalog.py "C:\Games\Baldur's Gate II Enhanced Edition modded" --out lab/out/eet-main-creatures.csv
```

Output goes to `lab/out/` (gitignored - it is install-specific).
