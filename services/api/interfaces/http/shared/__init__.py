"""HTTP routes shared by the React web app and Codmes surface."""

from . import auth, health, me, notices

__all__ = ["auth", "health", "me", "notices"]
