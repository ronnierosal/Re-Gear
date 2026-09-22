import fps from "../../../../assets/command-center/v3/production/01_fps.svg?v3-production";
import battery from "../../../../assets/command-center/v3/production/02_battery.svg?v3-production";
import controller from "../../../../assets/command-center/v3/production/03_controller.svg?v3-production";
import egpu from "../../../../assets/command-center/v3/production/04_egpu.svg?v3-production";
import display from "../../../../assets/command-center/v3/production/05_display.svg?v3-production";
import performance from "../../../../assets/command-center/v3/production/06_performance.svg?v3-production";
import manualTdp from "../../../../assets/command-center/v3/production/07_manual-tdp.svg?v3-production";
import autoTdp from "../../../../assets/command-center/v3/production/08_auto-tdp.svg?v3-production";
import handheld from "../../../../assets/command-center/v3/production/09_handheld.svg?v3-production";
import safeDisconnect from "../../../../assets/command-center/v3/production/10_safe-disconnect.svg?v3-production";
import disconnectSleep from "../../../../assets/command-center/v3/production/11_disconnect-sleep.svg?v3-production";
import disconnectShutdown from "../../../../assets/command-center/v3/production/12_disconnect-shutdown.svg?v3-production";
import resolution from "../../../../assets/command-center/v3/production/13_resolution.svg?v3-production";
import refreshRate from "../../../../assets/command-center/v3/production/14_refresh-rate.svg?v3-production";
import storage from "../../../../assets/command-center/v3/production/15_storage.svg?v3-production";
import wifi from "../../../../assets/command-center/v3/production/16_wifi.svg?v3-production";
import mic from "../../../../assets/command-center/v3/production/17_mic.svg?v3-production";
import record from "../../../../assets/command-center/v3/production/18_record.svg?v3-production";
import brightness from "../../../../assets/command-center/v3/production/19_brightness.svg?v3-production";
import volume from "../../../../assets/command-center/v3/production/20_volume.svg?v3-production";
import offlineReady from "../../../../assets/command-center/v3/production/21_offline-ready.svg?v3-production";
import charging from "../../../../assets/command-center/v3/production/22_charging.svg?v3-production";
import temperature from "../../../../assets/command-center/v3/production/23_temperature.svg?v3-production";
import fan from "../../../../assets/command-center/v3/production/24_fan.svg?v3-production";
import network from "../../../../assets/command-center/v3/production/25_network.svg?v3-production";
import gameReady from "../../../../assets/command-center/v3/production/26_game-ready.svg?v3-production";
import playerOrder from "../../../../assets/command-center/v3/production/27_player-order.svg?v3-production";
import audioOutput from "../../../../assets/command-center/v3/production/28_audio-output.svg?v3-production";
import gpuLoad from "../../../../assets/command-center/v3/production/29_gpu-load.svg?v3-production";
import powerDraw from "../../../../assets/command-center/v3/production/30_power-draw.svg?v3-production";
import frametime from "../../../../assets/command-center/v3/production/31_frametime.svg?v3-production";
import memory from "../../../../assets/command-center/v3/production/32_memory.svg?v3-production";
import clock from "../../../../assets/command-center/v3/production/33_clock.svg?v3-production";
import quickAccess from "../../../../assets/command-center/v3/production/34_quick-access.svg?v3-production";
import settings from "../../../../assets/command-center/v3/production/35_settings.svg?v3-production";
import about from "../../../../assets/command-center/v3/production/36_about.svg?v3-production";
import more from "../../../../assets/command-center/v3/production/37_more.svg?v3-production";

const productionArtwork = {
  fps, battery, controller, egpu, display, performance, "manual-tdp": manualTdp,
  "auto-tdp": autoTdp, handheld, "safe-disconnect": safeDisconnect,
  "disconnect-sleep": disconnectSleep, "disconnect-shutdown": disconnectShutdown,
  resolution, "refresh-rate": refreshRate, storage, wifi, mic, record, brightness,
  volume, "offline-ready": offlineReady, charging, temperature, fan, network,
  "game-ready": gameReady, "player-order": playerOrder, "audio-output": audioOutput,
  "gpu-load": gpuLoad, "power-draw": powerDraw, frametime, memory, clock,
  "quick-access": quickAccess, settings, about, more,
} as const;

export type V3ProductionArtworkId = keyof typeof productionArtwork;
export const v3ProductionArtworkIds = Object.freeze(Object.keys(productionArtwork) as V3ProductionArtworkId[]);

/** Canonical control-registry identity to the matching owner-approved illustration. */
const controlArtwork: Readonly<Record<string, V3ProductionArtworkId>> = {
  "fps-target": "fps", "manual-tdp": "manual-tdp", "auto-tdp": "auto-tdp",
  "performance-profile": "performance", "performance-resolution": "resolution",
  "refresh-rate": "refresh-rate", "display-target": "display",
  "egpu-connection": "egpu", "egpu-overview": "egpu", handheld: "handheld",
  "safe-disconnect": "safe-disconnect", "egpu-resolution": "resolution",
  "disconnect-sleep": "disconnect-sleep", "disconnect-shutdown": "disconnect-shutdown",
  "egpu-device": "egpu",
  "egpu-dock": "egpu", "egpu-display": "display",
  "egpu-link": "egpu", "egpu-link-widget": "egpu",
  "controller-summary": "controller", "controller-player1": "controller",
  "controller-battery": "battery", "controller-builtin": "controller",
  "controller-priority": "player-order", "controller-tv": "controller",
  "controller-settings": "settings", "offline-game": "game-ready",
  "offline-readiness": "offline-ready", "offline-select": "game-ready",
  "offline-sync": "offline-ready", "offline-schedule": "clock",
  diagnostics: "more", "reset-layout": "settings", tutorials: "about",
  "menu-shortcut": "quick-access", about: "about", help: "about",
  "quick-actions": "quick-access", appearance: "settings", updates: "more",
  brightness: "brightness", volume: "volume", mic: "mic", wifi: "wifi",
  overlay: "performance", recording: "record", audio: "audio-output",
};

export function v3TileArtworkId(controlId: string): V3ProductionArtworkId | undefined {
  return controlArtwork[controlId] ?? (controlId in productionArtwork ? controlId as V3ProductionArtworkId : undefined);
}

export function V3TileArtwork({ controlId }: { controlId: string }) {
  const artworkId = v3TileArtworkId(controlId);
  const src = artworkId ? productionArtwork[artworkId] : undefined;
  return src ? <img className="rg-v3-tile-artwork" data-v3-artwork={artworkId} src={src} alt="" aria-hidden="true"/> : null;
}
