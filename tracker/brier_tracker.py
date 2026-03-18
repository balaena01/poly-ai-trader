"""
Brier Score Tracker
- LLM予測確率の精度を追跡
- skill_score を計算してBayesian/Kellyにフィードバック
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict


class BrierTracker:
    """LLMキャリブレーション追跡"""

    MIN_SAMPLE = 20          # 統計的に意味を持つ最低サンプル数
    DATA_FILE = Path("data/brier_log.json")

    def __init__(self):
        self._records: Dict[str, dict] = {}
        self._load()

    def _load(self):
        if self.DATA_FILE.exists():
            try:
                self._records = json.loads(
                    self.DATA_FILE.read_text(encoding="utf-8")
                )
            except Exception:
                self._records = {}

    def _save(self):
        self.DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        self.DATA_FILE.write_text(
            json.dumps(self._records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def record_prediction(
        self,
        market_id: str,
        llm_prob: float,
        market_price: float,
    ):
        """シグナル生成時にLLM予測を記録（同一マーケットは最初の1件のみ）"""
        if market_id in self._records:
            return  # 既に記録済み → 上書きしない
        self._records[market_id] = {
            "llm_prob": round(llm_prob, 4),
            "market_price": round(market_price, 4),
            "predicted_at": datetime.now().isoformat(),
            "outcome": None,
            "resolved_at": None,
        }
        self._save()

    def record_outcome(self, market_id: str, outcome: float):
        """マーケット解決時に実結果を記録"""
        if market_id not in self._records:
            return
        if self._records[market_id].get("outcome") is not None:
            return  # 既に解決済み
        self._records[market_id]["outcome"] = round(outcome, 1)
        self._records[market_id]["resolved_at"] = datetime.now().isoformat()
        self._save()

    def get_skill_score(self, window: int = 30) -> Optional[float]:
        """
        直近 window 件の skill_score を返す。

        skill_score = 1 - (brier_llm / brier_market)
          > 0  → LLMが市場より優れている
          = 0  → 互角
          < 0  → LLMが市場より劣っている（有害）

        サンプル数 < MIN_SAMPLE の場合は None を返す。
        """
        resolved = [
            r for r in self._records.values()
            if r.get("outcome") is not None
        ]
        resolved.sort(key=lambda r: r.get("resolved_at", ""), reverse=True)
        resolved = resolved[:window]

        if len(resolved) < self.MIN_SAMPLE:
            return None

        brier_llm = sum(
            (r["llm_prob"] - r["outcome"]) ** 2 for r in resolved
        ) / len(resolved)
        brier_market = sum(
            (r["market_price"] - r["outcome"]) ** 2 for r in resolved
        ) / len(resolved)

        if brier_market == 0:
            return None

        return round(1.0 - brier_llm / brier_market, 4)

    def get_stats(self) -> dict:
        """統計情報"""
        resolved = [
            r for r in self._records.values()
            if r.get("outcome") is not None
        ]
        skill = self.get_skill_score()
        return {
            "total_predictions": len(self._records),
            "resolved": len(resolved),
            "skill_score": skill,
            "min_sample": self.MIN_SAMPLE,
            "calibrated": len(resolved) >= self.MIN_SAMPLE,
        }
