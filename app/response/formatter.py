import re
from typing import Union, Any, Optional
from app.core.schemas import ChatResponse


class ResponseFormatter:
    """Formats assistant responses into natural language suitable for voice and speech."""

    @staticmethod
    def format_for_voice(response: Union[ChatResponse, str, dict]) -> str:
        """Convert a ChatResponse, string, or dict into a concise natural language string."""
        if not response:
            return "I didn't catch that."

        # Extract text response from ChatResponse
        if isinstance(response, ChatResponse):
            raw_text = response.response or ""
            status = response.status
            error = response.error
            is_success = response.success
        elif isinstance(response, dict):
            raw_text = str(response.get("response", response.get("message", "")))
            status = response.get("status")
            error = response.get("error")
            is_success = response.get("success", True)
        else:
            raw_text = str(response)
            status = None
            error = None
            is_success = True

        raw_text = raw_text.strip()
        if not raw_text:
            return "I didn't catch that."

        # 1. Confirmation required format
        if status == "confirmation_required" or "requires confirmation:" in raw_text.lower():
            m = re.search(r"confirmation:\s*([^\n]+)", raw_text, re.IGNORECASE)
            desc = m.group(1).strip() if m else "this action"
            return f"{desc} requires confirmation. Do you want me to continue?"

        # 2. Permission denied format
        if "access denied:" in raw_text.lower() or "action denied:" in raw_text.lower():
            clean_reason = raw_text.replace("Access denied:", "").replace("Action denied:", "").strip()
            return f"Action denied: {clean_reason}"

        # 3. Tool creation success format
        if raw_text.startswith("Created folder:"):
            folder_name = raw_text.replace("Created folder:", "").strip()
            return f"Created the folder {folder_name}."

        if raw_text.startswith("Created file:"):
            file_name = raw_text.replace("Created file:", "").strip()
            return f"Created the file {file_name}."

        if "opened" in raw_text.lower() and "in vs code" in raw_text.lower():
            return raw_text

        # 4. Clean markdown formatting for voice (remove code fences, asterisks, bullet dashes)
        clean = raw_text
        clean = re.sub(r"```[\s\S]*?```", "", clean)
        clean = re.sub(r"[*_`#]", "", clean)
        clean = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", clean)

        # Trim long technical lists if speaking
        lines = [line.strip() for line in clean.split("\n") if line.strip()]
        if len(lines) > 5:
            clean = " ".join(lines[:3]) + " and more."
        else:
            clean = " ".join(lines)

        return clean.strip() or "Task completed."
