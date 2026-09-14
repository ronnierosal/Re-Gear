import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import net from "node:net";
import tls from "node:tls";
import http from "node:http";
import https from "node:https";
import dgram from "node:dgram";
import ts from "typescript";

/** ======================================================== KNOWN LIMITS ====
 *
 * Read this before trusting a sentence anywhere below it.
 *
 * WHAT THIS SUITE PROVES
 *  - Behaviour, through the binding's own surface: which buttons a captured
 *    choice carries, what reaches the port when one is pressed, when a choice
 *    retires, what a subscriber is handed and in what order, and what admission
 *    refuses. Every one of those is falsifiable by mutating the module.
 *  - Dormancy, ACROSS A BOUNDED WINDOW (`QUIET_WINDOW_MS`, below) of real
 *    elapsed time: no port call and no network call that a button press or an
 *    explicit `refresh()` did not ask for, in every phase the coordinator can
 *    publish, watched and unwatched, whatever mechanism asked for the turn.
 *    Counters, not name spies, are what make that mechanism-blind.
 *  - Four source-text lints on the module, which are lints and nothing else:
 *    it imports only the coordinator, names no scheduler or module loader,
 *    calls `refresh` in exactly one place, and states its anti-polling bound --
 *    in the sentence that makes the claim, not somewhere else in the header --
 *    as this file's window, rather than as a number that can drift from it or
 *    as an absolute that no window can prove.
 *  - Exhaustiveness over phases, against the coordinator's own `PowerPhase`
 *    rather than a list typed in here: a phase ADDED upstream fails this suite
 *    instead of silently going uncovered.
 *
 * WHAT IT DOES NOT PROVE
 *  - Anything about the coordinator's state machine. That has its own suite.
 *  - Anything about how #306's shell, or any other caller, uses this binding.
 *    NOTHING IN THE PRODUCT IMPORTS THIS MODULE YET; a green run here is not
 *    evidence that a popup exists, renders, or is wired to anything.
 *  - That the module reaches nothing outside the port and the network surface
 *    counted below. Disk, `process`, IPC to another process: none of those are
 *    counted, and the network surface itself has a named half that is an
 *    enumeration -- its reach and its edges are written out where it is built.
 *  - The source lints prove nothing about run-time behaviour. A name assembled
 *    at run time, or a global never spelled, walks past all four of them. The
 *    quiet window is what covers those, and only for its length. The bound gate
 *    is text too: it holds the claim to the window in the spellings written
 *    into it, and a header rephrased past those is a header it cannot judge.
 *  - That the division of labour with the coordinator is what the module's
 *    header says it is. That paragraph is a thing to read, not a thing checked.
 *
 * THE THREE THINGS IT CANNOT DO
 *  - Catch a poll whose period is LONGER than `QUIET_WINDOW_MS`. Such a poll
 *    never comes due inside the window, and 2s, 5s and 30s are periods a status
 *    poll is routinely given. Lengthening the window moves the gap, it does not
 *    close it -- there is always a longer interval -- so the number is stated
 *    rather than chased. If this module is ever wired to a real backend, that
 *    gap is the one a reviewer still has to close by reading it.
 *  - Bound a module that starves the event loop. Every measurement here is made
 *    out of loop turns, so a module that denies them denies the measurement
 *    too, and such a module would hang this run rather than fail it -- nothing
 *    scheduled on a starved loop can bound a starved loop, `node --test`'s own
 *    `timeout` included. A handle the module leaks and never closes holds the
 *    process open the same way, behind assertions that have already printed.
 *    This suite does not defend against either. That failure shape has not been
 *    observed in the module under test; it was only ever produced deliberately
 *    during review, and nothing here is built against it.
 *  - NOTICE A MODULE THAT ENDS THE PROCESS WHILE IT IS BEING IMPORTED, and of
 *    the three this is the one to be most afraid of, because it is the only
 *    quiet one. The two above announce themselves: a run that hangs is a run
 *    somebody has to go and kill. This one does not announce anything. `load()`
 *    is awaited at this file's top level, before any test is even registered,
 *    so a module that calls `process.exit(0)` during its own import ends the
 *    process there -- and `node --test` reports THE FILE AS A PASSING TEST.
 *    Green tick, exit 0, and every test in this file simply does not appear in
 *    the run: not failed, not skipped, absent. A reader who takes the exit code
 *    for the answer is reading a run in which nothing below this block executed.
 *    Nothing here detects it, and nothing here is going to: machinery against
 *    it was built in this file once and removed, and naming the shape is what
 *    is left. What a reader can do instead costs nothing -- look for this
 *    file's tests in the run's output, by name, and see that they ran.
 * ==========================================================================
 */

/** Driven through the binding's own surface, with the source gates as the
 * marked exception.
 *
 * Almost every assertion below is something a popup or an owner can see: the
 * buttons it was handed, the snapshot it renders from, and what the port did or
 * did not receive. The coordinator's state machine has its own suite;
 * re-asserting it here would only mean two tests failing for the same reason,
 * and neither of them saying which layer broke.
 *
 * The exceptions are the four source gates in this section, which read the
 * module's text off disk, and the phase list, which is read off the
 * coordinator's. What each of those proves is narrow, and it is stated where
 * they are.
 */

/** The module under test, compiled and concatenated rather than imported: it
 * reaches the coordinator by relative path, which cannot resolve inside a
 * `data:` URL. Exports are kept; the import lines are stripped, which is why
 * the source gates below read the file off disk instead of inspecting what was
 * executed here.
 *
 * `load()` is written to hand back a fresh instance each time -- the unique tail
 * makes every bundle a different specifier, so the loader has nothing cached to
 * return. The dormancy test needs that, because whatever an import arms it arms
 * once per instance and this file's own top-level import ran before any test
 * body did; so the test that needs it asserts it, on the one thing that would
 * show a cache hit: the identity of the function handed back. */
const compile = (name) => ts.transpileModule(readFileSync(new URL(`../src/${name}`, import.meta.url), "utf8"), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText;
let instances = 0;
const load = async () => {
  const bundle = compile("power-request-coordinator.ts")
    + compile("quick-access/expanded-command-center/power-choice-binding.ts").replace(/^import[^;]*;$/gm, "")
    + `\n//# sourceURL=power-choice-module-${instances++}.mjs\n`;
  const loaded = await import(`data:text/javascript;base64,${Buffer.from(bundle).toString("base64")}`);
  return loaded.createPowerChoiceBinding;
};
const createPowerChoiceBinding = await load();

const firstId = "a".repeat(32);
const secondId = "b".repeat(32);
/** Distinct valid request identities for the tests that capture more than
 * twice; the coordinator refuses a reused one. */
const idAt = (n) => n.toString(16).padStart(32, "0");
const attachment = `${"c".repeat(64)}:${"d".repeat(64)}`;
const otherAttachment = `${"e".repeat(64)}:${"f".repeat(64)}`;
const label = "RX 7600M XT dock";
const request = { attachmentToken: attachment, connectionLabel: label };
/** A port call held open, so a test can look at the binding mid-dispatch. */
const deferred = () => {
  let resolve;
  const promise = new Promise((yes) => { resolve = yes; });
  return { promise, resolve };
};
const reply = (overrides = {}) => ({
  schema_version: 1, request_id: firstId, power_action: "sleep", route_action: "whole_dock_sleep",
  busy: false, power_requested: true, ok: true,
  code: "dock_power.request_accepted_unverified", ...overrides,
});
/** The backend answering the request it was actually given, so a test that is
 * about the popup does not fail over correlation plumbing. */
const accepted = (action, token, id, overrides = {}) => reply({
  request_id: id, route_action: action,
  power_action: action === "whole_dock_shutdown" ? "shutdown" : "sleep", ...overrides,
});
/** Let every already-scheduled turn run, so real async work -- an awaited port
 * call, a promise chain -- has finished before we look.
 *
 * This is a drain, not a proof of anything. Three timer turns catch a 0ms
 * self-reschedule and leave a 50ms one entirely green. What covers intervals is
 * `quiet()` below and the tests built on it, and only up to the length of the
 * window they hold. */
const settle = async () => {
  for (let i = 0; i < 3; i += 1) {
    await new Promise((resolve) => setTimeout(resolve, 0));
    await new Promise((resolve) => setImmediate(resolve));
  }
};

/** How long "nothing happened" has to hold for, and the bound on every claim in
 * this file that begins "no port call".
 *
 * Real elapsed time rather than a count of turns, because an interval poll
 * sleeps through turns; many turns as well as long ones, because an interval is
 * not the only way to ask for one.
 *
 * The length is an ASSUMPTION, and it is the assumption that sets the bound: it
 * is a guess that a poll written into this module would be written with a short
 * period -- a few hundred milliseconds, a second -- and it is not evidence about
 * what anyone would write. A poll on a longer period than this simply never
 * comes due inside the window, and 2s, 5s and 30s are periods a status poll is
 * routinely given. Raising the number does not retire the gap, it moves it, so
 * the tests state the bound instead. */
const QUIET_WINDOW_MS = 1500;

/** Hold the process open for at least `QUIET_WINDOW_MS` of wall-clock time
 * across many event-loop turns of every kind -- macrotask, check phase,
 * microtask -- and report what the window actually cost, so a caller can assert
 * the time really elapsed instead of trusting this loop to have spent it. */
const quiet = async () => {
  const started = Date.now();
  /** The in-process half of the bound, and it only covers the easy half of the
   * problem. A module that merely SLOWS the loop -- long turns, not denied ones
   * -- could otherwise leave this loop waiting indefinitely for its hundredth
   * turn. With the ceiling it stops, reports what it actually got, and the
   * caller's assertions fail on the shortfall instead of waiting on it.
   *
   * A module that denies the loop turns altogether denies this check too: the
   * `await` never comes back, so the ceiling is never read. Nothing scheduled
   * on a starved loop can bound a starved loop. That is the hang written down
   * in KNOWN LIMITS at the top of this file, and nothing here covers it. */
  const ceiling = started + QUIET_WINDOW_MS * 4 + 5_000;
  let turns = 0;
  while ((Date.now() - started < QUIET_WINDOW_MS || turns < 100) && Date.now() < ceiling) {
    await new Promise((resolve) => setTimeout(resolve, 5));
    await new Promise((resolve) => setImmediate(resolve));
    await Promise.resolve();
    turns += 1;
  }
  return { elapsed: Date.now() - started, turns };
};

/** The network surface, counted the way the port is counted.
 *
 * "The port is the only thing here that reaches the backend" was false, and
 * falsely reassuring: a plainly spelled `fetch()` polling the backend from
 * inside the module moves no port counter and used to pass everything. So the
 * window counts the network surface too, and a call on any of it fails the
 * window exactly the way a port call does.
 *
 * WIDENING WAS THE CHOICE, not cutting the claim, and here is exactly what was
 * widened to -- because a claim wider than its instrument is the failure being
 * repaired, and repeating it one level out would be no repair at all. There are
 * two halves, and only the first is a list.
 *
 *  - The named entry points a caller reaches for: `fetch`, `XMLHttpRequest`,
 *    `WebSocket`, `EventSource`, `navigator.sendBeacon`. Spied on the object
 *    they hang off, so any call that resolves the name at call time is counted
 *    however the call site spells it. This half IS an enumeration, with an
 *    enumeration's gap -- the same shape the scheduler-name lint has.
 *  - The socket layer all of those arrive at: `net.connect`,
 *    `net.createConnection`, `net.Socket` and its `connect`, `tls.connect`,
 *    `http`/`https` `request` and `get`, `dgram.createSocket`. Still names, but
 *    names one layer down: where the APIs above ARRIVE rather than where a
 *    caller reaches. MEASURED, not assumed: a `fetch` in this runtime reaches
 *    the network through `net.connect` and `net.Socket.prototype.connect`, so a
 *    `fetch` CAPTURED INTO A VARIABLE BEFORE THESE SPIES EXISTED -- which the
 *    first half cannot see at all, and which is precisely how a poll would
 *    evade a name spy -- is still counted. That case is what the second half is
 *    for, and it is exercised by mutation, not hoped at.
 *
 * What neither half covers, stated rather than hoped over: a transport that
 * reaches the network without passing any name on either list. Nothing here
 * would know. Uncounted on purpose as well: IPC to another process, the
 * filesystem, `process` itself. None of those is how this module would reach a
 * backend, and none of them is watched.
 *
 * One thing that looks like a gap and is not: a URL the runtime refuses before
 * connecting -- a blocked port, say -- trips the named half and never reaches
 * the socket half. It never reaches a backend either, so there is nothing there
 * to miss. Worth knowing before writing the next mutant: one aimed at a blocked
 * port survives for that reason, not because the module was quiet. */
const NAMED_NETWORK_ENTRY_POINTS = [
  [() => globalThis, "fetch", "fetch"],
  [() => globalThis, "XMLHttpRequest", "XMLHttpRequest"],
  [() => globalThis, "WebSocket", "WebSocket"],
  [() => globalThis, "EventSource", "EventSource"],
  [() => globalThis.navigator, "sendBeacon", "navigator.sendBeacon"],
];
const SOCKET_LAYER = [
  [() => net, "Socket", "net.Socket"],
  [() => net.Socket.prototype, "connect", "net.Socket#connect"],
  [() => net, "connect", "net.connect"],
  [() => net, "createConnection", "net.createConnection"],
  [() => tls, "connect", "tls.connect"],
  [() => http, "request", "http.request"],
  [() => http, "get", "http.get"],
  [() => https, "request", "https.request"],
  [() => https, "get", "https.get"],
  [() => dgram, "createSocket", "dgram.createSocket"],
];
const watchNetwork = () => {
  const calls = [];
  const absent = [];
  const undo = [];

  const spy = ([holderOf, name, label]) => {
    const holder = holderOf();
    if (!holder) { absent.push(label); return false; }
    const descriptor = Object.getOwnPropertyDescriptor(holder, name);
    const original = holder[name];
    if (typeof original !== "function") { absent.push(label); return false; }
    const counted = new Proxy(original, {
      apply: (target, self, args) => { calls.push(`${label}()`); return Reflect.apply(target, self, args); },
      construct: (target, args, newTarget) => {
        calls.push(`new ${label}`);
        return Reflect.construct(target, args, newTarget === counted ? target : newTarget);
      },
    });
    Object.defineProperty(holder, name, {
      value: counted, writable: true, enumerable: descriptor?.enumerable ?? false, configurable: true,
    });
    undo.push(() => {
      if (descriptor) Object.defineProperty(holder, name, descriptor);
      else delete holder[name];
    });
    return true;
  };

  // `release` undoes these in reverse, so `net.Socket.prototype` is read
  // through the constructor's spy on the way in and restored under it on the
  // way out.
  //
  // Counted one half at a time, because a combined total cannot tell "both
  // halves are watching" apart from "the socket layer is watching and the
  // named half is gone". The socket layer is ten names of two core modules and
  // is never absent, so it clears on its own any floor a combined total could
  // carry -- and the named half, the half that catches a plainly spelled
  // `fetch`, could then be watching nothing at all without the total moving.
  let named = 0;
  let sockets = 0;
  for (const entry of NAMED_NETWORK_ENTRY_POINTS) if (spy(entry)) named += 1;
  for (const entry of SOCKET_LAYER) if (spy(entry)) sockets += 1;

  return {
    calls, absent, named, sockets, watched: named + sockets,
    release: () => { while (undo.length > 0) undo.pop()(); },
  };
};

/** The module's own syntax, read off disk.
 *
 * WHAT THE FOUR GATES BELOW PROVE, and it is all they prove: the module's
 * source text imports nothing but the coordinator, mentions no scheduler and no
 * module loader by a literal name, calls `refresh` in exactly one place, and
 * states its anti-polling bound -- in the sentence that makes the claim -- as
 * this file's window, rather than as a number that can drift away from it or as
 * an absolute no window can prove. That is a cheap lint against the ordinary
 * case, not a proof of dormancy. A name assembled at run time walks straight
 * past all four, and so does anything reached through a global never spelled.
 * The dormancy tests further down are what cover those -- for the length of the
 * window they hold, and without caring how the turn was asked for.
 *
 * They read the file rather than the module object because the bundle above
 * strips every import line before executing it -- the stripping is what makes
 * the relative coordinator path resolvable inside a `data:` URL, and it blinds
 * every behavioural test in this file to the module's import list as a side
 * effect. Typechecking does not close that either: an import of `react` is
 * well-typed, so `tsc` has nothing to say about it. (That last sentence is a
 * reason these gates exist, not something this file measures.) */
const MODULE_SOURCE = readFileSync(
  new URL("../src/quick-access/expanded-command-center/power-choice-binding.ts", import.meta.url), "utf8",
);
const MODULE_AST = ts.createSourceFile(
  "power-choice-binding.ts", MODULE_SOURCE, ts.ScriptTarget.ES2022, true,
);
const walkModule = (visit) => {
  const step = (node) => { visit(node); node.forEachChild(step); };
  step(MODULE_AST);
};

/** The value bindings an import declaration introduces, ignoring the type-only
 * ones. `import type { PowerView } from "x"` and `import { type T } from "x"`
 * contribute nothing: they are erased, and erased is the difference between
 * naming the coordinator and actually holding it. */
const valueBindingsOf = (clause) => {
  if (!clause || clause.isTypeOnly) return [];
  const names = clause.name ? [clause.name.text] : [];
  const bound = clause.namedBindings;
  if (bound && ts.isNamespaceImport(bound)) names.push(bound.name.text);
  else if (bound) for (const element of bound.elements) if (!element.isTypeOnly) names.push(element.name.text);
  return names;
};

/** The coordinator is the only thing this module is allowed to reach for. Not
 * #306's shell, not React, not `@decky/api`, not the port's implementation:
 * mounting a popup binding must not drag a dependency graph in behind it, and
 * an import is the one way a module acquires one without anybody calling it.
 *
 * The `valueImports` assertion is the half that can falsify the coordinator
 * import ITSELF. Deleting it leaves the type-only import of the same path
 * behind, so a gate that only collects module specifiers stays green while the
 * module no longer holds a coordinator at all -- and stays green on an empty
 * or wrong file too. */
test("the module's source text imports the coordinator and nothing else", () => {
  const specifiers = [];
  const valueImports = [];
  const loaded = [];
  walkModule((node) => {
    if ((ts.isImportDeclaration(node) || ts.isExportDeclaration(node))
      && node.moduleSpecifier && ts.isStringLiteral(node.moduleSpecifier)) {
      specifiers.push(node.moduleSpecifier.text);
      if (ts.isImportDeclaration(node)) {
        for (const name of valueBindingsOf(node.importClause)) {
          valueImports.push(`${name} from ${node.moduleSpecifier.text}`);
        }
      }
    } else if (ts.isImportEqualsDeclaration(node)) {
      loaded.push(node.getText(MODULE_AST));
    } else if (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword) {
      // A dynamic `import()` has no identifier to catch by name, so it is
      // caught here, by what is in callee position. Every OTHER loader --
      // `require`, `createRequire`, `importScripts` -- is caught by the name
      // gate below, wherever the name appears.
      loaded.push(node.getText(MODULE_AST));
    }
  });
  assert.deepEqual(loaded, [], "nothing is pulled in at run time either");
  assert.deepEqual([...new Set(specifiers)].sort(), ["../../power-request-coordinator"],
    `the module reached for something other than the coordinator: ${specifiers.join(", ")}`);
  assert.deepEqual(valueImports, ["createPowerRequestCoordinator from ../../power-request-coordinator"],
    "the module's one value import is the coordinator itself, and it is still there");
});

/** Schedulers, and module loaders.
 *
 * Matched wherever the name occurs -- identifier, property name, string literal
 * -- rather than only where a call's callee is spelled. Callee position alone
 * would catch `require("react")` and miss `const load = require; load(x)`,
 * `globalThis.require(x)` and `globalThis["require"](x)`.
 *
 * This is a lint on source text and nothing more. It catches every spelling of
 * a name it lists and no name assembled from pieces. */
const FORBIDDEN_NAMES = new Set([
  "setTimeout", "setInterval", "setImmediate", "queueMicrotask",
  "clearTimeout", "clearInterval", "clearImmediate",
  "requestAnimationFrame", "cancelAnimationFrame",
  "requestIdleCallback", "cancelIdleCallback", "postMessage",
  "MessageChannel", "BroadcastChannel", "nextTick", "scheduler",
  "Worker", "SharedWorker", "EventSource", "WebSocket",
  "require", "createRequire", "importScripts",
]);
test("the module's source text names no scheduler and no module loader", () => {
  const named = [];
  walkModule((node) => {
    const text = ts.isIdentifier(node) || ts.isStringLiteral(node)
      || ts.isNoSubstitutionTemplateLiteral(node) ? node.text : null;
    if (text !== null && FORBIDDEN_NAMES.has(text)) named.push(text);
  });
  assert.deepEqual(named, [],
    "the module names a scheduler or a module loader in its source text");
});

/** The module's header states the anti-polling guarantee, and that guarantee is
 * only true inside this file's window. This gate exists to stop an ABSOLUTE
 * version of it coming back -- "makes no port call, ever" -- because an
 * absolute guarantee is one no window can prove and no reader can check.
 *
 * THE FIRST VERSION OF THIS GATE DID NOT DO THAT. It asked only that the
 * guarantee PARAGRAPH name the constant somewhere, so a header that claimed
 * "IT MAKES NO PORT CALL, EVER -- `QUIET_WINDOW_MS` is how the claim is
 * spot-checked, not the limit of it" passed it: the absolute claim was back,
 * the constant was still named, and the gate stayed green. That restoration was
 * run against the old gate before this one was written, and it is the case the
 * two rules below exist to catch.
 *
 * The rules, and each one is separately falsifiable:
 *  - THE CLAIM SENTENCE CARRIES THE BOUND. Every sentence of the paragraph that
 *    says "no port call" must itself name `QUIET_WINDOW_MS` or state the
 *    constant's CURRENT value. A bound demoted to a later sentence -- or to a
 *    later paragraph, or to a footnote -- no longer qualifies the claim, and
 *    that is exactly how the restoration above reads.
 *  - THE PARAGRAPH SAYS NOTHING ABSOLUTE. "Ever", "never", "always", "at all
 *    times" and the rest of the list below re-read onto the claim from anywhere
 *    in the paragraph, which is why the whole paragraph is searched and not
 *    just the claim sentence.
 * And the rule that was already here, kept: the paragraph states no number
 * other than the window's current value, so a worked example in the prose --
 * "1.5 seconds", "two seconds" -- fails the moment the constant moves away from
 * it. The failure messages carry the current value, so the fix is a copy rather
 * than an arithmetic exercise.
 *
 * ITS REACH, WHICH IS THE REACH OF A TEXT LINT AND NO MORE: it holds the claim
 * to the window in the spellings written into it. An absolute claim made in
 * words that are on neither list -- "come what may", "in every window there is"
 * -- is one this gate cannot judge, and the module's header is then only as
 * honest as its reviewer. The paragraph itself is found by the words "no port
 * call"; rephrase past those and the gate fails loudly ("the guarantee
 * paragraph moved") rather than passing quietly, because a guarantee this file
 * cannot find is a guarantee this file cannot hold to anything. */
const MODULE_HEADER = MODULE_SOURCE.slice(0, MODULE_SOURCE.indexOf("*/") + 2);
const headerParagraphs = MODULE_HEADER.split(/\n[ \t]*\*[ \t]*\n/);
/** The paragraph as prose: comment gutter stripped, wrapping collapsed, so a
 * sentence can be read as a sentence instead of as the six lines it is typed
 * across. */
const asProse = (paragraph) => paragraph
  .replace(/^[ \t]*(?:\/\*\*|\*)[ \t]?/gm, "").replace(/\s+/g, " ").trim();
/** Split on a full stop followed by something a sentence starts with.
 * Deliberately crude, and crude in the safe direction: `power-choice-binding
 * .test.mjs` has no space after its dots, so a file name survives intact, and a
 * split this misses leaves a LONGER span that still has to carry the bound. */
const sentencesOf = (prose) => prose.split(/(?<=\.)\s+(?=[A-Z`("])/);
/** Scope words that turn a bounded claim back into an unbounded one. */
const ABSOLUTE_CLAIM = new RegExp(String.raw`\b(?:ever|never|always|forever|`
  + String.raw`permanently|indefinitely|unconditionally|at all times|`
  + String.raw`no matter how long|regardless of how long|in any window|`
  + String.raw`under any circumstances|whatever the window)\b`, "i");
test("the module states its anti-polling bound, in the sentence that claims it, as this file's window", () => {
  const guarantee = headerParagraphs.filter((paragraph) => /no port call/i.test(paragraph));
  assert.equal(guarantee.length, 1,
    `the guarantee paragraph moved: ${guarantee.length} paragraphs of the module's header say "no port call"`);
  const stated = asProse(guarantee[0]);

  const bound = String(QUIET_WINDOW_MS);
  const carriesBound = (text) => text.includes("QUIET_WINDOW_MS") || text.includes(bound);
  const claims = sentencesOf(stated).filter((sentence) => /no port call/i.test(sentence));
  assert.ok(claims.length > 0, "the guarantee paragraph no longer contains a sentence claiming it");
  const unbounded = claims.filter((sentence) => !carriesBound(sentence));
  assert.deepEqual(unbounded, [],
    "the module claims \"no port call\" in a sentence that states no bound, so as written it claims something"
    + ` no window can prove. The sentence making the claim must name QUIET_WINDOW_MS or state its current`
    + ` value, ${bound} -- a bound stated in some other sentence does not qualify this one.`);

  const absolute = stated.match(ABSOLUTE_CLAIM);
  assert.equal(absolute, null,
    `the module's guarantee says "${absolute?.[0]}", which claims the dormancy outside any window.`
    + " This suite holds the module for QUIET_WINDOW_MS and cannot prove a word of it past that,"
    + " so the header must not say it.");

  const numbers = (stated.match(/\d+(?:[.,]\d+)?/g) ?? []).filter((n) => n !== bound);
  assert.deepEqual(numbers, [],
    `the module's guarantee states ${numbers.join(", ")}, which is not the window this file holds.`
    + ` QUIET_WINDOW_MS is ${bound} today; name the constant instead, so the sentence moves when it does.`);
});

/** "This module never calls `refresh()`" was prose with nothing behind it. This
 * is what is behind it now: the module's source contains exactly one call whose
 * callee is spelled `refresh`, and it is the forward to the coordinator.
 *
 * A lint on source text, with a source lint's reach: a call made without
 * spelling the name -- through a captured reference, a computed property -- is
 * invisible to it. The readback counters in the quiet window are what cover
 * that, and only for the window's length. */
test("the module's source text calls refresh in exactly one place, and it is the forward", () => {
  const callSites = [];
  walkModule((node) => {
    if (!ts.isCallExpression(node)) return;
    const callee = node.expression;
    const name = ts.isPropertyAccessExpression(callee) ? callee.name.text
      : ts.isIdentifier(callee) ? callee.text : null;
    if (name === "refresh") callSites.push(callee.getText(MODULE_AST));
  });
  assert.deepEqual(callSites, ["coordinator.refresh"],
    "the module calls refresh somewhere other than the single forward to the coordinator");
});

/** Snapshot identity, position by position: two listeners agreeing on the
 * contents of their logs is not the same claim as agreeing on the order. */
const sameOrder = (actual, expected, message) => {
  assert.equal(actual.length, expected.length, `${message}: different number of publications`);
  actual.forEach((snapshot, index) => assert.equal(snapshot, expected[index], `${message}: publication ${index}`));
};

function harness(options = {}) {
  const calls = [];
  let reads = 0;
  let issued = 0;
  let reading;
  const port = {
    execute: async (...args) => {
      calls.push(args);
      return options.execute ? options.execute(...args) : accepted(...args);
    },
    readStatus: async () => { reads++; return reading; },
  };
  const binding = createPowerChoiceBinding(port, {
    requestId: options.requestId ?? (() => (issued++ === 0 ? firstId : secondId)),
  });
  return { binding, calls, port, setReading(value) { reading = value; }, get reads() { return reads; } };
}

// ------------------------------------------------------------- dormancy

/** WITHIN THE QUIET WINDOW THIS SUITE HOLDS, THE MODULE MAKES NO PORT CALL AND
 * NO NETWORK CALL THAT A BUTTON PRESS OR AN EXPLICIT `refresh()` DID NOT ASK
 * FOR -- in every phase, watched or unwatched, however a poll would have asked
 * for its turn.
 *
 * The window is the bound, and it belongs in the sentence rather than in a
 * footnote. `QUIET_WINDOW_MS` of real elapsed time is what "no port call" is
 * proved across; a poll whose period is longer than that never comes due inside
 * it, and 2s, 5s and 30s are periods a status poll is actually written with.
 * This test excludes none of those. Lengthening the window would only move the
 * number -- there is always a longer interval -- so the number is stated rather
 * than chased.
 *
 * What the window does cover, it covers regardless of MECHANISM, and that is
 * the real win over spying on scheduler names. `AbortSignal.timeout`,
 * `Atomics.waitAsync`, a listener on a global event target, a name assembled at
 * run time, a scheduler captured before any of this ran: none of them can do
 * anything without moving a counter, and moving a counter is the failure. A spy
 * on a name catches only the spellings it was told about.
 *
 * The port is counted because the port is the route this module is BUILT to
 * reach the backend by -- not because it is the only route there is. It is not,
 * and a plainly spelled `fetch()` polling the backend from in here would move
 * no port counter at all, so `watchNetwork()` above is counted alongside it:
 * the named entry points the runtime offers, and the socket and client names
 * underneath them. That second layer is a list and not a choke point; its
 * reach, and the gap that was measured rather than guessed, are written out
 * where it is defined.
 *
 * Those counters together bound what a poll could cause OUTSIDE the binding.
 * They are not everything the module can do -- retiring the choice and disposing
 * itself are damage that never touches a counter -- so the window also freezes
 * what a popup would see: each parked binding's snapshot identity, its choice,
 * and, where one is watching, the number of publications it has heard.
 *
 * Every phase the coordinator's own `PowerPhase` says the machine can publish
 * gets a binding, and the refresh path gets two more. Each case is parked three times over: WATCHED, with a subscriber
 * attached across the whole window; UNWATCHED, with none ever attached; and
 * ABANDONED, where the only subscriber detaches before the window opens. The
 * last two carry the weight, because a poll gated on `listeners.size === 0`
 * never runs while a subscriber is attached -- and panel closed, nobody
 * watching, is exactly the case where a background poll is worst.
 *
 * The bindings are held across one shared window rather than a window each.
 * Each is held for the whole of it with nothing pressed, which is the claim;
 * they have separate ports and separate counters, so nothing one of them does
 * can hide inside another's. That was prose until the window asserted it: the
 * ports are now checked to be distinct objects, because a shared one would let
 * a poll on the quietest binding be read as another binding's own press.
 *
 * Phases are asserted to have been PUBLISHED to a subscriber, not merely
 * reached, so a phase this test quietly stopped visiting fails instead of
 * passing -- and so does one counted because a fresh binding happens to start
 * in it.
 */
/** THE PHASE LIST IS THE COORDINATOR'S, NOT A NUMBER WRITTEN DOWN HERE.
 *
 * A list copied into this file can only fail one way: a phase REMOVED upstream
 * leaves a case here parking in a phase that no longer exists. The direction
 * that matters is the other one -- a phase ADDED to the coordinator, which a
 * copied list and the words "all nine" cannot see at all, and which arrives as
 * a phase nothing here has ever parked a binding in or checked for dormancy.
 *
 * So it is read off `PowerPhase` in the coordinator's own source. Add a member
 * there and the gate below fails until a park case exists for it; remove one
 * and it fails too. The parse is deliberately strict: if `PowerPhase` stops
 * being a plain union of string literals, this fails rather than quietly
 * deriving a shorter list. */
const COORDINATOR_SOURCE = readFileSync(
  new URL("../src/power-request-coordinator.ts", import.meta.url), "utf8",
);
const EVERY_PHASE = (() => {
  const ast = ts.createSourceFile(
    "power-request-coordinator.ts", COORDINATOR_SOURCE, ts.ScriptTarget.ES2022, true,
  );
  let found = null;
  const step = (node) => {
    if (ts.isTypeAliasDeclaration(node) && node.name.text === "PowerPhase") {
      if (!ts.isUnionTypeNode(node.type)) {
        throw new Error("the coordinator's PowerPhase is no longer a union, so this file cannot derive the phases");
      }
      found = node.type.types.map((member) => {
        if (!ts.isLiteralTypeNode(member) || !ts.isStringLiteral(member.literal)) {
          throw new Error(`the coordinator's PowerPhase has a non-literal member: ${member.getText(ast)}`);
        }
        return member.literal.text;
      });
    }
    node.forEachChild(step);
  };
  step(ast);
  if (!found) throw new Error("the coordinator no longer declares a PowerPhase type for this file to read");
  return found;
})();

/** The bound on the two tests below, and what it does and does not end.
 *
 * `node --test`'s own `timeout` is a timer, so it ends a test that merely runs
 * LONG -- a loaded machine, a window that drags, an await that never settles
 * while the loop is still turning -- with an ordinary TAP failure naming the
 * test. That is the honest half, and it is the half these two tests need.
 *
 * It cannot end a test whose module denies the loop timer turns at all, because
 * it is scheduled on the loop it would have to bound. That is the hang written
 * down in KNOWN LIMITS at the top of this file; nothing in this file covers it.
 *
 * Derived from the window, so the allowance moves when the window does: three
 * times the time actually held, plus a flat allowance for the drives and for a
 * loaded machine. */
const dormancyTimeout = (windows) => windows * QUIET_WINDOW_MS * 3 + 10_000;

/** A press held open, so a window covers a request still in flight. It is never
 * resolved: the point is that dispatching stays dispatching. */
const heldOpen = deferred();

/** One drive per phase the binding can be parked in, plus the two refresh
 * paths. `park` below runs every one of them once per subscription mode. */
const PARK_CASES = [
  // Construction on its own, with nothing asked of it.
  { name: "construction alone", phase: "idle", options: {}, drive: (h) => {
    assert.equal(h.binding.read().choice, null);
    assert.equal(h.calls.length, 0, "construction is not a submission");
    assert.equal(h.reads, 0, "construction is not a readback");
  } },

  { name: "idle after a dismissal", phase: "idle", options: {}, drive: (h) => {
    assert.equal(h.binding.beginSleep(request), true);
    h.binding.read().choice.cancel();
    assert.equal(h.calls.length, 0, "a dismissal is not a submission");
  } },

  { name: "choosing", phase: "choosing", options: {}, drive: (h) => {
    assert.equal(h.binding.beginSleep(request), true);
    assert.equal(h.calls.length, 0, "capture is not a submission");
    assert.equal(h.reads, 0, "capture is not a readback");
  } },

  { name: "dispatching", phase: "dispatching", options: { execute: () => heldOpen.promise }, drive: (h) => {
    assert.equal(h.binding.beginShutdown(request), true);
    void h.binding.read().choice.confirm();
    assert.equal(h.calls.length, 1, "one press, one submission");
    assert.ok(h.binding.read().choice, "and the popup keeps its buttons");
  } },

  { name: "pending", phase: "pending", options: {
    execute: async (...args) => accepted(...args, {
      busy: true, power_requested: false, ok: false, code: "dock_teardown.trial_running",
    }),
  }, drive: async (h) => {
    assert.equal(h.binding.beginSleep(request), true);
    await h.binding.read().choice.disconnectAndSleep();
    assert.ok(h.binding.read().choice, "a pending request is still on screen");
    assert.equal(h.reads, 0, "and pending does not read back on its own");
  } },

  { name: "requested", phase: "requested", options: {}, drive: async (h) => {
    assert.equal(h.binding.beginSleep(request), true);
    await h.binding.read().choice.keepConnectedAndSleep();
    assert.ok(h.binding.read().choice, "an accepted submission is not an observed sleep");
    assert.equal(h.reads, 0, "and requested does not follow up on its own");
  } },

  { name: "sleep_observed", phase: "sleep_observed", options: {
    execute: async (...args) => accepted(...args, {
      sleep_cycle_observed: true, code: "dock_power.sleep_cycle_observed",
    }),
  }, drive: async (h) => {
    assert.equal(h.binding.beginSleep(request), true);
    await h.binding.read().choice.disconnectAndSleep();
    assert.equal(h.binding.read().choice, null, "the popup is gone once the sleep is observed");
  } },

  { name: "refused", phase: "refused", options: {
    execute: async (...args) => accepted(...args, {
      power_requested: false, ok: false, code: "dock_power.shutdown_unverified",
    }),
  }, drive: async (h) => {
    assert.equal(h.binding.beginShutdown(request), true);
    await h.binding.read().choice.confirm();
    assert.equal(h.binding.read().choice, null, "a request that is over shows no buttons");
  } },

  { name: "uncertain", phase: "uncertain", options: {
    execute: async () => ({ schema_version: 1, request_id: firstId }),
  }, drive: async (h) => {
    assert.equal(h.binding.beginSleep(request), true);
    await h.binding.read().choice.disconnectAndSleep();
    assert.ok(h.binding.read().choice, "an unknown outcome is still an operation on screen");
    assert.equal(h.reads, 0, "and it is not a reason to start reading");
  } },

  { name: "disposed", phase: "disposed", options: {}, drive: (h) => {
    assert.equal(h.binding.beginShutdown(request), true);
    h.binding.dispose();
    assert.equal(h.binding.read().choice, null);
  } },

  // The refresh path: the readbacks the owner asked for, and nothing behind them.
  { name: "the owner's refresh", phase: "requested", options: {
    execute: async (...args) => accepted(...args, {
      busy: true, power_requested: false, ok: false, code: "dock_teardown.trial_running",
    }),
  }, drive: async (h) => {
    assert.equal(h.binding.beginSleep(request), true);
    await h.binding.read().choice.disconnectAndSleep();
    assert.equal(h.binding.read().power.phase, "pending");
    h.setReading(reply());
    await h.binding.refresh();
    await h.binding.refresh();
    assert.equal(h.reads, 2, "exactly the two readbacks the owner asked for");
  } },

  { name: "a disposed binding's refresh", phase: "disposed", options: {}, drive: async (h) => {
    assert.equal(h.binding.beginSleep(request), true);
    h.binding.dispose();
    await h.binding.refresh();
    assert.equal(h.reads, 0, "a disposed binding's readback never reaches the port");
  } },
];

/** WATCHED is the ordinary panel-open case. UNWATCHED and ABANDONED are the
 * ones a poll gated on `listeners.size === 0` would hide in. */
const SUBSCRIPTION_MODES = ["watched", "unwatched", "abandoned"];

/** The exhaustiveness claim, made falsifiable in the direction that matters.
 *
 * The dormancy test asserts every phase was PUBLISHED, which is the stronger
 * check but only reachable by running the whole window. This one is a cheap
 * gate on the same fact, and it fails for a reason the reader can act on:
 * naming the phase that has no park case. Both read the same derived list, so
 * neither can be satisfied by a number typed into this file. */
test("every phase the coordinator declares has a park case here, and no count is written down", () => {
  assert.ok(EVERY_PHASE.length > 0, "no phases were derived from the coordinator");
  assert.deepEqual([...new Set(EVERY_PHASE)], EVERY_PHASE,
    `the coordinator declares a duplicate phase: ${EVERY_PHASE.join(", ")}`);

  const parked = new Set(PARK_CASES.map((parkCase) => parkCase.phase));
  assert.deepEqual(EVERY_PHASE.filter((phase) => !parked.has(phase)), [],
    "the coordinator can publish a phase this file never parks a binding in, so the quiet window does not cover it");
  assert.deepEqual([...parked].filter((phase) => !EVERY_PHASE.includes(phase)), [],
    "this file parks a binding in a phase the coordinator no longer declares");

  // And the module's prose must not pin a count that goes stale the moment the
  // coordinator gains one -- the exact failure this derivation replaces.
  const pinned = MODULE_SOURCE.match(
    /\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|\d+)\s+phases\b/i,
  );
  assert.equal(pinned, null,
    `the module's prose pins a phase count ("${pinned?.[0]}"), which the coordinator can make wrong without touching this file`);
});

test("no port call and no network call in the quiet window that a press or an explicit refresh() did not ask for",
  { timeout: dormancyTimeout(1) }, async () => {
  const parked = [];
  const published = new Set();
  const network = watchNetwork();
  try {
  /** Drive a binding into its phase, then freeze everything a poll could move:
   * both port counters, the snapshot a popup renders from, the choice on it,
   * and -- when one is watching -- how many publications it has heard. */
  const park = async ({ name, phase, options, drive }, mode) => {
    const h = harness(options);
    let notifications = 0;
    let unsubscribe = () => {};
    if (mode !== "unwatched") {
      unsubscribe = h.binding.subscribe((view) => { published.add(view.power.phase); notifications += 1; });
    }
    await drive(h);
    const where = `${name} (${mode})`;
    assert.equal(h.binding.read().power.phase, phase, `${where}: parked in the wrong phase`);
    // Before the window opens, not during it: from here this binding has no
    // listener at all, which is what a `listeners.size === 0` poll waits for.
    if (mode === "abandoned") unsubscribe();
    parked.push({
      where, h, execute: h.calls.length, reads: h.reads,
      view: h.binding.read(), choice: h.binding.read().choice,
      notifications, heard: () => notifications,
    });
  };

  for (const mode of SUBSCRIPTION_MODES) {
    for (const parkCase of PARK_CASES) await park(parkCase, mode);
  }

  assert.deepEqual(EVERY_PHASE.filter((phase) => !published.has(phase)), [],
    `every phase was published to a subscriber, so the window really covers all ${EVERY_PHASE.length}`
    + ` the coordinator declares: ${EVERY_PHASE.join(", ")}`);
  assert.equal(parked.length, PARK_CASES.length * SUBSCRIPTION_MODES.length,
    "every case is parked in every subscription mode");
  // Separate ports, so nothing one binding does can be read as another's press.
  const ports = parked.map((p) => p.h.port);
  assert.equal(new Set(ports).size, ports.length,
    "two parked bindings share a port, so one binding's poll could hide in another's counter");

  const held = await quiet();
  assert.ok(held.elapsed >= QUIET_WINDOW_MS,
    `the window was ${held.elapsed}ms, not the ${QUIET_WINDOW_MS}ms it is meant to be`);
  assert.ok(held.turns >= 100, `the window was ${held.turns} event-loop turns`);
  for (const p of parked) {
    assert.equal(p.h.calls.length, p.execute,
      `${p.where}: the port was told to execute something nobody pressed`);
    assert.equal(p.h.reads, p.reads, `${p.where}: the port was read back with nobody asking`);
    // The half a port counter does not reach: damage that never leaves the
    // binding. A retirement or a self-disposal moves one of these three.
    assert.equal(p.h.binding.read(), p.view,
      `${p.where}: the snapshot moved with nobody pressing anything`);
    assert.equal(p.h.binding.read().choice, p.choice,
      `${p.where}: the choice on screen changed with nobody pressing anything`);
    assert.equal(p.heard(), p.notifications,
      `${p.where}: a publication went out that nobody asked for`);
  }
  // The route the port counters cannot see. A green line here means "nothing
  // on the watched list fired", never "nothing reached the network" -- so the
  // count that was actually watched is asserted too, and a runtime that offers
  // none of it fails rather than passing on an empty instrument.
  assert.deepEqual(network.calls, [],
    `the module reached the network with nobody pressing anything: ${network.calls.join(", ")}`);
  assert.ok(network.named >= 1 && !network.absent.includes("fetch"),
    `the named half of the network instrument watched ${network.named} of`
    + ` ${NAMED_NETWORK_ENTRY_POINTS.length} entry points and did not get \`fetch\`, so the line above says`
    + ` nothing about the route a poll would most plainly take. Absent here: ${network.absent.join(", ")}`);
  assert.ok(network.sockets >= 8,
    `only ${network.sockets} of the socket layer's ${SOCKET_LAYER.length} names exist in this runtime to`
    + ` watch, which is too few for this assertion to mean anything. Absent here: ${network.absent.join(", ")}`);
  } finally { network.release(); }
});

/** The same invariant across an import nobody has asked anything of.
 *
 * The instance is loaded HERE, inside the test body, so whatever an import arms
 * is armed now rather than before the first test ran -- which only holds if the
 * loader really did hand back a fresh instance, so that is asserted rather than
 * assumed. The first window covers the import by itself; nothing is
 * constructed, so there is no port it could have been handed, which is exactly
 * why the second window is the load-bearing one. An import that armed a
 * repeating turn and pointed it at the first port the module was given moves a
 * counter there.
 *
 * Bounded by the same window as the test above, and with the same gap: an
 * import that arms something for longer than `QUIET_WINDOW_MS` is not excluded
 * here. */
test("importing the module, and constructing from it, asks the port and the network for nothing in the quiet window",
  { timeout: dormancyTimeout(2) }, async () => {
  const network = watchNetwork();
  try {
  const create = await load();
  assert.notEqual(create, createPowerChoiceBinding,
    "load() handed back the instance this file already holds, so this test re-covers the old import");
  const afterImport = await quiet();
  assert.ok(afterImport.elapsed >= QUIET_WINDOW_MS, `import window: ${afterImport.elapsed}ms`);

  const touched = [];
  const forbidden = {
    execute: async (...args) => {
      touched.push(["execute", ...args]);
      throw new Error("a binding nobody pressed a button on must not submit power");
    },
    readStatus: async () => {
      touched.push(["readStatus"]);
      throw new Error("a binding nobody asked for a readback must not poll");
    },
  };
  // Nothing subscribes: a poll that waits for an empty listener set has its
  // opening here too, on a binding that has never had one.
  const binding = create(forbidden, { requestId: () => firstId });
  assert.equal(binding.read().power.phase, "idle");
  assert.equal(binding.read().choice, null);
  const view = binding.read();

  const afterConstruction = await quiet();
  assert.ok(afterConstruction.elapsed >= QUIET_WINDOW_MS,
    `construction window: ${afterConstruction.elapsed}ms`);
  assert.deepEqual(touched, [],
    "the port heard from a binding whose buttons nobody has pressed");
  assert.deepEqual(network.calls, [],
    `an import or a construction nobody asked anything of reached the network: ${network.calls.join(", ")}`);
  assert.equal(binding.read(), view, "and the snapshot moved with nobody touching it");
  binding.dispose();
  } finally { network.release(); }
});

test("a captured sleep choice offers its three buttons and writes nothing", async () => {
  const h = harness();
  assert.equal(h.binding.beginSleep(request), true);
  const { power, choice } = h.binding.read();
  assert.equal(power.phase, "choosing");
  assert.equal(power.intent, "sleep");
  assert.equal(choice.intent, "sleep");
  assert.equal(typeof choice.keepConnectedAndSleep, "function");
  assert.equal(typeof choice.disconnectAndSleep, "function");
  assert.equal(typeof choice.cancel, "function");
  assert.equal(choice.confirm, undefined, "a sleep popup cannot shut the dock down");
  assert.ok(Object.isFrozen(choice));
  assert.throws(() => { choice.disconnectAndSleep = () => {}; }, TypeError, "a button cannot be replaced");
  assert.throws(() => { choice.connectionLabel = "another dock"; }, TypeError, "the label cannot be rewritten");
  assert.equal(h.calls.length, 0, "capture is not a submission");
  assert.equal(h.reads, 0, "capture is not a poll");
  await settle();
  assert.equal(h.calls.length, 0);
  assert.equal(h.reads, 0);
});

test("a captured shutdown choice offers confirm and cancel, and nothing else", async () => {
  const h = harness();
  assert.equal(h.binding.beginShutdown(request), true);
  const { power, choice } = h.binding.read();
  assert.equal(power.phase, "choosing");
  assert.equal(power.intent, "shutdown");
  assert.equal(choice.intent, "shutdown");
  assert.equal(typeof choice.confirm, "function");
  assert.equal(typeof choice.cancel, "function");
  assert.equal(choice.disconnectAndSleep, undefined, "a shutdown popup cannot sleep the dock");
  assert.equal(choice.keepConnectedAndSleep, undefined);
  // Frozen, and asserted the way the sleep branch's freeze is asserted -- plus
  // the write that proves the freeze is doing something. `Object.isFrozen`
  // alone passed on both branches for reasons that had nothing to do with this
  // branch's `Object.freeze`, so deleting that call cost nothing. A popup that
  // can have `confirm` swapped out under it is a popup whose button can be
  // pointed at another request.
  assert.ok(Object.isFrozen(choice), "a shutdown popup's buttons are frozen");
  assert.throws(() => { choice.confirm = () => {}; }, TypeError, "confirm cannot be replaced");
  assert.throws(() => { choice.cancel = () => {}; }, TypeError, "cancel cannot be replaced");
  assert.throws(() => { choice.connectionLabel = "another dock"; }, TypeError, "the label cannot be rewritten");
  assert.throws(() => { choice.intent = "sleep"; }, TypeError, "and a shutdown cannot be turned into a sleep");
  assert.equal(choice.intent, "shutdown");
  assert.equal(h.calls.length, 0);
  assert.equal(h.reads, 0);
  await settle();
  assert.equal(h.calls.length, 0);
  assert.equal(h.reads, 0);
});

// --------------------------------------------------- what the caller supplies

/** Every button a popup can press, and the action each one puts on the wire.
 *
 * "The token reaches the port unchanged" has to hold on all three. A transform
 * applied on one route and not another is still a transform, and a test that
 * presses one button cannot see it. */
const PRESSES = [
  ["whole_dock_sleep", (binding, ask) => binding.beginSleep(ask), (choice) => choice.disconnectAndSleep()],
  ["whole_dock_sleep_connected", (binding, ask) => binding.beginSleep(ask),
    (choice) => choice.keepConnectedAndSleep()],
  ["whole_dock_shutdown", (binding, ask) => binding.beginShutdown(ask), (choice) => choice.confirm()],
];
/** One admission, one press, and whatever the port was handed. The admission
 * answer is returned rather than asserted, because the two tests below want
 * opposite things from it. */
const pressOnce = async (token, [action, admit, push]) => {
  const h = harness();
  const admitted = admit(h.binding, { attachmentToken: token, connectionLabel: label });
  if (admitted) await push(h.binding.read().choice);
  return { h, admitted, action };
};

/** A token built so the obvious ways of mangling one are VISIBLE at the port.
 *
 * `attachment` is not that token, and the gap it left was measured rather than
 * feared. Sixty-four `c`s and sixty-four `d`s spend three of the seventeen
 * characters a token can be spelled with, and carry no upper case and no
 * whitespace, so `toLowerCase()`, `trim()` and every single-character replace
 * landing on one of the other fourteen are all the IDENTITY on it. Each of
 * those, written into the module on the caller's token as it goes to the
 * coordinator, used to pass this entire file.
 *
 * So this one spends all seventeen: the hex alphabet forwards on one side and
 * backwards on the other. A replace shows wherever it lands -- INCLUDING the
 * landings that leave a token the coordinator still accepts, which are the
 * dangerous ones, because those reach the wire instead of being refused on the
 * way -- and a slice shows in the length.
 *
 * Case and surrounding whitespace cannot be carried IN this token: a ticket is
 * taken only for `""` or for lower-case hex, so no admissible token has an
 * upper-case character or a space to lose. Those two transforms are made
 * falsifiable one step earlier, by the test after this one.
 *
 * One transform neither test catches, and it is an equivalent mutant rather
 * than a hole: a plain `normalize()` is the identity on every token that can be
 * admitted at all, because `[0-9a-f:]` is stable under all four forms and no
 * string outside ASCII composes into ASCII. No token a caller could supply
 * tells that mutant from the module. A COMPATIBILITY normalisation is a
 * different matter, and the test below kills it. */
const exactToken = `${"0123456789abcdef".repeat(4)}:${"fedcba9876543210".repeat(4)}`;

test("the captured token reaches the port byte for byte, on every button, empty string included", async () => {
  for (const token of [attachment, exactToken, ""]) {
    for (const route of PRESSES) {
      const { h, admitted, action } = await pressOnce(token, route);
      const where = `${action}: ${JSON.stringify(token)}`;
      assert.equal(admitted, true, `${where}: the caller's own token was not admitted`);
      assert.equal(h.calls.length, 1, `${where}: one press, one submission`);
      assert.equal(h.calls[0][1], token,
        `${where}: the port was handed ${JSON.stringify(h.calls[0][1])} instead. The bytes the caller`
        + " supplied are not the bytes that were dispatched, so this module rewrote an attachment identity"
        + " on its way to the backend.");
      assert.deepEqual(h.calls, [[action, token, firstId]], where);
      assert.equal(h.binding.read().power.phase, "requested");
    }
  }
});

/** The two transforms an admissible token cannot show, caught where they do
 * their damage instead.
 *
 * `toLowerCase()` is invisible above because every token that gets a ticket is
 * already lower case, and `trim()` is invisible because none of them carries
 * whitespace. Neither is harmless for that: both change WHICH tokens get
 * through. Each token below is one character class away from admissible, so a
 * module that quietly massages the caller's bytes turns one of them into a
 * token that dispatches -- an attachment identity nobody wrote, naming hardware
 * the caller did not name.
 *
 * The rule is written as "refused OR dispatched identical", not as "refused",
 * on purpose. Which tokens the coordinator will take a ticket for is the
 * coordinator's business and has its own suite; what belongs here is that this
 * binding does not edit the caller's token to obtain one. Widen that grammar
 * upstream and these tokens start being admitted -- and this assertion follows
 * them to the port rather than going red for somebody else's change. */
const NEAR_MISS_TOKENS = [
  ["upper-cased", attachment.toUpperCase()],
  ["surrounded by whitespace", `  ${attachment}\n`],
  // Full-width digits: plain ASCII under a compatibility normalisation, and
  // nothing like a token without one.
  ["written in full-width digits", `${"\uFF10".repeat(64)}:${"\uFF11".repeat(64)}`],
  // The three below exist because the surrounded-by-whitespace entry above
  // bundles a leading and a trailing offence together, so a HALF measure
  // stayed refused and survived: `.trimStart()` and a space-strip each left
  // the other offence behind, and the list had no over-long token at all, so
  // a length clamp had nothing to clamp. Each of these carries ONE offence,
  // so a transform that fixes just that one turns a token this binding
  // refuses into one it admits, and is caught.
  ["led by one space", ` ${exactToken}`],
  ["trailed by one newline", `${exactToken}
`],
  ["one character too long", `${exactToken}0`],
];
test("a token this binding would have to alter to get admitted is refused, never altered", async () => {
  for (const [why, token] of NEAR_MISS_TOKENS) {
    for (const route of PRESSES) {
      const { h, admitted, action } = await pressOnce(token, route);
      const where = `${action}, ${why}`;
      if (admitted) {
        assert.deepEqual(h.calls, [[action, token, firstId]],
          `${where}: the binding changed the caller's token into one that got admitted, so bytes nobody`
          + " supplied reached the port");
      } else {
        assert.equal(h.calls.length, 0, `${where}: a refused admission dispatched something anyway`);
        assert.equal(h.binding.read().choice, null, `${where}: a refused admission left a popup on screen`);
        assert.equal(h.binding.read().power.phase, "idle", `${where}: a refused admission moved the phase`);
      }
    }
  }
});

test("a token the caller never supplied is refused, never invented", async () => {
  const seen = [];
  const h = harness();
  const unsubscribe = h.binding.subscribe((view) => seen.push(view));
  const idle = h.binding.read();
  for (const absent of [{}, { attachmentToken: undefined }, { attachmentToken: null },
    { attachmentToken: 0 }, { attachmentToken: {} }, { attachmentToken: ["" ] }]) {
    const missing = { connectionLabel: label, ...absent };
    assert.equal(h.binding.beginSleep(missing), false, `sleep: ${JSON.stringify(absent)}`);
    assert.equal(h.binding.beginShutdown(missing), false, `shutdown: ${JSON.stringify(absent)}`);
  }
  assert.equal(h.binding.read(), idle, "a refused admission publishes nothing");
  assert.equal(h.binding.read().choice, null, "and shows no popup");
  assert.equal(h.binding.read().power.phase, "idle");
  assert.deepEqual(seen, [], "presentation is told nothing happened, because nothing did");
  assert.equal(h.calls.length, 0, "an absent token is never dispatched as an empty one");
  assert.equal(h.reads, 0);
  await settle();
  assert.equal(h.calls.length, 0);
  assert.equal(h.reads, 0);
  unsubscribe();

  // An explicitly empty token is a topology the coordinator documents as legal,
  // and the binding is not entitled to second-guess it.
  assert.equal(h.binding.beginSleep({ attachmentToken: "", connectionLabel: label }), true);
  await h.binding.read().choice.disconnectAndSleep();
  assert.deepEqual(h.calls, [["whole_dock_sleep", "", firstId]],
    "the refusals consumed neither a request identity nor the single-flight slot");
  assert.equal(h.binding.read().power.phase, "requested");
});

/** The token's rule, one field over. A caller that omitted `connectionLabel`
 * used to be ADMITTED: the coordinator took a ticket, the binding put a
 * dispatchable choice on screen, and `true` came back telling the owner to
 * render a popup whose words are `undefined`. "The caller forgot the words" and
 * "the caller meant no words" are different facts, exactly as they are for the
 * token, so an absent label is refused rather than coerced to "".
 *
 * The refusal has to leave the binding untouched in the same three ways the
 * token's does -- no publication, no ticket, no burned identity -- because a
 * refusal that consumed the single-flight slot would wedge every later request
 * behind a popup that was never shown. */
test("a connection label the caller never supplied is refused, never coerced to empty", async () => {
  const seen = [];
  const h = harness();
  const unsubscribe = h.binding.subscribe((view) => seen.push(view));
  const idle = h.binding.read();
  for (const absent of [{}, { connectionLabel: undefined }, { connectionLabel: null },
    { connectionLabel: 0 }, { connectionLabel: {} }, { connectionLabel: ["dock"] },
    { connectionLabel: Symbol("dock") }]) {
    const missing = { attachmentToken: attachment, ...absent };
    assert.equal(h.binding.beginSleep(missing), false, `sleep: ${String(absent.connectionLabel)}`);
    assert.equal(h.binding.beginShutdown(missing), false, `shutdown: ${String(absent.connectionLabel)}`);
  }
  assert.equal(h.binding.read(), idle, "a refused admission publishes nothing");
  assert.equal(h.binding.read().choice, null, "and puts no popup up with no words on it");
  assert.equal(h.binding.read().power.phase, "idle");
  assert.deepEqual(seen, [], "presentation is told nothing happened, because nothing did");
  assert.equal(h.calls.length, 0, "and nothing is dispatched for a request nobody could read");
  assert.equal(h.reads, 0);
  await settle();
  assert.equal(h.calls.length, 0);
  assert.equal(h.reads, 0);
  unsubscribe();

  // An explicitly empty label is the caller's decision, the way an empty token
  // is, and the binding is not entitled to second-guess it.
  assert.equal(h.binding.beginSleep({ attachmentToken: attachment, connectionLabel: "" }), true);
  assert.equal(h.binding.read().choice.connectionLabel, "");
  await h.binding.read().choice.disconnectAndSleep();
  assert.deepEqual(h.calls, [["whole_dock_sleep", attachment, firstId]],
    "the refusals consumed neither a request identity nor the single-flight slot");
  assert.equal(h.binding.read().power.phase, "requested");
});

test("the connection label is rendered exactly as the caller wrote it", () => {
  for (const text of ["", "  RX 7600M XT  ", "Dock ⚡ (unidentified)", "eGPU"]) {
    const sleeping = harness();
    sleeping.binding.beginSleep({ attachmentToken: attachment, connectionLabel: text });
    assert.equal(sleeping.binding.read().choice.connectionLabel, text, JSON.stringify(text));

    const stopping = harness();
    stopping.binding.beginShutdown({ attachmentToken: "", connectionLabel: text });
    assert.equal(stopping.binding.read().choice.connectionLabel, text, JSON.stringify(text));
  }
});

test("admission is reported, and a refused admission writes nothing", () => {
  const h = harness();
  assert.equal(h.binding.beginSleep({ attachmentToken: "not-a-token", connectionLabel: label }), false);
  assert.equal(h.binding.read().choice, null);
  assert.equal(h.binding.read().power.phase, "idle");
  assert.equal(h.calls.length, 0);
  assert.equal(h.reads, 0);

  assert.equal(h.binding.beginShutdown(request), true);
  const live = h.binding.read().choice;
  assert.equal(h.binding.beginSleep(request), false, "one power request at a time");
  assert.equal(h.binding.read().choice, live, "a refused admission leaves the live popup its buttons");
  assert.equal(h.binding.read().power.intent, "shutdown");
  assert.equal(h.calls.length, 0);
});

test("a request that fails while it is being read leaves no ticket wedged", async () => {
  const h = harness();
  const badToken = {
    get attachmentToken() { throw new Error("token accessor failed"); },
    connectionLabel: label,
  };
  const badLabel = {
    attachmentToken: attachment,
    get connectionLabel() { throw new Error("label accessor failed"); },
  };
  assert.throws(() => h.binding.beginSleep(badToken), /token accessor failed/,
    "the owner is told its request object is broken");
  assert.throws(() => h.binding.beginShutdown(badLabel), /label accessor failed/);
  assert.throws(() => h.binding.beginSleep(badLabel), /label accessor failed/);
  assert.equal(h.binding.read().power.phase, "idle", "and no request survives the failure");
  assert.equal(h.binding.read().choice, null);
  assert.equal(h.calls.length, 0);
  assert.equal(h.reads, 0);

  // The single-flight slot is the point: a ticket held by the coordinator with
  // no popup to cancel it would refuse every later request, forever.
  assert.equal(h.binding.beginSleep(request), true, "the binding still admits the next request");
  assert.equal(h.binding.read().power.requestId, firstId, "and the failures burned no identity");
  await h.binding.read().choice.disconnectAndSleep();
  assert.deepEqual(h.calls, [["whole_dock_sleep", attachment, firstId]]);
  assert.equal(h.binding.read().power.phase, "requested");
});

/** `requestId` is the caller's function and it runs inside the coordinator's
 * admission, which is inside this binding's capture. An owner that asks for a
 * second choice from in there opens a capture inside a capture -- and if
 * suppression were a flag rather than a count, the inner one's exit would clear
 * it, and the outer ticket's `choosing` would go out paired with the inner
 * request's popup: a snapshot whose requestId and whose buttons belong to two
 * different requests, one of them already displaced. */
test("a capture nested inside another stays suppressed until the outer one ends", () => {
  const calls = [];
  const port = {
    execute: async (...args) => { calls.push(args); return accepted(...args); },
    readStatus: async () => { throw new Error("a capture is not a poll"); },
  };
  let binding;
  let reentered = false;
  binding = createPowerChoiceBinding(port, {
    requestId: () => {
      if (reentered) return secondId;
      reentered = true;
      binding.beginShutdown({ attachmentToken: otherAttachment, connectionLabel: "inner" });
      return firstId;
    },
  });
  const seen = [];
  binding.subscribe((view) => seen.push(view));

  assert.equal(binding.beginSleep({ attachmentToken: attachment, connectionLabel: "outer" }), true);
  assert.ok(reentered, "the caller's identity generator captured again from inside the capture");

  const owner = { [secondId]: "inner", [firstId]: "outer" };
  for (const view of seen) {
    if (!view.choice) continue;
    assert.equal(view.choice.connectionLabel, owner[view.power.requestId],
      `a request was published holding the "${view.choice.connectionLabel}" popup`);
  }
  assert.equal(seen.length, 2, "one publication per capture, and nothing in between");
  assert.equal(binding.read().power.requestId, firstId, "the outer admission is the live one");
  assert.equal(binding.read().choice.connectionLabel, "outer");
  assert.equal(calls.length, 0);
});

/** The one path on which a REFUSED admission still has something to publish,
 * and the whole reason the refusal branch publishes at all.
 *
 * Inside the outer capture, the caller's `requestId` captures a choice of its
 * own and then dismisses it. That dismissal's `idle` is suppressed -- it is
 * raised inside a capture -- but it has already cleared the choice. Then the
 * outer admission fails, so nothing else will ever publish for it. Without the
 * publish on the refusal branch, `read()` is left holding the dismissed
 * popup's snapshot: buttons the coordinator has already stopped answering, on
 * a binding that is idle, with no publication coming to correct it. */
test("an admission refused after a suppressed dismissal still publishes the dismissal", () => {
  let issued = 0;
  const calls = [];
  const port = {
    execute: async (...args) => { calls.push(args); return accepted(...args); },
    readStatus: async () => { throw new Error("a capture is not a poll"); },
  };
  let binding;
  let nested = false;
  binding = createPowerChoiceBinding(port, {
    requestId: () => {
      if (nested) return idAt(issued++);
      nested = true;
      assert.equal(binding.beginSleep({ attachmentToken: attachment, connectionLabel: "inner" }), true);
      binding.read().choice.cancel();
      // Not a usable identity, so the outer admission is refused.
      return "not-a-valid-request-id";
    },
  });
  const seen = [];
  binding.subscribe((view) => seen.push([view.power.phase, view.choice?.connectionLabel ?? null]));

  assert.equal(binding.beginShutdown({ attachmentToken: otherAttachment, connectionLabel: "outer" }), false,
    "the outer admission was refused");
  assert.ok(nested, "the caller's identity generator captured and dismissed from inside the capture");
  assert.deepEqual(seen, [["choosing", "inner"], ["idle", null]],
    "the dismissal reaches presentation, late but exactly once");
  assert.equal(binding.read().choice, null,
    "no popup is left holding buttons for a ticket that was already dismissed");
  assert.equal(binding.read().power.phase, "idle");
  assert.equal(calls.length, 0);
});

// -------------------------------------------------------------- retirement

test("the choice retires the moment the request is over", async () => {
  const cancelled = harness();
  cancelled.binding.beginSleep(request);
  cancelled.binding.read().choice.cancel();
  assert.equal(cancelled.binding.read().power.phase, "idle");
  assert.equal(cancelled.binding.read().choice, null, "idle");

  const refused = harness({
    execute: async (...args) => accepted(...args, { power_requested: false, ok: false, code: "dock_power.sleep_unverified" }),
  });
  refused.binding.beginSleep(request);
  await refused.binding.read().choice.disconnectAndSleep();
  assert.equal(refused.binding.read().power.phase, "refused");
  assert.equal(refused.binding.read().choice, null, "refused");

  const slept = harness({
    execute: async (...args) => accepted(...args, { sleep_cycle_observed: true, code: "dock_power.sleep_cycle_observed" }),
  });
  slept.binding.beginSleep(request);
  await slept.binding.read().choice.disconnectAndSleep();
  assert.equal(slept.binding.read().power.phase, "sleep_observed");
  assert.equal(slept.binding.read().choice, null, "sleep_observed");

  const gone = harness();
  gone.binding.beginShutdown(request);
  gone.binding.dispose();
  assert.equal(gone.binding.read().power.phase, "disposed");
  assert.equal(gone.binding.read().choice, null, "disposed");
});

test("an accepted submission is not a completed sleep, and does not close the popup", async () => {
  const h = harness();
  h.binding.beginSleep(request);
  const choice = h.binding.read().choice;
  await choice.keepConnectedAndSleep();
  assert.equal(h.binding.read().power.phase, "requested");
  assert.equal(h.binding.read().choice, choice, "power_requested is a submission, not an observed sleep");

  const unverified = harness({ execute: async () => ({ schema_version: 1, request_id: firstId }) });
  unverified.binding.beginSleep(request);
  const pendingChoice = unverified.binding.read().choice;
  await pendingChoice.disconnectAndSleep();
  assert.equal(unverified.binding.read().power.phase, "uncertain");
  assert.equal(unverified.binding.read().choice, pendingChoice, "an unknown outcome is still an operation");
});

test("the popup keeps its buttons while the request is dispatching", async () => {
  const waiting = deferred();
  const h = harness({ execute: () => waiting.promise });
  const seen = [];
  h.binding.subscribe((view) => seen.push([view.power.phase, view.choice]));
  h.binding.beginSleep(request);
  const choice = h.binding.read().choice;
  const running = choice.disconnectAndSleep();
  const dispatching = seen.find(([phase]) => phase === "dispatching");
  assert.ok(dispatching, "presentation is told the press was taken");
  assert.equal(dispatching[1], choice);
  assert.equal(h.binding.read().choice, choice);
  waiting.resolve(accepted("whole_dock_sleep", attachment, firstId));
  await running;
  assert.equal(h.binding.read().power.phase, "requested");
  assert.equal(h.calls.length, 1);
});

// ------------------------------------------------------- stale popup buttons

test("buttons from a retired popup never act on the request that replaced it", async () => {
  const h = harness();
  h.binding.beginSleep({ attachmentToken: attachment, connectionLabel: "old dock" });
  const old = h.binding.read().choice;
  old.cancel();
  assert.equal(h.binding.read().choice, null);

  assert.equal(h.binding.beginShutdown({ attachmentToken: otherAttachment, connectionLabel: "new dock" }), true);
  const current = h.binding.read().choice;
  const snapshot = h.binding.read();
  old.cancel();
  await old.disconnectAndSleep();
  await old.keepConnectedAndSleep();
  assert.equal(h.calls.length, 0, "a retired popup cannot dispatch");
  assert.equal(h.binding.read(), snapshot, "and cannot disturb the current request");
  assert.equal(h.binding.read().choice, current);
  assert.equal(current.connectionLabel, "new dock");
  assert.equal(h.binding.read().power.phase, "choosing");
  assert.equal(h.binding.read().power.intent, "shutdown");

  await current.confirm();
  assert.deepEqual(h.calls, [["whole_dock_shutdown", otherAttachment, secondId]]);
});

/** The replacement that actually distinguishes a ticket-bound button from one
 * resolved against whatever is current: same intent, so every button the stale
 * popup holds also exists on the live request. A binding that looked the
 * buttons up instead of keeping them would sleep the new dock from the old
 * popup, and a sleep-replaced-by-shutdown test would never notice. */
test("a stale sleep popup cannot drive the sleep that replaced it", async () => {
  const h = harness();
  h.binding.beginSleep({ attachmentToken: attachment, connectionLabel: "old dock" });
  const old = h.binding.read().choice;
  old.cancel();
  assert.equal(h.binding.read().choice, null);

  assert.equal(h.binding.beginSleep({ attachmentToken: otherAttachment, connectionLabel: "new dock" }), true);
  const current = h.binding.read().choice;
  const snapshot = h.binding.read();
  assert.notEqual(current, old, "a second capture is a second popup");

  await old.disconnectAndSleep();
  await old.keepConnectedAndSleep();
  old.cancel();
  assert.equal(h.calls.length, 0, "the retired popup's own buttons reach nothing");
  assert.equal(h.binding.read(), snapshot, "and leave the live request exactly where it was");
  assert.equal(h.binding.read().choice, current);
  assert.equal(current.connectionLabel, "new dock");
  assert.equal(h.binding.read().power.phase, "choosing");
  assert.equal(h.binding.read().power.intent, "sleep");
  assert.equal(h.binding.read().power.requestId, secondId);

  await current.disconnectAndSleep();
  assert.deepEqual(h.calls, [["whole_dock_sleep", otherAttachment, secondId]],
    "only the live popup's button dispatches, with the live token and identity");
});

test("a stale shutdown popup cannot drive the shutdown that replaced it", async () => {
  const h = harness();
  h.binding.beginShutdown({ attachmentToken: attachment, connectionLabel: "old dock" });
  const old = h.binding.read().choice;
  old.cancel();
  assert.equal(h.binding.read().choice, null);

  assert.equal(h.binding.beginShutdown({ attachmentToken: otherAttachment, connectionLabel: "new dock" }), true);
  const current = h.binding.read().choice;
  const snapshot = h.binding.read();
  assert.notEqual(current, old);

  await old.confirm();
  old.cancel();
  assert.equal(h.calls.length, 0, "the retired popup's confirm reaches nothing");
  assert.equal(h.binding.read(), snapshot);
  assert.equal(h.binding.read().choice, current);
  assert.equal(current.connectionLabel, "new dock");
  assert.equal(h.binding.read().power.phase, "choosing");
  assert.equal(h.binding.read().power.intent, "shutdown");
  assert.equal(h.binding.read().power.requestId, secondId);

  await current.confirm();
  assert.deepEqual(h.calls, [["whole_dock_shutdown", otherAttachment, secondId]]);
});

test("dismissing before the press writes nothing; after it, nothing is recalled or replayed", async () => {
  const before = harness();
  before.binding.beginSleep(request);
  const dismissed = before.binding.read().choice;
  dismissed.cancel();
  dismissed.cancel();
  assert.equal(before.calls.length, 0);
  assert.equal(before.reads, 0);
  assert.equal(before.binding.read().power.phase, "idle");
  assert.equal(before.binding.read().choice, null);

  const after = harness();
  after.binding.beginShutdown(request);
  const choice = after.binding.read().choice;
  await choice.confirm();
  assert.equal(after.calls.length, 1);
  const settled = after.binding.read();
  choice.cancel();
  await choice.confirm();
  await settle();
  assert.equal(after.calls.length, 1, "a second press is not a second request");
  assert.equal(after.reads, 0);
  assert.equal(after.binding.read(), settled, "and cancelling a submitted request changes nothing");
});

// ---------------------------------------------------------- presentation

test("a popup that throws, re-enters or disposes cannot change the dispatch", async () => {
  const noisy = harness();
  const seen = [];
  noisy.binding.subscribe(() => { throw new Error("popup render failed"); });
  noisy.binding.subscribe((view) => seen.push(view.power.phase));
  noisy.binding.beginSleep(request);
  await noisy.binding.read().choice.disconnectAndSleep();
  assert.deepEqual(noisy.calls, [["whole_dock_sleep", attachment, firstId]]);
  assert.equal(noisy.binding.read().power.phase, "requested");
  assert.deepEqual(seen, ["choosing", "dispatching", "requested"], "a failing subscriber does not silence the others");

  const reentrant = harness();
  const identities = [];
  reentrant.binding.subscribe((view) => identities.push(view === reentrant.binding.read()));
  reentrant.binding.beginSleep(request);
  await reentrant.binding.read().choice.keepConnectedAndSleep();
  assert.ok(identities.length > 0);
  assert.ok(identities.every(Boolean), "a re-entrant read sees the snapshot being published");
  assert.equal(reentrant.calls.length, 1);
  assert.equal(reentrant.binding.read().power.phase, "requested");

  const disposing = harness();
  disposing.binding.subscribe((view) => { if (view.power.phase === "requested") disposing.binding.dispose(); });
  disposing.binding.beginShutdown(request);
  await disposing.binding.read().choice.confirm();
  assert.equal(disposing.calls.length, 1, "disposal does not recall a committed submission");
  assert.equal(disposing.reads, 0);
  assert.equal(disposing.binding.read().power.phase, "disposed");
  assert.equal(disposing.binding.read().choice, null);
});

/** One queue, one order. A subscriber that publishes again mid-delivery must
 * not be served ahead of the listeners already owed the publication in flight:
 * a nested fan-out runs to completion first, so everyone behind the re-entrant
 * popup is handed the queue backwards and finishes on the oldest snapshot --
 * the one carrying buttons for a ticket that has already been retired. */
test("every listener is handed every publication in the same order", () => {
  const h = harness();
  const front = [];
  const back = [];
  let reentered = false;
  h.binding.subscribe((view) => {
    front.push(view);
    if (reentered || view.power.phase !== "choosing") return;
    reentered = true;
    h.binding.read().choice.cancel();
  });
  h.binding.subscribe((view) => back.push(view));

  assert.equal(h.binding.beginSleep(request), false,
    "the first listener cancelled the choice during the publication announcing it");
  assert.ok(reentered, "the first listener published from inside the delivery");
  assert.equal(front.length, 2);
  assert.equal(back.length, 2);
  sameOrder(back, front, "the listener behind the re-entrant one");
  assert.equal(back[0].power.phase, "choosing", "and it still receives the choosing snapshot");
  assert.ok(back[0].choice, "carrying the choice that publication was about");
  assert.equal(back[0].choice, front[0].choice);
  assert.equal(back[1].power.phase, "idle", "the re-entrant publication is queued behind, not nested inside");
  assert.notEqual(back[0], back[1], "and nobody is handed the same snapshot twice");
  assert.equal(h.binding.read(), back[1], "read() is always the newest");
  assert.equal(h.binding.read().choice, null);
  assert.equal(h.calls.length, 0);
});

/** The same claim under load: one listener that publishes from inside its own
 * delivery, one that throws every time, three that only record -- in every
 * arrangement that puts the re-entrant popup first, in the middle and last, and
 * at one and two levels of re-entry. */
const layout = (position, log, reenter) => {
  const thrower = () => { throw new Error("popup render failed"); };
  const record = (slot) => (view) => log[slot].push(view);
  const both = (slot) => (view) => { log[slot].push(view); reenter(view); };
  if (position === "first") return [both(0), thrower, record(1), record(2)];
  if (position === "middle") return [record(0), thrower, both(1), record(2)];
  return [record(0), record(1), thrower, both(2)];
};
for (const position of ["first", "middle", "last"]) {
  for (const levels of [1, 2]) {
    test(`publications stay serialized: re-entrant popup ${position}, ${levels} level(s) deep`, () => {
      let issued = 0;
      const h = harness({ requestId: () => idAt(issued++) });
      const log = [[], [], []];
      let remaining = levels;
      const reenter = (view) => {
        if (remaining <= 0) return;
        remaining -= 1;
        // Retire the popup, then capture a new one: two real publications,
        // each with its own snapshot, raised from inside a delivery.
        if (view.choice) view.choice.cancel();
        else h.binding.beginSleep(request);
      };
      layout(position, log, reenter).forEach((listener) => h.binding.subscribe(listener));

      assert.equal(h.binding.beginSleep(request), false,
        "the re-entrant popup cancelled this choice during the publication announcing it");
      assert.equal(remaining, 0, "the re-entrant popup published from inside its own delivery");
      const expected = 1 + levels;
      for (const [slot, seen] of log.entries()) {
        assert.equal(seen.length, expected, `listener ${slot} received ${seen.length} of ${expected}`);
        assert.equal(new Set(seen).size, expected, `listener ${slot} was handed a snapshot twice`);
        sameOrder(seen, log[0], `listener ${slot} against listener 0`);
        assert.equal(seen[seen.length - 1], h.binding.read(),
          `listener ${slot} finished on the newest snapshot`);
      }
      assert.equal(log[0][0].power.phase, "choosing", "the first publication carried the buttons");
      assert.ok(log[0][0].choice);
      assert.equal(h.calls.length, 0, "and none of it dispatched anything");
      assert.equal(h.reads, 0);
    });
  }
}

/** What the ordering is actually protecting: the popup renders whatever it was
 * handed last. Behind a re-entrant listener publishing twice, a nested fan-out
 * leaves that last delivery holding the FIRST publication -- a choice already
 * cancelled, with buttons the coordinator has stopped answering. */
test("the popup behind a re-entrant listener never ends up rendering a retired choice", async () => {
  let issued = 0;
  const h = harness({ requestId: () => idAt(issued++) });
  const rendered = [];
  let steps = 2;
  h.binding.subscribe((view) => {
    if (steps <= 0) return;
    steps -= 1;
    if (view.choice) view.choice.cancel();
    else h.binding.beginSleep({ attachmentToken: otherAttachment, connectionLabel: "new dock" });
  });
  h.binding.subscribe(() => { throw new Error("popup render failed"); });
  h.binding.subscribe((view) => rendered.push(view));

  assert.equal(h.binding.beginSleep({ attachmentToken: attachment, connectionLabel: "old dock" }), false,
    "the old dock's choice was cancelled and replaced during the publication announcing it");
  assert.equal(steps, 0, "two publications were raised from inside the delivery");

  const onScreen = rendered[rendered.length - 1];
  assert.equal(onScreen, h.binding.read(), "the popup is left rendering the newest snapshot, not the oldest");
  assert.equal(onScreen.power.phase, "choosing");
  assert.ok(onScreen.choice, "and it is holding buttons");
  assert.equal(onScreen.choice.connectionLabel, "new dock", "for the request that is actually live");
  await onScreen.choice.disconnectAndSleep();
  assert.deepEqual(h.calls, [["whole_dock_sleep", otherAttachment, idAt(1)]],
    "so pressing one dispatches, instead of reaching a ticket that is already gone");
});

/** The tests above never put more than one publication in the queue at a time:
 * each re-entrant turn raises one, and it is delivered before the next turn can
 * raise another. At depth one, first-out and last-out are the same element, so
 * none of them can tell a queue from a stack.
 *
 * These three hold two or more publications at once. The order is asserted
 * element by element, for every listener, because that is the claim: not that
 * everyone saw the same set, but that everyone saw the same sequence, oldest
 * first, ending on the snapshot `read()` returns. */
const phasesOf = (log) => log.map((view) => view.power.phase);
const labelsOf = (log) => log.map((view) => view.choice?.connectionLabel ?? null);

test("two publications raised in one turn are delivered oldest first", async () => {
  let issued = 0;
  const h = harness({ requestId: () => idAt(issued++) });
  const front = [];
  const middle = [];
  const back = [];
  let reentered = false;
  h.binding.subscribe((view) => {
    front.push(view);
    if (reentered) return;
    reentered = true;
    // Two publications, one turn: the queue is two deep while the delivery
    // that provoked it is still running.
    view.choice.cancel();
    h.binding.beginSleep({ attachmentToken: otherAttachment, connectionLabel: "new dock" });
  });
  h.binding.subscribe((view) => middle.push(view));
  h.binding.subscribe((view) => back.push(view));

  assert.equal(h.binding.beginSleep({ attachmentToken: attachment, connectionLabel: "old dock" }), false,
    "the old dock's choice was cancelled and replaced during the publication announcing it");
  assert.ok(reentered, "the listener published twice from inside its own delivery");
  for (const [name, log] of [["front", front], ["middle", middle], ["back", back]]) {
    assert.deepEqual(phasesOf(log), ["choosing", "idle", "choosing"], `${name}: phases, in order`);
    assert.deepEqual(labelsOf(log), ["old dock", null, "new dock"], `${name}: popups, in order`);
    assert.equal(new Set(log).size, 3, `${name}: was handed a snapshot twice`);
    sameOrder(log, front, `${name} against front`);
    assert.equal(log[log.length - 1], h.binding.read(), `${name}: finished on the newest snapshot`);
  }
  assert.equal(h.calls.length, 0, "none of it dispatched anything");
  await back[back.length - 1].choice.disconnectAndSleep();
  assert.deepEqual(h.calls, [["whole_dock_sleep", otherAttachment, idAt(1)]],
    "and the popup is left holding buttons for the request that is actually live");
});

test("two different listeners publishing in one delivery are delivered oldest first", async () => {
  let issued = 0;
  const h = harness({ requestId: () => idAt(issued++) });
  const log = [[], [], []];
  let retired = false;
  let captured = false;
  h.binding.subscribe((view) => {
    log[0].push(view);
    if (retired) return;
    retired = true;
    view.choice.cancel();
  });
  h.binding.subscribe((view) => {
    log[1].push(view);
    if (captured) return;
    captured = true;
    // Raised from the same delivery as the cancel above, and behind it.
    h.binding.beginSleep({ attachmentToken: otherAttachment, connectionLabel: "new dock" });
  });
  h.binding.subscribe((view) => log[2].push(view));

  assert.equal(h.binding.beginSleep({ attachmentToken: attachment, connectionLabel: "old dock" }), false,
    "one listener cancelled this choice and the next replaced it, both inside its announcement");
  assert.ok(retired && captured, "both listeners published from inside the same delivery");
  for (const [slot, seen] of log.entries()) {
    assert.deepEqual(phasesOf(seen), ["choosing", "idle", "choosing"], `listener ${slot}: phases, in order`);
    assert.deepEqual(labelsOf(seen), ["old dock", null, "new dock"], `listener ${slot}: popups, in order`);
    sameOrder(seen, log[0], `listener ${slot} against listener 0`);
    assert.equal(seen[seen.length - 1], h.binding.read(), `listener ${slot}: finished on the newest snapshot`);
  }
  assert.equal(h.binding.read().power.requestId, idAt(1), "the live request is the one published last");
  assert.equal(h.calls.length, 0);
  assert.equal(h.reads, 0);
});

/** Four deep, and the phases repeat: `idle`, `choosing`, `idle`, `choosing`.
 * A drain that collapsed the queue to what looks new -- newest only, or one
 * publication per phase -- would hand the popup a plausible-looking subset and
 * leave it on the wrong one. */
test("a queue four deep is drained in full, in order, repeated phases included", async () => {
  let issued = 0;
  const h = harness({ requestId: () => idAt(issued++) });
  const thirdAttachment = `${"1".repeat(64)}:${"2".repeat(64)}`;
  const log = [[], []];
  let reentered = false;
  h.binding.subscribe((view) => {
    log[0].push(view);
    if (reentered) return;
    reentered = true;
    view.choice.cancel();
    h.binding.beginSleep({ attachmentToken: otherAttachment, connectionLabel: "dock A" });
    h.binding.read().choice.cancel();
    h.binding.beginSleep({ attachmentToken: thirdAttachment, connectionLabel: "dock B" });
  });
  h.binding.subscribe(() => { throw new Error("popup render failed"); });
  h.binding.subscribe((view) => log[1].push(view));

  assert.equal(h.binding.beginSleep({ attachmentToken: attachment, connectionLabel: "old dock" }), false,
    "the old dock's choice was cancelled and twice replaced during the publication announcing it");
  assert.ok(reentered, "four publications were raised from inside one delivery");
  for (const [slot, seen] of log.entries()) {
    assert.deepEqual(phasesOf(seen), ["choosing", "idle", "choosing", "idle", "choosing"],
      `listener ${slot}: every publication, in order`);
    assert.deepEqual(labelsOf(seen), ["old dock", null, "dock A", null, "dock B"],
      `listener ${slot}: every popup, in order`);
    assert.equal(new Set(seen).size, 5, `listener ${slot}: was handed a snapshot twice`);
    sameOrder(seen, log[0], `listener ${slot} against listener 0`);
    assert.equal(seen[seen.length - 1], h.binding.read(), `listener ${slot}: finished on the newest snapshot`);
  }
  assert.equal(h.calls.length, 0, "and a throwing popup in the middle reordered nothing");
  await log[1][4].choice.disconnectAndSleep();
  assert.deepEqual(h.calls, [["whole_dock_sleep", thirdAttachment, idAt(2)]]);
});

/** Every sequence above alternates -- choosing, idle, choosing, idle -- so a
 * drain that silently SKIPPED a queued publication whose phase matched the one
 * it had just delivered would pass all of them, and the popups would be a
 * publication short without a single assertion moving. The ordering guarantee
 * has two halves and only one of them has been falsifiable: nothing is
 * reordered, and nothing is omitted. This is the second.
 *
 * Two adjacent `choosing` publications, queued together, come out of a capture
 * nested inside another: the inner one publishes its own `choosing` when its
 * capture closes, and the outer publishes a second one when its admission
 * displaces the inner. Raise that from inside a delivery and both sit in the
 * queue, back to back, same phase, different snapshots -- and the second is the
 * live one, so a drain that collapsed them would leave every popup holding
 * buttons for a ticket the coordinator has already displaced. */
test("two adjacent queued publications sharing a phase are both delivered", () => {
  let issued = 0;
  const calls = [];
  const port = {
    execute: async (...args) => { calls.push(args); return accepted(...args); },
    readStatus: async () => { throw new Error("a capture is not a poll"); },
  };
  let binding;
  let nesting = false;
  binding = createPowerChoiceBinding(port, {
    requestId: () => {
      if (nesting) {
        nesting = false;
        binding.beginShutdown({ attachmentToken: otherAttachment, connectionLabel: "inner" });
      }
      return idAt(issued++);
    },
  });
  const log = [[], []];
  let reentered = false;
  binding.subscribe((view) => {
    log[0].push(view);
    if (reentered) return;
    reentered = true;
    // Retire the live choice, then capture a replacement whose own identity
    // generator captures again from inside it. Three publications are queued
    // behind the delivery still running, and the last two share a phase.
    view.choice.cancel();
    nesting = true;
    binding.beginSleep({ attachmentToken: attachment, connectionLabel: "outer" });
  });
  binding.subscribe(() => { throw new Error("popup render failed"); });
  binding.subscribe((view) => log[1].push(view));

  assert.equal(binding.beginSleep({ attachmentToken: attachment, connectionLabel: "first" }), false,
    "the first choice was retired during the publication announcing it");
  assert.equal(nesting, false, "the replacement's identity generator captured again from inside it");
  assert.equal(issued, 3, "three identities were minted, so three captures really happened");

  for (const [slot, seen] of log.entries()) {
    assert.deepEqual(phasesOf(seen), ["choosing", "idle", "choosing", "choosing"],
      `listener ${slot}: the two adjacent publications sharing a phase both arrive`);
    assert.deepEqual(labelsOf(seen), ["first", null, "inner", "outer"],
      `listener ${slot}: and they are different popups, in order`);
    assert.equal(new Set(seen).size, 4, `listener ${slot}: was handed a snapshot twice`);
    sameOrder(seen, log[0], `listener ${slot} against listener 0`);
    assert.equal(seen[seen.length - 1], binding.read(), `listener ${slot}: finished on the newest snapshot`);
  }
  assert.equal(binding.read().choice.connectionLabel, "outer",
    "the later of the two is the live one, which is why dropping it would matter");
  assert.equal(calls.length, 0);
});

test("a listener that throws costs the publications behind it nothing", () => {
  const h = harness();
  const seen = [];
  let thrown = 0;
  let reentered = false;
  h.binding.subscribe((view) => {
    thrown += 1;
    if (!reentered && view.power.phase === "choosing") {
      reentered = true;
      h.binding.read().choice.cancel();
    }
    throw new Error("popup render failed");
  });
  h.binding.subscribe((view) => seen.push(view.power.phase));

  assert.equal(h.binding.beginSleep(request), false,
    "the thrower cancelled the choice before it threw, during the publication announcing it");
  assert.equal(thrown, 2, "the thrower is re-entered for the publication it raised");
  assert.deepEqual(seen, ["choosing", "idle"],
    "a throw mid-drain abandons neither the queue nor the listeners behind it");
  assert.equal(h.binding.read().choice, null);

  // And the drain flag survived: the next publication starts its own.
  assert.equal(h.binding.beginShutdown(request), true);
  assert.deepEqual(seen, ["choosing", "idle", "choosing"]);
  assert.equal(h.calls.length, 0);
});

test("a delivered snapshot is frozen, not only the idle one", () => {
  const h = harness();
  const delivered = [];
  h.binding.subscribe((view) => delivered.push(view));
  assert.equal(h.binding.beginSleep(request), true);
  h.binding.read().choice.cancel();

  assert.equal(delivered.length, 2);
  for (const [index, view] of delivered.entries()) {
    assert.ok(Object.isFrozen(view), `publication ${index} is handed out frozen`);
    assert.throws(() => { view.choice = null; }, TypeError, `publication ${index}: choice`);
    assert.throws(() => { view.power = null; }, TypeError, `publication ${index}: power`);
  }
  assert.ok(Object.isFrozen(delivered[0].choice), "and so are the buttons inside it");
  assert.equal(delivered[0].power.phase, "choosing");
  assert.equal(delivered[1].choice, null);
});

test("a popup unsubscribed during a fan-out never receives that publication", () => {
  const h = harness();
  const late = [];
  let detachLate = () => {};
  h.binding.subscribe(() => { detachLate(); });
  detachLate = h.binding.subscribe((view) => late.push(view.power.phase));

  assert.equal(h.binding.beginSleep(request), true);
  assert.deepEqual(late, [], "detached before its turn is detached");
  assert.equal(h.binding.read().power.phase, "choosing");
  h.binding.read().choice.cancel();
  assert.deepEqual(late, [], "and it stays detached");
  assert.equal(h.calls.length, 0);
});

/** The drain copies the listener set before each fan-out, and that copy is a
 * decision about one case: a popup that mounts from inside a delivery. Iterate
 * the live set instead and it is handed the publication already in flight --
 * a publication reporting a change from a state it was not attached for, so it
 * would render a transition it has no "before" for. It should be attached from
 * the next publication on. */
test("a popup that mounts mid-fan-out is attached for what comes next, not for what is in flight", () => {
  const h = harness();
  const late = [];
  const tail = [];
  let mounted = false;
  h.binding.subscribe((view) => {
    if (mounted || view.power.phase !== "choosing") return;
    mounted = true;
    h.binding.subscribe((remounted) => late.push(remounted.power.phase));
  });
  h.binding.subscribe((view) => tail.push(view.power.phase));

  assert.equal(h.binding.beginSleep(request), true, "nothing here retired the choice");
  assert.ok(mounted, "the popup subscribed from inside the delivery");
  assert.deepEqual(late, [],
    "the publication in flight is a change from a state it was never attached for");
  assert.deepEqual(tail, ["choosing"], "and the popups already attached are unaffected");

  h.binding.read().choice.cancel();
  assert.deepEqual(late, ["idle"], "from the next publication on, it is an ordinary subscriber");
  assert.deepEqual(tail, ["choosing", "idle"]);
  assert.equal(h.calls.length, 0);
});

test("disposing from inside a subscriber stops the rest of that fan-out", async () => {
  const h = harness();
  const tail = [];
  h.binding.subscribe((view) => { if (view.power.phase === "dispatching") h.binding.dispose(); });
  h.binding.subscribe((view) => tail.push(view.power.phase));

  h.binding.beginShutdown(request);
  const choice = h.binding.read().choice;
  await choice.confirm();
  assert.equal(tail.includes("dispatching"), false,
    "the fan-out the disposal interrupted is not resumed behind it");
  assert.deepEqual(tail, ["choosing", "disposed"], "the disposal itself is still delivered");
  assert.equal(h.calls.length, 0, "a disposal before the dispatch starts is not a dispatch");
  assert.equal(h.reads, 0);
  assert.equal(h.binding.read().power.phase, "disposed");
  assert.equal(h.binding.read().choice, null);
  await settle();
  assert.equal(h.calls.length, 0);
});

/** A StrictMode remount lands exactly here: the unmount disposes the binding
 * and the re-mount's effect subscribes again, both from inside the delivery the
 * disposal is queued behind. There is one publication left for a registration
 * made at that moment to be handed, and it must not be handed it. */
test("a popup that mounts into a disposal attaches to nothing", async () => {
  const h = harness();
  const late = [];
  const tail = [];
  h.binding.subscribe((view) => {
    if (view.power.phase !== "dispatching") return;
    h.binding.dispose();
    h.binding.subscribe((remounted) => late.push(remounted.power.phase));
  });
  h.binding.subscribe((view) => tail.push(view.power.phase));

  h.binding.beginShutdown(request);
  await h.binding.read().choice.confirm();
  assert.deepEqual(tail, ["choosing", "disposed"], "the popups that were attached still hear the disposal");
  assert.deepEqual(late, [], "the one that mounted into it was never attached");
  assert.equal(h.calls.length, 0);
  await settle();
  assert.deepEqual(late, []);
});

test("subscribing to a binding already disposed hands back a detached handle", () => {
  const h = harness();
  h.binding.beginShutdown(request);
  h.binding.dispose();

  let delivered = 0;
  const detach = h.binding.subscribe(() => { delivered++; });
  assert.equal(typeof detach, "function", "an owner still gets a cleanup it can call");
  detach();
  detach();
  assert.equal(h.binding.beginSleep(request), false);
  assert.equal(h.binding.beginShutdown(request), false);
  assert.equal(delivered, 0, "and it never hears anything");
  assert.equal(h.calls.length, 0);
});

/** StrictMode double-invokes effects: mount, unmount, mount again, with the
 * same callback identity. If the cleanup detached by function rather than by
 * registration, the first popup's cleanup would silently kill the second
 * popup's subscription, and nothing on screen would ever update again. */
test("a stale unsubscribe handle cannot detach a later subscription", () => {
  const h = harness();
  const seen = [];
  const popup = (view) => seen.push(view.power.phase);

  const firstMount = h.binding.subscribe(popup);
  firstMount();
  const secondMount = h.binding.subscribe(popup);
  firstMount();
  firstMount();

  assert.equal(h.binding.beginSleep(request), true);
  assert.deepEqual(seen, ["choosing"], "the live subscription survives the stale handle");
  h.binding.read().choice.cancel();
  assert.deepEqual(seen, ["choosing", "idle"]);

  secondMount();
  secondMount();
  h.binding.beginShutdown(request);
  assert.deepEqual(seen, ["choosing", "idle"], "and its own handle still detaches it, idempotently");

  // Two registrations of one function are two subscriptions, not one.
  const twice = harness();
  let deliveries = 0;
  const counted = () => { deliveries++; };
  const detachA = twice.binding.subscribe(counted);
  twice.binding.subscribe(counted);
  twice.binding.beginSleep(request);
  assert.equal(deliveries, 2, "each registration is delivered to");
  detachA();
  twice.binding.read().choice.cancel();
  assert.equal(deliveries, 3, "and detaching one leaves the other attached");
});

test("a snapshot changes identity only when something is published", async () => {
  const h = harness();
  const idle = h.binding.read();
  assert.equal(h.binding.read(), idle);
  assert.ok(Object.isFrozen(idle));
  assert.throws(() => { idle.choice = null; }, TypeError);

  let notifications = 0;
  const unsubscribe = h.binding.subscribe(() => { notifications++; });
  assert.equal(h.binding.beginSleep(request), true);
  const choosing = h.binding.read();
  assert.notEqual(choosing, idle, "a new choice is a new snapshot");
  assert.equal(h.binding.read(), choosing, "and nothing else moves it");
  assert.equal(notifications, 1, "one publication for one capture");

  assert.equal(h.binding.beginShutdown(request), false);
  assert.equal(h.binding.read(), choosing, "a refused capture is not a change");
  await h.binding.refresh();
  assert.equal(h.binding.read(), choosing, "an ignored readback is not a change");
  assert.equal(notifications, 1);

  choosing.choice.cancel();
  assert.notEqual(h.binding.read(), choosing);
  assert.equal(h.binding.read().choice, null);
  assert.equal(notifications, 2);
  unsubscribe();
  h.binding.beginSleep(request);
  assert.equal(notifications, 2, "an unsubscribed popup hears nothing");
  assert.notEqual(h.binding.read(), choosing);
});

// ----------------------------------------------------------- owner actions

test("refresh is the owner's readback, and nothing here follows up on one", async () => {
  const h = harness({
    execute: async (...args) => accepted(...args, {
      busy: true, power_requested: false, ok: false, code: "dock_teardown.trial_running",
    }),
  });
  h.binding.beginSleep(request);
  await h.binding.refresh();
  assert.equal(h.reads, 0, "there is nothing to read back before a submission");

  const choice = h.binding.read().choice;
  await choice.disconnectAndSleep();
  assert.equal(h.binding.read().power.phase, "pending");
  assert.equal(h.binding.read().choice, choice, "a pending request is still on screen");
  assert.equal(h.reads, 0, "dispatch does not poll");

  h.setReading(reply({ sleep_cycle_observed: true, code: "dock_power.sleep_cycle_observed" }));
  await h.binding.refresh();
  assert.equal(h.reads, 1, "exactly the one readback the owner asked for");
  assert.equal(h.binding.read().power.phase, "sleep_observed");
  assert.equal(h.binding.read().choice, null);
  await settle();
  // A drain, not a window: this catches a follow-up in the turns immediately
  // behind the readback. Intervals up to `QUIET_WINDOW_MS` are the port-call
  // test's business, and longer ones are nobody's.
  assert.equal(h.reads, 1, "nothing follows up in the turns behind it");
  assert.equal(h.calls.length, 1);
});

test("disposal detaches presentation, forbids new dispatch, and recalls nothing", async () => {
  const waiting = deferred();
  const h = harness({ execute: () => waiting.promise });
  const seen = [];
  h.binding.subscribe((view) => seen.push(view.power.phase));
  h.binding.beginShutdown(request);
  const choice = h.binding.read().choice;
  const running = choice.confirm();
  h.binding.dispose();
  assert.deepEqual(seen, ["choosing", "dispatching", "disposed"], "presentation sees the disposal itself");

  waiting.resolve(accepted("whole_dock_shutdown", attachment, firstId));
  await running;
  await settle();
  assert.deepEqual(seen, ["choosing", "dispatching", "disposed"], "and nothing after it");
  assert.equal(h.calls.length, 1, "committed work is neither recalled nor repeated");
  assert.equal(h.binding.read().power.phase, "disposed");
  assert.equal(h.binding.read().choice, null);

  assert.equal(h.binding.beginSleep(request), false);
  assert.equal(h.binding.beginShutdown(request), false);
  await h.binding.refresh();
  await choice.confirm();
  choice.cancel();
  h.binding.dispose();
  assert.equal(h.calls.length, 1);
  assert.equal(h.reads, 0);
  assert.equal(h.binding.read().power.phase, "disposed");
});

/** An owner whose own `requestId` disposes the binding leaves the coordinator
 * holding a ticket that no popup can ever be attached to: presentation is gone
 * before the buttons exist. Admitting it anyway would put a live choice on a
 * binding that has already promised to show nothing and dispatch nothing.
 *
 * The disposal lands in the middle of the capture, which is the one moment a
 * publication is being held back -- and it is the one publication that must not
 * be. The popups attached at that moment are about to be detached for good: if
 * the disposal is the publication that gets swallowed, their last word is a
 * request whose owner is already gone, and they keep rendering it forever. */
test("a binding disposed while its request identity was being minted admits nothing", async () => {
  const calls = [];
  const port = {
    execute: async (...args) => { calls.push(args); return accepted(...args); },
    readStatus: async () => { throw new Error("a disposed binding must not poll"); },
  };
  let binding;
  binding = createPowerChoiceBinding(port, {
    requestId: () => { binding.dispose(); return firstId; },
  });
  const seen = [];
  const rendered = [];
  binding.subscribe((view) => seen.push(view.power.phase));
  binding.subscribe((view) => rendered.push(view));

  assert.equal(binding.beginSleep(request), false, "the admission the owner disposed under is not a choice");
  assert.equal(binding.read().choice, null, "and leaves no buttons on a binding nobody is watching");
  assert.deepEqual(seen, ["disposed"], "an attached popup is told its owner is gone");
  const last = rendered[rendered.length - 1];
  assert.equal(last, binding.read(), "and that is the snapshot it is left rendering");
  assert.equal(last.power.phase, "disposed",
    "not a live phase from the request the disposal interrupted");
  assert.equal(last.power.intent, null, "with no intent");
  assert.equal(last.power.requestId, null, "and no request identity still on screen");
  assert.equal(last.choice, null);
  assert.equal(calls.length, 0);

  assert.equal(binding.beginSleep(request), false, "and the binding stays shut");
  assert.equal(binding.beginShutdown(request), false);
  await binding.refresh();
  await settle();
  assert.deepEqual(seen, ["disposed"], "with nothing published after the disposal");
  assert.equal(calls.length, 0);
  assert.equal(binding.read(), last);
  assert.equal(binding.read().choice, null);
});

/** The other end of the same window: the choice is admitted, and the popup it
 * is published to disposes the owner as it renders. `true` here would tell the
 * caller a choice is on screen when the disposal has already taken it off --
 * and left nothing that could ever put one there again. */
test("a choice the popup disposed on sight is not reported as shown", async () => {
  const h = harness();
  const seen = [];
  const tail = [];
  h.binding.subscribe((view) => {
    seen.push(view.power.phase);
    if (view.power.phase === "choosing") h.binding.dispose();
  });
  h.binding.subscribe((view) => tail.push(view.power.phase));

  assert.equal(h.binding.beginSleep(request), false,
    "the capture was invalidated by the disposal it provoked");
  assert.deepEqual(seen, ["choosing", "disposed"]);
  assert.deepEqual(tail, ["disposed"],
    "the fan-out the disposal interrupted is not resumed behind it, and the disposal still lands");
  assert.equal(h.binding.read().power.phase, "disposed");
  assert.equal(h.binding.read().choice, null, "there is no popup to have reported");
  assert.equal(h.binding.beginShutdown(request), false, "and the binding stays shut");
  assert.equal(h.calls.length, 0);
  assert.equal(h.reads, 0);
  await settle();
  assert.equal(h.calls.length, 0);
});

/** Disposal is not the only way the choice a call put on screen is gone before
 * that call returns -- it is just the loudest. A popup that dismisses the
 * request as it renders it, and a popup that dismisses it and asks for another,
 * both leave the caller holding a `true` that means "render a popup for the
 * choice you just asked for" when that choice is retired or displaced. The
 * answer has to be about the choice this call put up, not about whether the
 * binding happens to have one. */
test("a choice retired or replaced during its own announcement is not reported as shown", async () => {
  const dismissed = harness();
  const seen = [];
  dismissed.binding.subscribe((view) => {
    seen.push(view.power.phase);
    if (view.power.phase === "choosing") view.choice.cancel();
  });
  assert.equal(dismissed.binding.beginSleep(request), false,
    "the popup dismissed the choice during the very publication announcing it");
  assert.deepEqual(seen, ["choosing", "idle"], "and the dismissal is published like any other");
  assert.equal(dismissed.binding.read().choice, null, "there is no popup for the caller to render");
  assert.equal(dismissed.binding.read().power.phase, "idle");
  assert.equal(dismissed.calls.length, 0);

  // A different choice on screen is not this call's choice. `false` here is
  // what separates "is the one I asked for standing?" from "is anything?".
  let issued = 0;
  const replaced = harness({ requestId: () => idAt(issued++) });
  let swapped = false;
  replaced.binding.subscribe((view) => {
    if (swapped || view.power.phase !== "choosing") return;
    swapped = true;
    view.choice.cancel();
    replaced.binding.beginSleep({ attachmentToken: otherAttachment, connectionLabel: "new dock" });
  });
  assert.equal(replaced.binding.beginSleep({ attachmentToken: attachment, connectionLabel: "old dock" }), false,
    "the choice this call put up was displaced before the call returned");
  assert.ok(replaced.binding.read().choice, "a choice is on screen, and it is not this one");
  assert.equal(replaced.binding.read().choice.connectionLabel, "new dock");
  assert.equal(replaced.binding.read().power.requestId, idAt(1));
  assert.equal(replaced.calls.length, 0);

  // And the ordinary case still answers yes: nothing touched it on the way out.
  const kept = harness();
  kept.binding.subscribe(() => {});
  assert.equal(kept.binding.beginSleep(request), true);
  assert.ok(kept.binding.read().choice);
  await settle();
  assert.equal(kept.calls.length, 0);
});
