# September 9 documentation, release and coordination review

Reviewed source: `358f411e15ed6293c480f34068c24b36df40a52b` (declares **0.3.67**).
Assigned starting queue: two open PRs (#200, #204), five open issues
(#34, #88, #94, #96, #108). Shared main and other owners' checkouts were not edited.

## Decisions and remaining work

| Item | Evidence and disposition |
|---|---|
| [#88](https://github.com/ronnierosal/Re-Gear/issues/88) | Closed as delivered/superseded: #33 `cc53c467`, #100 `516929e4`, preserved #84 `af58cdb8`; #138 `227cb814` and #139 `5b18edfa` supersede the older strict issue-only workflow. Both providers load the same lifecycle. Existing sessions still reload on resume. |
| [#96](https://github.com/ronnierosal/Re-Gear/issues/96) | Closed: attachment policy `01c846f` is merged through #33. Discussion #91 links the merged policy; no scanner, automatic intake or guaranteed detection is implied. |
| [#34](https://github.com/ronnierosal/Re-Gear/issues/34) | Updated and retained open. Coordination, Auto TDP series and UI review have merged evidence. Controller, G1/TV and hardware checkboxes remain separate; eGPU ownership is unchanged. Native UI validation belongs to hub task `qa-controller-validation`. |
| [#200](https://github.com/ronnierosal/Re-Gear/pull/200) | Superseding checkpoint preserves #198 typed presentation and the historical 0.3.63 holder-status fix. Replaces obsolete .63/latest, inert-tile and draft #132/#153 claims with current source evidence. Merge and live Wiki publication must be verified independently. |
| [#204](https://github.com/ronnierosal/Re-Gear/pull/204) | Four runtime version declarations at `ffb80c604c0f6e4590076bd744f722024c0e28a0` say .65; current source consistently says .67 via #215. Do not merge a rollback. Closed as superseded after exact diff/current-version review; release owner notified, staging task already done, and Quick Access owner confirmed that ownership. Preserved archive provenance limits are below. |
| [#94](https://github.com/ronnierosal/Re-Gear/issues/94) | Closed software delivery: #95 merged `b48ff735`; identity update `2bbd6ad7` uses Re-Gear. Discussion #91 now pins reviewed source `358f411` and checksum. Real handheld report remains unverified and explicitly described as such there. |
| [#108](https://github.com/ronnierosal/Re-Gear/issues/108) | Deferred following current eGPU reviewer confirmation of installation-contract/owner sequencing requirements. No CI, package or generated-output gate removed. See findings below. |

## Historical archive audit

Read local ZIPs without extraction, modification, staging or device access:

| Archive | SHA-256 | Embedded revision |
|---|---|---|
| Re-Gear-0.3.64.zip | `4170f5dc5349a503422f88ca6853e9ecd053e9258d157cb7a09a7467be48c4f6` | `uncommitted` |
| Re-Gear-0.3.65.zip | `5c05ca20feb3d17a9e21dc80c2c2b7d5948091e70cf35c6f43902b43e7c34b1e` | `uncommitted` |
| Re-Gear-0.3.67.zip | `7fe98c9c9c4597ce5a5c0f89bad56ea502e8acec6533226feb86f987db3bd519` | `9f7ce8192c014475e5d4adc81f85ac8dfb50d016` |

The first two hashes match #204, but cannot establish its exact-commit claims.
The .67 embedded revision matches #215's actual head, not the different full SHA
in its body. The release owner received these findings. Do not rewrite or reuse
any existing archive. Current public GitHub Releases remain v0.3.57/.58 development
candidates; later local archives are not newly published releases.

## Why #108 is not a safe delete-dist change today

- Runtime/package contracts require `dist/index.js` and its map on disk.
  `scripts/check_plugin_package.py` explicitly requires both; the deploy script
  checks installed `dist/index.js`.
- The documented developer deployment path in `scripts/deploy_hdm_to_ally.ps1`
  runs `pnpm build` before package validation and ZIP construction. It requires
  the Node/pnpm toolchain. The release pipeline also explicitly builds first.
- `scripts/build_plugin.py` itself consumes existing outputs; it does not invoke
  Node. Therefore the current direct package-from-checkout operation can depend
  on committed outputs. It must either remain supported or receive an explicit
  build prerequisite/migration before removing tracked files.
- This review found no basis for promising arbitrary raw-checkout installation
  without outputs. ZIP installation receives already-built outputs. These are
  distinct paths, not evidence that runtime can run without dist.
- The active `security-installer-pr` task owns `.github/workflows/ci.yml` (#165).
  #81 is still open, #82 is closed, and the eGPU owner retains its integration
  sequence. The eGPU reviewer confirmed deferral: establish security-owner scope/order agreement and reconcile active release/frontend integration first.
- Preserve both reproducible build/output verification and the controlled archive
  provenance verifier. A future packaging proposal must demonstrate source-to-ZIP
  equivalence, missing/stale-output refusal, complete package tests, and agreed
  merge order. Dropping verification to clear CI is not an acceptable fix.

## Checks and boundaries

31 hub regression tests pass. Community helper: nine tests, eight pass and one
Linux-only selector skip on Windows; original #95 Linux CI passed timeout/output
bounds. Current package contract passes. Merged policy ancestry, live issue/PR
states, immutable helper publication and archive hashes/metadata were checked.

Source tests, source integration, live Wiki publication, public release assets,
staging, installation and device verification remain separate. No hardware was
inspected or changed. Software GPU removal never proves physical unplug safety.

Documentation impact: multiple
