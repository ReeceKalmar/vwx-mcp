"""Bounded reads of native status snapshots, never a request/job retry.

Windows can briefly deny a read while the native publisher atomically replaces
the file. Only that PermissionError is retried. Parsing, freshness and schema
validation belong to the caller and must still fail closed. Do not use this
helper for leases, requests, publication records or native result files.
"""
from pathlib import Path
import time


def read_diagnostic_text(path):
    """Read UTF-8 status text with four attempts and at most 30ms of delay."""
    path = Path(path)
    for attempt in range(4):
        try:
            return path.read_text(encoding='utf-8')
        except PermissionError:
            if attempt == 3:
                raise
            time.sleep(0.01)
