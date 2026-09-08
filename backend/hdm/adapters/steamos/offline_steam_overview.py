"""Minimize one already-observed local Steam overview; no Steam calls or I/O.

Candidate schema: decky-frontend-lib App.ts at 247eb635ea7acdc3e7807d5f99722daf854aaa70.
The future delivery owner must validate this schema on SteamOS, bind the selected
game privately, and pass source/cost/game/freshness admission before using it.
This module is deliberately not constructed by production snapshot delivery.
"""

from ...domain.offline_readiness import (
    CloudSaveState,
    DownloadState,
    InstallState,
    OfflineReadinessEvidence,
)

# EDisplayStatus: explicit unfinished/failed states only. ReadyToLaunch is not
# evidence that all offline prerequisites or installation checks have passed.
_UPDATES = frozenset({6, 18, 19, 20, 21, 39})
_DOWNLOADS = frozenset({3, 7, 22, 23, 24, 25, 38})
# EAppCloudStatus. Disabled/Unknown/Invalid and future values remain Unknown.
_CLOUD_PENDING = frozenset({4, 5, 6, 7, 10})


def project_local_steam_overview(
    overview: object, *, expected_app_id: int
) -> OfflineReadinessEvidence:
    """Return categorical evidence for exactly one privately bound base game.

    Accept only plain decoded records, exact integers, and explicit booleans.
    Never enumerate a library or fall back to selected/most-available clients.
    Missing/ambiguous identities, shortcuts, and remote-only data fail closed.
    Unknown cloud failures remain unknown rather than being mislabeled pending.
    """
    unknown = OfflineReadinessEvidence()
    if type(expected_app_id) is not int or not 0 < expected_app_id < 2**32:
        return unknown
    if type(overview) is not dict:
        return unknown
    app_id = overview.get("appid")
    if type(app_id) is not int or app_id != expected_app_id:
        return unknown
    app_type = overview.get("app_type")
    if type(app_type) is not int or app_type != 1:
        return unknown
    local = overview.get("local_per_client_data")
    if type(local) is not dict:
        return unknown
    # An explicit unsupported platform or active stream cannot describe a usable
    # local installation. Require affirmative local-platform evidence.
    if local.get("is_available_on_current_platform") is not True:
        return unknown
    if local.get("is_invalid_os_type", False) is not False:
        return unknown
    if local.get("streaming_to_local_client", False) is not False:
        return unknown

    installed = local.get("installed")
    install = (
        InstallState.INSTALLED if installed is True else
        InstallState.NOT_INSTALLED if installed is False else
        InstallState.UNKNOWN
    )
    display = local.get("display_status")
    download = DownloadState.UNKNOWN
    if type(display) is int:
        if display in _UPDATES:
            download = DownloadState.PENDING_UPDATE
        elif display in _DOWNLOADS:
            download = DownloadState.PENDING_DOWNLOAD

    cloud = CloudSaveState.UNKNOWN
    cloud_status = local.get("cloud_status")
    if type(cloud_status) is int:
        if cloud_status == 3:
            cloud = CloudSaveState.SYNCED
        elif cloud_status == 9:
            cloud = CloudSaveState.CONFLICT
        elif cloud_status in _CLOUD_PENDING:
            cloud = CloudSaveState.PENDING
    return OfflineReadinessEvidence(
        install=install,
        download=download,
        cloud_save=cloud,
        # This source proves neither cached entitlement nor internet/DRM rules.
        # It therefore cannot produce Ready to try offline by itself.
    )
