"""Isolation — كل وكيل يعمل في عزلة قبل النقاش."""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class IsolatedContext:
    member: str
    input: str
    own_response: str = ""
    committed: bool = False


class IsolationManager:
    def __init__(self):
        self.contexts = {}
        self.phase = "independent"

    def prepare(self, members, input_data):
        self.contexts = {}
        for m in members:
            self.contexts[m.name] = IsolatedContext(member=m.name, input=input_data)

    def get_context(self, member_name):
        return self.contexts[member_name].input

    def commit(self, member_name, response):
        ctx = self.contexts[member_name]
        ctx.own_response = response
        ctx.committed = True

    def all_committed(self):
        return all(c.committed for c in self.contexts.values())

    def reveal_for_debate(self):
        if not self.all_committed():
            raise RuntimeError("العزل لم يكتمل!")
        self.phase = "debate"
        return {name: ctx.own_response for name, ctx in self.contexts.items()}
