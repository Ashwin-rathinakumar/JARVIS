import os
import sys
import platform
import shutil
from pathlib import Path
from typing import Dict, Any


def get_system_information() -> str:
    """Return comprehensive information about the system and runtime."""
    info = {
        "Operating System": platform.system(),
        "OS Version": platform.version(),
        "Release": platform.release(),
        "Architecture": platform.machine(),
        "Processor": platform.processor(),
        "Computer Name": platform.node(),
        "Python Version": sys.version.split()[0],
        "Working Directory": str(Path.cwd()),
    }

    # Add disk info
    try:
        total, used, free = shutil.disk_usage(Path.cwd())
        info["Disk Space"] = f"{free / (1024**3):.1f} GB free of {total / (1024**3):.1f} GB"
    except Exception:
        pass

    # Add CPU cores
    cores = os.cpu_count()
    if cores:
        info["CPU Cores"] = str(cores)

    output = []
    for key, value in info.items():
        output.append(f"{key}: {value}")

    return "\n".join(output)


def get_cpu_info() -> str:
    """Return CPU information."""
    cores = os.cpu_count() or "Unknown"
    return f"Processor: {platform.processor()}\nArchitecture: {platform.machine()}\nLogical CPU Cores: {cores}"


def get_memory_info() -> str:
    """Return RAM usage information on Windows."""
    try:
        import ctypes
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        mem = MEMORYSTATUSEX()
        mem.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem)):
            total_gb = mem.ullTotalPhys / (1024 ** 3)
            avail_gb = mem.ullAvailPhys / (1024 ** 3)
            used_gb = total_gb - avail_gb
            return (
                f"Memory Load: {mem.dwMemoryLoad}%\n"
                f"Total RAM: {total_gb:.2f} GB\n"
                f"Used RAM: {used_gb:.2f} GB\n"
                f"Available RAM: {avail_gb:.2f} GB"
            )
    except Exception as e:
        return f"Unable to retrieve memory info: {e}"

    return "Memory information unavailable on this platform."


def get_disk_info() -> str:
    """Return disk usage for current drive."""
    try:
        drive = Path.cwd().anchor or "C:\\"
        total, used, free = shutil.disk_usage(drive)
        return (
            f"Drive: {drive}\n"
            f"Total: {total / (1024**3):.2f} GB\n"
            f"Used: {used / (1024**3):.2f} GB ({used / total * 100:.1f}%)\n"
            f"Free: {free / (1024**3):.2f} GB"
        )
    except Exception as e:
        return f"Unable to retrieve disk info: {e}"


def get_hostname() -> str:
    """Return the hostname/computer name."""
    return f"Computer Name: {platform.node()}"


def get_python_version() -> str:
    """Return the Python runtime version."""
    return f"Python {platform.python_version()} ({platform.python_implementation()})"


def get_current_directory() -> str:
    """Return the current working directory."""
    return f"Current Directory: {Path.cwd()}"