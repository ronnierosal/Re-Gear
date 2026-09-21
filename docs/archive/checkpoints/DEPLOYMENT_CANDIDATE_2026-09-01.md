> **Historical checkpoint.** Retained from source `9421c6f`; statements describe that dated session, not current availability.

# Current-main deployment candidate — 2026-09-01

## Status

**Locally verified D0/D1 candidate; not yet ready to stage for supervised D2.**
No Ally connection, deployment, service restart, or hardware mutation occurred
while preparing this record. The remaining blocker is a verified rollback
archive that matches the last observed installed Ally baseline.

## Candidate provenance

- Source commit: `84219fc8fd7e6e4eca9d86714a03474d94953836`
- Version: `0.2.0`
- Archive: `out/HandheldDockMode-0.2.0.zip`
- SHA-256: `A6883B493A51F1B0388AFE04E67B71CD504A0C6893860C3A5A5472A6EDC27C01`
- Embedded `build_info.json`: schema `1`, version `0.2.0`, revision
  `84219fc8fd7e6e4eca9d86714a03474d94953836`
- D1 layout: 153 entries below exactly one `HandheldDockMode/` root; required
  `plugin.json`, `package.json`, `main.py`, `dist/index.js`, backend API, and
  build metadata are present.

## Local verification

All passed on this exact source before archive inspection:

- `python scripts/check_architecture.py`
- `python -m unittest discover -s tests -v` — 671 passed, 5 skipped
- `python -m compileall -q backend tests scripts`
- `pnpm test:frontend` — 47 passed
- `pnpm typecheck`
- `pnpm build`
- `python scripts/check_plugin_package.py .`
- `python scripts/build_plugin.py`
- archive layout and embedded-build inspection

## Rollback status

The last *observed installed* Ally build is version `0.2.0`, revision
`e73d249db568` from the 2026-09-01 no-write capture. A matching local archive
is not available, so rollback to that installed baseline is **not verified**.

The pre-build local archive was retained without overwrite at
`out/rollback/HandheldDockMode-0.2.0-25802649bfdd5bad1a5a7e0f73a38fc311fb69b4.zip`:

- embedded revision: `25802649bfdd5bad1a5a7e0f73a38fc311fb69b4`
- SHA-256: `DF5BC520D9C595D2E6FAB36F6805D6291E366B3898BA9DF010B5FAF6AC359B44`

It is a preserved local fallback only, not evidence that it is installed or a
verified D2 rollback package. Do not substitute it silently for the missing
`e73d249` rollback artifact.

If a recovered validation-artifact directory is proposed as that rollback,
first require its embedded revision to match the captured public label:

```text
python scripts/verify_validation_artifact.py <recovered-artifact-directory> \
  --expected-revision-prefix e73d249db568
```

This is a bounded prefix comparison only. It does not prove the recovered
archive was installed, and it does not replace independent checksum review or
an explicit rollback decision.

Once both candidate and recovered rollback artifact directories are available,
check the pair before the supervised D2 checklist:

```text
python scripts/verify_d2_artifacts.py <candidate-artifact-directory> \
  <rollback-artifact-directory> \
  --rollback-revision-prefix e73d249db568
```

`verified_for_supervised_review` is artifact readiness only. It does not make
this record stageable until the maintainer confirms the D2 physical and
lifecycle preconditions.

After a supervised D2 run has created redacted before/after captures, retain a
local consistency check alongside the checklist record:

```text
python scripts/verify_d2_evidence_record.py <candidate-artifact-directory> \
  <rollback-artifact-directory> <before-capture.json> <after-capture.json> \
  --rollback-revision-prefix e73d249db568
```

This checks only the saved evidence record's privacy/schema, package labels,
boot continuity, and uptime ordering. It is not proof of any D2 human or live
hardware acceptance criterion.

## Supervised D2 checklist

1. Obtain or independently verify the rollback archive/provenance matching the
   current installed Ally baseline, or approve a different explicit rollback
   plan before installation.
2. With the maintainer/player present, confirm known-good internal display,
   controls, network, Steam, Decky, and SSH. Keep the current candidate, the
   verified rollback package, and player-visible recovery available locally.
3. Confirm the G1 is physically disconnected. Capture redacted before-state and
   boot/session evidence; no transition, sleep, or process action is allowed.
4. Install this one combined archive through Decky's native lifecycle only.
   Do not replace files beneath a running plugin.
5. Verify the QAM HDM build label, backend/frontend critical hashes, one plugin
   instance, expected RPC schema, and lease/resource baseline. Exercise native
   unload/reload and verify return to baseline.
6. Record redacted after-state. Only then consider D2a and a separately named,
   player-watched G1 attachment stage. Do not combine attachment with display,
   sleep, process, or physical-removal testing.

## Next safe task

Obtain the exact installed-baseline rollback archive or an explicit maintainer
rollback decision, then conduct D2 with the G1 disconnected. This candidate is
local verification evidence only; it does not validate any Ally ↔ G1 journey
stage.
