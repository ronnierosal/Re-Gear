"""Inactive, explicitly pre-native session preparation. Always withholds launch."""
from dataclasses import dataclass
from .device_filter_prepared_source import PreparedLaunchObservationSource,PreparedLaunchCollection
from .device_filter_prepare_server import FilterPrepareServer
from .device_filter_session_entry import (SessionEntryExpectation,SessionEntryPurpose,
    EffectiveSessionEntry,EffectiveSessionEntryObserver)
from .device_filter_runtime_peer import SessionEntryRuntimeObservation,observe_session_entry_runtime_peer


@dataclass(frozen=True)
class SessionEntryPreparedCollection(PreparedLaunchCollection):
    purpose: SessionEntryPurpose=SessionEntryPurpose.PREPARE_WITHHOLD
    native_execution_authorized: bool=False

    def __post_init__(self):
        super().__post_init__()
        if self.purpose is not SessionEntryPurpose.PREPARE_WITHHOLD or self.native_execution_authorized is not False:
            raise ValueError('session collection must withhold native execution')


class SessionEntryPreparedObservationSource(PreparedLaunchObservationSource):
    _unit='gamescope-session.service'
    _expectation_type=SessionEntryExpectation
    _effective_type=EffectiveSessionEntry
    _effective_factory=EffectiveSessionEntryObserver
    _collection_type=SessionEntryPreparedCollection

    def _effective_role_valid(self,value):
        return (value.purpose is SessionEntryPurpose.PREPARE_WITHHOLD
                and value.native_execution_authorized is False)


class SessionEntryPrepareServer(FilterPrepareServer):
    """Requires one combined session source; never accepts the native runtime role."""
    def __init__(self,journal,user,observe_combined,*,observe_runtime=observe_session_entry_runtime_peer,**kwargs):
        if not callable(observe_combined):raise ValueError('session collection source required')
        super().__init__(journal,user,None,None,observe_combined=observe_combined,
                         observe_runtime=observe_runtime,**kwargs)

    def _arm_valid(self,arm):return arm.unit=='gamescope-session.service'

    def _runtime_valid(self,value):
        return (type(value) is SessionEntryRuntimeObservation
                and value.purpose=='prepare_and_withhold_session_entry'
                and value.identity.unit=='gamescope-session.service')

    def _combined_valid(self,value):
        return (type(value) is SessionEntryPreparedCollection
                and value.purpose is SessionEntryPurpose.PREPARE_WITHHOLD
                and value.native_execution_authorized is False)
