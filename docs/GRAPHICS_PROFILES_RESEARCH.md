# Automatic per-game graphics profiles — source research

Status: research for the first-adapter milestone (issue #374), gathered by the
cloud Claude session on 2026-09-22. This records what was consulted, what could
not be reached, and which claims are therefore **not** made. No third-party
implementation code was read, copied or adapted; everything below is
observation of behaviour, documentation and on-disk layout.

## What was consulted

| Source | What it is | License | What was taken |
| --- | --- | --- | --- |
| [SteamTinkerLaunch](https://github.com/sonic2kk/steamtinkerlaunch) — wiki page [Configuration Files](https://github.com/sonic2kk/steamtinkerlaunch/wiki/Configuration-Files) | Linux wrapper for the Steam client offering per-game tool configuration | GPL-3.0 | **Inspiration only, no code.** Confirms the prevailing convention of keying per-game state by Steam AppID: game configuration under `gamecfgs/id/<AppID>` inside `$HOME/.config/steamtinkerlaunch`, with a title-named symlink for humans. Re-Gear keys backups and provenance by AppID too, but by target path as well — see the limitation this project hit that AppID alone does not cover. The wiki documents **no** backup of a game's own configuration, so nothing there informed the backup design. |
| [stereolabs/zed-unreal-examples `DefaultGameUserSettings.ini`](https://raw.githubusercontent.com/stereolabs/zed-unreal-examples/master/UE4_Examples/Config/DefaultGameUserSettings.ini) | A published, real Unreal Engine 4 configuration file | MIT (repository) | **Schema shape only.** Evidence that the engine writes `[ScalabilityGroups]` with `sg.ResolutionQuality`, `sg.ViewDistanceQuality`, `sg.AntiAliasingQuality`, `sg.ShadowQuality`, `sg.PostProcessQuality`, `sg.TextureQuality`, `sg.EffectsQuality`, and `[/Script/Engine.GameUserSettings]` carrying a `Version` key (observed value `5`) alongside resolution and VSync keys. The fixture's contents were written for this repository, not copied; key and section names are facts about a format, not expression. |

Both sources are credited here and in the PR. Neither contributed code, tests
or text to this repository, so `THIRD_PARTY_NOTICES.md` needs no new entry; if
any implementation is later adapted from SteamTinkerLaunch, its GPL-3.0 terms
and a notice entry become mandatory first.

## What could not be reached, and what is therefore not claimed

This session's network egress proxy blocks `partner.steamgames.com`,
`help.steampowered.com` and `dev.epicgames.com`, and `api.github.com` returns
403 through it. Consequences, stated rather than papered over:

- **Steam Cloud ordering is undocumented here and remains an open gate.** No
  claim is made about when Steam syncs a game's configuration relative to
  launch and exit, or how it resolves a conflict when a file changed outside
  the game. Nothing in this milestone runs against a real Steam Cloud path, and
  filesystem atomicity is not evidence of cloud cooperation. This must be
  resolved from Valve's own documentation before any production integration.
- **Games rewriting settings on exit is handled structurally, not by
  documentation.** Re-Gear's answer does not depend on knowing which games do
  it: a write is only performed when the caller asserts the game is not
  running, and any later change by anyone — game or player — is detected as a
  conflict by digest before Re-Gear writes again.
- **No pinned upstream revision for SteamTinkerLaunch.** The commit SHA could
  not be fetched through the proxy, so the reference above is to the project
  and its wiki page as read on 2026-09-22, not to a pinned revision. A pinned
  revision is required before any reuse decision.
- **No shipped game's configuration has been verified.** The schema adapter is
  written against the Unreal `GameUserSettings.ini` layout evidenced above, but
  no real game's file was read. The fixtures are therefore an explicitly
  labelled **synthetic mechanism demonstration**, and real-game support remains
  unproven. Support level 2 (Managed) is reachable in fixtures only.

## Steam on-disk layout used

Public filesystem structure, not code: `steamapps/libraryfolders.vdf` for
additional library roots, `steamapps/appmanifest_<appid>.acf` for the install
directory, `steamapps/common/<installdir>/` for a native game, and
`steamapps/compatdata/<appid>/pfx/drive_c/users/steamuser/Documents/` for a
Proton game's documents directory.

Two lessons were taken from reading these files adversarially rather than
optimistically:

1. **A manifest can disagree with its own name.** `appmanifest_620.acf` whose
   body declares `"appid" "999999"` is contradictory evidence about which game
   is installed, and either reading would be a guess. Re-Gear refuses instead.
2. **The same AppID can appear in more than one library.** Two matching
   manifests are ambiguity, not a race to the first plausible path.

## Where this leaves the milestone

The mechanism is demonstrated end to end on fixtures; the game knowledge is
not. Advisor and Unknown are the honest support levels for any real player
today, and the code enforces that: without a registered schema whose version
matches and whose current values the adapter recognises, no write happens at
all.
