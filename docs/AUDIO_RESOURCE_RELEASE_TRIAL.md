# Audio resource-release trial and recovery (draft implementation)

This slice supports the audio portion of [issue #52](https://github.com/ronnierosal/Re-Gear/issues/52)
and the [resource-release experiment #51](https://github.com/ronnierosal/Re-Gear/issues/51).
It is implemented locally for review; it is not installed, activated, or hardware-validated.

The player benefit is a recoverable way to investigate remaining external audio
ownership after returning to internal display and audio. A fresh observation binds
the selected audio function, available profile, internal default sink, idle game
state and session identity. The controller saves the original profile before
requesting off, journals interrupted steps, and restores only the same observed
attachment and profile. The optional transition guard serializes pending audio
recovery with presentation transitions.

An off profile is not evidence that descriptors closed. Results deliberately do
not grant resource-release or disconnect clearance. Main plugin composition and
RPCs remain unchanged: this PR does not activate audio profile mutation. The
existing internal-audio relationship matcher is device-specific evidence, not a
claim that other hardware is validated.

The journal uses an independent Linux filesystem helper extracted from the prior
experimental filter journal. No filter lifecycle, installation, grant, or kernel
mutation is included. Source slices originated in 2c127cc, 8353799, 2c83ce5,
8b904e0, ce69ec0, 15ece97 and e14403a; unrelated probes and progress history are
excluded.

Validation on this isolated release-0.3.55 base: architecture check, compilation,
and 1,146 backend tests passed (17 platform skips). Linux-only filesystem tests
remain to be rerun for this isolated slice. Remaining work is runtime composition,
supervised cable-attached profile off/restore, and before/after resource evidence.
No physical unplug safety claim follows from these tests.

## Fresh recovery context (stacked implementation)

The next slice adds `AudioTrialContextSource` and `LiveAudioTrialFactory` from
8bea01b and 3d2bed6. It brackets a Portable idle snapshot with hardware, boot,
Gamescope owner/process and service invocation observations. The recovery
factory resolves the current owner anew for each durable record and builds
fresh observers with a bounded deadline.

The existing `FilterUnitObserver` name is retained for source compatibility;
this helper only reads four systemd properties for two fixed service names.
It adds no filter lifecycle or kernel access. No main.py factory composition,
RPC, off action, or automatic recovery activation is included. Those hookups
are absent from the source worktree and remain future work.

On the isolated stacked base, 1,171 backend tests passed (17 platform skips),
with architecture and compilation checks passing. No hardware run occurred.

## A reboot ends the trial rather than wedging it

Every observation the controller accepts is bound to the record's `boot_hash`,
which is what makes restoration safe: a profile is only ever restored onto the
same attachment it was taken from. It also means a record cannot outlive its
boot. If the machine goes down between off and restore, no live observation can
match the record again, so no restoration attempt can succeed however often it
is retried -- while the record stayed pending, refusing every supervised
presentation transition and every new trial, with deleting the journal by hand
as the only remedy.

`AudioTrialPhase.ABANDONED` is the way out, and `decide_trial_boot` is the
decision behind it. It follows `relaunch_intent`, which answers the same fact
the same way: a reboot ends every claim its record had. When the recovery entry
point finds a pending record from another boot it retires the record to that
terminal phase and still refuses that attempt, with `audio.recovery_abandoned`.
Nothing is restored and no command is issued to the audio device: the profile is
left exactly as the reboot found it, and the distinct code is what tells the
operator to check whether that boot left it off. Subsequent transitions are no
longer answerable by a claim belonging to a boot that is gone.

Two refusals are deliberately unchanged. Retirement happens only where recovery
was explicitly requested, so an ordinary transition never quietly discards
durable audio state; and a record whose *observed* identity is unknown or
changed -- topology, portable sink, game state, or a boot the running system
cannot confirm -- still blocks everything. Retiring is the permissive direction
here, the inverse of a relaunch intent where refusing and discarding are the
same answer, so a record is retired only when the running boot is positively
identified and positively different. An unreadable boot id retires nothing.
