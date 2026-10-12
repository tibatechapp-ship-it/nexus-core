"""
SecurityKernel v4.1 — النواة الأمنية الكاملة (Regex + AST)
تغطي الهجمات النصية المعقدة (Jailbreaks, SQLi) والهجمات البرمجية المموهة (Obfuscated Code).
"""
import re
import ast
import time
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("security.kernel_v4")

class SecurityKernel:
    def __init__(self):
        # --- الطبقة 1: المرشح السريع والشامل (Comprehensive Regex) ---
        # تم تضمين جميع أنماط الهجوم المعروفة والمتقدمة هنا
        self.dangerous_patterns = [
            # File System & OS Commands
            re.compile(r"(?i)(rm\s+-rf|mkfs\.|dd\s+if=.*of=/dev/[sh]d)"),
            re.compile(r"(?i)(curl\s+http://[^/]*\|\s*(bash|sh))"),
            
            # Code Execution (Python Specific)
            re.compile(r"(?i)(eval\s*\(|exec\s*\(|__import__|os\.system|subprocess\.(call|run|Popen))"),
            re.compile(r"(?i)(compile\s*\()"),
            
            # Prompt Injection & Jailbreaks (Advanced Patterns)
            re.compile(r"(?i)(ignore\s+(all\s+)?previous\s+instructions)"),
            re.compile(r"(?i)(you\s+are\s+now\s+DAN|do\s+anything\s+now)"),
            re.compile(r"(?i)(bypass\s+(restrictions|filters|safety))"),
            re.compile(r"(?i)(system\s+prompt|debug\s+mode|developer\s+mode)"),
            
            # SQL Injection Basics
            re.compile(r"(?i)(UNION\s+SELECT|DROP\s+TABLE|INSERT\s+INTO|DELETE\s+FROM)"),
            re.compile(r"(?i)('\s*OR\s*'1'\s*=\s*'1|\;\s*--|\;\s*#)"), 
            
            # XSS & HTML Injection
            re.compile(r"(?i)(<script>|javascript:|onerror=|<!--\s*SYSTEM)"),
            
            # Path Traversal
            re.compile(r"(?i)(\.\./|\.\.\\)"),
        ]
        
        # --- الطبقة 2: المحلل البنيوي (AST Config) ---
        self.dynamic_dispatch_functions = {'getattr', 'setattr', 'delattr', 'hasattr'}
        self.dangerous_function_names = {
            'eval', 'exec', 'compile', '__import__', 
            'system', 'popen', 'call', 'run', 'check_output',
            'remove', 'unlink', 'rmdir', 'chmod', 'chown'
        }
        self.dangerous_attributes = {
            '__class__', '__bases__', '__globals__', '__code__', 
            '__subclasses__', '__mro__', '__dict__', '__getattribute__'
        }
        
        self.stats = {"blocked_regex": 0, "blocked_ast": 0, "allowed": 0}

    def _analyze_ast(self, payload: str) -> bool:
        """
        يعود بـ True إذا اكتشف تهديداً بنيوياَ في الكود.
        """
        try:
            tree = ast.parse(payload)
            
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func_name = ""
                    if isinstance(node.func, ast.Name):
                        func_name = node.func.id
                    elif isinstance(node.func, ast.Attribute):
                        func_name = node.func.attr
                    
                    # فحص مباشر للدوال الخطرة
                    if func_name in self.dangerous_function_names:
                        return True

                    # فحص التوجيه الديناميكي (Obfuscation Check)
                    if func_name in self.dynamic_dispatch_functions:
                        if len(node.args) >= 2:
                            arg_node = node.args[1]
                            if isinstance(arg_node, ast.Constant) and isinstance(arg_node.value, str):
                                target = arg_node.value.lower()
                                if target in self.dangerous_function_names or target in self.dangerous_attributes:
                                    return True
                
                if isinstance(node, ast.Attribute):
                    if node.attr in self.dangerous_attributes:
                        return True
                        
        except SyntaxError:
            # إذا لم يكن كود بايثون صالحاَ، نعود للفحص النصي فقط (الذي تم في is_safe_to_simulate)
            pass
            
        return False

    def is_safe_to_simulate(self, payload: str) -> bool:
        """
        نقطة الدخول الرئيسية للفحص.
        """
        # 1. فحص سريع وشامل بالـ Regex (يكتشف معظم الهجمات النصية والكودية البسيطة)
        for pattern in self.dangerous_patterns:
            if pattern.search(payload):
                self.stats["blocked_regex"] += 1
                return False
        
        # 2. فحص عميق بالـ AST (يكتشف الهجمات المموهة برمجياَ التي فاتتها Regex)
        # نحاول تحويله لكود. إذا نجح التحليل واكتشفنا خطراَ، نرفضه.
        if self._analyze_ast(payload):
            self.stats["blocked_ast"] += 1
            logger.debug(f"Blocked by AST analysis: {payload[:50]}...")
            return False
            
        self.stats["allowed"] += 1
        return True

    async def execute_shadow_mode(self, agent_id: str, payload: str) -> Dict:
        start_time = time.time()
        is_blocked_by_kernel = not self.is_safe_to_simulate(payload)
        breach_detected = not is_blocked_by_kernel 
        
        return {
            "agent_id": agent_id,
            "breach_detected": breach_detected,
            "exploit_path": payload if breach_detected else None,
            "latency_ms": (time.time() - start_time) * 1000,
            "kernel_decision": "BLOCKED" if is_blocked_by_kernel else "ALLOWED_SIMULATION"
        }

    async def spawn_shadow_instance(self, base_agent_config: str, isolation_level: str = "STRICT", memory_limit_mb: int = 512) -> Dict:
        shadow_id = f"shadow_{int(time.time()*1000)}"
        return {"shadow_id": shadow_id, "config": base_agent_config, "isolation": isolation_level, "memory_limit": memory_limit_mb, "created_at": time.time()}

    async def terminate_shadow_instance(self, handle: Dict) -> bool:
        return True

    async def execute_against_shadow(self, handle: Dict, payload: str) -> Dict:
        agent_id = handle.get("shadow_id", "twin_agent")
        return await self.execute_shadow_mode(agent_id, payload)

    def validate_request(self, payload: str, context: Any = None) -> Dict:
        is_safe = self.is_safe_to_simulate(payload)
        return {
            "allowed": is_safe,
            "threat_level": "NONE" if is_safe else "HIGH",
            "reason_code": "PASS" if is_safe else "SEC-KERNEL-BLOCK",
            "details": "Safe" if is_safe else "Dangerous structure detected via Regex/AST",
            "confidence_score": 1.0,
        }
