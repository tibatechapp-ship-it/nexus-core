"""Reputation Economy - كل جندي لديه رصيد سمعة."""
import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Any, Optional

logger = logging.getLogger("Reputation")

# مكافآت وعقوبات
REWARDS = {
    "task_success": +5,
    "task_elite": +20,        # أداء استثنائي
    "vaccine_produced": +15,  # اكتشف تهديداً جديداً
    "consensus_correct": +8,  # صوّت صح في الإجماع
}

PENALTIES = {
    "task_failure": -3,
    "task_timeout": -5,
    "hallucination": -15,
    "constitution_violation": -30,
    "consensus_wrong": -10,
}

# عتبات
RANK_UP_THRESHOLD = 100    # coins للترقية
DEMOTION_THRESHOLD = -50   # coins للتخفيض
EXILE_THRESHOLD = -100     # coins للإقصاء


class ReputationBank:
    """بنك السمعة: يدير رصيد كل جندي."""
    
    def __init__(self, file_path: str = "data/company/reputation.json"):
        Path(file_path).parent.mkdir(parents=True, exist_ok=True)
        self.file_path = file_path
        self.accounts: Dict[str, Dict] = {}
        self.transactions: List[Dict] = []
        self._load()
    
    def _load(self):
        if Path(self.file_path).exists():
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.accounts = data.get("accounts", {})
                self.transactions = data.get("transactions", [])
    
    def _save(self):
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump({
                "accounts": self.accounts,
                "transactions": self.transactions[-500:],  # آخر 500 معاملة
            }, f, ensure_ascii=False, indent=2)
    
    def open_account(self, soldier_id: str, initial: int = 50) -> Dict:
        """يفتح حساباً لجندي جديد."""
        if soldier_id not in self.accounts:
            self.accounts[soldier_id] = {
                "soldier_id": soldier_id,
                "balance": initial,
                "lifetime_earned": 0,
                "lifetime_spent": 0,
                "transactions": 0,
                "opened": time.time(),
                "last_change": time.time(),
            }
            self._save()
            logger.info(f"Opened account for {soldier_id}: +{initial}")
        return self.accounts[soldier_id]
    
    def reward(self, soldier_id: str, action: str, reason: str = "") -> Dict:
        """يكافئ جندياً على إجراء."""
        amount = REWARDS.get(action, 0)
        if amount == 0:
            return {"error": f"Unknown reward: {action}"}
        return self._transact(soldier_id, amount, action, reason)
    
    def penalize(self, soldier_id: str, action: str, reason: str = "") -> Dict:
        """يعاقب جندياً على إجراء."""
        amount = PENALTIES.get(action, 0)
        if amount == 0:
            return {"error": f"Unknown penalty: {action}"}
        return self._transact(soldier_id, amount, action, reason)
    
    def _transact(self, soldier_id: str, amount: int, action: str, reason: str) -> Dict:
        if soldier_id not in self.accounts:
            self.open_account(soldier_id)
        
        acc = self.accounts[soldier_id]
        acc["balance"] += amount
        if amount > 0:
            acc["lifetime_earned"] += amount
        else:
            acc["lifetime_spent"] += abs(amount)
        acc["transactions"] += 1
        acc["last_change"] = time.time()
        
        tx = {
            "soldier_id": soldier_id,
            "amount": amount,
            "action": action,
            "reason": reason[:200],
            "balance_after": acc["balance"],
            "time": time.time(),
        }
        self.transactions.append(tx)
        self._save()
        
        # قرار
        decision = self._decide(acc["balance"])
        logger.info(f"{soldier_id}: {amount:+d} ({action}) → {acc['balance']} [{decision}]")
        
        return {
            "soldier_id": soldier_id,
            "amount": amount,
            "new_balance": acc["balance"],
            "decision": decision,
        }
    
    def _decide(self, balance: int) -> str:
        if balance <= EXILE_THRESHOLD:
            return "EXILE"
        if balance <= DEMOTION_THRESHOLD:
            return "DEMOTE"
        if balance >= RANK_UP_THRESHOLD:
            return "PROMOTE"
        return "KEEP"
    
    def get_balance(self, soldier_id: str) -> int:
        return self.accounts.get(soldier_id, {}).get("balance", 0)
    
    def get_account(self, soldier_id: str) -> Optional[Dict]:
        return self.accounts.get(soldier_id)
    
    def leaderboard(self, top: int = 10) -> List[Dict]:
        """أفضل 10 جنود."""
        sorted_accounts = sorted(
            self.accounts.values(),
            key=lambda a: a["balance"],
            reverse=True
        )
        return sorted_accounts[:top]
    
    def stats(self) -> Dict[str, Any]:
        if not self.accounts:
            return {"accounts": 0, "total_coins": 0}
        balances = [a["balance"] for a in self.accounts.values()]
        return {
            "accounts": len(self.accounts),
            "total_coins": sum(balances),
            "avg_balance": round(sum(balances) / len(balances), 2),
            "richest": max(balances),
            "poorest": min(balances),
        }
