"""
Session management API endpoints.
"""

import json
import logging
from fastapi import APIRouter, HTTPException
from sqlalchemy import asc, text

from ii_agent.db.models import Event
from ii_agent.db.manager import DatabaseManager
from ..models.messages import SessionResponse, EventResponse, SessionInfo, EventInfo

logger = logging.getLogger(__name__)

sessions_router = APIRouter(prefix="/api", tags=["sessions"])


@sessions_router.get("/sessions/{device_id}", response_model=SessionResponse)
async def get_sessions_by_device_id(device_id: str):
    """Get all sessions for a specific device ID, sorted by creation time descending.
    For each session, also includes the first user message if available.

    Args:
        device_id: The device identifier to look up sessions for

    Returns:
        A list of sessions with their details and first user message, sorted by creation time descending
    """
    try:
        # Initialize database manager
        db_manager = DatabaseManager()

        # Get all sessions for this device, sorted by created_at descending
        with db_manager.get_session() as session:
            # Use raw SQL query to get sessions with their first user message
            query = text("""
            SELECT 
                session.id AS session_id,
                session.*, 
                event.id AS first_event_id,
                event.event_payload AS first_message,
                event.timestamp AS first_event_time
            FROM session
            LEFT JOIN event ON session.id = event.session_id
            WHERE event.id IN (
                SELECT e.id
                FROM event e
                WHERE e.event_type = "user_message" 
                AND e.timestamp = (
                    SELECT MIN(e2.timestamp)
                    FROM event e2
                    WHERE e2.session_id = e.session_id
                    AND e2.event_type = "user_message"
                )
            )
            AND session.device_id = :device_id
            ORDER BY session.created_at DESC
            """)

            # Execute the raw query with parameters
            result = session.execute(query, {"device_id": device_id})

            # Convert result to a list of dictionaries
            sessions = []
            for row in result:
                session_data = SessionInfo(
                    id=row.id,
                    workspace_dir=row.workspace_dir,
                    created_at=row.created_at,
                    device_id=row.device_id,
                    first_message=json.loads(row.first_message)
                    .get("content", {})
                    .get("text", "")
                    if row.first_message
                    else "",
                )
                sessions.append(session_data)

            return SessionResponse(sessions=sessions)

    except Exception as e:
        logger.error(f"Error retrieving sessions: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error retrieving sessions: {str(e)}"
        )


@sessions_router.get("/sessions/{session_id}/events", response_model=EventResponse)
async def get_session_events(session_id: str):
    """Get all events for a specific session ID, sorted by timestamp ascending.

    Args:
        session_id: The session identifier to look up events for

    Returns:
        A list of events with their details, sorted by timestamp ascending
    """
    try:
        # Initialize database manager
        db_manager = DatabaseManager()

        # Get all events for this session, sorted by timestamp ascending
        with db_manager.get_session() as session:
            events = (
                session.query(Event)
                .filter(Event.session_id == session_id)
                .order_by(asc(Event.timestamp))
                .all()
            )

            # Convert events to a list of dictionaries
            event_list = []
            for e in events:
                event_info = EventInfo(
                    id=e.id,
                    session_id=e.session_id,
                    timestamp=e.timestamp.isoformat(),
                    event_type=e.event_type,
                    event_payload=e.event_payload,
                    workspace_dir=e.session.workspace_dir,
                )
                event_list.append(event_info)

            return EventResponse(events=event_list)

    except Exception as e:
        logger.error(f"Error retrieving events: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error retrieving events: {str(e)}"
        )
