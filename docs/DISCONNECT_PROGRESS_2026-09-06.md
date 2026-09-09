# Disconnect resource-release progress, September 6, 2026

This public summary records the hardware driver's dated return-run evidence.
It does not replace deployment contracts or establish support for other devices.

> **Superseded for the resource-release conclusion.** This record is accurate for
> installed 0.3.54 and is retained as history. Resource release later succeeded on
> installed 0.3.58; see
> [disconnect progress, 2026-09-08](DISCONNECT_PROGRESS_2026-09-08.md). The
> shutdown-before-disconnect policy below is unchanged.

## Recorded hardware run

- Configuration: ASUS ROG Ally X with GPD G1; installed Re-Gear **0.3.54 / e765fad4b928**.
- Cable remained attached; no new plugin, filter, or service was installed during the run.
- The player observed Steam on TV, then used Prepare to disconnect to return to the handheld and confirmed normal display, controls, and audio.
- After return, Steam retained external render descriptors and mappings with resident allocations; Mesa OpenGL was present.
- A privileged read-only follow-up also found Gamescope retained external descriptors and resident allocations; Vulkan/device-selection libraries were present.
- WirePlumber retained an audio-control descriptor although playback endpoints were closed.
- GPU engine activity was unknown. Retained allocations do not prove active rendering. The allocation follow-up inspected only these three processes; it was not a complete clearance scan. There was no live-phase capture during TV output.

**Result:** visible return succeeded; resource release did not. No physical-unplug clearance was granted.

## Changed experiment and review boundary

The next hypothesis is that internal GPU selection must cover Steam's OpenGL use as well as Vulkan. The extension is packaged in the staged **0.3.56** candidate, [draft PR #82](https://github.com/ronnierosal/Re-Gear/pull/82), combining the graphics trial #53, allocation diagnostics #57, and return-control correction #62. It is not installed or hardware validated. The separate device-filter series is excluded. Selection itself does not prove that clients cannot reopen the external GPU.

[Issue #51](https://github.com/ronnierosal/Re-Gear/issues/51) owns the experiment and its observed outcome. [Issue #52](https://github.com/ronnierosal/Re-Gear/issues/52) owns remaining audio release and recovery. Local recovery and preparation tests are prerequisites, not proof of a usable resource-release session. Software removal and eventual live-disconnect validation remain unfinished.

The return-button state mismatch was fixed locally after the observed confusing control flow; that local patch is not evidence of installed behavior. Sleep, shutdown, delayed detection, and startup controller symptoms remain separately tracked rather than assigned a speculative common cause.

Follow the existing [deployment rules](DEPLOYMENT_VALIDATION.md), [safety invariants](SAFETY_INVARIANTS.md), and [reviewed diagnostics](DIAGNOSTICS.md). Under the current tested policy, fully shut down before disconnecting the eGPU.

## Publication review checkpoint

The maintainer has prioritized GitHub review, issue tracking, notes, and Wiki publication. Hardware installation and experiments are paused pending a separate supervised continuation.

- Reviewed 26 open draft G1/audio PRs in the #53–#82 range. Twenty-five have successful foundation checks; #62 fails committed frontend-output verification because `dist/index.js.map` changes during the CI build. See [the failed run](https://github.com/ronnierosal/Re-Gear/actions/runs/34076074185) and [issue #59](https://github.com/ronnierosal/Re-Gear/issues/59). Green checks against stacked bases do not establish readiness to merge into main.
- [Issue #55](https://github.com/ronnierosal/Re-Gear/issues/55) maps the published filter/recovery series through #81. Publication is complete; code review and integration remain open. No missing publication slice was established by this audit.
- The staged candidate source is `cfe7f2361005029b293cd973770ac8a4bbc62af8`; SHA-256 is `af56a3ec3dded4ac1cfd20bbc1afcc017702744fddeab83eec7108eb9e3d1734`. Independent local review verified archive CRC, embedded revision/version, architecture, and 40 focused graphics-trial and allocation tests. Candidate #82 CI is green. The earlier recorded full matrix ran 1,101 backend tests (nine skipped) and passed 199 frontend tests; that full matrix was not repeated for this documentation review.
- Remaining work has existing owners: experiment #51, audio activation/recovery #52, software removal and reconnect #54, review/integration #55, return controls #59, and conditional filtered launch #69. Keep these issues open; publication and tests do not establish hardware completion.

This checkpoint covers publication/dependency metadata, CI results, candidate integrity, and focused trial checks. It is not an exhaustive correctness or security review of all experimental filter code. No merge, deployment, service change, or hardware transition was performed.
