# Architecture and dependency boundaries

Re-Gear keeps decisions separate from the code that reads or changes the operating
system. This lets contributors test policy without touching a device.

## For players — no technical background needed

The interface reports what Re-Gear can establish and explains unavailable actions.
A missing reading is not permission to guess that a device is ready. You do not
need to run developer commands to use the [Player Guide](../player/README.md).

## Technical details — for advanced users and contributors

### Hexagonal layout

| Layer | Location | Responsibility | Dependency boundary |
|---|---|---|---|
| Domain | `backend/regear/domain/` | Immutable observations, policies, states and decisions | Pure; no filesystem, subprocess, network or OS calls |
| Ports | `backend/regear/ports/` | Interfaces through which services request observations or effects | Describes capabilities without choosing SteamOS mechanisms |
| Application | `backend/regear/application/` | Coordinates decisions, evidence and ordered operations | Uses domain and ports; hardware effects supplied through interfaces |
| Adapters | `backend/regear/adapters/steamos/` | Implements observations and tightly scoped effects | OS details stay at the boundary; command execution follows the approved runner |
| Delivery/composition | `backend/regear/delivery/`, `main.py` | Constructs services, binds RPCs, manages lifecycle and durable operation state | Must construct the real required observers, guards and effects |
| Frontend | `src/` | Presents status and requests actions through typed RPCs | Cannot supply arbitrary commands, PIDs or hardware authority |

Dependencies point toward policy and interfaces. Runtime calls can travel outward
through injected ports; that does not make the domain depend on an adapter.
Physical connection, render GPU, display target, Gamescope and game state are
independent observations. Combining them into a convenient label must not erase
unknown or contradictory evidence.

### Follow one request

1. A mounted UI control calls a typed backend RPC in
   [main.py](../../../main.py).
2. Delivery obtains current evidence and constructs the appropriate service.
3. Application policy decides whether the exact requested operation may proceed.
4. Adapters execute only the approved effects; the service re-observes results.
5. Delivery returns structured state; the UI renders the result without promoting
   a submitted request into a successful operation.

A tested helper with no production caller is an implemented component, not an
integrated feature. See [eGPU lifecycle acceptance](egpu-lifecycle.md) for this
distinction at each stage, and [scripts and gates](scripts-and-ci.md) for checks.

The owning [architecture document](../../ARCHITECTURE.md),
[architecture checker](../../../scripts/check_architecture.py), and
[safety invariants](../../SAFETY_INVARIANTS.md) define the detailed boundaries.
This guide changes no runtime behavior and makes no installation claim.
