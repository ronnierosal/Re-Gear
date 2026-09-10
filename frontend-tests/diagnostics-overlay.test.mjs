import assert from "node:assert/strict";
import test from "node:test";

import {
  diagnosticLoggingLabel,
  diagnosticOverlayRows,
  overheadMeasurementLabel,
  reportedBuildLabel,
} from "../src/diagnostics-overlay.ts";


function payload() {
  return {
    snapshot: {
      schema_version: 3,
      observed_at: "2026-08-31T12:00:00Z",
      host_profile: "asus-rog-ally-x",
      support_tier: "certified",
      game_state: "idle",
      gpus: [
        {
          stable_id: "private-gpu-id",
          role: "external",
          vendor_device: "1002:7480",
          present: true,
          selected_for_render: true,
          confidence: "verified",
        },
      ],
      displays: [
        {
          stable_id: "private-display-id",
          connector: "HDMI-A-9",
          kind: "external",
          connected: true,
          active: true,
          edid_ready: true,
          confidence: "verified",
        },
      ],
      gamescope: {
        running: true,
        pid: 1234,
        output_order: ["HDMI-A-9"],
        render_gpu_stable_id: "private-gpu-id",
        render_vendor_device: "1002:7480",
        confidence: "verified",
      },
      disconnect_readiness: {
        applicable: true,
        scan_complete: true,
        ready: false,
        egpu_stable_id: "private-gpu-id",
        clients: [
          {
            instance_id: "private-instance-id",
            pid: 9876,
            name: "sample-client",
            kind: "user",
            resources: ["drm_render"],
            close_eligible: true,
            reason: "fixture",
          },
        ],
        storage_devices: 0,
        storage_in_use: false,
        error: "",
      },
      sleep_guard: {
        required: true,
        active: true,
        confidence: "verified",
        reason: "fixture",
        error: "",
      },
      egpu_link: {
        applicable: true,
        state: "up",
        confidence: "observed",
        reason: "egpu.link_observed",
        error: "",
        speed_gtps: 16.0,
        width_lanes: 4,
      },
      blockers: [{ code: "test.blocker", message: "Fixture blocker" }],
    },
    inference: { mode: "tv_docked", reasons: [] },
    health: {
      state: "attention_required",
      components: [
        { component: "placement", state: "ready", reason: "" },
        { component: "egpu_link", state: "unknown", reason: "egpu.link_unobserved" },
      ],
      blockers: ["health.egpu_link_unknown"],
    },
    attach_readiness: {
      schema_version: 1,
      stage: "ready_idle",
      code: "attach.ready_idle",
      poll_after_ms: 1000,
    },
    diagnostics: {
      schema_version: 2,
      timings_ms: [{ stage: "snapshot_total", duration_ms: 25.4 }],
      hardware_profiles: {
        schema_version: 1,
        host: { status: "exact", profile_id: "asus-rog-ally-x" },
        egpu: { status: "exact", profile_id: "gpd-g1-rx7600mxt-titan-ridge" },
        capabilities: [
          { axis: "egpu_transport", value: "usb4", confidence: "verified", basis: "exact_host_profile" },
          { axis: "external_display_output", value: "verified", confidence: "verified", basis: "exact_egpu_profile" },
          { axis: "display_handoff", value: "experimental", confidence: "observed", basis: "composed_exact_profiles" },
          { axis: "external_audio_output", value: "verified", confidence: "verified", basis: "exact_egpu_profile" },
          { axis: "audio_handoff", value: "experimental", confidence: "observed", basis: "composed_exact_profiles" },
          { axis: "external_controller_promotion", value: "unknown", confidence: "unknown", basis: "exact_host_profile" },
          { axis: "internal_controller_suppression", value: "unknown", confidence: "unknown", basis: "exact_host_profile" },
          { axis: "sleep_behavior", value: "disconnect_before_sleep_verified", confidence: "verified", basis: "exact_egpu_profile" },
          { axis: "removal_behavior", value: "shutdown_before_disconnect", confidence: "verified", basis: "exact_egpu_profile" },
        ],
      },
    },
  };
}

test("overlay is empty until a snapshot exists", () => {
  assert.deepEqual(diagnosticOverlayRows(null), []);
});

test("missing watcher delivery is visible rather than silently omitted", () => {
  const rows = diagnosticOverlayRows(payload());
  assert.deepEqual(
    rows.find((row) => row.name === "Docked-iGPU watch"),
    { name: "Docked-iGPU watch", value: "unavailable" },
  );
});

test("overlay exposes useful categorical state without raw identities", () => {
  const rows = diagnosticOverlayRows(payload(), {
    schema_version: 1,
    stage: "promotion_ready",
    code: "docked_igpu.promotion_ready",
    poll_after_ms: 0,
    inspection_available: false,
    acknowledgement_required: false,
  });
  const text = JSON.stringify(rows);
  assert.match(text, /Device profile/);
  assert.match(text, /recognized/);
  assert.doesNotMatch(text, /asus-rog-ally-x/);
  assert.doesNotMatch(text, /gpd-g1-rx7600mxt-titan-ridge/);
  assert.match(text, /test\.blocker/);
  assert.match(text, /sample-client/);
  assert.match(text, /drm render/);
  assert.match(text, /snapshot_total 25ms/);
  assert.match(text, /host exact/);
  assert.match(text, /usb4/);
  assert.match(text, /shutdown before disconnect/);
  assert.match(text, /eGPU link/);
  assert.match(text, /up · observed/);
  assert.match(text, /eGPU link metrics/);
  assert.match(text, /16 GT\/s · x4 lanes · current values, not a performance rating/);
  assert.match(text, /System health/);
  assert.match(text, /attention required/);
  assert.match(text, /health egpu link unknown/);
  assert.match(text, /eGPU attach/);
  assert.match(text, /ready idle · attach ready idle/);
  assert.match(text, /Docked-iGPU watch/);
  assert.match(text, /promotion ready/);
  assert.match(text, /Promotion inspection/);
  assert.match(text, /Peripheral observation/);
  assert.match(text, /unavailable/);
  for (const forbidden of [
    "private-gpu-id",
    "private-display-id",
    "private-instance-id",
    "HDMI-A-9",
    "1002:7480",
    "1234",
    "9876",
  ]) {
    assert.doesNotMatch(text, new RegExp(forbidden.replaceAll(":", "\\:")));
  }
});

test("Re-Gear overhead presentation is bounded, privacy-safe, and never claims game impact", () => {
  const observed = overheadMeasurementLabel({
    schema_version: 1,
    status: "observed",
    code: "private.measurement.code",
    game_impact: "unknown",
    total_cost_ms: 15.4,
  });
  assert.equal(observed, "15ms observed · game impact unknown");
  assert.doesNotMatch(observed, /private/);
  assert.equal(overheadMeasurementLabel({
    schema_version: 1,
    status: "deferred",
    code: "private",
    game_impact: "unknown",
  }), "deferred · game impact unknown");
  assert.equal(overheadMeasurementLabel(undefined), "unavailable");
  assert.equal(overheadMeasurementLabel({
    schema_version: 1,
    status: "observed",
    code: "private",
    game_impact: "unknown",
    total_cost_ms: -1,
  }), "unavailable");
});

test("reported build requires complete public comparison evidence", () => {
  assert.equal(reportedBuildLabel({ schema_version: 1, version: "0.2.0", revision: "a".repeat(12), candidate_match: "current_candidate" }), "v0.2.0 · aaaaaaaaaaaa · current candidate");
  assert.equal(reportedBuildLabel({ schema_version: 1, version: "0.2.0", revision: "private", candidate_match: "current_candidate" }), "unavailable");
  assert.equal(reportedBuildLabel(undefined), "unavailable");
});

test("peripheral diagnostics remain categorical when an observation is mapped", () => {
  const rows = diagnosticOverlayRows(payload(), null, null, {
    schema_version: 1,
    controller: {
      complete: true,
      exact: true,
      builtin_available: true,
      external_connected: true,
      code: "peripheral.controller.mapped",
    },
    audio: {
      complete: true,
      exact: false,
      external_available: null,
      portable_available: true,
      code: "peripheral.audio.unmapped",
    },
  });

  assert.deepEqual(rows.find((row) => row.name === "Peripheral observation"), {
    name: "Peripheral observation",
    value: "controller mapped · audio unmapped",
  });
  assert.deepEqual(rows.find((row) => row.name === "Peripheral evidence"), {
    name: "Peripheral evidence",
    value: "peripheral controller mapped · peripheral audio unmapped",
  });
  const text = JSON.stringify(rows);
  assert.doesNotMatch(text, /binding|\/sys\/class|event[0-9]|card[0-9]/i);
});

test("action history is bounded in the optional overlay and remains categorical", () => {
  const rows = diagnosticOverlayRows(payload(), null, null, null, {
    schema_version: 1,
    entries: [
      {
        occurred_at: "2026-08-31T12:00:00Z",
        kind: "recovery",
        outcome: "recovered",
        code: "recovery.portable_restored",
      },
      {
        occurred_at: "2026-08-31T11:59:00Z",
        kind: "sleep",
        outcome: "blocked",
        code: "sleep.egpu_attached_blocked",
      },
      {
        occurred_at: "2026-08-31T11:58:00Z",
        kind: "transition",
        outcome: "succeeded",
        code: "transition.portable_ready",
      },
      {
        occurred_at: "2026-08-31T11:57:00Z",
        kind: "peripheral",
        outcome: "failed",
        code: "peripheral.controller_unavailable",
      },
    ],
  });

  const actionRows = rows.filter((row) => row.name.startsWith("Recent action"));
  assert.equal(actionRows.length, 3);
  assert.match(JSON.stringify(actionRows), /recovery.*recovered.*portable restored/);
  assert.doesNotMatch(JSON.stringify(actionRows), /2026-08-31|private-gpu-id|HDMI-A-9/);
});

test("verbose logging status exposes a bounded countdown without private state", () => {
  assert.equal(diagnosticLoggingLabel(null), "unavailable");
  assert.equal(diagnosticLoggingLabel({
    schema_version: 1,
    enabled: false,
    mode: "off",
    duration: "",
    remaining_seconds: null,
    code: "diagnostics.verbose_default_off",
  }), "off · diagnostics verbose default off");
  assert.equal(diagnosticLoggingLabel({
    schema_version: 1,
    enabled: true,
    mode: "ttl",
    duration: "2_hours",
    remaining_seconds: 3661,
    code: "diagnostics.verbose_enabled",
  }), "on · 1h 2m remaining");
  assert.equal(diagnosticLoggingLabel({
    schema_version: 1,
    enabled: true,
    mode: "until_reboot",
    duration: "until_reboot",
    remaining_seconds: null,
    code: "diagnostics.verbose_enabled",
  }), "on · until reboot");
});
