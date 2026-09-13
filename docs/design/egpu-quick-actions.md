# Re-Gear eGPU Quick Actions UX

The eGPU action set is shared between the eGPU module and Command Center Quick Access. Runtime may disable unsupported actions, but it should not rename or reinterpret them.

## Action order

Use this order whenever all six are visible:

1. Switch to Handheld
2. Safe Disconnect
3. Resolution
4. eGPU Status
5. Disconnect + Sleep
6. Disconnect + Shutdown

The first four occupy the first row of the 4-column grid. The two power-combination actions occupy the next row.

## Action meanings

### Switch to Handheld
Return presentation from the external TV path to the handheld using the verified runtime path. This is not Safe Disconnect and does not imply the eGPU is removable.

### Safe Disconnect
Open or begin the verified Safe Disconnect workflow. Keep unplug clearance separate from software removal state.

### Resolution
Open the verified display-target / resolution control. Do not expose unsupported modes as actionable.

### eGPU Status
Open the detailed eGPU surface with connection, dock mode, display output, render GPU, link and readiness information.

### Disconnect + Sleep
Run Safe Disconnect, then submit sleep only if runtime confirms the sequence is allowed. This is optional convenience; ordinary sleep while the eGPU remains attached is also a valid path when runtime permits it.

### Disconnect + Shutdown
Run Safe Disconnect, then submit shutdown only if runtime confirms the sequence is allowed.

## Sleep interception UX

When the user requests sleep while an eGPU is attached, show the centered `EgpuSleepChoicePopup` with:

- primary: Sleep — keep eGPU connected
- secondary: Safe Disconnect + Sleep
- cancel/back

Do not force Safe Disconnect just because the eGPU is attached.

## USB authorization UX

When authorization blocks the connection flow, show `UsbAuthorizationPopup` with the observed device identity and explicit Authorize / Not now actions. Do not invent persistent trust controls.

## Auto TV popup

Use the compact centered fast-path popup for healthy Auto TV switching. Normal runtime should fit the four-step flow and complete within the usual short connection window. Delay UI is exceptional, not the default presentation.
