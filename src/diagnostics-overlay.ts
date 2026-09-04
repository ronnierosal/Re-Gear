import type {
  DockedIgpuStatusPayload,
  DiagnosticLoggingStatusPayload,
  ActionHistoryPayload,
  HardwareCapabilityAxis,
  PeripheralStatusPayload,
  SnapshotPayload,
} from "./backend";


export interface DiagnosticOverlayRow {
  name: string;
  value: string;
}

function humanize(value: string): string {
  return value.replaceAll("_", " ").replaceAll(".", " ");
}

function yesNoUnknown(value: boolean | null): string {
  return value === true ? "yes" : value === false ? "no" : "unknown";
}

export function overheadMeasurementLabel(
  measurement: SnapshotPayload["diagnostics"]["overhead_measurement"] | undefined,
): string {
  if (!measurement || measurement.schema_version !== 1 || measurement.game_impact !== "unknown") {
    return "unavailable";
  }
  if (
    measurement.status === "observed"
    && typeof measurement.total_cost_ms === "number"
    && Number.isFinite(measurement.total_cost_ms)
    && measurement.total_cost_ms >= 0
  ) {
    return `${Math.round(measurement.total_cost_ms)}ms observed · game impact unknown`;
  }
  if (measurement.status === "deferred") {
    return "deferred · game impact unknown";
  }
  if (measurement.status === "stale" || measurement.status === "evidence_insufficient") {
    return "evidence incomplete · game impact unknown";
  }
  return "unavailable";
}

export function reportedBuildLabel(build: SnapshotPayload["diagnostics"]["build"] | undefined): string {
  if (!build || build.schema_version !== 1 || !/^[0-9A-Za-z.+-]{1,32}$/.test(build.version)
    || !/^[0-9a-f]{12}$/.test(build.revision) || !build.candidate_match) return "unavailable";
  const match = build.candidate_match === "current_candidate" ? "current candidate"
    : build.candidate_match === "different_build" ? "different build" : "comparison unavailable";
  return `v${build.version} · ${build.revision} · ${match}`;
}

export function diagnosticOverlayRows(
  payload: SnapshotPayload | null,
  dockedIgpuStatus: DockedIgpuStatusPayload | null = null,
  loggingStatus: DiagnosticLoggingStatusPayload | null = null,
  peripheralStatus: PeripheralStatusPayload | null = null,
  actionHistory: ActionHistoryPayload | null = null,
): DiagnosticOverlayRow[] {
  if (!payload) {
    return [];
  }
  const { snapshot } = payload;
  const renderer = snapshot.gpus.find((gpu) => gpu.selected_for_render === true);
  const externalGpu = snapshot.gpus.find((gpu) => gpu.role === "external");
  const externalDisplay = snapshot.displays.find((display) => display.kind === "external");
  const disconnect = snapshot.disconnect_readiness;
  const profiles = payload.diagnostics.hardware_profiles;
  const capabilities = new Map(
    profiles.capabilities.map((capability) => [capability.axis, capability]),
  );
  const capability = (axis: HardwareCapabilityAxis): string => {
    const value = capabilities.get(axis);
    return value ? `${humanize(value.value)} · ${humanize(value.confidence)}` : "unknown";
  };
  const rows: DiagnosticOverlayRow[] = [
    { name: "Observed mode", value: humanize(payload.inference.mode) },
    {
      name: "System health",
      value: humanize(payload.health?.state ?? "unavailable"),
    },
    {
      name: "Health blockers",
      value: payload.health?.blockers.length
        ? payload.health.blockers.map(humanize).join(", ")
        : "none",
    },
    {
      name: "eGPU attach",
      value: payload.attach_readiness
        ? `${humanize(payload.attach_readiness.stage)} · ${humanize(payload.attach_readiness.code)}`
        : "unavailable",
    },
    { name: "Snapshot schema", value: String(snapshot.schema_version) },
    { name: "Reported Re-Gear build", value: reportedBuildLabel(payload.diagnostics.build) },
    {
      name: "Device profile",
      value: profiles.host.status === "exact"
        ? "recognized"
        : humanize(profiles.host.status),
    },
    { name: "Support tier", value: humanize(snapshot.support_tier) },
    {
      name: "Profile evidence",
      value: `host ${humanize(profiles.host.status)} · eGPU ${humanize(profiles.egpu.status)}`,
    },
    { name: "eGPU transport", value: capability("egpu_transport") },
    {
      name: "Display capability",
      value: `output ${capability("external_display_output")} · handoff ${capability("display_handoff")}`,
    },
    {
      name: "Audio capability",
      value: `output ${capability("external_audio_output")} · handoff ${capability("audio_handoff")}`,
    },
    {
      name: "Controller capability",
      value: `promote ${capability("external_controller_promotion")} · suppress ${capability("internal_controller_suppression")}`,
    },
    {
      name: "Sleep and removal",
      value: `${capability("sleep_behavior")} · ${capability("removal_behavior")}`,
    },
    {
      name: "Gamescope",
      value: `${yesNoUnknown(snapshot.gamescope.running)} · ${humanize(snapshot.gamescope.confidence)}`,
    },
    {
      name: "Observed renderer",
      value: renderer ? `${humanize(renderer.role)} · ${humanize(renderer.confidence)}` : "unknown",
    },
    {
      name: "External GPU",
      value: externalGpu
        ? `present ${yesNoUnknown(externalGpu.present)} · ${humanize(externalGpu.confidence)}`
        : "not observed",
    },
    {
      name: "eGPU link",
      value: snapshot.egpu_link.applicable
        ? `${humanize(snapshot.egpu_link.state)} · ${humanize(snapshot.egpu_link.confidence)}`
        : "not applicable",
    },
    {
      name: "eGPU link metrics",
      value: snapshot.egpu_link.applicable
        && typeof snapshot.egpu_link.speed_gtps === "number"
        && typeof snapshot.egpu_link.width_lanes === "number"
        ? `${snapshot.egpu_link.speed_gtps} GT/s · x${snapshot.egpu_link.width_lanes} lanes · current values, not a performance rating`
        : "not reported",
    },
    {
      name: "External display",
      value: externalDisplay
        ? `connected ${yesNoUnknown(externalDisplay.connected)} · active ${yesNoUnknown(externalDisplay.active)} · ${humanize(externalDisplay.confidence)}`
        : "not observed",
    },
    {
      name: "Sleep flow",
      value: snapshot.sleep_guard.required
        ? snapshot.sleep_guard.active ? "guard active" : "guard required but inactive"
        : "guard not required",
    },
    {
      name: "Disconnect scan",
      value: disconnect.applicable
        ? `${disconnect.scan_complete ? "complete" : "incomplete"} · ${disconnect.ready ? "software ready" : "blocked"}`
        : "not applicable",
    },
    {
      name: "Blocker codes",
      value: snapshot.blockers.length
        ? snapshot.blockers.map((blocker) => blocker.code).join(", ")
        : "none",
    },
    {
      name: "Stage timings",
      value: payload.diagnostics.timings_ms
        .map((timing) => `${timing.stage} ${Math.round(timing.duration_ms)}ms`)
        .join(" · ") || "unavailable",
    },
    {
      name: "Re-Gear overhead",
      value: overheadMeasurementLabel(payload.diagnostics.overhead_measurement),
    },
    {
      name: "Verbose logging",
      value: diagnosticLoggingLabel(loggingStatus),
    },
    {
      name: "Peripheral observation",
      value: peripheralStatus
        ? `controller ${peripheralStatus.controller.exact ? "mapped" : "unmapped"} · audio ${peripheralStatus.audio.exact ? "mapped" : "unmapped"}`
        : "unavailable",
    },
    {
      name: "Peripheral evidence",
      value: peripheralStatus
        ? `${humanize(peripheralStatus.controller.code)} · ${humanize(peripheralStatus.audio.code)}`
        : "unavailable",
    },
  ];
  rows.push(
    ...(dockedIgpuStatus
      ? [
      {
        name: "Docked-iGPU watch",
        value: `${humanize(dockedIgpuStatus.stage)} · ${humanize(dockedIgpuStatus.code)}`,
      },
      {
        name: "Promotion inspection",
        value: dockedIgpuStatus.inspection_available
          ? "available · read-only"
          : "unavailable",
      },
        ]
      : [
          {
            name: "Docked-iGPU watch",
            value: "unavailable",
          },
        ]),
  );
  disconnect.clients.forEach((client, index) => {
    rows.push({
      name: `Client ${index + 1}`,
      value: `${client.name} · ${humanize(client.kind)} · ${client.resources.map(humanize).join(", ")}`,
    });
  });
  actionHistory?.entries.slice(0, 3).forEach((entry, index) => {
    rows.push({
      name: `Recent action ${index + 1}`,
      value: `${humanize(entry.kind)} · ${humanize(entry.outcome)} · ${humanize(entry.code)}`,
    });
  });
  return rows;
}

export function diagnosticLoggingLabel(
  status: DiagnosticLoggingStatusPayload | null,
): string {
  if (!status) {
    return "unavailable";
  }
  if (!status.enabled) {
    return `off · ${humanize(status.code)}`;
  }
  if (status.mode === "until_reboot") {
    return "on · until reboot";
  }
  const remaining = Math.max(0, status.remaining_seconds ?? 0);
  const hours = Math.floor(remaining / 3600);
  const minutes = Math.ceil((remaining % 3600) / 60);
  const countdown = hours > 0
    ? `${hours}h ${minutes}m remaining`
    : `${minutes}m remaining`;
  return `on · ${countdown}`;
}
