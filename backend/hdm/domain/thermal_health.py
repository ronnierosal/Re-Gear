"""Pure optional thermal assessment; no sensor reader, poller, or fan authority."""
import math
from dataclasses import dataclass
from enum import StrEnum

class ThermalState(StrEnum): UNAVAILABLE="unavailable"; UNKNOWN="unknown"; NORMAL="normal"; ATTENTION="attention"
@dataclass(frozen=True,slots=True)
class ThermalReading:
 source: str
 temperature_c: float | None
 fresh: bool
 available: bool
 sustained_samples: int = 0
def assess_thermal(reading: ThermalReading) -> ThermalState:
 if not reading.available: return ThermalState.UNAVAILABLE
 if reading.temperature_c is None or not reading.fresh or not math.isfinite(reading.temperature_c) or reading.temperature_c < 0: return ThermalState.UNKNOWN
 if reading.temperature_c >= 90 and reading.sustained_samples >= 3: return ThermalState.ATTENTION
 return ThermalState.NORMAL
