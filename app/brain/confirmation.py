import time
import uuid
from typing import Dict, Optional, Any
from app.core.schemas import ConfirmationDetails
from app.config.settings import ACTION_CONFIRMATION_TTL_SECONDS
from app.utils.logger import logger


class ConfirmationManager:
    """Manages pending confirmations for medium/high-risk actions."""

    def __init__(self):
        self._pending: Dict[str, ConfirmationDetails] = {}

    def create_confirmation(
        self,
        plan_id: str,
        step_id: str,
        tool: str,
        arguments: Dict[str, Any],
        description: str,
    ) -> str:
        """Create a new unpredictable confirmation token with expiration TTL."""
        token = str(uuid.uuid4())
        expires_at = time.time() + ACTION_CONFIRMATION_TTL_SECONDS
        details = ConfirmationDetails(
            confirmation_id=token,
            plan_id=plan_id,
            step_id=step_id,
            tool=tool,
            arguments=arguments,
            description=description,
            expires_at=expires_at,
        )
        self._pending[token] = details
        logger.info(f"Created confirmation request for step '{step_id}' ({tool})")
        return token

    def get_confirmation(self, confirmation_id: str) -> Optional[ConfirmationDetails]:
        """Retrieve confirmation details if valid and not expired."""
        details = self._pending.get(confirmation_id)
        if not details:
            return None
        if time.time() > details.expires_at:
            logger.info("Confirmation expired.")
            del self._pending[confirmation_id]
            return None
        return details

    def consume_confirmation(self, confirmation_id: str) -> Optional[ConfirmationDetails]:
        """Consume and remove confirmation token upon approval."""
        details = self.get_confirmation(confirmation_id)
        if details:
            del self._pending[confirmation_id]
            logger.info(f"Consumed confirmation for step '{details.step_id}'")
            return details
        return None

    def cancel_confirmation(self, confirmation_id: str) -> bool:
        """Cancel a pending confirmation."""
        if confirmation_id in self._pending:
            del self._pending[confirmation_id]
            logger.info("Cancelled confirmation")
            return True
        return False

    def cleanup_expired(self) -> None:
        """Remove all expired tokens."""
        now = time.time()
        expired = [k for k, v in self._pending.items() if now > v.expires_at]
        for k in expired:
            del self._pending[k]


confirmation_manager = ConfirmationManager()
