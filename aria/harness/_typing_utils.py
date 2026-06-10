from __future__ import annotations

import re

_TYPING_SUBTASK_RE = re.compile(r"^\s*(type|enter)\b", re.IGNORECASE)


def is_typing_subtask(subtask: str) -> bool:
    return bool(_TYPING_SUBTASK_RE.match(subtask))
