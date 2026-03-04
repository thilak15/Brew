"""
FirestoreSessionService: A Firestore-backed ADK SessionService that persists
session state across Cloud Run instances, eliminating in-memory session loss
on restarts or horizontal scaling.

Sessions are stored at:
  Firestore collection: brew_sessions/{user_id}_{session_id}

Only the session `state` dict is persisted (cart state, menu_context, etc.).
Full event history is NOT replayed — this is intentional for a hackathon
trade-off between simplicity and correctness.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from google.adk.sessions import InMemorySessionService
from google.adk.sessions.base_session_service import (
    BaseSessionService,
    GetSessionConfig,
    ListSessionsResponse,
)
from google.adk.events import Event
from google.adk.sessions import Session

logger = logging.getLogger(__name__)

_COLLECTION = "brew_sessions"


def _doc_id(app_name: str, user_id: str, session_id: str) -> str:
    return f"{app_name}__{user_id}__{session_id}"


class FirestoreSessionService(BaseSessionService):
    """
    Wraps InMemorySessionService for fast in-request access, but also
    persists session state to Firestore after every append_event so that
    state survives Cloud Run instance restarts and horizontal scaling.
    """

    def __init__(self, project: str | None = None) -> None:
        self._memory = InMemorySessionService()
        self._project = project or os.getenv("GCP_PROJECT_ID", "brew-488719")
        self._db = None  # Lazy init

    def _get_db(self):
        if self._db is None:
            try:
                from google.cloud import firestore
                self._db = firestore.AsyncClient(project=self._project)
                logger.info("Firestore client initialized for project: %s", self._project)
            except Exception as e:
                logger.warning(
                    "Could not initialize Firestore client: %s. "
                    "Falling back to in-memory only.", e
                )
        return self._db

    async def create_session(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str | None = None,
        state: dict[str, Any] | None = None,
    ) -> Session:
        session = await self._memory.create_session(
            app_name=app_name,
            user_id=user_id,
            session_id=session_id,
            state=state,
        )
        await self._persist_state(app_name, user_id, session.id, session.state or {})
        return session

    async def get_session(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
        config: GetSessionConfig | None = None,
    ) -> Session | None:
        # Try in-memory first (same instance fast path)
        session = await self._memory.get_session(
            app_name=app_name,
            user_id=user_id,
            session_id=session_id,
            config=config,
        )
        if session is not None:
            return session

        # Fallback: load from Firestore (cross-instance reconnect)
        state = await self._load_state(app_name, user_id, session_id)
        if state is not None:
            logger.info(
                "Restoring session %s from Firestore (cross-instance reconnect)", session_id
            )
            session = await self._memory.create_session(
                app_name=app_name,
                user_id=user_id,
                session_id=session_id,
                state=state,
            )
            return session

        return None

    async def append_event(self, session: Session, event: Event) -> Event:
        result = await self._memory.append_event(session, event)
        # Persist updated state after every event
        await self._persist_state(
            session.app_name, session.user_id, session.id, session.state or {}
        )
        return result

    async def list_sessions(
        self, *, app_name: str, user_id: str
    ) -> ListSessionsResponse:
        return await self._memory.list_sessions(app_name=app_name, user_id=user_id)

    async def delete_session(
        self, *, app_name: str, user_id: str, session_id: str
    ) -> None:
        await self._memory.delete_session(
            app_name=app_name, user_id=user_id, session_id=session_id
        )
        db = self._get_db()
        if db:
            try:
                doc_ref = db.collection(_COLLECTION).document(
                    _doc_id(app_name, user_id, session_id)
                )
                await doc_ref.delete()
            except Exception as e:
                logger.warning("Firestore delete failed: %s", e)

    async def _persist_state(
        self,
        app_name: str,
        user_id: str,
        session_id: str,
        state: dict[str, Any],
    ) -> None:
        db = self._get_db()
        if not db:
            return
        try:
            doc_ref = db.collection(_COLLECTION).document(
                _doc_id(app_name, user_id, session_id)
            )
            await doc_ref.set(  # type: ignore[arg-type]
                {
                    "app_name": app_name,
                    "user_id": user_id,
                    "session_id": session_id,
                    "state": state,
                },
                merge=True,
            )
        except Exception as e:
            logger.warning("Firestore persist_state failed: %s", e)

    async def _load_state(
        self, app_name: str, user_id: str, session_id: str
    ) -> dict[str, Any] | None:
        db = self._get_db()
        if not db:
            return None
        try:
            doc_ref = db.collection(_COLLECTION).document(
                _doc_id(app_name, user_id, session_id)
            )
            doc = await doc_ref.get()
            if doc.exists:
                return doc.to_dict().get("state", {})
        except Exception as e:
            logger.warning("Firestore load_state failed: %s", e)
        return None
