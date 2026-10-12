"""A2A Agent Card — describes a NovaMind agent (Google A2A spec)."""
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional

A2A_VERSION = "0.2.0"


@dataclass
class AgentSkill:
    id: str
    name: str
    description: str
    input_modes: List[str] = field(default_factory=lambda: ["text"])
    output_modes: List[str] = field(default_factory=lambda: ["text"])
    tags: List[str] = field(default_factory=list)


@dataclass
class AgentCard:
    name: str
    description: str
    version: str = "1.0.0"
    url: str = "http://localhost:8000"
    capabilities: Dict = field(default_factory=lambda: {"streaming": False})
    default_input_modes: List[str] = field(default_factory=lambda: ["text"])
    default_output_modes: List[str] = field(default_factory=lambda: ["text"])
    skills: List[AgentSkill] = field(default_factory=list)
    provider: Optional[Dict] = None
    documentation_url: Optional[str] = None

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["protocolVersion"] = A2A_VERSION
        return d


__all__ = ["AgentCard", "AgentSkill", "A2A_VERSION"]
