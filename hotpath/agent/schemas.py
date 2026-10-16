"""Structured artifacts exchanged between Nemotron and HotPath.

Anything the model produces that HotPath acts on is validated against one of
these schemas; nothing is scraped out of prose.
"""

from pydantic import BaseModel, Field

from hotpath.execution.worktrees import FileChange


class PatchCandidate(BaseModel):
    name: str = Field(description="Short identifier, e.g. 'per-sku-locks'")
    strategy: str = Field(description="One sentence: what the fix changes")
    expected_effect: str = Field(description="What should happen to latency, throughput and correctness")
    risks: str = Field(default="", description="What could go wrong with this approach")
    changes: list[FileChange] = Field(
        default=[], description="Complete new contents of every file the fix modifies or creates"
    )
    patch: str | None = Field(default=None, description="Alternatively, a unified diff (used for hand-written patches)")
