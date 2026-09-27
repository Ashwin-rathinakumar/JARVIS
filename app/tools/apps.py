import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from app.tools.projects import find_vscode_launcher
from app.utils.logger import logger

APPLICATIONS = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "paint": "mspaint.exe",
    "explorer": "explorer.exe",
}

ALIASES = {
    "microsoft calculator": "calculator",
    "windows calculator": "calculator",
    "calc": "calculator",
    "microsoft notepad": "notepad",
    "windows notepad": "notepad",
    "text editor": "notepad",
    "microsoft paint": "paint",
    "ms paint": "paint",
    "mspaint": "paint",
    "file explorer": "explorer",
    "windows explorer": "explorer",
    "files": "explorer",
    "vscode": "vscode",
    "vs code": "vscode",
    "visual studio code": "vscode",
    "code": "vscode",
    "browser": "browser",
    "web browser": "browser",
    "edge": "msedge",
    "microsoft edge": "msedge",
    "chrome": "chrome",
    "google chrome": "chrome",
}


def normalize_app(app: str) -> str:
    cleaned = app.lower().strip()
    return ALIASES.get(cleaned, cleaned)


def open_application(app: str) -> str:
    app_name = normalize_app(app)

    try:
        if app_name == "vscode":
            launcher_info = find_vscode_launcher()
            if not launcher_info:
                return "I couldn't find VS Code on this machine."
            launcher, use_shell = launcher_info
            if use_shell:
                subprocess.Popen(f'"{launcher}"', shell=True)
            else:
                subprocess.Popen([launcher], shell=False)
            logger.info("Opened VS Code")
            return "Opened VS Code."

        if app_name in {"browser", "web browser"}:
            # Open default browser or Edge
            subprocess.Popen(["cmd.exe", "/c", "start", "https://www.google.com"], shell=False)
            logger.info("Opened web browser")
            return "Opened default web browser."

        if app_name == "msedge":
            subprocess.Popen(["cmd.exe", "/c", "start", "msedge"], shell=False)
            logger.info("Opened Microsoft Edge")
            return "Opened Microsoft Edge."

        if app_name == "chrome":
            chrome_path = shutil.which("chrome") or (
                Path(os.environ.get("ProgramFiles", "")) / "Google" / "Chrome" / "Application" / "chrome.exe"
            )
            if chrome_path and Path(chrome_path).exists():
                subprocess.Popen([str(chrome_path)], shell=False)
                logger.info("Opened Google Chrome")
                return "Opened Google Chrome."
            return "Google Chrome was not found on this machine."

        if app_name == "explorer":
            subprocess.Popen(["explorer.exe"], shell=False)
            logger.info("Opened File Explorer")
            return "Opened File Explorer."

        if app_name in APPLICATIONS:
            subprocess.Popen(APPLICATIONS[app_name], shell=False)
            logger.info(f"Opened {app_name}")
            return f"Opened {app_name}."

        # Try generic which
        which_path = shutil.which(app_name) or shutil.which(f"{app_name}.exe")
        if which_path:
            subprocess.Popen([which_path], shell=False)
            logger.info(f"Opened {app_name} via PATH")
            return f"Opened {app_name}."

        return f"I don't know how to open '{app_name}' yet."

    except Exception as error:
        logger.error(f"Unable to open {app_name}: {error}")
        return f"Unable to open {app_name}: {error}"


def close_application(app: str) -> str:
    app_name = normalize_app(app)

    PROCESS_NAMES = {
        "calculator": "CalculatorApp.exe",
        "notepad": "notepad.exe",
        "paint": "mspaint.exe",
        "vscode": "Code.exe",
        "msedge": "msedge.exe",
        "chrome": "chrome.exe",
    }

    process_name = PROCESS_NAMES.get(app_name)
    if not process_name:
        # Fallback to appending .exe if appropriate
        if not app_name.endswith(".exe"):
            process_name = f"{app_name}.exe"
        else:
            process_name = app_name

    # Never kill critical system processes
    protected = {"explorer.exe", "svchost.exe", "csrss.exe", "winlogon.exe", "services.exe", "python.exe"}
    if process_name.lower() in protected:
        return f"Refusing to close protected process '{process_name}' for system stability."

    try:
        result = subprocess.run(
            ["taskkill", "/IM", process_name, "/F"],
            capture_output=True,
            text=True
        )

        if result.returncode == 0:
            logger.info(f"Closed {app_name} ({process_name})")
            return f"Closed {app_name}."

        return f"{app_name.capitalize()} does not appear to be running."

    except Exception as error:
        logger.error(f"Unable to close {app_name}: {error}")
        return f"Unable to close {app_name}: {error}"