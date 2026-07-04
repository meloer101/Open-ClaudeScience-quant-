from __future__ import annotations

from quantbench.memory.store import UserMemoryStore


def build_memory_augmented_system_prompt(base_prompt: str, memory_store: UserMemoryStore) -> str:
    index = memory_store.render_index().strip()
    if not index:
        return base_prompt
    return "\n".join(
        [
            base_prompt.rstrip(),
            "",
            "## User Long-Term Memory",
            "Use these project-global memories only as visible defaults or context. Do not silently change research assumptions.",
            index,
        ]
    )
