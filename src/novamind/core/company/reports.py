"""Reports - تقارير جاهزة للإرسال."""
import logging
from datetime import datetime
from typing import Dict, List, Any

logger = logging.getLogger("Reports")


from novamind.core.company.insights import InsightsEngine

class ReportGenerator:
    def __init__(self, supreme):
        self.supreme = supreme
    
    def _header(self, title):
        return f"*🏢 NovaMind — {title}*\n{'-' * 30}\n"
    
    def morning_report(self):
        msg = self._header("تقرير الصباح ☀️")
        msg += f"📅 {datetime.now().strftime('%Y-%m-%d')}\n\n"
        soldiers = self.supreme.soldiers
        msg += f"👥 الوكلاء: *{len(soldiers)}*\n"
        specs = {}
        for s in soldiers:
            specs[s.specialty] = specs.get(s.specialty, 0) + 1
        if specs:
            msg += "\n*التخصصات:*\n"
            for spec, count in sorted(specs.items()):
                msg += f"  • {spec}: {count}\n"
        report = self.supreme.full_report()
        msg += f"\n*حالة النظام:*\n"
        msg += f"  • دستور: {'✅' if report['constitution_valid'] else '❌'}\n"
        msg += f"  • سجل: {'✅' if report['audit']['valid'] else '❌'}\n"
        msg += f"  • صناديق: {report['sandbox']['total_sandboxes']}\n"
        
        # Insights
        try:
            insights = InsightsEngine(self.supreme).analyze()
            if insights:
                msg += "\n*ملاحظات:*\n"
                for ins in insights[:3]:
                    emoji = {"CRITICAL": "🚨", "WARNING": "⚠️", "INFO": "ℹ️"}.get(ins["level"], "•")
                    msg += f"{emoji} {ins['message']}\n"
        except Exception:
            pass
        
        return msg
    
    def midday_report(self):
        msg = self._header("تقرير منتصف اليوم 🌤️")
        msg += f"⏰ {datetime.now().strftime('%H:%M')}\n\n"
        s = self.supreme.stats
        msg += f"*العمليات:*\n"
        msg += f"  • مهام: {s['missions_total']}\n"
        msg += f"  • نجح: {s['missions_success']} ✅\n"
        msg += f"  • فشل: {s['missions_failed']} ❌\n"
        msg += f"  • محجوب: {s['missions_blocked']} 🚫\n"
        if s['missions_total'] > 0:
            rate = s['missions_success'] / s['missions_total'] * 100
            msg += f"\n*معدل النجاح:* {rate:.1f}%"
        return msg
    
    def evening_report(self):
        msg = self._header("تقرير المساء 🌆")
        msg += f"⏰ {datetime.now().strftime('%H:%M')}\n\n"
        board = self.supreme.targets.get_leaderboard()
        if board:
            msg += "*🏆 أفضل 5 وكلاء:*\n"
            for i, r in enumerate(board[:5], 1):
                emoji = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"][i-1]
                msg += f"{emoji} {r['soldier_id'][:12]} ({r['specialty']})\n"
                msg += f"    مهام: {r['tasks']} | نجاح: {r['success_rate']*100:.0f}%\n"
        else:
            msg += "لا يوجد نشاط اليوم."
        return msg
    
    def night_report(self):
        msg = self._header("تقرير الليل 🌙")
        msg += f"📅 {datetime.now().strftime('%Y-%m-%d')}\n\n"
        try:
            evaluation = self.supreme.targets.evaluate_all(self.supreme.soldiers)
            msg += "*التقييم اليومي:*\n"
            msg += f"  • تم تقييم: {evaluation['total_evaluated']}\n"
            msg += f"  • Coins: {evaluation['total_coins_delta']:+d}\n\n"
            for v, c in evaluation['verdicts'].items():
                emoji = {"PERFECT": "🌟", "EXCEED": "⭐", "MEET": "✅",
                         "PARTIAL": "⚠️", "MISS_MIN": "❌"}.get(v, "•")
                msg += f"  {emoji} {v}: {c}\n"
        except Exception as e:
            msg += f"⚠️ {e}\n"
        s = self.supreme.stats
        msg += f"\n*الإجماليات:*\n"
        msg += f"  • مهام: {s['missions_total']}\n"
        msg += f"  • نجح: {s['missions_success']}\n"
        msg += f"  • تطعيمات: {s['vaccines']}\n"
        return msg
    
    def status_report(self):
        msg = self._header("حالة النظام 🏥")
        r = self.supreme.full_report()
        s = r['stats']
        msg += "*العمليات:*\n"
        msg += f"  • مهام: {s['missions_total']}\n"
        msg += f"  • نجح: {s['missions_success']}\n"
        msg += f"  • فشل: {s['missions_failed']}\n\n"
        msg += "*البنية:*\n"
        msg += f"  • وكلاء: {r['soldiers_count']}\n"
        msg += f"  • ثكنات: {r['barracks']['total_barracks']}\n"
        msg += f"  • صناديق: {r['sandbox']['total_sandboxes']}\n\n"
        msg += "*التعلم:*\n"
        msg += f"  • جينات: {r['genome']['total_genes']}\n"
        msg += f"  • تطعيمات: {r['vaccination']['total']}\n"
        msg += f"  • دروس: {r['memory']['lessons']}\n"
        return msg
    
    def agents_report(self):
        msg = self._header("قائمة الوكلاء 👥")
        if not self.supreme.soldiers:
            return msg + "لا يوجد وكلاء."
        by_spec = {}
        for s in self.supreme.soldiers:
            by_spec.setdefault(s.specialty, []).append(s)
        for spec, soldiers in sorted(by_spec.items()):
            msg += f"\n*{spec.upper()}* ({len(soldiers)}):\n"
            for s in soldiers[:5]:
                trust = s.stats.trust_score
                emoji = "🟢" if trust >= 0.7 else "🟡" if trust >= 0.4 else "🔴"
                msg += f"  {emoji} {s.id[:12]} | {s.rank.name} | {trust:.2f}\n"
            if len(soldiers) > 5:
                msg += f"  ... و {len(soldiers)-5} آخرين\n"
        return msg
    
    def leaderboard_report(self):
        msg = self._header("لوحة الصدارة 🏆")
        board = self.supreme.targets.get_leaderboard()
        if not board:
            return msg + "لا يوجد نشاط."
        for i, r in enumerate(board[:10], 1):
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"{i}.")
            msg += f"{medal} *{r['soldier_id'][:12]}* ({r['specialty']})\n"
            msg += f"    {r['tasks']} مهمة | {r['success_rate']*100:.0f}% | {r['score']}\n"
        return msg
    
    def full_report(self):
        msg = "=" * 40 + "\n"
        msg += "📊 *تقرير NovaMind الكامل*\n"
        msg += "=" * 40 + "\n\n"
        msg += self.status_report() + "\n"
        msg += self.agents_report() + "\n"
        msg += self.leaderboard_report() + "\n"
        return msg
