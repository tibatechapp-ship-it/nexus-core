"""Isolation — كل وكيل يعمل في عزلة قبل النقاش."""
from __future__ import annotations
from typing import Any
from dataclasses import dataclass


@dataclass
class IsolatedContext:
    member: str
    input: str
    own_response: str = ""
    committed: bool = False


class IsolationManager:
    def __init__(self: Any) -> None:
        self.contexts: dict[str, Any] = {}
        self.phase = "independent"

    def prepare(self: Any, members: Any, input_data: Any) -> Any:
        self.contexts = {}
        for m in members:
            self.contexts[m.name] = IsolatedContext(member=m.name, input=input_data)

    def get_context(self: Any, member_name: Any) -> Any:
        return self.contexts[member_name].input

    def commit(self: Any, member_name: Any, response: Any) -> Any:
        ctx = self.contexts[member_name]
        ctx.own_response = response
        ctx.committed = True

    def all_committed(self: Any) -> Any:
        return all(c.committed for c in self.contexts.values())

    def reveal_for_debate(self: Any) -> Any:
        if not self.all_committed():
            raise RuntimeError("العزل لم يكتمل!")
        self.phase = "debate"
        return {name: ctx.own_response for name, ctx in self.contexts.items()}
