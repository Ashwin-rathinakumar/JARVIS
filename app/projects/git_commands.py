"""Explicit Git command grammar. General Git questions never select a tool."""
import re

from app.brain.routing import normalize_request_text


def parse_git_command(message):
    text = re.sub(r"^please\s+", "", normalize_request_text(message), flags=re.I).rstrip(".!?")
    operation = None
    target = None
    commit_message = None
    status = re.fullmatch(r"(?:(?:check|show|get)\s+(?:the\s+)?|what(?:'s| is)\s+(?:the\s+)?)?git\s+status(?:\s+(?:of|for)\s+(.+))?", text, re.I)
    status = status or re.fullmatch(r"(?:check|show)\s+(.+?)\s+git\s+status", text, re.I)
    text = re.sub(r"\s+first$", "", text, flags=re.I)
    branch = re.fullmatch(r"what\s+branch\s+(?:am\s+i\s+on|is\s+(.+?)\s+on)", text, re.I)
    if status or branch:
        operation, target = "status", (status or branch).group(1)
    else:
        match = re.fullmatch(r"(push|pull|upload)\s*(.*)", text, re.I)
        if match:
            operation = {"upload": "publish"}.get(match[1].lower(), match[1].lower())
            target = re.sub(r"\s+to\s+github$", "", match[2], flags=re.I)
            target = re.sub(r"^(?:the\s+)?latest\s+", "", target, flags=re.I)
            target = re.sub(r"^(?:changes\s+(?:of|for|from)\s+)", "", target, flags=re.I)
            target = re.sub(r"\s+changes$", "", target, flags=re.I)
        else:
            match = re.fullmatch(r"(?:commit\b|create\s+a\s+commit\b)\s*(.*)", text, re.I)
            if match:
                body = match[1]
                push = re.search(r"\s*(?:and|then|and then)\s+push(?:\s+(?:them|it))?(?:\s+to\s+github)?$", body, re.I)
                operation = "commit_push" if push else "commit"
                if push:
                    body = body[:push.start()]
                parts = re.split(r"\s*(?:\bas\b|\bcalled\b|\bwith message\b)\s*", body, maxsplit=1, flags=re.I)
                target = re.sub(r"^(?:the\s+|these\s+|those\s+|current\s+)*changes\s*(?:(?:of|for|in)\s+)?", "", parts[0], flags=re.I)
                if len(parts) == 2:
                    commit_message = parts[1].strip().strip('"')
    if not operation:
        return None
    target = (target or "").strip()
    if target.lower() in {"", "it", "its", "this", "them", "changes", "those changes", "the repo", "this repo", "this project", "the project", "current project", "the current project", "my project"}:
        target = None
    args = {"project_name": target}
    if operation in {"commit", "commit_push", "publish"}:
        args["message"] = commit_message or "Update project changes"
    return {"intent": "tool", "tool": "git_" + operation, "arguments": args}
