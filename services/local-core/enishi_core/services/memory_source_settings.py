"""本人代理AIが利用する記憶ソース設定。"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from enishi_core.models import MemorySourceSetting

LOCAL_SOURCE = "memories"
KNOWN_SOURCES = [
    LOCAL_SOURCE,
    "conversation_history",
    "projects",
    "calendar",
    "github",
    "obsidian",
    "notion",
    "google_drive",
]


def _is_connected(source: str) -> bool:
    return source == LOCAL_SOURCE


def _default_setting(source: str) -> MemorySourceSetting:
    connected = _is_connected(source)
    return MemorySourceSetting(
        source=source,
        connected=connected,
        enabled=connected,
        scope="ENISHI local memories" if connected else "",
    )


def list_settings(session: Session) -> list[MemorySourceSetting]:
    existing = {row.source: row for row in session.scalars(select(MemorySourceSetting))}
    for source in KNOWN_SOURCES:
        if source not in existing:
            setting = _default_setting(source)
            session.add(setting)
            existing[source] = setting
    for setting in existing.values():
        setting.connected = _is_connected(setting.source)
        if not setting.connected:
            setting.enabled = False
    session.commit()
    return [existing[source] for source in KNOWN_SOURCES]


def put_settings(
    session: Session,
    updates: list[dict[str, object]],
) -> list[MemorySourceSetting]:
    existing = {row.source: row for row in list_settings(session)}
    for item in updates:
        source = str(item["source"])
        setting = existing.get(source)
        if setting is None:
            setting = _default_setting(source)
            session.add(setting)
            existing[source] = setting
        setting.connected = _is_connected(source)
        requested_enabled = bool(item.get("enabled", setting.enabled))
        setting.enabled = requested_enabled if setting.connected else False
        setting.scope = str(item.get("scope", setting.scope or ""))
    session.commit()
    return [existing[source] for source in sorted(existing)]
