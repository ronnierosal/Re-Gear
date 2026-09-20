# Fan-safe prepared eGPU disconnect

Status: source foundation only. It is not packaged, installed, or authorized for
a hardware trial.

The cable-retained `software_down` state is not a stable operating or charging
state. On the installed 0.3.124 GPD G1 trial, the full software teardown stopped
the enclosure fans while the still-powered enclosure became hot. No temperature
or fan telemetry was retained after teardown. Software reconnect remains out of
scope.

The replacement lifecycle has two explicit phases:

1. **Prepared and connected.** Return presentation to the handheld and release
   clients while keeping the exact GPU bound to `amdgpu` and the USB4 tunnel
   authorized. Firmware remains responsible for automatic fan control. Re-Gear
   may display read-only GPU temperature and fan RPM when a complete exact-device
   hwmon observation exists.
2. **Final teardown and physical removal.** Only a fresh explicit player action
   may begin the existing GPU, USB-branch, and tunnel teardown. Once the result is
   `software_down`, the UI must say that physical unplug is required. The state
   must not be presented as stable, charging-safe, complete, or eligible for a
   software reconnect. Completion requires separate verified transport absence.

`backend/regear/adapters/steamos/egpu_cooling.py` performs bounded read-only
inspection of the exact PCI GPU's hwmon directory. It accepts an `amdgpu` source
only when temperature, fan RPM, and an observed automatic fan-control mode are
all available. Missing, ambiguous, malformed, excessive, or changed evidence
fails closed. Zero RPM remains an observation because supported firmware may
use zero-RPM operation; detecting a hazardous trend requires an evidence-backed
device policy and multiple samples.

This foundation intentionally does not write `pwm1`, `pwm1_enable`, fan curves,
power limits, driver state, USB state, or USB4 authorization. Manual fan control
could disable firmware safeguards and needs separate manufacturer evidence,
rollback, watchdog behavior, and hardware validation. The next integration slice
belongs to the existing whole-dock transaction owner and must preserve automatic
TV connection behavior.

References:

- Linux hwmon ABI: <https://www.kernel.org/doc/html/latest/hwmon/sysfs-interface.html>
- AMD GPU thermal interfaces: <https://www.kernel.org/doc/html/latest/gpu/amdgpu/thermal.html>
