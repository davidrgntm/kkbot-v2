import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr
from typing import List, Optional
from pytz import timezone as pytz_timezone

class Settings(BaseSettings):
    # Telegram
    bot_token: SecretStr
    admin_ids: str 
    
    # Project
    group_chat_id: int
    timezone: str = "Asia/Tashkent"
    
    # Google (Fayl yo'li YOKI JSON matni)
    google_sheet_id: str
    google_creds_path: str = "google_credentials.json"
    google_creds_json: Optional[str] = None

    # SQLite
    db_path: str = "data/kkbot.db"

    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    def get_admin_ids(self) -> List[int]:
        return [int(x.strip()) for x in self.admin_ids.split(',') if x.strip()]

    def get_timezone_obj(self):
        return pytz_timezone(self.timezone)

config = Settings()