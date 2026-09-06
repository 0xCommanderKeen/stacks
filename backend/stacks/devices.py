"""Named read-only credentials; owner sessions remain a separate authority."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from stacks.models import DeviceCredential, now
from stacks.schemas import DeviceIssued, DeviceOut, DevicePage


def device_out(device):
    return DeviceOut(**{name: getattr(device, name) for name in DeviceOut.model_fields})


class Devices:
    def __init__(self, library):
        self.library = library

    def issue(self, request, catalog_url):
        password = secrets.token_urlsafe(32)
        with self.library.lock, self.library.sessions.begin() as session:
            if session.scalar(select(func.count()).select_from(DeviceCredential)) >= 100:
                raise ValueError("Revoke an unused reader credential before adding another.")
            device = DeviceCredential(
                name=request.name,
                scope=request.scope,
                digest=hashlib.sha256(password.encode()).hexdigest(),
            )
            session.add(device)
            session.flush()
            return DeviceIssued(
                device=device_out(device),
                username="stacks",
                password=password,
                catalog_url=catalog_url,
            )

    def list(self, limit=24, offset=0):
        with self.library.sessions() as session:
            return DevicePage(
                items=[
                    device_out(device)
                    for device in session.scalars(
                        select(DeviceCredential)
                        .order_by(DeviceCredential.created_at.desc(), DeviceCredential.id)
                        .limit(limit)
                        .offset(offset)
                    )
                ],
                total=session.scalar(select(func.count()).select_from(DeviceCredential)),
                limit=limit,
                offset=offset,
            )

    def revoke(self, device_id):
        with self.library.lock, self.library.sessions.begin() as session:
            device = session.get(DeviceCredential, device_id)
            if device is None:
                raise KeyError(device_id)
            session.delete(device)

    def authenticate(self, username, password):
        if username != "stacks" or len(password) > 256:
            return None
        digest = hashlib.sha256(password.encode()).hexdigest()
        with self.library.lock, self.library.sessions.begin() as session:
            device = session.scalar(
                select(DeviceCredential).where(DeviceCredential.digest == digest)
            )
            if device is None:
                return None
            threshold = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
            if device.last_used_at is None or device.last_used_at < threshold:
                device.last_used_at = now()
            return device.scope
