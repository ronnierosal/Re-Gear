# Source inventory and evidence boundaries

## Immutable baselines

| Project | Publisher | Revision | Revision date | Use |
|---|---|---|---|---|
| [Panel de Control](https://github.com/Hooandee/panel-de-control/tree/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc) | Hooandee and contributors | `c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc` | September 9, 2026, 13:53:09 +02:00 | Upstream implementation and test reference; package metadata says 0.45.0 |
| [Re-Gear](https://github.com/ronnierosal/Re-Gear/tree/c09df57fe03a8d89c69afb0c8d9fb1664d14c741) | Ronnie Rosal and contributors | `c09df57fe03a8d89c69afb0c8d9fb1664d14c741` | September 9, 2026, 17:06:13 -07:00 | Fresh remote-main comparison baseline |

Access/review date: September 9, 2026, America/Los_Angeles; September 10 UTC.
Commit dates identify snapshots, not installation dates or hardware-test dates.

The upstream source was read from a no-checkout clone outside the Re-Gear
worktrees. Git object reads did not execute the upstream application, scripts,
build hooks, tests, dependency installation, or agent instructions. No upstream
source/asset is vendored by these notes. The source review is not a complete
security audit or license-compliance audit of either project's entire dependency
graph.

## Evidence index

[ENGINEERING.md](ENGINEERING.md) places immutable source links and line ranges
beside each finding. [ATTRIBUTION.md](ATTRIBUTION.md) links the exact declarations
and licensing references. [SOURCE_MANIFEST.json](SOURCE_MANIFEST.json) records
the byte count, SHA-256, line count, revision and URL for each distinct repository
file cited in those notes. Hashes establish which bytes the notes reference;
they do not establish safety, authorship, or correctness.

The manifest is a reference-file inventory, not a claim that every line in each
listed file was reviewed. It excludes uncited material encountered while browsing
the source tree. Test assertions count as inspected only where stated in the
engineering note; a discovered filename or test name is not a passing test result.

| Area | Production paths examined | Test evidence used | Practical limit |
|---|---|---|---|
| Battery | Charge-limit adapters, main RPC, reconciliation, shutdown invalidation | Requested versus observed limit and failed-write tests | Fake backend; actual provider/firmware behavior untested |
| Power/profiles | GPU-load controller, profile persistence, scope selection, UI floor | Threshold and inheritance assertions | No FPS/power benchmark; no eGPU generalization |
| Telemetry/lifecycle | Sampler, bounded store, local-learning toggle, suspend/AC logic | Missing metrics and delayed/stale suspend evidence | No measured collection cost or resume proof |
| HUD | Ownership journal, conflict/restore paths, worker ordering | Existing config/takeover and coordinator cases | No actual MangoHud instance or ZIP exercised |
| Customization | Module state, layout migration, provider composition | Pure module/layout tests | Does not establish native controller operation |
| Native UI | Owner-document focus and visibility/navigation lifecycle | Mocked QAM/document and existing Re-Gear focus cases | Steam/Decky/D-pad device validation remains |
| Launch options | Token parse/serialize, identity, autosave, native setter | Parser corpus and mocked save behavior | No Steam settings changed; counterexample is static |
| Display | Preview binding, timeout, HDR setter | Scope/game preview tests and HDR command tests | No physical output/HDR readback |
| Audio | Route classifier, PipeWire session selection, routing journal | Failed/no-op restart/backoff cases | No audio playback, loudness, or latency measurement |
| Controllers | Capability checks, reset/default/merge/load sequence | Ordinary-edit reset assertion and production control flow | Fake does not model existing-profile loss; no remap executed |
| Fans | Missing-sensor path, serialized ownership/release | Blocked tick versus release assertion | No thermal safety or crash handback proof |
| Download mode | Dimming helpers and documented behavior | No end-to-end download test used | Full lifecycle and energy benefit remain research |
| Delivery/licensing | License declarations, notices, CI, release/build recipe, Re-Gear package list | Static file-list/declaration comparison | No release binary/dependency audit or legal certification |

## Primary external references

These sources establish general interfaces or legal terms. Their applicability
to an installed version or particular device must be checked when implementing.

1. Free Software Foundation, **GNU General Public License, version 3**, June 29,
   2007; [full text hosted by the Open Source Initiative](https://opensource.org/license/gpl-3.0).
   Used for notice, modification, source-delivery, version-choice and applicable
   Installation Information requirements.
2. Free Software Foundation, **How to Use GNU Licenses for Your Own Software**,
   [official guidance](https://www.gnu.org/licenses/gpl-howto.en.html).
   Used for preserving copied-code copyright notices. Official indexed content
   was available; direct page retrieval timed out during this review.
3. US Copyright Office, **Computer Programs**,
   [registration guidance](https://www.copyright.gov/register/tx-programs.html).
   Used for the distinction between protected expression and program ideas,
   logic, algorithms and methods; not a determination about a specific adaptation.
4. flightlessmango and MangoHud contributors, **MangoHud configuration**,
   [upstream README](https://github.com/flightlessmango/MangoHud#hud-configuration).
   Used for global/application configuration and environment-override concepts.
   Installed MangoHud behavior/version was not checked.
5. PipeWire contributors, **Filter-Chain**,
   [official module documentation](https://docs.pipewire.org/page_module_filter_chain.html).
   Used for the documented audio-processing mechanism; no device/preset approval implied.
6. Linux kernel contributors, **power_supply sysfs ABI**,
   [upstream ABI documentation](https://github.com/torvalds/linux/blob/master/Documentation/ABI/testing/sysfs-class-power).
   Reference for charge-control attributes. Availability and semantics on the
   actual target firmware/kernel require independent observation.
7. Free Software Foundation, **Frequently Asked Questions about the GNU Licenses**,
   [official FAQ](https://www.gnu.org/licenses/gpl-faq.en.html).
   Used for version compatibility and rights-holder control of alternative licensing.
   Official indexed content was available; direct retrieval timed out.

## Material disagreements and open questions

- Upstream README says RyzenAdj is not bundled; notices and the release build
  path say/build otherwise. No specific released ZIP was opened to settle its
  actual payload. Treat developer, prerelease and release builds separately.
- Re-Gear's third-party notice claims the full GPL text is in `LICENSE`; the
  pinned file is a short notice with a link. The inspected package list includes
  that file. Archive verification and a focused correction are follow-ups.
- Upstream's local-learning toggle defaults enabled. “Local-only” is not the
  same as opt-in, and disabling stored learning does not stop every control sensor.
- Capability detection, setter return, verified readback, native delivery, and
  actual player experience remain separate evidence levels.
- No elapsed-time estimate is assigned to the proposed implementation slices.
  Current owners and branch state must be rechecked before work starts.
