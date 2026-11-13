import hashlib
import json
import uuid
from datetime import timezone
from sqlalchemy.exc import IntegrityError
from pydantic import ValidationError

from .contracts import CrowdReport, SensorEvent
from .db import iso, utcnow
from .models import Observation


def ingest(session, raw, source, contributor=None, now=None):
    now = now or utcnow()
    contract = SensorEvent if source == "wsn" else CrowdReport
    try:
        model = contract.model_validate(raw)
        if source == "crowd" and model.contributor_id != contributor:
            raise ValueError("contributor_identity_mismatch")
        payload = model.model_dump(mode="json")
        payload["observed_at"] = iso(model.observed_at.astimezone(timezone.utc))
        payload["authenticated_contributor"] = contributor if source == "crowd" else model.node_id
        event_id = model.event_id
        status, reason = "queued", None
    except (ValidationError, ValueError) as error:
        payload = {"invalid_payload": raw, "authenticated_contributor": contributor}
        requested = raw.get("event_id") if isinstance(raw, dict) else None
        event_id = requested if isinstance(requested, str) and 8 <= len(requested) <= 100 else "invalid-"+str(uuid.uuid4())
        status, reason = "rejected", "invalid_observation_contract"
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    existing = session.get(Observation, event_id)
    if existing:
        if existing.fingerprint != fingerprint:
            return {"event_id": event_id, "status": "conflict", "reason": "event_id_payload_mismatch"}
        return {"event_id": event_id, "status": "duplicate", "original_status": existing.status}
    row = Observation(event_id=event_id, source=source, trip_id=payload.get("trip_id"),
                      observed_at=payload.get("observed_at"), received_at=iso(now), payload=payload,
                      fingerprint=fingerprint, status=status, reason=reason, available_at=iso(now))
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError:
        existing = session.get(Observation, event_id)
        if existing is None:
            raise
        return {"event_id": event_id, "status": "duplicate" if existing.fingerprint == fingerprint else "conflict",
                "reason": None if existing.fingerprint == fingerprint else "event_id_payload_mismatch"}
    return {"event_id": event_id, "status": status, "reason": reason}
