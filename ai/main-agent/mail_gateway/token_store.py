from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken


@dataclass
class OAuthTokenRecord:
    owner_user_id: str
    provider: str
    account_id: str
    address: str
    access_token: str
    refresh_token: Optional[str]
    expires_at: Optional[int]
    scopes: tuple[str, ...]
    display_name: Optional[str] = None


class EncryptedFileTokenStore:
    """Encrypted token vault with user-level ownership isolation."""

    def __init__(self, path: str | None = None, key: str | None = None) -> None:
        self.path = Path(path or os.environ.get("MAIL_GATEWAY_TOKEN_STORE", "./var/mail_tokens.bin"))
        raw_key = key or os.environ.get("MAIL_GATEWAY_ENCRYPTION_KEY")
        if not raw_key:
            raise RuntimeError("MAIL_GATEWAY_ENCRYPTION_KEY is required")
        self.fernet = Fernet(raw_key.encode("ascii"))

    def _load(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        try:
            clear = self.fernet.decrypt(self.path.read_bytes())
        except InvalidToken as exc:
            raise RuntimeError("Unable to decrypt mail token store") from exc
        return json.loads(clear.decode("utf-8"))

    def _save(self, data: dict[str, dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        encrypted = self.fernet.encrypt(payload)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_bytes(encrypted)
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)

    @staticmethod
    def _key(user_id: str, provider: str, account_id: str) -> str:
        return f"{user_id}:{provider.lower()}:{account_id}"

    def upsert(self, record: OAuthTokenRecord) -> None:
        data = self._load()
        encoded = asdict(record)
        encoded["scopes"] = list(record.scopes)
        data[self._key(record.owner_user_id, record.provider, record.account_id)] = encoded
        self._save(data)

    def get(self, user_id: str, provider: str, account_id: str) -> OAuthTokenRecord:
        data = self._load()
        raw = dict(data[self._key(user_id, provider, account_id)])
        raw["scopes"] = tuple(raw.get("scopes", []))
        return OAuthTokenRecord(**raw)

    def list_provider(self, user_id: str, provider: str) -> list[OAuthTokenRecord]:
        prefix = f"{user_id}:{provider.lower()}:"
        result = []
        for key, raw in self._load().items():
            if not key.startswith(prefix):
                continue
            item = dict(raw)
            item["scopes"] = tuple(item.get("scopes", []))
            result.append(OAuthTokenRecord(**item))
        return result
