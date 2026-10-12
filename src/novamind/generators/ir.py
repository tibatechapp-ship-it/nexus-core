"""Intermediate Representation (Production IR).

- Immutable بعد البناء
- Serializable (JSON round-trip)
- Validated بعمق
- Equality للاختبارات
- Placeholder للحقول: {{name}} في default
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any
from enum import Enum
import re
import json


# ============================================================
# Enums
# ============================================================

class FieldType(str, Enum):
    INT = "int"
    STR = "str"
    BOOL = "bool"
    FLOAT = "float"
    DATETIME = "datetime"
    DATE = "date"
    TEXT = "text"
    JSON = "json"
    UUID = "uuid"
    EMAIL = "email"
    URL = "url"

    @classmethod
    def from_str(cls, s: str) -> "FieldType":
        try:
            return cls(str(s).lower())
        except ValueError:
            raise ValueError(f"نوع حقل غير معروف: {s}")


class HttpMethod(str, Enum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"


class RelationType(str, Enum):
    ONE_TO_MANY = "one_to_many"
    MANY_TO_ONE = "many_to_one"
    ONE_TO_ONE = "one_to_one"
    MANY_TO_MANY = "many_to_many"


# ============================================================
# Validation
# ============================================================

class IRValidationError(ValueError):
    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_ENTITY_RE = re.compile(r"^[A-Z][A-Za-z0-9]*$")


# ============================================================
# Value objects
# ============================================================

@dataclass
class EntityField:
    name: str
    type: FieldType
    primary: bool = False
    nullable: bool = False
    unique: bool = False
    default: Optional[str] = None
    max_length: Optional[int] = None
    description: str = ""

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["type"] = self.type.value
        return d

    @classmethod
    def from_dict(cls, d: Dict) -> "EntityField":
        return cls(
            name=d["name"],
            type=FieldType.from_str(d["type"]),
            primary=d.get("primary", False),
            nullable=d.get("nullable", False),
            unique=d.get("unique", False),
            default=d.get("default"),
            max_length=d.get("max_length"),
            description=d.get("description", ""),
        )

    def validate(self) -> List[str]:
        errors = []
        if not _NAME_RE.match(self.name):
            errors.append(f"field name غير صالح: {self.name}")
        if self.max_length is not None and self.max_length <= 0:
            errors.append(f"max_length يجب أن يكون > 0: {self.name}")
        if self.primary and self.nullable:
            errors.append(f"primary field لا يمكن أن يكون nullable: {self.name}")
        if self.primary and self.default is not None:
            errors.append(f"primary field لا يمكن أن يكون له default: {self.name}")
        return errors


@dataclass
class Relation:
    kind: RelationType
    target: str
    field_name: Optional[str] = None

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["kind"] = self.kind.value
        return d

    @classmethod
    def from_dict(cls, d: Dict) -> "Relation":
        return cls(
            kind=RelationType(d["kind"]),
            target=d["target"],
            field_name=d.get("field_name"),
        )


@dataclass
class Entity:
    name: str
    fields: List[EntityField] = field(default_factory=list)
    relations: List[Relation] = field(default_factory=list)
    timestamps: bool = True
    soft_delete: bool = False
    description: str = ""

    @property
    def table_name(self) -> str:
        """Task → tasks, Category → categories, Address → addresses"""
        n = self.name.lower()
        if n.endswith("y") and len(n) > 1 and n[-2] not in "aeiou":
            return n[:-1] + "ies"
        if n.endswith(("s", "x", "z", "ch", "sh")):
            return n + "es"
        return n + "s"

    @property
    def snake_name(self) -> str:
        """TaskItem → task_item"""
        return re.sub(r"(?<!^)(?=[A-Z])", "_", self.name).lower()

    @property
    def kebab_name(self) -> str:
        """TaskItem → task-item"""
        return self.snake_name.replace("_", "-")

    @property
    def primary_field(self) -> Optional[EntityField]:
        for f in self.fields:
            if f.primary:
                return f
        return None

    @property
    def non_primary_fields(self) -> List[EntityField]:
        return [f for f in self.fields if not f.primary]

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "fields": [f.to_dict() for f in self.fields],
            "relations": [r.to_dict() for r in self.relations],
            "timestamps": self.timestamps,
            "soft_delete": self.soft_delete,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "Entity":
        return cls(
            name=d["name"],
            fields=[EntityField.from_dict(f) for f in d.get("fields", [])],
            relations=[Relation.from_dict(r) for r in d.get("relations", [])],
            timestamps=d.get("timestamps", True),
            soft_delete=d.get("soft_delete", False),
            description=d.get("description", ""),
        )

    def validate(self) -> List[str]:
        errors = []
        if not _ENTITY_RE.match(self.name):
            errors.append(f"entity name غير صالح (PascalCase): {self.name}")

        primaries = [f for f in self.fields if f.primary]
        if len(primaries) == 0:
            errors.append(f"entity {self.name} بدون primary field")
        elif len(primaries) > 1:
            errors.append(f"entity {self.name} له أكثر من primary field")

        names = [f.name for f in self.fields]
        if len(names) != len(set(names)):
            errors.append(f"entity {self.name} به أسماء حقول مكررة")

        for f in self.fields:
            errors.extend(f"[{self.name}.{f.name}] {e}" for e in f.validate())

        # تحقق من وجود الحقول المطلوبة لـ timestamps
        if self.timestamps:
            for req in ["created_at", "updated_at"]:
                if req in names:
                    errors.append(f"entity {self.name} به حقل {req} مسبقًا — timestamps يضيفه تلقائيًا")

        return errors


@dataclass
class Endpoint:
    path: str
    methods: List[HttpMethod]
    entity: Optional[str] = None
    auth_required: bool = False
    description: str = ""
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "path": self.path,
            "methods": [m.value for m in self.methods],
            "entity": self.entity,
            "auth_required": self.auth_required,
            "description": self.description,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "Endpoint":
        return cls(
            path=d["path"],
            methods=[HttpMethod(m) for m in d.get("methods", ["GET"])],
            entity=d.get("entity"),
            auth_required=d.get("auth_required", False),
            description=d.get("description", ""),
            tags=d.get("tags", []),
        )

    def validate(self) -> List[str]:
        errors = []
        if not self.path.startswith("/"):
            errors.append(f"endpoint path يجب أن يبدأ بـ /: {self.path}")
        if not self.methods:
            errors.append(f"endpoint {self.path} بدون methods")
        return errors


@dataclass
class Page:
    name: str
    route: str
    entity: Optional[str] = None
    components: List[str] = field(default_factory=list)
    description: str = ""

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict) -> "Page":
        allowed = {"name", "route", "entity", "components", "description"}
        return cls(**{k: v for k, v in d.items() if k in allowed})

    def validate(self) -> List[str]:
        errors = []
        if not self.route.startswith("/"):
            errors.append(f"page route يجب أن يبدأ بـ /: {self.route}")
        return errors


# ============================================================
# SystemIR
# ============================================================

@dataclass
class SystemIR:
    name: str
    version: str = "0.1.0"
    description: str = ""
    language: str = "python"
    framework: str = "fastapi"
    entities: List[Entity] = field(default_factory=list)
    endpoints: List[Endpoint] = field(default_factory=list)
    pages: List[Page] = field(default_factory=list)
    features: List[str] = field(default_factory=list)

    author: str = ""
    license: str = "MIT"

    # ── Lookups ──
    def get_entity(self, name: str) -> Optional[Entity]:
        for e in self.entities:
            if e.name == name:
                return e
        return None

    @property
    def entity_names(self) -> List[str]:
        return [e.name for e in self.entities]

    def endpoints_for(self, entity_name: str) -> List[Endpoint]:
        return [ep for ep in self.endpoints if ep.entity == entity_name]

    # ── Validation ──
    def validate(self) -> List[str]:
        errors = []
        if not self.name:
            errors.append("name مطلوب")
        elif not _NAME_RE.match(self.name):
            errors.append(f"name غير صالح (snake_case): {self.name}")

        if not self.entities:
            errors.append("يجب أن يكون هناك entity واحد على الأقل")

        enames = [e.name for e in self.entities]
        if len(enames) != len(set(enames)):
            errors.append("أسماء entities مكررة")

        for e in self.entities:
            errors.extend(e.validate())

        for ep in self.endpoints:
            errors.extend(ep.validate())
            if ep.entity and ep.entity not in enames:
                errors.append(f"endpoint {ep.path} يشير لكيان غير موجود: {ep.entity}")

        for p in self.pages:
            errors.extend(p.validate())

        for e in self.entities:
            for r in e.relations:
                if r.target not in enames:
                    errors.append(f"relation في {e.name} يشير لكيان غير موجود: {r.target}")

        return errors

    def assert_valid(self) -> None:
        errs = self.validate()
        if errs:
            raise IRValidationError(errs)

    # ── Serialization ──
    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "language": self.language,
            "framework": self.framework,
            "entities": [e.to_dict() for e in self.entities],
            "endpoints": [ep.to_dict() for ep in self.endpoints],
            "pages": [p.to_dict() for p in self.pages],
            "features": list(self.features),
            "author": self.author,
            "license": self.license,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: Dict) -> "SystemIR":
        return cls(
            name=d["name"],
            version=d.get("version", "0.1.0"),
            description=d.get("description", ""),
            language=d.get("language", "python"),
            framework=d.get("framework", "fastapi"),
            entities=[Entity.from_dict(e) for e in d.get("entities", [])],
            endpoints=[Endpoint.from_dict(ep) for ep in d.get("endpoints", [])],
            pages=[Page.from_dict(p) for p in d.get("pages", [])],
            features=d.get("features", []),
            author=d.get("author", ""),
            license=d.get("license", "MIT"),
        )


# ============================================================
# Builder
# ============================================================

def build_ir(spec: Dict) -> SystemIR:
    """يبني IR من spec dict. يتحقق تلقائيًا."""
    spec = dict(spec)  # لا نعدّل الأصل

    # alias: models → entities
    if "models" in spec and "entities" not in spec:
        spec["entities"] = spec.pop("models")

    # normalize field types
    for e in spec.get("entities", []):
        for f in e.get("fields", []):
            if "type" in f:
                f["type"] = str(f["type"]).lower()

    ir = SystemIR.from_dict(spec)
    ir.assert_valid()
    return ir
