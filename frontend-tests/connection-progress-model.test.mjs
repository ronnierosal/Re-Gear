import assert from "node:assert/strict";
import test from "node:test";

import { connectionProgressModalModel } from "../src/connection-progress-model.ts";

const automatic = (stage) => ({ schema_version: 1, enabled: true, stage, code: `automatic_dock.${stage}` });

test("pending TV stays visible while automatic docking continues", () => {
  const model = connectionProgressModalModel(
    { label: "eGPU detected", detail: "Waiting for a connected TV output.", settling: false },
    automatic("waiting"),
  );

  assert.equal(model.phase, "connecting");
  assert.deepEqual(model.rows.find((row) => row.key === "tv"), {
    key: "tv", label: "TV HDMI detected", state: "pending", stateLabel: "Waiting for TV",
  });
  assert.match(model.keepConnectedMessage, /hidden/i);
  assert.match(model.keepConnectedMessage, /background/i);
});

test("only verified dock evidence presents the TV as active", () => {
  const model = connectionProgressModalModel(
    { label: "TV Docked", detail: "The live render GPU and TV output are verified.", settling: false },
    automatic("docked"),
  );

  assert.equal(model.phase, "ready");
  assert.equal(model.rows.find((row) => row.key === "tv")?.state, "ready");
  assert.equal(model.rows.find((row) => row.key === "automatic")?.stateLabel, "TV active");
});

test("an action-required automatic status never resembles switching", () => {
  const model = connectionProgressModalModel(
    { label: "TV initializing", detail: "Waiting for evidence.", settling: true },
    automatic("action_required"),
  );

  assert.equal(model.phase, "connecting");
  assert.equal(model.rows.find((row) => row.key === "automatic")?.state, "blocked");
});
