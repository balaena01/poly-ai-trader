"""
Position Tracker
- オープンポジション管理
- PnL計算 (解決時)
- 永続化
"""
import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
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
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # YES token ID (スキャン外ポジションの現在価格取得に使用; 常にYES token)
    yes_token_id: Optional[str] = None

    # GTC注文追跡 (買い)
    order_id: Optional[str] = None        # CLOBのorder ID
    order_filled: bool = True             # False = GTC未約定

    # GTC売り注文追跡 (利確・損切り・LLM逆転クローズ)
    pending_sell_order_id: Optional[str] = None   # 売り注文発注済み・約定待ち
    pending_sell_price: Optional[float] = None    # 売り時の YES 価格

    # 手動売却フラグ (トークン未保有等でシステムクローズ不可)
    needs_manual_sale: bool = False

    # エントリー時の LLM エッジ (エッジ消失利確に使用)
    entry_edge: Optional[float] = None

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
            "yes_token_id": self.yes_token_id,
            "question": self.question,
            "side": self.side,
            "entry_price": self.entry_price,
            "size": self.size,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "order_id": self.order_id,
            "order_filled": self.order_filled,
            "pending_sell_order_id": self.pending_sell_order_id,
            "pending_sell_price": self.pending_sell_price,
            "needs_manual_sale": self.needs_manual_sale,
            "entry_edge": self.entry_edge,
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
            yes_token_id=data.get("yes_token_id"),
            question=data["question"],
            side=data["side"],
            entry_price=data["entry_price"],
            size=data["size"],
            status=PositionStatus(data["status"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            order_id=data.get("order_id"),
            order_filled=data.get("order_filled", True),
            pending_sell_order_id=data.get("pending_sell_order_id"),
            pending_sell_price=data.get("pending_sell_price"),
            needs_manual_sale=data.get("needs_manual_sale", False),
            entry_edge=data.get("entry_edge"),
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
        yes_token_id: Optional[str] = None,
        entry_edge: Optional[float] = None,
    ) -> Position:
        """トレード記録"""
        import uuid

        pos_id = str(uuid.uuid4())[:8]

        position = Position(
            id=pos_id,
            market_id=market_id,
            token_id=token_id,
            yes_token_id=yes_token_id,
            question=question,
            side=side,
            entry_price=entry_price,
            size=size,
            order_id=order_id,
            order_filled=order_filled,
            entry_edge=entry_edge,
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

    def mark_needs_manual_sale(self, pos_id: str):
        """手動売却が必要なポジションとしてマーク"""
        if pos_id in self.positions:
            self.positions[pos_id].needs_manual_sale = True
            self._save()

    def dismiss_manual_sale(self, pos_id: str):
        """手動売却アラートを解除"""
        if pos_id in self.positions:
            self.positions[pos_id].needs_manual_sale = False
            self._save()

    def mark_pending_sell(self, pos_id: str, order_id: str, sell_price: float):
        """GTC売り注文発注済みとしてマーク"""
        if pos_id in self.positions:
            self.positions[pos_id].pending_sell_order_id = order_id
            self.positions[pos_id].pending_sell_price = sell_price
            self._save()

    def cancel_pending_sell(self, pos_id: str):
        """GTC売り注文キャンセル → ACTIVEに戻す"""
        if pos_id in self.positions:
            self.positions[pos_id].pending_sell_order_id = None
            self.positions[pos_id].pending_sell_price = None
            self._save()

    def get_pending_sell_positions(self) -> List[Position]:
        """GTC売り注文待ちポジション"""
        return [p for p in self.positions.values()
                if p.status == PositionStatus.OPEN and p.pending_sell_order_id]

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

    def get_closed_positions(self, limit: int = 20) -> List[Position]:
        """クローズ済みポジションを新しい順で取得"""
        closed = [
            p for p in self.positions.values()
            if p.status in (PositionStatus.RESOLVED, PositionStatus.CLOSED)
        ]
        closed.sort(key=lambda p: p.resolved_at or p.created_at, reverse=True)
        return closed[:limit]
    
    def check_exit_conditions(
        self,
        current_prices: Dict[str, float],       # market_id -> yes_price
        take_profit_pct: float = 0.40,
        stop_loss_pct: float = -0.80,           # 価格ベース損切り (最終保険)
        collapse_threshold: float = 0.88,       # 確率崩壊ストップ
        stop_loss_near_expiry_days: int = 7,    # 近解決損切り: 残りN日以内
        stop_loss_near_expiry_pct: float = -0.40,  # 近解決損切り: 含み損閾値
        end_dates: Dict[str, any] = None,       # market_id -> end_date (近解決チェック用)
        last_signals: Dict[str, any] = None,    # market_id -> Signal (エッジ消失チェック用)
        edge_take_profit_threshold: float = 0.05,  # エッジがこれ以下で利確
    ) -> List[Dict]:
        """
        利確・損切り条件をチェック

        損切り優先度:
          1. 確率崩壊ストップ: market が圧倒的多数決を出した (thesis 崩壊)
          2. 近解決 × 含み損: 残り日数少なく回復見込みなし
          3. 価格ベース損切り: ほぼ全損時の最終保険
          ※ LLM逆転クローズは orchestrator 側で別途処理

        Returns:
            [{"position": Position, "action": str, "reason": str, "pnl_pct": float, "detail": str}]
        """
        from datetime import datetime, timezone
        exit_signals = []
        now = datetime.now(timezone.utc)
        end_dates = end_dates or {}
        last_signals = last_signals or {}

        for pos in self.get_open_positions():
            if pos.needs_manual_sale:
                continue
            if pos.pending_sell_order_id:
                continue
            yes_price = current_prices.get(pos.market_id)
            if yes_price is None:
                continue

            pnl_pct = pos.get_unrealized_pnl_pct(yes_price)
            action = "SELL_YES" if pos.side.upper() == "BUY_YES" else "SELL_NO"
            is_no = pos.side.upper() == "BUY_NO"

            # ── 1. 確率崩壊ストップ ───────────────────────────────────────────
            # BUY_NO: YES確率 >= collapse_threshold → YES がほぼ確定 → NO thesis 崩壊
            # BUY_YES: YES確率 <= (1 - collapse_threshold) → NO がほぼ確定
            if is_no and yes_price >= collapse_threshold:
                exit_signals.append({
                    "position": pos, "action": action, "reason": "collapse_stop",
                    "pnl_pct": pnl_pct,
                    "detail": f"YES確率{yes_price:.0%} ≥ 崩壊閾値{collapse_threshold:.0%}",
                })
                continue
            if not is_no and yes_price <= (1.0 - collapse_threshold):
                exit_signals.append({
                    "position": pos, "action": action, "reason": "collapse_stop",
                    "pnl_pct": pnl_pct,
                    "detail": f"YES確率{yes_price:.0%} ≤ {1-collapse_threshold:.0%} (NO崩壊)",
                })
                continue

            # ── 2. 近解決 × 含み損 ────────────────────────────────────────────
            end_date = end_dates.get(pos.market_id)
            if end_date is not None:
                if end_date.tzinfo is None:
                    end_date = end_date.replace(tzinfo=timezone.utc)
                days_left = (end_date - now).total_seconds() / 86400
                if days_left <= stop_loss_near_expiry_days and pnl_pct <= stop_loss_near_expiry_pct:
                    exit_signals.append({
                        "position": pos, "action": action, "reason": "near_expiry_stop",
                        "pnl_pct": pnl_pct,
                        "detail": f"残{days_left:.1f}日 ≤ {stop_loss_near_expiry_days}日 かつ pnl{pnl_pct:.0%} ≤ {stop_loss_near_expiry_pct:.0%}",
                    })
                    continue

            # ── 3. エッジ消失利確 (メイン) ───────────────────────────────────
            # entry_edge が記録されていて、最新シグナルのエッジが閾値以下になったら利確
            # ※ 14日制約は適用しない (thesis消滅 = 残り日数に関係なく撤退すべき)
            if pos.entry_edge is not None:
                sig = last_signals.get(pos.market_id)
                if sig is not None:
                    current_edge = abs(getattr(sig, 'edge', 1.0))
                    if current_edge < edge_take_profit_threshold:
                        exit_signals.append({
                            "position": pos, "action": action, "reason": "edge_take_profit",
                            "pnl_pct": pnl_pct,
                            "detail": f"エッジ消失 entry_edge={pos.entry_edge:+.1%} → current_edge={current_edge:+.1%}",
                        })
                        continue

            # ── 4. 利確 (価格ベース・セカンダリ) ─────────────────────────────
            if pnl_pct >= take_profit_pct:
                exit_signals.append({
                    "position": pos, "action": action, "reason": "take_profit",
                    "pnl_pct": pnl_pct, "detail": f"pnl{pnl_pct:+.0%}",
                })
                continue

            # ── 5. 損切り (価格ベース・最終保険) ─────────────────────────────
            if pnl_pct <= stop_loss_pct:
                exit_signals.append({
                    "position": pos, "action": action, "reason": "stop_loss",
                    "pnl_pct": pnl_pct, "detail": f"pnl{pnl_pct:+.0%} ≤ {stop_loss_pct:.0%}",
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
