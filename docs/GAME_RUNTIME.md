# Active game runtime evidence

Re-Gear has a dormant read-only adapter for enriching one already exact Steam game
scope identity with private process/runtime evidence. It does not close,
relaunch, signal, or otherwise affect a game.

## Evidence boundary

The input is a backend-derived exact Steam AppID and bounded set of recognized
systemd scope names. The adapter then:

1. finds every exact scope below the fixed user-service cgroup root
2. reads the bounded union of `cgroup.procs`
3. reads each process twice from procfs and binds PID plus start time
4. records parent PID and executable basename privately
5. recognizes Proton only from allowlisted environment-key presence
6. produces a stable semantic generation and a distinct collection sample

Missing scopes, duplicate scope identities, an invalid or oversized PID set,
process disappearance/PID reuse, an AppID conflict, unreadable procfs evidence,
or an oversized environment all produce one categorical Unknown result. Partial
process graphs are discarded.

The adapter retains no environment values or executable paths. PID, parent,
start time, scope, and executable basename remain private backend evidence and
must not enter public snapshots, support bundles, or the transition journal.

## Current limits

This slice proves exact scope process identity, parent/launcher relationships,
and native-versus-Proton classification only. It does not yet prove:

- Steam title or game version
- a specific Proton build/version
- launcher child ownership outside the exact scope set
- actual rendering GPU for the game without a separate bounded engine probe
- save behavior, relaunch behavior, or compatibility status

The existing Support Preview RPC now constructs this adapter only for one
explicit read-only evidence pass. Any future guarded operation must still
revalidate the exact AppID/scopes and a fresh runtime generation independently.

## eGPU render-client correlation

A dormant application service brackets one exact, complete eGPU-client snapshot
between two fresh game-runtime samples. Only an unchanged process graph, exact
host/eGPU profile, exact eGPU identity, complete blocker scan, matching
PID/start-time instance, game classification, and G1 DRM render-node ownership
can produce `present`. A complete scan with no matching render client can
produce `absent`; races and conflicts produce `unknown`.

This is ownership evidence, not rendering proof. An open render node does not
prove that engine counters are active, and absence from the G1 does not by
itself identify which other GPU is rendering. The result therefore exposes an
always-false `proves_rendering_gpu` property and cannot promote compatibility or
claim Docked-eGPU by itself.

## Bounded active-render evidence

A second dormant read-only service can obtain stronger evidence from DRM
`fdinfo`. A private binding provider must first resolve one exact GPU stable ID,
PCI BDF, and render node from the same exact profile snapshot. The procfs
adapter then requires, for every matching descriptor:

- the exact bound render-node target
- `amdgpu` as the DRM driver
- the exact bound PCI identity from `drm-pdev`
- a categorical DRM client ID
- bounded engine counters
- unchanged PID plus process start time around each scan

The service brackets two complete counter samples inside an unchanged exact game
runtime and waits 50-250 ms through an injected bounded waiter. A counter
increase is `active`; unchanged counters are only `idle_window`; no matching
descriptor is `no_client`. A changed client/engine set, decreased counter,
runtime race, unreadable evidence, or binding conflict is `unknown`.

`active` proves that an exact game process accumulated DRM engine time on that
exact GPU during that bounded window. It does not prove exclusive use, future
use, display placement, or broad compatibility.

The read-only GPD G1 binding resolver is implemented. It requires
the exact snapshot profile/identity, independently re-runs the complete
DRM/PCI/USB4 G1 matcher, requires the same stable ID and GPU BDF, accepts exactly
one render node under that PCI device, and verifies that its `/dev/dri` target is
a character device. A separate Ally internal-GPU resolver re-observes the exact
certified DMI tuple, exactly one verified internal snapshot GPU, and exactly one
AMD `boot_vga` card with a matching vendor/device identity before accepting one
character-device render node. Neither resolver trusts DRM card numbers, render
node suffixes, or PCI addresses supplied by delivery.

The existing Support Preview action is now the first production construction
of these read-only pieces. When an exact Gamescope user and one exact running
Steam game are available, it samples internal and G1 engine counters inside one
shared runtime/snapshot bracket and one bounded wait interval, then adds only
categorical evidence to the preview event log. Either target being Unknown marks
the comparison incomplete. The payload carries
game state, exactness, native/Proton category, eGPU-client category/count,
internal/external activity category, active-engine count, reason, and placement.
It excludes AppID, scopes, PID/start time, executable data, PCI/DRM identities,
stable IDs, and generations. Idle or unknown game state skips all deep process
and DRM scans. Fresh exact game-session samples bracket the complete comparison;
a changed game, Gamescope user, runtime category, snapshot, or cross-target placement
discards the complete observation.

This is not a new RPC, continuous monitor, transition authority, or hardware
proof. It runs only when the user already requests a support preview and any
unknown or changing identity remains categorical Unknown.

The dormant compatibility-test collector is the first consumer. It accepts an
eGPU-handoff result only when the intentional test baseline names the same exact
Steam AppID on the internal GPU, the bounded evidence is `active`, and the same
evidence snapshot is Docked-eGPU. It records a hashed evidence generation in the
active test session. It cannot finish, review, promote, or publish the result;
those existing explicit gates remain separate.
