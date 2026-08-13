"""Статические ассеты страницы: оформление и скрипты.

Отделены от рендеринга, потому что меняются по другим поводам и другими людьми.
"""

from .css import CSS, TAB_CSS
from .scripts import (
    FILTER_SCRIPT,
    LAUNCH_SCRIPT,
    SEARCH_SCRIPT,
    SSE_SCRIPT,
    STATUS_POLL_SCRIPT,
    TAB_SCRIPT,
    TASK_OPS_SCRIPT,
    VIEW_SCRIPT,
    WORKSPACE_IMPORT_SCRIPT,
)

__all__ = [
    "CSS", "TAB_CSS", "FILTER_SCRIPT", "LAUNCH_SCRIPT", "SEARCH_SCRIPT", "SSE_SCRIPT",
    "STATUS_POLL_SCRIPT", "TAB_SCRIPT", "TASK_OPS_SCRIPT", "VIEW_SCRIPT",
    "WORKSPACE_IMPORT_SCRIPT",
]
