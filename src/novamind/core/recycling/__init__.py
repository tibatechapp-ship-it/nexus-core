"""وكالة معالجة النفايات البرمجية"""
from .waste_detector import WasteDetector, WasteType, WasteItem, Severity
from .waste_fixer import WasteFixer, FixResult
from .waste_recycler import WasteRecycler, RecycledItem
from .agency import RecyclingAgency, CycleReport
__all__ = [
    "WasteDetector", "WasteType", "WasteItem", "Severity",
    "WasteFixer", "FixResult",
    "WasteRecycler", "RecycledItem",
    "RecyclingAgency", "CycleReport",
]
