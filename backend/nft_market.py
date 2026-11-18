"""Read-only NFT market normalization and conservative profitability screening.

No wallet connection, signing, orders, purchases or deposits are performed.
All monetary inputs must use the same quote currency and normalized units.
"""
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Optional


def decimal_value(value: Any, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{field} must be a valid decimal")
    if not result.is_finite():
        raise ValueError(f"{field} must be finite")
    return result


@dataclass(frozen=True)
class Listing:
    marketplace: str
    chain: str
    collection: str
    token_id: str
    currency: str
    price: Decimal
    url: Optional[str] = None

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> "Listing":
        required = ("marketplace", "chain", "collection", "token_id", "currency", "price")
        missing = [key for key in required if payload.get(key) in (None, "")]
        if missing:
            raise ValueError("Missing listing fields: " + ", ".join(missing))
        values = {key: str(payload[key]).strip() for key in required}
        if any(not values[key] for key in required):
            raise ValueError("Listing fields cannot be blank")
        price = decimal_value(payload["price"], "price")
        if price <= 0:
            raise ValueError("price must be greater than zero")
        return cls(
            marketplace=values["marketplace"].lower(),
            chain=values["chain"].lower(),
            collection=values["collection"].lower(),
            token_id=values["token_id"],
            currency=values["currency"].upper(),
            price=price,
            url=str(payload["url"]) if payload.get("url") else None,
        )


@dataclass(frozen=True)
class ArbitrageScreen:
    eligible_for_review: bool
    gross_spread: Decimal
    estimated_costs: Decimal
    estimated_net: Decimal
    net_margin_pct: Optional[Decimal]
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        for key in ("gross_spread", "estimated_costs", "estimated_net", "net_margin_pct"):
            if result[key] is not None:
                result[key] = str(result[key])
        result["reasons"] = list(self.reasons)
        return result


def screen_cross_market_opportunity(
    buy_price: Any,
    sell_price: Any,
    *,
    buy_currency: Optional[str] = None,
    sell_currency: Optional[str] = None,
    marketplace_buy_fee_pct: Any = 0,
    marketplace_sell_fee_pct: Any = 0,
    royalty_pct: Any = 0,
    gas_cost: Any = 0,
    bridge_cost: Any = 0,
    slippage_pct: Any = 0,
    safety_buffer_pct: Any = 2,
    min_net_margin_pct: Any = 5,
    buy_marketplace: Optional[str] = None,
    sell_marketplace: Optional[str] = None,
    same_asset_verified: bool = False,
    liquidity_verified: bool = False,
) -> ArbitrageScreen:
    """Estimate net spread; candidate eligibility requires evidence and currency match."""
    buy = decimal_value(buy_price, "buy_price")
    sell = decimal_value(sell_price, "sell_price")
    if buy <= 0 or sell <= 0:
        raise ValueError("buy_price and sell_price must be greater than zero")

    buy_fee = decimal_value(marketplace_buy_fee_pct, "marketplace_buy_fee_pct")
    sell_fee = decimal_value(marketplace_sell_fee_pct, "marketplace_sell_fee_pct")
    royalty = decimal_value(royalty_pct, "royalty_pct")
    slippage = decimal_value(slippage_pct, "slippage_pct")
    buffer = decimal_value(safety_buffer_pct, "safety_buffer_pct")
    minimum = decimal_value(min_net_margin_pct, "min_net_margin_pct")
    gas = decimal_value(gas_cost, "gas_cost")
    bridge = decimal_value(bridge_cost, "bridge_cost")

    for name, value in (
        ("marketplace_buy_fee_pct", buy_fee),
        ("marketplace_sell_fee_pct", sell_fee),
        ("royalty_pct", royalty),
        ("slippage_pct", slippage),
        ("safety_buffer_pct", buffer),
        ("min_net_margin_pct", minimum),
    ):
        if value < 0 or value >= 100:
            raise ValueError(f"{name} must be in [0, 100)")
    if gas < 0 or bridge < 0:
        raise ValueError("gas_cost and bridge_cost cannot be negative")

    reasons = []
    if not buy_currency or not sell_currency:
        reasons.append("Quote currency is missing")
    elif buy_currency.strip().upper() != sell_currency.strip().upper():
        reasons.append("Buy and sell quote currencies do not match")
    if buy_marketplace and sell_marketplace and buy_marketplace.strip().lower() == sell_marketplace.strip().lower():
        reasons.append("Listings are from the same marketplace")
    if not buy_marketplace or not sell_marketplace:
        reasons.append("Marketplace identity is incomplete")
    if not same_asset_verified:
        reasons.append("Exact asset identity is not verified")
    if not liquidity_verified:
        reasons.append("Executable exit liquidity is not verified")

    gross = sell - buy
    buy_cost = buy * buy_fee / Decimal("100")
    sell_cost = sell * (sell_fee + royalty + slippage + buffer) / Decimal("100")
    costs = buy_cost + sell_cost + gas + bridge
    net = gross - costs
    margin = net / buy * Decimal("100")
    if gross <= 0:
        reasons.append("No positive gross spread")
    if margin < minimum:
        reasons.append(f"Net margin is below the {minimum}% review threshold")

    return ArbitrageScreen(not reasons, gross, costs, net, margin, tuple(reasons))
