"""
Position Tracker
- オープンポジション管理
- PnL計算 (解決時)
- 永続化
"""
import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Dict, Optional
from pathlib import Path
from enum import Enum


class PositionStatus(Enum):
    OPEN = "open"
    CLOSED = "closed"
    RESOLVED = "resolved"


@dataclass
class Position:
    """ポジション"""
    id: str
    market_id: str
    token_id: str
    question: str
    side: str  # "buy_yes", "buy_no", "BUY_YES", "BUY_NO"
    entry_price: float
    size: float  # USDC
    
    status: PositionStatus = PositionStatus.OPEN
    created_at: datetime = field(default_factory=datetime.now)

    # GTC注文追跡
    order_id: Optional[str] = None        # CLOBのorder ID
    order_filled: bool = True             # False = GTC未約定

    # 解決後
    exit_price: Optional[float] = None
    resolved_at: Optional[datetime] = None
    pnl: float = 0.0
    
    def calculate_unrealized_pnl(self, current_yes_price: float) -> float:
        """含み損益を計算 (YES価格ベース)"""
        if self.status != PositionStatus.OPEN:
            return self.pnl
        
        # 現在価格でポジションを売った場合の損益
        side_upper = self.side.upper()
        
        if side_upper == "BUY_YES":
            # YES を買った → 現在の YES 価格で売る
            current_value = current_yes_price * self.size / self.entry_price
            unrealized = current_value - self.size
        else:  # BUY_NO
            # NO を買った → 現在の NO 価格 (1 - YES) で売る
            current_no_price = 1 - current_yes_price
            entry_no_price = 1 - self.entry_price  # entry_price は YES 価格
            current_value = current_no_price * self.size / entry_no_price
            unrealized = current_value - self.size
        
        return unrealized
    
    def get_unrealized_pnl_pct(self, current_yes_price: float) -> float:
        """含み損益 (%)"""
        if self.size == 0:
            return 0.0
        unrealized = self.calculate_unrealized_pnl(current_yes_price)
        return unrealized / self.size
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "market_id": self.market_id,
            "token_id": self.token_id,
            "question": self.question,
            "side": self.side,
            "entry_price": self.entry_price,
            "size": self.size,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "order_id": self.order_id,
            "order_filled": self.order_filled,
            "exit_price": self.exit_price,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "pnl": self.pnl,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "Position":
        return cls(
            id=data["id"],
            market_id=data["market_id"],
            token_id=data["token_id"],
            question=data["question"],
            side=data["side"],
            entry_price=data["entry_price"],
            size=data["size"],
            status=PositionStatus(data["status"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            order_id=data.get("order_id"),
            order_filled=data.get("order_filled", True),
            exit_price=data.get("exit_price"),
            resolved_at=datetime.fromisoformat(data["resolved_at"]) if data.get("resolved_at") else None,
            pnl=data.get("pnl", 0.0),
        )


class PositionTracker:
    """ポジション追跡"""
    
    DATA_FILE = Path(__file__).parent.parent / "data" / "positions.json"
    
    def __init__(self):
        self.positions: Dict[str, Position] = {}
        self._load()
    
    def record_trade(
        self,
        market_id: str,
        token_id: str,
        question: str,
        side: str,
        entry_price: float,
        size: float,
        order_id: Optional[str] = None,
        order_filled: bool = True,
    ) -> Position:
        """トレード記録"""
        import uuid

        pos_id = str(uuid.uuid4())[:8]

        position = Position(
            id=pos_id,
            market_id=market_id,
            token_id=token_id,
            question=question,
            side=side,
            entry_price=entry_price,
            size=size,
            order_id=order_id,
            order_filled=order_filled,
        )
        
        self.positions[pos_id] = position
        self._save()
        
        print(f"📝 ポジション記録: {side} ${size:.2f} @ {entry_price:.4f}")
        
        return position
    
    def resolve_position(
        self,
        position_id: str,
        resolution: float,  # 1.0 = YES won, 0.0 = NO won
    ) -> float:
        """ポジション解決 + PnL計算"""
        if position_id not in self.positions:
            return 0.0
        
        pos = self.positions[position_id]
        
        if pos.status != PositionStatus.OPEN:
            return pos.pnl
        
        # PnL計算
        # BUY_YES: 勝てば (1 - entry_price) × size, 負ければ -entry_price × size
        # BUY_NO:  勝てば entry_price × size, 負ければ -(1 - entry_price) × size
        
        if pos.side in ("buy_yes", "BUY_YES"):
            if resolution >= 0.5:  # YES won
                pnl = (1 - pos.entry_price) * pos.size
            else:  # NO won
                pnl = -pos.entry_price * pos.size
        else:  # buy_no
            if resolution < 0.5:  # NO won
                pnl = pos.entry_price * pos.size
            else:  # YES won
                pnl = -(1 - pos.entry_price) * pos.size
        
        pos.pnl = pnl
        pos.exit_price = resolution
        pos.status = PositionStatus.RESOLVED
        pos.resolved_at = datetime.now()
        
        self._save()
        
        print(f"💰 解決: {pos.question[:30]}... PnL: ${pnl:+.2f}")
        
        return pnl
    
    def get_pending_positions(self) -> List[Position]:
        """GTC未約定ポジション（order_filled=False）を取得"""
        return [p for p in self.positions.values()
                if p.status == PositionStatus.OPEN and not p.order_filled]

    def mark_order_filled(self, pos_id: str):
        """GTC注文が約定済みとしてマーク"""
        if pos_id in self.positions:
            self.positions[pos_id].order_filled = True
            self._save()

    def remove_position(self, pos_id: str):
        """ポジションを削除（キャンセル時用）"""
        if pos_id in self.positions:
            del self.positions[pos_id]
            self._save()

    def resolve_by_market(self, market_id: str, resolution: float) -> float:
        """マーケットIDで解決"""
        total_pnl = 0.0
        
        for pos in self.positions.values():
            if pos.market_id == market_id and pos.status == PositionStatus.OPEN:
                total_pnl += self.resolve_position(pos.id, resolution)
        
        return total_pnl
    
    def get_open_positions(self) -> List[Position]:
        """オープンポジション取得"""
        return [p for p in self.positions.values() if p.status == PositionStatus.OPEN]
    
    def check_exit_conditions(
        self,
        current_prices: Dict[str, float],  # market_id -> yes_price
        take_profit_pct: float = 0.20,     # 20% で利確
        stop_loss_pct: float = -0.30,      # -30% で損切り
    ) -> List[Dict]:
        """
        利確・損切り条件をチェック
        
        Returns:
            [{"position": Position, "action": "SELL_YES"|"SELL_NO", "reason": str, "pnl_pct": float}]
        """
        exit_signals = []
        
        for pos in self.get_open_positions():
            yes_price = current_prices.get(pos.market_id)
            if yes_price is None:
                continue
            
            pnl_pct = pos.get_unrealized_pnl_pct(yes_price)
            
            # 利確チェック
            if pnl_pct >= take_profit_pct:
                action = "SELL_YES" if pos.side.upper() == "BUY_YES" else "SELL_NO"
                exit_signals.append({
                    "position": pos,
                    "action": action,
                    "reason": "take_profit",
                    "pnl_pct": pnl_pct,
                })
            
            # 損切りチェック
            elif pnl_pct <= stop_loss_pct:
                action = "SELL_YES" if pos.side.upper() == "BUY_YES" else "SELL_NO"
                exit_signals.append({
                    "position": pos,
                    "action": action,
                    "reason": "stop_loss",
                    "pnl_pct": pnl_pct,
                })
        
        return exit_signals
    
    def close_position(
        self,
        position_id: str,
        exit_price: float,
        realized_pnl: float,
    ) -> Optional[Position]:
        """ポジションをクローズ (早期売却)"""
        pos = self.positions.get(position_id)
        if not pos or pos.status != PositionStatus.OPEN:
            return None
        
        pos.status = PositionStatus.CLOSED
        pos.exit_price = exit_price
        pos.resolved_at = datetime.now()
        pos.pnl = realized_pnl
        
        self._save()
        
        print(f"📤 ポジションクローズ: {pos.question[:30]}... PnL: ${realized_pnl:+.2f}")
        
        return pos
    
    def get_open_market_ids(self) -> List[str]:
        """オープンポジションのマーケットID"""
        return list(set(p.market_id for p in self.get_open_positions()))
    
    def get_total_pnl(self) -> float:
        """総PnL (解決済み + 早期クローズ)"""
        return sum(
            p.pnl for p in self.positions.values()
            if p.status in (PositionStatus.RESOLVED, PositionStatus.CLOSED)
        )
    
    def get_total_exposure(self) -> float:
        """総エクスポージャー (オープンポジション)"""
        return sum(p.size for p in self.get_open_positions())
    
    def get_stats(self) -> Dict:
        """統計"""
        closed = [
            p for p in self.positions.values()
            if p.status in (PositionStatus.RESOLVED, PositionStatus.CLOSED)
        ]

        wins = sum(1 for p in closed if p.pnl > 0)
        losses = sum(1 for p in closed if p.pnl < 0)

        return {
            "total_positions": len(self.positions),
            "open": len(self.get_open_positions()),
            "resolved": len(closed),
            "wins": wins,
            "losses": losses,
            "win_rate": wins / len(closed) if closed else 0,
            "total_pnl": self.get_total_pnl(),
            "total_exposure": self.get_total_exposure(),
        }
    
    def _save(self):
        """保存"""
        os.makedirs(self.DATA_FILE.parent, exist_ok=True)
        
        data = {pid: pos.to_dict() for pid, pos in self.positions.items()}
        
        with open(self.DATA_FILE, "w") as f:
            json.dump(data, f, indent=2)
    
    def _load(self):
        """読み込み"""
        if not self.DATA_FILE.exists():
            return
        
        try:
            with open(self.DATA_FILE) as f:
                data = json.load(f)
            
            for pid, pdata in data.items():
                self.positions[pid] = Position.from_dict(pdata)
            
            print(f"📂 {len(self.positions)} ポジション読み込み")
        except Exception as e:
            print(f"⚠️ ポジション読み込みエラー: {e}")


# CLI
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Position Tracker")
    parser.add_argument("--list", action="store_true", help="オープンポジション一覧")
    parser.add_argument("--stats", action="store_true", help="統計")
    parser.add_argument("--history", action="store_true", help="全履歴")
    
    args = parser.parse_args()
    
    tracker = PositionTracker()
    
    if args.list:
        print("📋 オープンポジション:\n")
        for pos in tracker.get_open_positions():
            print(f"  {pos.id}: {pos.question[:40]}...")
            print(f"      {pos.side} ${pos.size:.2f} @ {pos.entry_price:.4f}")
            print()
    
    elif args.stats:
        stats = tracker.get_stats()
        print("📊 統計:\n")
        for k, v in stats.items():
            if isinstance(v, float):
                print(f"  {k}: {v:.2f}")
            else:
                print(f"  {k}: {v}")
    
    elif args.history:
        print("📜 全ポジション:\n")
        for pos in tracker.positions.values():
            status_icon = "🟢" if pos.status == PositionStatus.OPEN else "⚪"
            pnl_str = f"PnL: ${pos.pnl:+.2f}" if pos.pnl else ""
            print(f"  {status_icon} {pos.question[:40]}...")
            print(f"      {pos.side} ${pos.size:.2f} @ {pos.entry_price:.4f} {pnl_str}")
            print()
    
    else:
        print("Position Tracker")
        print("  --list    オープンポジション")
        print("  --stats   統計")
        print("  --history 全履歴")
