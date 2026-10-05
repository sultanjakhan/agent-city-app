"""Read local host facts without probing providers or launching model runtimes."""
from datetime import datetime, timezone
import os
import platform
import shutil


def snapshot(data_directory):
    memory = None
    if hasattr(os, "sysconf"):
        try:
            pages, page_size = os.sysconf("SC_PHYS_PAGES"), os.sysconf("SC_PAGE_SIZE")
            if pages > 0 and page_size > 0:
                memory = pages * page_size
        except (ValueError, OSError):
            pass
    disk = shutil.disk_usage(data_directory)
    return {"schemaVersion": 1, "observedAt": datetime.now(timezone.utc).isoformat(),
            "system": platform.system(), "release": platform.release(),
            "architecture": platform.machine(), "logicalCpuCount": os.cpu_count(),
            "physicalMemoryBytes": memory,
            "dataDisk": {"totalBytes": disk.total, "freeBytes": disk.free}}
