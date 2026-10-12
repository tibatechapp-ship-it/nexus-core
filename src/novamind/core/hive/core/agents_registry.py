"""Mock agents registry for hive.factory.executor."""


class _MockAgent(dict):
    def __init__(self, name):
        super().__init__()
        self["name"] = name
        self["specialty"] = "generic"
        self["tools"] = []
        self["permissions"] = ["*"]
        self["system_prompt"] = "You are a helpful agent."
        self["role"] = "agent"

    @property
    def name(self):
        return self["name"]

    @property
    def specialty(self):
        return self["specialty"]

    def get_specialty(self):
        return self["specialty"]


_MOCK_AGENTS = {}


def get_agent(name):
    if name not in _MOCK_AGENTS:
        _MOCK_AGENTS[name] = _MockAgent(name)
    return _MOCK_AGENTS[name]


def can_use_tool(agent, tool):
    return True


def has_permission(agent, action):
    return True


def record_tool_call(*args, **kwargs):
    pass
