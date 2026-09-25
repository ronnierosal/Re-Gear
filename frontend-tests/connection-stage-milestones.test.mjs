import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const read = file => readFileSync(new URL("../src/" + file, import.meta.url), "utf8");
const compile = file => ts.transpileModule(read(file), {compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022}}).outputText;
const url = text => "data:text/javascript;base64," + Buffer.from(text).toString("base64");
const {connectionMilestones: milestones, connectionProgressViewModel: view, MILESTONE_LABELS, SLOW_NOTICE_SECONDS} = await import(url(compile("connection-progress-model.ts")));
const {connectionLiveStatus} = await import(url(compile("connection-live-status.ts")));

const NOW = 1_000;
const status = (stage, extra = {}) => ({phase:"checking", connected:true, expiresAt:NOW + 10_000, seconds:5,
  title:"Checking connection readiness", rows:[{label:"No game running", state:"ready"}], canSwitch:false, stage, ...extra});
const states = m => m.steps.map(step => step.state);

test("five milestones use the approved labels", () => {
  assert.deepEqual([...MILESTONE_LABELS], ["Detect eGPU", "Load GPU driver", "Verify connection", "Find TV", "Prepare and switch display"]);
});

test("every documented readiness stage maps conservatively", () => {
  const expected = {
    waiting_for_pci: 0, transport_detected: 1, waiting_for_driver: 1, waiting_for_link: 2,
    waiting_for_hdmi: 3, ready_display_pending: 3, waiting_for_audio: 4, waiting_for_session: 4, stabilizing: 4,
  };
  for (const [stage, active] of Object.entries(expected)) {
    const m = milestones(status(stage), NOW);
    assert.equal(m.activeStep, active, stage);
    assert.deepEqual(states(m), MILESTONE_LABELS.map((_, i) => i < active ? "done" : i === active ? "active" : "pending"), stage);
    assert.equal(m.complete, false, stage);
    assert.match(m.currentDetail, new RegExp(`^Step ${active + 1} of 5 · `), stage);
  }
});

test("stabilizing is final preparation, never link verification", () => {
  const m = milestones(status("stabilizing", {title:"Checking connection stability"}), NOW);
  assert.equal(m.activeStep, 4);
  assert.equal(m.steps[2].state, "done");
  assert.equal(m.currentDetail, "Step 5 of 5 · Checking connection");
});

test("final preparation keeps the exact current reason", () => {
  assert.equal(milestones(status("waiting_for_audio", {title:"Checking audio recovery"}), NOW).currentDetail, "Step 5 of 5 · Checking audio");
  assert.equal(milestones(status("waiting_for_session", {title:"Waiting for Gaming Mode"}), NOW).currentDetail, "Step 5 of 5 · Waiting for Gaming Mode");
});

test("unmapped stages stay unknown and never advance a milestone", () => {
  for (const stage of ["some_future_stage", "timed_out", "", undefined]) {
    const m = milestones(status(stage, {title:"Detection timed out — keep eGPU connected"}), NOW);
    assert.equal(m.activeStep, -1, String(stage));
    assert.ok(m.steps.every(step => step.state === "pending"), String(stage));
    assert.equal(m.currentDetail, "Detection timed out — keep eGPU connected");
  }
});

test("automatic switching activates step five without claiming completion", () => {
  const m = milestones(status("ready_idle", {phase:"switching", automaticStage:"switching"}), NOW);
  assert.equal(m.activeStep, 4);
  assert.equal(m.headline, "Switching to TV");
  assert.equal(m.steps[4].state, "active");
  assert.equal(m.complete, false);
});

test("completion requires the fresh docked + docked_egpu phase", () => {
  const done = milestones(status("ready_idle", {phase:"complete", automaticStage:"docked"}), NOW);
  assert.equal(done.complete, true);
  assert.equal(done.headline, "Connected to TV");
  assert.ok(done.steps.every(step => step.state === "done"));
  // automatic docked alone is not completion: connectionLiveStatus only reports
  // phase "complete" with docked_egpu inference.
  const observed = new Date(Date.now()).toISOString();
  const live = connectionLiveStatus({snapshot:{observed_at:observed, game_state:"idle"}, inference:{mode:"portable"},
    connection_readiness:{stage:"ready_idle", checks_age_ms:0, checks:{}}}, {stage:"docked", enabled:true}, "journal.idle");
  assert.equal(live.phase, "checking");
  assert.equal(milestones(live).complete, false);
  // Expired evidence cannot stay complete.
  assert.equal(milestones(status("ready_idle", {phase:"complete"}), NOW + 20_000).complete, false);
});

test("stale evidence is historical: grey, no current-green claim, no advance", () => {
  const m = milestones(status("waiting_for_link"), NOW + 20_000);
  assert.equal(m.stale, true);
  assert.equal(m.headline, "Waiting for a fresh update");
  assert.equal(m.currentDetail, "Last observed: Verify connection");
  assert.deepEqual(states(m), ["stale", "stale", "stale", "pending", "pending"]);
  assert.ok(!m.steps.some(step => step.state === "done" || step.state === "active"));
  assert.equal(m.slowNotice, undefined);
  const complete = milestones(status("ready_idle", {phase:"complete"}), NOW + 20_000);
  assert.ok(!complete.steps.some(step => step.state === "done"));
});

test("blocked stages keep their truthful backend reason", () => {
  const link = milestones(status("link_training_failed", {title:"Connection link needs attention"}), NOW);
  assert.equal(link.attention, true);
  assert.equal(link.headline, "Action required");
  assert.equal(link.steps[2].state, "attention");
  assert.equal(link.currentDetail, "Step 3 of 5 · Connection link needs attention");
  const setup = milestones(status("action_required", {title:"Display setup required — open Re-Gear Diagnostics"}), NOW);
  assert.equal(setup.attention, true);
  assert.equal(setup.activeStep, -1);
  assert.equal(setup.currentDetail, "Display setup required — open Re-Gear Diagnostics");
  const game = milestones(status("waiting_for_session", {title:"Close the game to continue", rows:[{label:"No game running", state:"blocked"}]}), NOW);
  assert.equal(game.attention, true);
  assert.equal(game.currentDetail, "Step 5 of 5 · Close the game to continue");
  assert.equal(game.headline, "Action required");
  assert.equal(game.steps[4].state, "attention", "a blocked prerequisite never renders as active progress");
  assert.ok(!game.steps.some(step => step.state === "active"));
  const model = read("connection-progress-model.ts");
  assert.doesNotMatch(model, /"Close the game to continue"/, "attention copy comes from the backend-derived title");
});

test("the 30-second notice is presentation-only and suppressed where it would mislead", () => {
  assert.equal(SLOW_NOTICE_SECONDS, 30);
  assert.equal(milestones(status("waiting_for_driver", {seconds:29}), NOW).slowNotice, undefined);
  const slow = milestones(status("waiting_for_driver", {seconds:30}), NOW);
  assert.equal(slow.slowNotice, "Slower than usual · Keep the eGPU connected");
  assert.equal(slow.activeStep, 1, "the notice never changes milestones");
  assert.equal(milestones(status("waiting_for_hdmi", {seconds:90, displayPending:true}), NOW).slowNotice, undefined);
  assert.equal(milestones(status("link_training_failed", {seconds:90}), NOW).slowNotice, undefined);
  assert.equal(milestones(status("ready_idle", {seconds:90, phase:"complete"}), NOW).slowNotice, undefined);
  // The longer troubleshooting evidence in Details is unchanged.
  assert.match(view({...status("waiting_for_driver", {seconds:60}), rows:[{label:"GPU and driver", state:"waiting"}]}, NOW).delayNotice, /Taking longer than expected/);
});

test("progress is milestone-based and never derived from elapsed time", () => {
  const early = milestones(status("waiting_for_link", {seconds:1}), NOW);
  const late = milestones(status("waiting_for_link", {seconds:250}), NOW);
  assert.deepEqual(states(early), states(late));
  const model = read("connection-progress-model.ts");
  assert.doesNotMatch(model, /usually|~9|nine seconds/i);
});

test("live status exposes observed stages without changing its runtime meaning", () => {
  const observed = new Date(Date.now()).toISOString();
  const live = connectionLiveStatus({snapshot:{observed_at:observed, game_state:"idle"}, inference:{mode:"portable"},
    connection_readiness:{stage:"waiting_for_link", checks_age_ms:0, checks:{}}}, {stage:"switching", enabled:true}, "journal.idle");
  assert.equal(live.stage, "waiting_for_link");
  assert.equal(live.automaticStage, "switching");
  assert.equal(live.phase, "switching");
  assert.equal(connectionLiveStatus(null, null, undefined).stage, undefined);
});

test("overlay keeps B Hide, Y Details, full diagnostics and no new timers or I/O", () => {
  const overlay = read("connection-progress-overlay.tsx");
  assert.match(overlay, /<DialogButton onClick=\{props\.onHide\}><span className="rg-key">B<\/span> Hide<\/DialogButton>/);
  assert.match(overlay, /<DialogButton onClick=\{toggleDetails\}><span className="rg-key">Y<\/span> Details<\/DialogButton>/);
  assert.match(overlay, /<details ref=\{details\} className="rg-connection-details">/);
  assert.match(overlay, /props\.rows\.map\(row=><div key=\{row\.key\} className="rg-popup-row">/);
  for (const file of ["connection-progress-overlay.tsx", "connection-progress-model.ts"]) {
    assert.doesNotMatch(read(file), /setInterval|setTimeout|fetch\(|callable|getSnapshot|from "\.\/backend"|<button/, file);
  }
});

test("completed-state quiet dismissal and store-owned polling are unchanged", () => {
  const panel = read("connection-live-panel.tsx");
  assert.match(panel, /timer = setTimeout\(finish, 3500\)/);
  const monitor = read("connection-monitor.ts");
  assert.equal((monitor.match(/schedule\(/g) ?? []).length, 1, "one poll loop");
  assert.match(monitor, /schedule\(\(\) => void poll\(\), 1000\)/);
});

test("reduced motion removes shimmer and pulse; stale removes all motion", () => {
  const css = read("connection-panel-style.ts");
  assert.match(css, /@media\(prefers-reduced-motion:reduce\)\{\.rg-milestone-segment,\.rg-milestone-dot,\.rg-live-dot\{animation:none!important\}\}/);
  assert.match(css, /\.rg-popup:has\(\.rg-milestones\[data-stale=true\]\) \.rg-popup-state-icon/);
  assert.match(css, /\.rg-milestone-segment\[data-state=done\]\{background:#87da91\}/);
  assert.doesNotMatch(css, /\.rg-milestone-segment\[data-state=(done|stale|pending)\][^}]*animation/);
});

test("GPU name still comes only from verified, unambiguous evidence", () => {
  const model = read("connection-progress-model.ts");
  assert.doesNotMatch(model, /model_name|gpus/);
  const observed = new Date(Date.now()).toISOString();
  const base = {snapshot:{observed_at:observed, game_state:"idle", gpus:[
    {present:true, role:"external", confidence:"verified", model_name:"Example GPU"},
    {present:true, role:"unknown", confidence:"verified", model_name:"Other GPU"}]}, inference:{mode:"portable"},
    connection_readiness:{stage:"waiting_for_driver", checks_age_ms:0, checks:{}}};
  assert.equal(connectionLiveStatus(base, null, "journal.idle").gpuName, undefined);
});

test("a retained previous result blocks as attention with the backend reason", () => {
  const journal = milestones(status("waiting_for_hdmi", {title:"Previous result needs acknowledgement",
    rows:[{label:"No game running", state:"ready"}, {label:"Previous result cleared", state:"blocked"}]}), NOW);
  assert.equal(journal.attention, true);
  assert.equal(journal.headline, "Action required");
  assert.equal(journal.steps[3].state, "attention");
  assert.ok(!journal.steps.some(step => step.state === "active"));
  assert.equal(journal.currentDetail, "Step 4 of 5 · Previous result needs acknowledgement");
  assert.equal(journal.slowNotice, undefined);
  // The live status path produces that blocked row from a retained journal.
  const observed = new Date(Date.now()).toISOString();
  const live = connectionLiveStatus({snapshot:{observed_at:observed, game_state:"idle"}, inference:{mode:"portable"},
    connection_readiness:{stage:"waiting_for_hdmi", checks_age_ms:0, checks:{}}}, {enabled:true}, "journal.failed");
  assert.equal(milestones(live).attention, true);
  assert.equal(milestones(live).headline, "Action required");
});

test("an unknown stage with a blocked prerequisite is attention without a milestone claim", () => {
  const m = milestones(status("some_future_stage", {title:"Close the game to continue", rows:[{label:"No game running", state:"blocked"}]}), NOW);
  assert.equal(m.attention, true);
  assert.equal(m.activeStep, -1);
  assert.ok(m.steps.every(step => step.state === "pending"));
});

test("stale progress keeps the observed count for assistive technology", () => {
  const m = milestones(status("waiting_for_audio"), NOW + 20_000);
  assert.equal(m.stale, true);
  assert.equal(m.observedDone, 4);
  assert.equal(m.currentDetail, "Last observed: Prepare and switch display");
  assert.equal(milestones(status("waiting_for_link"), NOW).observedDone, 2);
  assert.equal(milestones(status("ready_idle", {phase:"complete"}), NOW).observedDone, 5);
  assert.equal(milestones(status("some_future_stage"), NOW).observedDone, 0);
  assert.equal(m.progressText, "Status stale. Last observed at step 5 of 5: Prepare and switch display");
  const tv = milestones(status("waiting_for_hdmi"), NOW + 20_000);
  assert.equal(tv.observedDone, 3);
  assert.equal(tv.progressText, "Status stale. Last observed at step 4 of 5: Find TV");
  assert.doesNotMatch(tv.progressText, /confirmed|current/i);
  assert.equal(milestones(status("some_future_stage"), NOW + 20_000).progressText, "Status stale. No milestone observed");
  assert.equal(milestones(status("waiting_for_link"), NOW).progressText, milestones(status("waiting_for_link"), NOW).currentDetail);
  const overlay = read("connection-progress-overlay.tsx");
  assert.match(overlay, /aria-valuenow=\{m\.observedDone\} aria-valuetext=\{m\.progressText\}/);
});

test("attention stops active progress animation in the rendered overlay", () => {
  const css = read("connection-panel-style.ts");
  // Only the active state animates a segment or dot; attention has no animation rule.
  assert.match(css, /\.rg-milestone-segment\[data-state=active\]\{[^}]*animation:/);
  assert.match(css, /\.rg-milestone\[data-state=active\] \.rg-milestone-dot\{[^}]*animation:/);
  assert.doesNotMatch(css, /data-state=attention\][^{]*\{[^}]*animation/);
  const overlay = read("connection-progress-overlay.tsx");
  assert.match(overlay, /data-active=\{!m\.stale && !m\.attention && !gpuReady/);
  assert.match(overlay, /data-active=\{!m\.stale && !m\.attention && !done && tvFound\}/);
  for (const m of [
    milestones(status("waiting_for_session", {title:"Close the game to continue", rows:[{label:"No game running", state:"blocked"}]}), NOW),
    milestones(status("waiting_for_link", {title:"Previous result needs acknowledgement", rows:[{label:"Previous result cleared", state:"blocked"}]}), NOW),
  ]) {
    assert.equal(m.attention, true);
    assert.ok(!m.steps.some(step => step.state === "active"), "no milestone is in the animated active state");
    assert.ok(m.steps.some(step => step.state === "attention"));
  }
});
