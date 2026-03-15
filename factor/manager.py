"""
Factor Manager
- ファクターのライフサイクル管理
- 自動淘汰 (50トレード後に評価)
- パフォーマンス追跡
"""
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional
from pathlib import Path

from .miner import Factor, FactorHypothesis, FactorMiner, FactorType
from .backtester import FactorBacktester, BacktestResult


@dataclass
class FactorStats:
    """ファクター統計"""
    total_factors: int
    active_factors: int
    killed_factors: int
    avg_ic: float
    avg_sharpe: float
    best_factor: Optional[str] = None
    worst_factor: Optional[str] = None


class FactorManager:
    """ファクター管理"""
    
    DATA_DIR = Path(__file__).parent.parent / "data" / "factors"
    
    def __init__(
        self,
        max_active_factors: int = 10,
        min_ic: float = 0.05,
        min_trades_for_evaluation: int = 50,
        auto_kill: bool = True,
    ):
        """
        初期化
        
        Args:
            max_active_factors: 最大アクティブファクター数
            min_ic: 最小IC (これ以下は淘汰)
            min_trades_for_evaluation: 評価に必要なトレード数
            auto_kill: 自動淘汰を有効化
        """
        self.max_active_factors = max_active_factors
        self.min_ic = min_ic
        self.min_trades_for_evaluation = min_trades_for_evaluation
        self.auto_kill = auto_kill
        
        # ファクター格納
        self.factors: Dict[str, Factor] = {}
        
        # ツール
        self.miner = FactorMiner()
        self.backtester = FactorBacktester()
        
        # データディレクトリ作成
        os.makedirs(self.DATA_DIR, exist_ok=True)
        
        # 保存されたファクターを読み込み
        self._load_factors()
    
    # ========== ファクター操作 ==========
    
    async def mine_new_factor(
        self,
        context: str = None,
        factor_type: FactorType = None,
    ) -> Optional[Factor]:
        """
        新しいファクターを生成・バックテスト・追加
        
        Args:
            context: 市場コンテキスト
            factor_type: 生成するタイプ
        
        Returns:
            追加されたFactor or None
        """
        # アクティブ数チェック
        active_count = sum(1 for f in self.factors.values() if f.is_active)
        if active_count >= self.max_active_factors:
            print(f"⚠️ アクティブファクター上限 ({self.max_active_factors}) に達しています")
            # 最悪のファクターを淘汰
            self._kill_worst_factor()
        
        # 仮説生成
        existing_names = [f.hypothesis.name for f in self.factors.values()]
        hypothesis = await self.miner.generate_hypothesis(
            context=context,
            factor_type=factor_type,
            existing_factors=existing_names,
        )
        
        if not hypothesis:
            return None
        
        print(f"📝 新仮説: {hypothesis.name}")
        
        # バックテスト
        result = self.backtester.backtest(hypothesis)
        
        print(f"   IC: {result.ic:.3f} | Sharpe: {result.sharpe:.2f} | Win: {result.win_rate:.0%}")
        
        # ICチェック
        if result.ic < self.min_ic:
            print(f"   ❌ IC不足 ({result.ic:.3f} < {self.min_ic})")
            return None
        
        # Factor作成
        factor = Factor(
            hypothesis=hypothesis,
            ic=result.ic,
            sharpe=result.sharpe,
            win_rate=result.win_rate,
            total_trades=result.total_trades,
            total_pnl=result.total_pnl,
        )
        
        # 追加
        self.factors[hypothesis.id] = factor
        self._save_factors()
        
        print(f"   ✅ ファクター追加: {hypothesis.name}")
        
        return factor
    
    def add_factor(self, factor: Factor):
        """ファクターを追加"""
        self.factors[factor.hypothesis.id] = factor
        self._save_factors()
    
    def get_factor(self, factor_id: str) -> Optional[Factor]:
        """ファクターを取得"""
        return self.factors.get(factor_id)
    
    def get_active_factors(self) -> List[Factor]:
        """アクティブなファクターを取得"""
        return [f for f in self.factors.values() if f.is_active]
    
    def kill_factor(self, factor_id: str, reason: str = "Manual"):
        """ファクターを淘汰"""
        if factor_id in self.factors:
            factor = self.factors[factor_id]
            factor.is_active = False
            factor.deactivated_at = datetime.now()
            factor.deactivate_reason = reason
            self._save_factors()
            print(f"💀 ファクター淘汰: {factor.hypothesis.name} ({reason})")
    
    # ========== トレード記録 ==========
    
    def record_trade(
        self,
        factor_id: str,
        pnl: float,
        entry_price: float,
        exit_price: float,
    ):
        """
        トレードを記録
        
        Args:
            factor_id: ファクターID
            pnl: 損益
            entry_price: エントリー価格
            exit_price: エグジット価格
        """
        if factor_id not in self.factors:
            return
        
        factor = self.factors[factor_id]
        
        # 履歴追加
        factor.trade_history.append({
            "timestamp": datetime.now().isoformat(),
            "pnl": pnl,
            "entry_price": entry_price,
            "exit_price": exit_price,
        })
        
        # 統計更新
        factor.total_trades += 1
        factor.total_pnl += pnl
        
        wins = sum(1 for t in factor.trade_history if t.get("pnl", 0) > 0)
        factor.win_rate = wins / len(factor.trade_history)
        
        # IC再計算 (簡易)
        avg_pnl = factor.total_pnl / factor.total_trades
        factor.ic = (factor.win_rate - 0.5) * 2 * (1 + avg_pnl / 100)
        factor.ic = max(-1, min(1, factor.ic))
        
        # 自動淘汰チェック
        if self.auto_kill:
            self._check_and_kill(factor)
        
        self._save_factors()
    
    def _check_and_kill(self, factor: Factor):
        """淘汰条件をチェック"""
        if not factor.is_active:
            return
        
        # 最小トレード数に達していなければスキップ
        if factor.total_trades < self.min_trades_for_evaluation:
            return
        
        # IC不足
        if factor.ic < self.min_ic:
            self.kill_factor(
                factor.hypothesis.id,
                f"IC不足 ({factor.ic:.3f} < {self.min_ic})"
            )
            return
        
        # 連続損失 (5連敗)
        recent = factor.trade_history[-5:]
        if len(recent) >= 5 and all(t.get("pnl", 0) < 0 for t in recent):
            self.kill_factor(
                factor.hypothesis.id,
                "5連敗"
            )
    
    def _kill_worst_factor(self):
        """最悪のファクターを淘汰"""
        active = self.get_active_factors()
        if not active:
            return
        
        # ICが最も低いファクターを選択
        worst = min(active, key=lambda f: f.ic)
        self.kill_factor(worst.hypothesis.id, "スペース確保のため淘汰")
    
    # ========== 統計 ==========
    
    def get_stats(self) -> FactorStats:
        """統計を取得"""
        factors = list(self.factors.values())
        active = [f for f in factors if f.is_active]
        killed = [f for f in factors if not f.is_active]
        
        avg_ic = sum(f.ic for f in active) / len(active) if active else 0
        avg_sharpe = sum(f.sharpe for f in active) / len(active) if active else 0
        
        best = max(active, key=lambda f: f.ic) if active else None
        worst = min(active, key=lambda f: f.ic) if active else None
        
        return FactorStats(
            total_factors=len(factors),
            active_factors=len(active),
            killed_factors=len(killed),
            avg_ic=avg_ic,
            avg_sharpe=avg_sharpe,
            best_factor=best.hypothesis.name if best else None,
            worst_factor=worst.hypothesis.name if worst else None,
        )
    
    def get_leaderboard(self, top_n: int = 10) -> List[Dict]:
        """リーダーボードを取得"""
        active = self.get_active_factors()
        sorted_factors = sorted(active, key=lambda f: f.ic, reverse=True)
        
        return [
            {
                "rank": i + 1,
                "name": f.hypothesis.name,
                "type": f.hypothesis.type.value,
                "ic": f"{f.ic:.3f}",
                "sharpe": f"{f.sharpe:.2f}",
                "win_rate": f"{f.win_rate:.0%}",
                "trades": f.total_trades,
                "pnl": f"${f.total_pnl:.2f}",
            }
            for i, f in enumerate(sorted_factors[:top_n])
        ]
    
    # ========== 永続化 ==========
    
    def _save_factors(self):
        """ファクターを保存"""
        data = {}
        for fid, factor in self.factors.items():
            data[fid] = {
                "hypothesis": factor.hypothesis.to_dict(),
                "ic": factor.ic,
                "sharpe": factor.sharpe,
                "win_rate": factor.win_rate,
                "total_trades": factor.total_trades,
                "total_pnl": factor.total_pnl,
                "is_active": factor.is_active,
                "deactivated_at": factor.deactivated_at.isoformat() if factor.deactivated_at else None,
                "deactivate_reason": factor.deactivate_reason,
                "trade_history": factor.trade_history[-100:],  # 最新100件のみ
            }
        
        path = self.DATA_DIR / "factors.json"
        with open(path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def _load_factors(self):
        """ファクターを読み込み"""
        path = self.DATA_DIR / "factors.json"
        if not path.exists():
            return
        
        try:
            with open(path) as f:
                data = json.load(f)
            
            for fid, fdata in data.items():
                hyp_data = fdata["hypothesis"]
                hypothesis = FactorHypothesis(
                    id=hyp_data["id"],
                    name=hyp_data["name"],
                    description=hyp_data["description"],
                    type=FactorType(hyp_data["type"]),
                    entry_condition=hyp_data["entry_condition"],
                    exit_condition=hyp_data["exit_condition"],
                    parameters=hyp_data.get("parameters", {}),
                )
                
                factor = Factor(
                    hypothesis=hypothesis,
                    ic=fdata["ic"],
                    sharpe=fdata["sharpe"],
                    win_rate=fdata["win_rate"],
                    total_trades=fdata["total_trades"],
                    total_pnl=fdata["total_pnl"],
                    is_active=fdata["is_active"],
                    trade_history=fdata.get("trade_history", []),
                )
                
                if fdata.get("deactivated_at"):
                    factor.deactivated_at = datetime.fromisoformat(fdata["deactivated_at"])
                factor.deactivate_reason = fdata.get("deactivate_reason", "")
                
                self.factors[fid] = factor
            
            print(f"📂 {len(self.factors)} ファクターを読み込みました")
            
        except Exception as e:
            print(f"⚠️ ファクター読み込みエラー: {e}")


# テスト
async def _cli():
    import argparse
    
    parser = argparse.ArgumentParser(description="Factor Manager")
    parser.add_argument("--mine", help="新ファクター生成 (コンテキスト)")
    parser.add_argument("--list", action="store_true", help="アクティブファクター一覧")
    parser.add_argument("--stats", action="store_true", help="統計表示")
    parser.add_argument("--leaderboard", action="store_true", help="リーダーボード")
    parser.add_argument("--evaluate", action="store_true", help="全ファクター評価")
    
    args = parser.parse_args()
    
    manager = FactorManager(max_active_factors=5)
    
    if args.mine:
        print(f"⛏️ 新ファクター生成中...")
        print(f"   コンテキスト: {args.mine}\n")
        
        factor = await manager.mine_new_factor(
            context=args.mine,
            factor_type=FactorType.MOMENTUM,
        )
        
        if factor:
            print(f"✅ 追加: {factor.hypothesis.name}")
            print(f"   ID: {factor.hypothesis.id}")
            print(f"   説明: {factor.hypothesis.description}")
        else:
            print("❌ 生成失敗")
    
    elif args.list:
        print("📋 アクティブファクター:\n")
        for f in manager.factors.values():
            print(f"  • {f.hypothesis.name}")
            print(f"    ID: {f.hypothesis.id}")
            print(f"    トレード数: {f.total_trades}")
            print(f"    IC: {f.ic:.4f}")
            print()
    
    elif args.stats:
        stats = manager.get_stats()
        print("📊 統計:\n")
        print(f"  総ファクター:     {stats.total_factors}")
        print(f"  アクティブ:       {stats.active_factors}")
        print(f"  淘汰済み:         {stats.killed_factors}")
        print(f"  平均IC:           {stats.avg_ic:.4f}")
        print(f"  平均Sharpe:       {stats.avg_sharpe:.2f}")
        if stats.best_factor:
            print(f"  ベスト:           {stats.best_factor}")
        if stats.worst_factor:
            print(f"  ワースト:         {stats.worst_factor}")
    
    elif args.leaderboard:
        print("🏆 リーダーボード:\n")
        leaderboard = manager.get_leaderboard()
        if leaderboard:
            for entry in leaderboard:
                ic_str = f"{entry['ic']:.4f}" if isinstance(entry['ic'], float) else entry['ic']
                print(f"  {entry['rank']}. {entry['name']} (IC: {ic_str})")
        else:
            print("  (ファクターがありません)")
    
    elif args.evaluate:
        print("🔍 全ファクター評価中...\n")
        killed = manager.evaluate_all()
        
        if killed:
            print(f"❌ 淘汰: {len(killed)} ファクター")
            for f in killed:
                print(f"   - {f.hypothesis.name}")
        else:
            print("✅ 淘汰なし")
    
    else:
        # デモ
        print("📦 Factor Manager\n")
        print("使い方:")
        print("  --mine 'コンテキスト'  新ファクター生成")
        print("  --list               アクティブファクター一覧")
        print("  --stats              統計表示")
        print("  --leaderboard        リーダーボード")
        print("  --evaluate           全ファクター評価")


if __name__ == "__main__":
    import asyncio
    asyncio.run(_cli())
