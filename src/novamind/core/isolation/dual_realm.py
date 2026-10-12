"""
DualRealm — الفصل التام بين نظام التشغيل ونظام التدريب

- Operations Realm: العاملون (ينفذون مهام)
- Training Realm: المدربون (يصنعون وكلاء)
- Coordination Bridge: قناة وحيدة بينهم (controlled)
"""
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Set
from pathlib import Path
import uuid
import json
import time
import logging

logger = logging.getLogger("dual_realm")


class Realm(Enum):
    OPERATIONS = "operations"
    TRAINING = "training"
    COORDINATION = "coordination"


@dataclass
class RealmIdentity:
    """هوية داخل عالم معين"""
    agent_id: str
    realm: Realm
    name: str
    rank: str
    domain: str
    created_at: float = 0.0
    # الأهم: لا يعرف إلا realmه
    visible_realms: Set[Realm] = field(default_factory=set)
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = time.time()
        # كل كيان يرى realmه فقط + coordination
        if not self.visible_realms:
            self.visible_realms = {self.realm, Realm.COORDINATION}


class DualRealmManager:
    """
    مدير العالمين المعزولين
    
    قاعدة صارمة:
    - Operations لا ترى Training والعكس
    - التواصل فقط عبر Coordination
    - كل realm له base_dir خاص
    """
    
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir / ".nova" / "realms"
        
        # مساحات منفصلة
        self.operations_dir = self.base_dir / "operations"
        self.training_dir = self.base_dir / "training"
        self.coordination_dir = self.base_dir / "coordination"
        
        for d in [self.operations_dir, self.training_dir, self.coordination_dir]:
            d.mkdir(parents=True, exist_ok=True)
        
        # سجلات منفصلة
        self.identities: Dict[str, RealmIdentity] = {}
        self.realm_members: Dict[Realm, Set[str]] = {
            Realm.OPERATIONS: set(),
            Realm.TRAINING: set(),
            Realm.COORDINATION: set(),
        }
        
        # جدار ناري — من يستطيع التواصل مع من
        self.firewall: Dict[Realm, Set[Realm]] = {
            Realm.OPERATIONS: {Realm.OPERATIONS, Realm.COORDINATION},
            Realm.TRAINING: {Realm.TRAINING, Realm.COORDINATION},
            Realm.COORDINATION: {Realm.OPERATIONS, Realm.TRAINING, Realm.COORDINATION},
        }
        
        logger.info("DualRealmManager initialized")
    
    def register(self, identity: RealmIdentity) -> str:
        """سجّل كياناً في عالمه"""
        self.identities[identity.agent_id] = identity
        self.realm_members[identity.realm].add(identity.agent_id)
        
        # احفظ في مساحته
        realm_dir = self._get_realm_dir(identity.realm)
        (realm_dir / f"{identity.agent_id}.json").write_text(
            json.dumps({
                "id": identity.agent_id,
                "name": identity.name,
                "rank": identity.rank,
                "domain": identity.domain,
                "realm": identity.realm.value,
            }, indent=2, ensure_ascii=False)
        )
        
        logger.info(f"Registered [{identity.realm.value}] {identity.name} ({identity.agent_id})")
        return identity.agent_id
    
    def _get_realm_dir(self, realm: Realm) -> Path:
        return {
            Realm.OPERATIONS: self.operations_dir,
            Realm.TRAINING: self.training_dir,
            Realm.COORDINATION: self.coordination_dir,
        }[realm]
    
    def can_communicate(self, from_id: str, to_id: str) -> bool:
        """هل يمكن لهذين الكيانين التواصل؟"""
        if from_id not in self.identities or to_id not in self.identities:
            return False
        
        from_realm = self.identities[from_id].realm
        to_realm = self.identities[to_id].realm
        
        # فحص جدار الحماية
        return to_realm in self.firewall[from_realm]
    
    def list_visible(self, agent_id: str) -> List[str]:
        """من يرى هذا الكيان؟ (فقط realmه + coordination)"""
        if agent_id not in self.identities:
            return []
        
        identity = self.identities[agent_id]
        visible = set()
        
        for other_id, other in self.identities.items():
            if other_id == agent_id:
                continue
            if other.realm in identity.visible_realms:
                visible.add(other_id)
        
        return list(visible)
    
    def isolate_write(self, agent_id: str, key: str, value: Any):
        """كتابة معزولة داخل realm الكيان"""
        if agent_id not in self.identities:
            return
        
        identity = self.identities[agent_id]
        realm_dir = self._get_realm_dir(identity.realm)
        agent_file = realm_dir / f"{agent_id}_state.json"
        
        state = {}
        if agent_file.exists():
            state = json.loads(agent_file.read_text())
        state[key] = value
        agent_file.write_text(json.dumps(state, indent=2, default=str, ensure_ascii=False))
    
    def stats(self) -> Dict:
        """إحصائيات النظامين"""
        return {
            "operations_count": len(self.realm_members[Realm.OPERATIONS]),
            "training_count": len(self.realm_members[Realm.TRAINING]),
            "coordination_count": len(self.realm_members[Realm.COORDINATION]),
            "total": len(self.identities),
        }
