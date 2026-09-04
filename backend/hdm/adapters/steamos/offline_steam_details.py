"""Categorical projection of one context-bound Steam app-details callback.

The caller owns private request/game/session binding. This adapter performs no
subscription, network request, game action, persistence, or source-age inference.
An installation folder is not proof of complete installation or entitlement.
"""

from dataclasses import replace

from ...domain.offline_readiness import (
    CloudSaveState,
    DownloadState,
    InstallState,
    OfflineReadinessEvidence,
    OnlineCheckRequirement,
)


def project_steam_app_details(details: object) -> OfflineReadinessEvidence:
    if type(details) is not dict:
        return OfflineReadinessEvidence()
    evidence = OfflineReadinessEvidence()
    folder = details.get("iInstallFolder")
    if type(folder) is int and folder == -1:
        evidence = replace(evidence, install=InstallState.NOT_INSTALLED)
    display = details.get("eDisplayStatus")
    if type(display) is int:
        if display in {6, 18, 19, 20, 21, 39}:
            evidence = replace(evidence, download=DownloadState.PENDING_UPDATE)
        elif display in {3, 7, 22, 23, 24, 25, 38}:
            evidence = replace(evidence, download=DownloadState.PENDING_DOWNLOAD)
    cloud = details.get("eCloudStatus")
    if type(cloud) is int:
        if cloud == 9:
            evidence = replace(evidence, cloud_save=CloudSaveState.CONFLICT)
        elif cloud in {4, 5, 6, 7, 10}:
            evidence = replace(evidence, cloud_save=CloudSaveState.PENDING)
        elif cloud == 3 and all(details.get(key) is True for key in (
            "bCloudAvailable", "bCloudEnabledForAccount", "bCloudEnabledForApp"
        )):
            evidence = replace(evidence, cloud_save=CloudSaveState.SYNCED)
    if details.get("bIsThirdPartyUpdater") is True:
        evidence = replace(evidence, online_check_requirements=(
            OnlineCheckRequirement.THIRD_PARTY_LAUNCHER,
        ))
    return evidence
