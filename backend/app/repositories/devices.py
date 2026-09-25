"""Device registration repository.

``UserDeviceRepository`` lives in ``app.repositories.sync`` alongside the change log it is
used with; this module re-exports it so ``app.repositories`` has one obvious import path
per concept.
"""

from app.repositories.sync import UserDeviceRepository

__all__ = ["UserDeviceRepository"]
