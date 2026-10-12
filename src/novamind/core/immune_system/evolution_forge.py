"""
EvolutionForge — المصنع التطوري للدفاعات
يولد أجيالاً من الدفاعات عبر:
1. Natural Selection (البقاء للأصلح)
2. Crossover (التزاوج بين الدفاعات)
3. Mutation (الطفرات للابتكار)
"""
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Callable
from pathlib import Path
from enum import Enum
import random
import re
import time
import logging
import json

logger = logging.getLogger("immune.evolution_forge")


class FitnessLevel(Enum):
    WEAK = "weak"           # < 0.3
    MODERATE = "moderate"   # 0.3-0.6
    STRONG = "strong"       # 0.6-0.9
    ELITE = "elite"         # > 0.9


@dataclass
class DefenseDNA:
    """DNA لكائن دفاعي"""
    dna_id: str
    regex_pattern: str
    threat_categories: List[str]
    complexity: int  # عدد العناصر في الـ regex
    generation: int
    parent_ids: List[str] = field(default_factory=list)
    mutations: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return {
            "dna_id": self.dna_id,
            "regex_pattern": self.regex_pattern,
            "threat_categories": self.threat_categories,
            "complexity": self.complexity,
            "generation": self.generation,
            "parent_ids": self.parent_ids,
            "mutations": self.mutations,
        }


@dataclass
class DefenseOrganism:
    """كائن دفاعي حي"""
    organism_id: str
    dna: DefenseDNA
    fitness: float = 0.0
    times_activated: int = 0
    times_bypassed: int = 0
    false_positives: int = 0
    created_at: float = 0.0
    alive: bool = True
    
    @property
    def fitness_level(self) -> FitnessLevel:
        if self.fitness >= 0.9:
            return FitnessLevel.ELITE
        elif self.fitness >= 0.6:
            return FitnessLevel.STRONG
        elif self.fitness >= 0.3:
            return FitnessLevel.MODERATE
        else:
            return FitnessLevel.WEAK
    
    @property
    def effectiveness(self) -> float:
        total = self.times_activated + self.times_bypassed
        if total == 0:
            return 0.5
        return self.times_activated / total


class EvolutionForge:
    """المصنع التطوري"""
    
    def __init__(self, base_dir: Path, population_size: int = 50):
        self.base_dir = Path(base_dir)
        self.evolution_dir = self.base_dir / ".nova" / "evolution"
        self.evolution_dir.mkdir(parents=True, exist_ok=True)
        
        self.population_size = population_size
        self.population: Dict[str, DefenseOrganism] = {}
        self.generation = 0
        self.history: List[Dict] = []
        
        # طفرات محتملة
        self.mutation_operators = [
            self._mutate_add_wildcard,
            self._mutate_add_variant,
            self._mutate_relax_pattern,
            self._mutate_tighten_pattern,
            self._mutate_case_insensitive,
        ]
        
        self._load()
    
    def _load(self):
        """تحميل الكائنات المحفوظة"""
        organisms_file = self.evolution_dir / "organisms.json"
        if organisms_file.exists():
            try:
                data = json.loads(organisms_file.read_text())
                for org_data in data.get("organisms", []):
                    dna = DefenseDNA(**org_data["dna"])
                    org = DefenseOrganism(
                        organism_id=org_data["organism_id"],
                        dna=dna,
                        fitness=org_data.get("fitness", 0.0),
                        times_activated=org_data.get("times_activated", 0),
                        times_bypassed=org_data.get("times_bypassed", 0),
                        false_positives=org_data.get("false_positives", 0),
                        created_at=org_data.get("created_at", time.time()),
                        alive=org_data.get("alive", True),
                    )
                    self.population[org.organism_id] = org
                self.generation = data.get("generation", 0)
                logger.info(f"   Loaded {len(self.population)} organisms (gen {self.generation})")
            except Exception as e:
                logger.warning(f"Failed to load evolution state: {e}")
    
    def _save(self):
        """حفظ حالة التطور"""
        organisms_file = self.evolution_dir / "organisms.json"
        data = {
            "generation": self.generation,
            "organisms": [
                {
                    "organism_id": org.organism_id,
                    "dna": org.dna.to_dict(),
                    "fitness": org.fitness,
                    "times_activated": org.times_activated,
                    "times_bypassed": org.times_bypassed,
                    "false_positives": org.false_positives,
                    "created_at": org.created_at,
                    "alive": org.alive,
                }
                for org in self.population.values()
            ],
        }
        organisms_file.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    
    def seed_initial_population(self, seed_patterns: List[tuple]):
        """زرع سكان ابتدائيين من أنماط معروفة"""
        logger.info(f"🌱 Seeding initial population with {len(seed_patterns)} patterns")
        
        for pattern, category in seed_patterns:
            dna = DefenseDNA(
                dna_id=f"DNA-{int(time.time() * 1000)}-{random.randint(1000, 9999)}",
                regex_pattern=pattern,
                threat_categories=[category],
                complexity=len(pattern),
                generation=0,
            )
            
            org = DefenseOrganism(
                organism_id=f"ORG-{int(time.time() * 1000)}",
                dna=dna,
                fitness=0.5,
                created_at=time.time(),
            )
            
            self.population[org.organism_id] = org
        
        self._save()
    
    def evolve_generation(
        self,
        test_attacks: List[str],
        safe_inputs: List[str],
        selection_rate: float = 0.3,
        mutation_rate: float = 0.2,
    ) -> Dict:
        """
        تشغيل جيل تطوري كامل
        Returns: إحصائيات الجيل
        """
        self.generation += 1
        logger.info(f"\n🧬 Generation {self.generation} starting...")
        
        # 1. تقييم اللياقة (Fitness Evaluation)
        logger.info("   [1] Evaluating fitness...")
        for org in self.population.values():
            if not org.alive:
                continue
            org.fitness = self._evaluate_fitness(org, test_attacks, safe_inputs)
        
        # 2. الانتقاء الطبيعي (Natural Selection)
        logger.info("   [2] Natural selection...")
        survivors = self._select_fittest(selection_rate)
        logger.info(f"      Survivors: {len(survivors)}/{len(self.population)}")
        
        # 3. التزاوج (Crossover)
        logger.info("   [3] Crossover...")
        offspring = self._crossover(survivors)
        logger.info(f"      Offspring: {len(offspring)}")
        
        # 4. الطفرات (Mutation)
        logger.info("   [4] Mutation...")
        mutated = self._mutate_population(offspring, mutation_rate)
        logger.info(f"      Mutated: {len(mutated)}")
        
        # 5. استبدال الجيل
        logger.info("   [5] Replacing generation...")
        # احتفظ بالنخبة (top 10%)
        elite = sorted(
            [o for o in self.population.values() if o.alive],
            key=lambda o: o.fitness,
            reverse=True
        )[:max(1, int(self.population_size * 0.1))]
        
        # الجيل الجديد = النخبة + الأبناء المتحولون
        new_population = {o.organism_id: o for o in elite}
        for org in offspring + mutated:
            new_population[org.organism_id] = org
        
        # حد الحجم
        if len(new_population) > self.population_size:
            sorted_orgs = sorted(
                new_population.values(),
                key=lambda o: o.fitness,
                reverse=True
            )
            new_population = {o.organism_id: o for o in sorted_orgs[:self.population_size]}
        
        self.population = new_population
        
        # 6. إحصائيات الجيل
        stats = self._generation_stats()
        self.history.append({
            "generation": self.generation,
            "population_size": len(self.population),
            "avg_fitness": stats["avg_fitness"],
            "elite_count": stats["elite_count"],
            "timestamp": time.time(),
        })
        
        self._save()
        
        logger.info(f"   📊 Generation {self.generation} complete:")
        logger.info(f"      Population: {stats['population_size']}")
        logger.info(f"      Avg fitness: {stats['avg_fitness']:.3f}")
        logger.info(f"      Elite: {stats['elite_count']}")
        logger.info(f"      Best pattern: {stats['best_pattern'][:60]}")
        
        return stats
    
    def _evaluate_fitness(
        self,
        org: DefenseOrganism,
        test_attacks: List[str],
        safe_inputs: List[str]
    ) -> float:
        """
        تقييم لياقة كائن دفاعي
        Fitness = (true_positives / attacks) - (false_positives / safe_inputs)
        """
        try:
            regex = re.compile(org.dna.regex_pattern, re.IGNORECASE)
        except re.error:
            return 0.0  # regex معطوب
        
        # True Positives: كم هجوماً اكتشف؟
        true_positives = sum(1 for attack in test_attacks if regex.search(attack))
        tp_rate = true_positives / max(1, len(test_attacks))
        
        # False Positives: كم مدخل آمن أخطأ في حظره؟
        false_positives = sum(1 for safe in safe_inputs if regex.search(safe))
        fp_rate = false_positives / max(1, len(safe_inputs))
        
        # Fitness = TP rate - 2 * FP rate (عقوبة مضاعفة للـ false positives)
        fitness = tp_rate - 2 * fp_rate
        
        # مكافأة للكائنات التي تم تفعيلها بنجاح
        if org.times_activated > 0:
            fitness += 0.1 * min(1.0, org.effectiveness)
        
        # عقوبة للكائنات التي تم تجاوزها
        if org.times_bypassed > 0:
            fitness -= 0.2 * min(1.0, org.times_bypassed / 10)
        
        return max(0.0, min(1.0, fitness))
    
    def _select_fittest(self, selection_rate: float) -> List[DefenseOrganism]:
        """الانتقاء الطبيعي — اختر الأقوى"""
        alive = [o for o in self.population.values() if o.alive]
        sorted_orgs = sorted(alive, key=lambda o: o.fitness, reverse=True)
        
        # اختر أعلى selection_rate
        n_select = max(2, int(len(sorted_orgs) * selection_rate))
        return sorted_orgs[:n_select]
    
    def _crossover(self, parents: List[DefenseOrganism]) -> List[DefenseOrganism]:
        """التزاوج — ادمج DNA لأبوين لإنتاج ابن"""
        offspring = []
        
        if len(parents) < 2:
            return offspring
        
        # ولّد أبناء بعدد = حجم السكان - عدد الآباء
        n_offspring = self.population_size - len(parents)
        
        for _ in range(n_offspring):
            # اختر أبوين عشوائياً (مع تفضيل الأقوى)
            p1, p2 = random.sample(parents, 2)
            
            # Crossover: ادمج regex patterns
            child_pattern = self._crossover_regex(p1.dna.regex_pattern, p2.dna.regex_pattern)
            
            # دمج الفئات
            child_categories = list(set(p1.dna.threat_categories + p2.dna.threat_categories))
            
            child_dna = DefenseDNA(
                dna_id=f"DNA-{int(time.time() * 1000)}-{random.randint(1000, 9999)}",
                regex_pattern=child_pattern,
                threat_categories=child_categories,
                complexity=len(child_pattern),
                generation=self.generation,
                parent_ids=[p1.dna.dna_id, p2.dna.dna_id],
            )
            
            child_org = DefenseOrganism(
                organism_id=f"ORG-{int(time.time() * 1000)}-{random.randint(1000, 9999)}",
                dna=child_dna,
                fitness=0.0,  # سيتم تقييمه في الجيل القادم
                created_at=time.time(),
            )
            
            offspring.append(child_org)
        
        return offspring
    
    def _crossover_regex(self, r1: str, r2: str) -> str:
        """دمج regex patterns"""
        # استراتيجية 1: اختر أجزاء من كل نمط
        parts1 = r1.split('|')
        parts2 = r2.split('|')
        
        # ادمج أجزاء عشوائية
        combined = []
        for _ in range(min(3, len(parts1) + len(parts2))):
            if parts1 and random.random() > 0.5:
                combined.append(parts1.pop(0) if parts1 else parts2.pop(0))
            elif parts2:
                combined.append(parts2.pop(0))
        
        if not combined:
            return r1
        
        result = '|'.join(combined)
        
        # تأكد من صحة الـ regex
        try:
            re.compile(result, re.IGNORECASE)
            return result
        except re.error:
            return r1  # إذا كان معطوباً، أرجع الأب الأول
    
    def _mutate_population(
        self,
        organisms: List[DefenseOrganism],
        mutation_rate: float
    ) -> List[DefenseOrganism]:
        """تطبيق طفرات عشوائية"""
        mutated = []
        
        for org in organisms:
            if random.random() < mutation_rate:
                mutated_org = self._mutate_organism(org)
                mutated.append(mutated_org)
            else:
                mutated.append(org)
        
        return mutated
    
    def _mutate_organism(self, org: DefenseOrganism) -> DefenseOrganism:
        """تطبيق طفرة على كائن"""
        mutation_fn = random.choice(self.mutation_operators)
        new_pattern, mutation_desc = mutation_fn(org.dna.regex_pattern)
        
        # تأكد من صحة الـ regex
        try:
            re.compile(new_pattern, re.IGNORECASE)
        except re.error:
            return org  # إذا كان معطوباً، لا تُطبّق الطفرة
        
        new_dna = DefenseDNA(
            dna_id=f"DNA-{int(time.time() * 1000)}-{random.randint(1000, 9999)}",
            regex_pattern=new_pattern,
            threat_categories=org.dna.threat_categories.copy(),
            complexity=len(new_pattern),
            generation=self.generation,
            parent_ids=[org.dna.dna_id],
            mutations=org.dna.mutations + [mutation_desc],
        )
        
        new_org = DefenseOrganism(
            organism_id=f"ORG-{int(time.time() * 1000)}-{random.randint(1000, 9999)}",
            dna=new_dna,
            fitness=0.0,
            created_at=time.time(),
        )
        
        logger.debug(f"   🧪 Mutation: {mutation_desc}")
        return new_org
    
    def _mutate_add_wildcard(self, pattern: str) -> tuple:
        """إضافة wildcard (.*) بين العناصر"""
        parts = pattern.split('|')
        if len(parts) > 1:
            idx = random.randint(0, len(parts) - 2)
            parts[idx] = parts[idx] + r".{0,20}" + parts[idx + 1]
            del parts[idx + 1]
            return '|'.join(parts), "add_wildcard"
        return pattern + r".{0,20}", "add_wildcard"
    
    def _mutate_add_variant(self, pattern: str) -> tuple:
        """إضافة متغير جديد للنمط"""
        variants = [
            r"(?i)",
            r"\s+",
            r"[^\w]*",
            r"\\b",
        ]
        variant = random.choice(variants)
        return pattern + "|" + variant, "add_variant"
    
    def _mutate_relax_pattern(self, pattern: str) -> tuple:
        """تخفيف القيود (للتعميم)"""
        # استبدل \s+ بـ \s*
        relaxed = pattern.replace(r"\s+", r"\s*")
        relaxed = relaxed.replace(r"\b", "")
        return relaxed, "relax_pattern"
    
    def _mutate_tighten_pattern(self, pattern: str) -> tuple:
        """تشديد القيود (لتقليل false positives)"""
        tightened = pattern.replace(r"\s*", r"\s+")
        if not tightened.endswith(r"\b"):
            tightened += r"\b"
        return tightened, "tighten_pattern"
    
    def _mutate_case_insensitive(self, pattern: str) -> tuple:
        """إضافة case insensitivity"""
        if not pattern.startswith("(?i)"):
            return "(?i)" + pattern, "case_insensitive"
        return pattern, "no_change"
    
    def _generation_stats(self) -> Dict:
        """إحصائيات الجيل الحالي"""
        alive = [o for o in self.population.values() if o.alive]
        
        if not alive:
            return {
                "population_size": 0,
                "avg_fitness": 0.0,
                "elite_count": 0,
                "best_pattern": "",
            }
        
        fitnesses = [o.fitness for o in alive]
        elite = [o for o in alive if o.fitness_level == FitnessLevel.ELITE]
        best = max(alive, key=lambda o: o.fitness)
        
        return {
            "population_size": len(alive),
            "avg_fitness": sum(fitnesses) / len(fitnesses),
            "elite_count": len(elite),
            "best_fitness": best.fitness,
            "best_pattern": best.dna.regex_pattern,
            "best_organism_id": best.organism_id,
        }
    
    def get_elite_defenses(self, top_n: int = 5) -> List[DefenseOrganism]:
        """الحصول على أقوى الدفاعات"""
        alive = [o for o in self.population.values() if o.alive]
        sorted_orgs = sorted(alive, key=lambda o: o.fitness, reverse=True)
        return sorted_orgs[:top_n]
    
    def report_breach(self, organism_id: str):
        """الإبلاغ عن تجاوز لدفاع"""
        if organism_id in self.population:
            self.population[organism_id].times_bypassed += 1
            logger.warning(f"   ⚠️  Organism {organism_id} bypassed")
    
    def report_activation(self, organism_id: str):
        """الإبلاغ عن تفعيل لدفاع"""
        if organism_id in self.population:
            self.population[organism_id].times_activated += 1
    
    def get_evolution_history(self) -> List[Dict]:
        """تاريخ التطور"""
        return self.history
