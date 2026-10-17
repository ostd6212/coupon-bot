from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Config:
    telegram_token: str
    anthropic_api_key: str
    model: str
    allowed_user_ids: frozenset[int]
    tz: ZoneInfo
    reminder_hour: int
    evening_hour: int
    data_dir: Path

    @property
    def db_path(self) -> Path:
        return self.data_dir / "coupons.db"

    @property
    def photos_dir(self) -> Path:
        return self.data_dir / "photos"


def load_config(env=os.environ) -> Config:
    missing = [k for k in ("TELEGRAM_BOT_TOKEN", "ANTHROPIC_API_KEY", "ALLOWED_USER_IDS") if not env.get(k)]
    if missing:
        raise RuntimeError(f"Missing environment variables: {', '.join(missing)}")
    try:
        ids = frozenset(int(x) for x in env["ALLOWED_USER_IDS"].replace(" ", "").split(",") if x)
    except ValueError as e:
        raise RuntimeError("ALLOWED_USER_IDS must be comma-separated integers") from e
    if not ids:
        raise RuntimeError("ALLOWED_USER_IDS is empty")
    return Config(
        telegram_token=env["TELEGRAM_BOT_TOKEN"],
        anthropic_api_key=env["ANTHROPIC_API_KEY"],
        model=env.get("CLAUDE_MODEL") or "claude-haiku-5-5",
        allowed_user_ids=ids,
        tz=ZoneInfo(env.get("TZ") or "Europe/Madrid"),
        reminder_hour=int(env.get("REMINDER_HOUR") or 9),
        evening_hour=int(env.get("EVENING_HOUR") or 19),
        data_dir=Path(env.get("DATA_DIR") or "data"),
    )
