"""Pure guided hardware-health result contract with no active tests or authority."""
from dataclasses import dataclass
from enum import StrEnum
class HealthCheckState(StrEnum): HEALTHY="healthy"; ATTENTION="attention"; UNKNOWN="unknown"
@dataclass(frozen=True,slots=True)
class HealthCheckInput:
 name:str; available:bool; healthy:bool|None
def assess_health_check(value:HealthCheckInput)->tuple[HealthCheckState,str]:
 if not value.available or value.healthy is None:return HealthCheckState.UNKNOWN,"Review fresh read-only evidence."
 if value.healthy:return HealthCheckState.HEALTHY,"No action is needed."
 return HealthCheckState.ATTENTION,"Review the related status before changing settings."
