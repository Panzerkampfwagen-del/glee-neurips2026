"""Typed state compilation from raw GLEE game dicts.

All numeric reasoning downstream uses these structures; the LLM never
touches arithmetic.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BargainingState:
    money: float
    round: int
    max_rounds: int | None
    horizon_known: bool
    delta_me: float
    my_player: str
    current_player: str
    proposer: str | None
    last_offer: dict | None
    complete_information: bool
    messages_allowed: bool
    history: list = field(default_factory=list)

    @property
    def i_propose(self) -> bool:
        return self.current_player == self.my_player and self.proposer == self.my_player

    @property
    def rounds_left(self) -> int | None:
        if not self.horizon_known or self.max_rounds is None:
            return None
        return max(0, self.max_rounds - self.round + 1)


def compile_bargaining(game: dict) -> BargainingState:
    s = game["game_state"]
    me = game["your_player"]
    opp = "player_2" if me == "player_1" else "player_1"
    return BargainingState(
        money=float(s["money_to_divide"]),
        round=int(s.get("round", 1)),
        max_rounds=s.get("max_rounds"),
        horizon_known=bool(s.get("horizon_known", True)),
        delta_me=float(s[f"delta_{me.split('_')[1]}"]),
        my_player=me,
        current_player=s.get("current_player", ""),
        proposer=s.get("proposer"),
        last_offer=s.get("last_offer"),
        complete_information=bool(s.get("complete_information", True)),
        messages_allowed=bool(s.get("messages_allowed", False)),
        history=list(s.get("history") or []),
    )


@dataclass
class NegotiationState:
    role: str
    my_value: float
    round: int
    max_rounds: int | None
    horizon_known: bool
    my_player: str
    current_player: str
    last_offer: dict | None
    complete_information: bool
    messages_allowed: bool
    history: list = field(default_factory=list)

    @property
    def is_seller(self) -> bool:
        return self.role == "seller"

    @property
    def is_final_round(self) -> bool:
        return (
            self.horizon_known
            and self.max_rounds is not None
            and self.round >= self.max_rounds
        )

    @property
    def rounds_left(self) -> int | None:
        if not self.horizon_known or self.max_rounds is None:
            return None
        return max(0, self.max_rounds - self.round + 1)


def compile_negotiation(game: dict) -> NegotiationState:
    s = game["game_state"]
    me = game["your_player"] if "your_player" in game else s["current_player"]
    role = s.get(f"{me}_role")
    if role is None:
        p1_role = s.get("player_1_role", "seller")
        role = p1_role if me == "player_1" else ("buyer" if p1_role == "seller" else "seller")
    value_key = f"{me}_value"
    my_value = float(s[value_key]) if value_key in s else None
    if my_value is None:
        my_value = float(s["player_1_value"] if role == "seller" and me == "player_1"
                         else s["player_2_value"] if role == "buyer" and me == "player_2"
                         else s.get("player_1_value", 0.0))
    return NegotiationState(
        role=role,
        my_value=my_value,
        round=int(s.get("round", 1)),
        max_rounds=s.get("max_rounds"),
        horizon_known=bool(s.get("horizon_known", True)),
        my_player=me,
        current_player=s.get("current_player", ""),
        last_offer=s.get("last_offer"),
        complete_information=bool(s.get("complete_information", True)),
        messages_allowed=bool(s.get("messages_allowed", False)),
        history=list(s.get("history") or []),
    )


@dataclass
class PersuasionState:
    am_seller: bool
    price: float
    p: float
    v: float | None
    u: float
    mode: str
    current_quality: str | None
    seller_message: str | dict | None
    round: int
    total_rounds: int
    seller_total_payoff: float
    buyer_total_payoff: float
    my_player: str
    history: list = field(default_factory=list)

    @property
    def rounds_left(self) -> int:
        return max(0, self.total_rounds - self.round + 1)


def compile_persuasion(game: dict) -> PersuasionState:
    s = game["game_state"]
    me = game["your_player"] if "your_player" in game else s.get("current_player", "")
    am_seller = me == "player_1"
    msg = s.get("seller_message")
    mode = s.get("seller_message_type") or s.get("message_type")
    if mode not in ("text", "binary"):
        mode = "text" if isinstance(msg, str) and msg else "binary"
    return PersuasionState(
        am_seller=am_seller,
        price=float(s["product_price"]),
        p=float(s["p"]),
        v=float(s["v"]) if s.get("v") is not None else None,
        u=float(s.get("u", 0.0)),
        mode=mode,
        current_quality=s.get("current_quality"),
        seller_message=msg,
        round=int(s.get("round", 1)),
        total_rounds=int(s.get("total_rounds", s.get("max_rounds", 10))),
        seller_total_payoff=float(s.get("seller_total_payoff", 0.0)),
        buyer_total_payoff=float(s.get("buyer_total_payoff", 0.0)),
        my_player=me,
        history=list(s.get("history") or []),
    )
