"""Per-client logbook. Avoid repeated questions and reused full drafts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fingerprint(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().casefold())


@dataclass
class ClientRecord:
    client_id: str
    name: str = ""
    city: str = ""
    facts: list[str] = field(default_factory=list)
    interests: list[str] = field(default_factory=list)
    used_ctas: list[str] = field(default_factory=list)
    used_drafts: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "client_id": self.client_id,
            "name": self.name,
            "city": self.city,
            "facts": list(self.facts),
            "interests": list(self.interests),
            "used_ctas": list(self.used_ctas),
            "used_drafts": list(self.used_drafts),
            "notes": list(self.notes),
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ClientRecord":
        return cls(
            client_id=str(data.get("client_id") or ""),
            name=str(data.get("name") or ""),
            city=str(data.get("city") or ""),
            facts=list(data.get("facts") or []),
            interests=list(data.get("interests") or []),
            used_ctas=list(data.get("used_ctas") or []),
            used_drafts=list(data.get("used_drafts") or []),
            notes=list(data.get("notes") or []),
            updated_at=str(data.get("updated_at") or ""),
        )


class Logbook:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or "logbook.json")
        if self.path.exists() and self.path.is_dir():
            self.path = self.path / "logbook.json"
        elif self.path.suffix == "" and not self.path.exists():
            self.path = self.path / "logbook.json"
        self._clients: dict[str, ClientRecord] = {}
        self.load()

    def load(self) -> None:
        if not self.path.is_file():
            self._clients = {}
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        rows = raw.get("clients", raw if isinstance(raw, dict) else {})
        self._clients = {}
        if isinstance(rows, dict):
            for key, value in rows.items():
                if isinstance(value, dict):
                    record = ClientRecord.from_dict({"client_id": key, **value})
                    self._clients[key] = record

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"clients": {key: row.to_dict() for key, row in sorted(self._clients.items())}}
        self.path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def get(self, client_id: str, name: str = "", city: str = "") -> ClientRecord:
        key = (client_id or "").strip() or (name or "").strip().casefold()
        if not key:
            key = "unknown"
        record = self._clients.get(key)
        if record is None:
            record = ClientRecord(client_id=key, name=name, city=city, updated_at=_now())
            self._clients[key] = record
        if name and not record.name:
            record.name = name
        if city and not record.city:
            record.city = city
        return record

    def add_fact(self, client_id: str, fact: str, name: str = "", city: str = "") -> ClientRecord:
        record = self.get(client_id, name=name, city=city)
        text = " ".join((fact or "").split())
        if text and fingerprint(text) not in {fingerprint(item) for item in record.facts}:
            record.facts.append(text)
            record.updated_at = _now()
            self.save()
        return record

    def remember_draft(self, client_id: str, draft: str, cta: str, name: str = "", city: str = "") -> None:
        record = self.get(client_id, name=name, city=city)
        fp = fingerprint(draft)
        if fp and fp not in record.used_drafts:
            record.used_drafts.append(fp)
        cta_fp = fingerprint(cta)
        if cta_fp and cta_fp not in record.used_ctas:
            record.used_ctas.append(cta_fp)
        record.updated_at = _now()
        self.save()

    def used_cta_set(self, client_id: str) -> set[str]:
        return {fingerprint(item) for item in self.get(client_id).used_ctas}

    def used_draft_set(self, client_id: str) -> set[str]:
        return set(self.get(client_id).used_drafts)

    def apply_ingest(
        self,
        client_id: str,
        ingest: Any,
        *,
        name: str = "",
        city: str = "",
    ) -> ClientRecord:
        """Merge parsed history into the record. Never overwrite a good city with a guess."""
        record = self.get(client_id, name=name or getattr(ingest, "client_name", ""), city=city)
        incoming_name = (getattr(ingest, "client_name", "") or name or "").strip()
        incoming_city = (getattr(ingest, "client_city", "") or "").strip()
        if incoming_name and not record.name:
            record.name = incoming_name.split()[0]
        if incoming_city and not record.city:
            record.city = incoming_city
        for fact in getattr(ingest, "facts", []) or []:
            text = " ".join(str(fact).split())
            if text and fingerprint(text) not in {fingerprint(item) for item in record.facts}:
                record.facts.append(text)
        for interest in getattr(ingest, "interests", []) or []:
            label = str(interest).strip()
            if label and label not in record.interests:
                record.interests.append(label)
        for question in getattr(ingest, "operator_questions", []) or []:
            fp = fingerprint(question)
            if fp and fp not in record.used_ctas:
                record.used_ctas.append(fp)
        record.updated_at = _now()
        self.save()
        return record
