"""Source-labelled handheld APU power research; no native profile claims."""

from __future__ import annotations

from ..domain.power_profile_catalog import (
    DeviceIdentity,
    DevicePowerProfile,
    DocumentedPowerRange,
    EvidenceDimensions,
    OemModeClaim,
    PowerProfileCatalog,
    PowerRangeKind,
    PowerSource,
    SourceReference,
)


ALLY_SPEC = SourceReference(
    "asus-ally-x-2024-spec",
    "https://rog.asus.com/gaming-handhelds/rog-ally/rog-ally-x-2024/spec/",
    "Official specification; published 9-30 W APU TDP range.",
)
ALLY_CHINA = SourceReference(
    "asus-ally-x-2024-cn",
    "https://rog.asus.com.cn/gaming-handhelds/rog-ally/rog-ally-x-2024/",
    "Official China page; regional OEM Windows mode claims.",
)
ALLY_GLOBAL = SourceReference(
    "asus-ally-x-2024-global",
    "https://rog.asus.com/gaming-handhelds/rog-ally/rog-ally-x-2024/",
    "Official global page; differing regional/firmware OEM mode claims.",
)
ALLY_COMPARISON = SourceReference(
    "asus-handheld-comparison-2025-sg",
    "https://rog.asus.com/sg/gaming-handhelds/rog-xbox-ally-x-2025/",
    "Official ASUS comparison; corroborates RC72LA 17 W battery Performance and 30 W AC Turbo claims.",
)
LENOVO_GUIDE = SourceReference(
    "lenovo-legion-go-8apu1-guide",
    "https://download.lenovo.com/pccbbs/pubs/legion_go_8apu1/user_guide/en/index.html",
    "Official original Legion Go guide; OEM Windows modes and custom range.",
)
DECK_LCD_SPEC = SourceReference(
    "valve-steam-deck-lcd-tech",
    "https://www.steamdeck.com/en/tech/deck",
    "Official Steam Deck LCD APU specification; 4-15 W.",
)
DECK_OLED_SPEC = SourceReference(
    "valve-steam-deck-oled-tech",
    "https://www.steamdeck.com/en/tech",
    "Official Steam Deck OLED APU specification; 4-15 W.",
)
GPD_IDENTITY_NOTE = SourceReference(
    "regear-gpd-win-mini-2023-scope",
    "https://github.com/ronnierosal/Re-Gear/issues/488",
    "Scope record: exact device limits, defaults and OEM modes remain unknown.",
)


RESEARCHED = EvidenceDimensions(researched=True)
CONFLICTED_RESEARCH = EvidenceDimensions(researched=True, source_conflicted=True)


ALLY_X_2024 = DevicePowerProfile(
    DeviceIdentity("ASUSTeK COMPUTER INC.", "ROG Ally X", "RC72LA"),
    CONFLICTED_RESEARCH,
    (ALLY_SPEC, ALLY_CHINA, ALLY_GLOBAL, ALLY_COMPARISON),
    documented_range=DocumentedPowerRange(9, 30, PowerRangeKind.PUBLISHED_APU_TDP, ALLY_SPEC),
    oem_claims=(
        OemModeClaim("Silent", 13, PowerSource.BATTERY, ALLY_CHINA),
        OemModeClaim("Performance", 17, PowerSource.BATTERY, ALLY_CHINA),
        OemModeClaim("Turbo", 25, PowerSource.BATTERY, ALLY_CHINA),
        OemModeClaim("Turbo", 30, PowerSource.AC, ALLY_CHINA),
        OemModeClaim("Silent", 10, None, ALLY_GLOBAL),
        OemModeClaim("Performance", 15, None, ALLY_GLOBAL),
        OemModeClaim("Turbo", 25, PowerSource.BATTERY, ALLY_GLOBAL),
        OemModeClaim("Turbo", 30, PowerSource.AC, ALLY_GLOBAL),
        OemModeClaim("Performance", 17, PowerSource.BATTERY, ALLY_COMPARISON),
        OemModeClaim("Turbo", 30, PowerSource.AC, ALLY_COMPARISON),
    ),
)

LEGION_GO_8APU1 = DevicePowerProfile(
    DeviceIdentity("LENOVO", "Legion Go 8APU1", "83E1"),
    RESEARCHED,
    (LENOVO_GUIDE,),
    documented_range=DocumentedPowerRange(5, 30, PowerRangeKind.OEM_CUSTOM_MODE, LENOVO_GUIDE),
    oem_claims=(
        OemModeClaim("Quiet", 8, None, LENOVO_GUIDE),
        OemModeClaim("Balance", 15, None, LENOVO_GUIDE),
        OemModeClaim("Performance", 20, None, LENOVO_GUIDE),
        OemModeClaim("Custom ceiling", 30, None, LENOVO_GUIDE),
    ),
)

STEAM_DECK_LCD = DevicePowerProfile(
    DeviceIdentity("Valve", "Steam Deck", "LCD"),
    RESEARCHED,
    (DECK_LCD_SPEC,),
    documented_range=DocumentedPowerRange(4, 15, PowerRangeKind.PUBLISHED_APU_TDP, DECK_LCD_SPEC),
)

STEAM_DECK_OLED = DevicePowerProfile(
    DeviceIdentity("Valve", "Steam Deck", "OLED"),
    RESEARCHED,
    (DECK_OLED_SPEC,),
    documented_range=DocumentedPowerRange(4, 15, PowerRangeKind.PUBLISHED_APU_TDP, DECK_OLED_SPEC),
)

GPD_WIN_MINI_2023 = DevicePowerProfile(
    DeviceIdentity("GPD", "G1617-01", "Win Mini 2023 7840U"),
    RESEARCHED,
    (GPD_IDENTITY_NOTE,),
)


HANDHELD_POWER_CATALOG = PowerProfileCatalog(
    version=1,
    profiles=(
        ALLY_X_2024,
        LEGION_GO_8APU1,
        STEAM_DECK_LCD,
        STEAM_DECK_OLED,
        GPD_WIN_MINI_2023,
    ),
)
