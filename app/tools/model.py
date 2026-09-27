from typing import Any, Dict


def get_model_status(brain=None) -> Dict[str, Any]:
    if brain is None:
        return {"success": False, "message": "Model status is unavailable.", "error_code": "MODEL_STATUS_UNAVAILABLE"}
    status = brain.status()
    availability = "available" if status["available"] else "unavailable"
    fallback = status.get("fallback") or "none"
    return {
        "success": True,
        "message": (
            f"Model provider: {status['provider']}. Model: {status['model']}. "
            f"Endpoint: {status['endpoint_category']}. Status: {availability}. Fallback: {fallback}."
        ),
        "data": status,
    }
