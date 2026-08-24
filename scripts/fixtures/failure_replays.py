"""F1–F6 failure-replay fixtures: one synthetic game dict per documented
live failure (docs/04 §1). Each fixture reproduces the state that triggered
the divergence; wire into tests/test_live_regressions.py with these asserts:

F1: decision with prose-style fields must NOT fall back to unconditional
    Accept — output must respect solver role-awareness.
F2: buyer history containing a confirmed lie must still buy when posterior
    EV is strongly positive on later truthful-claim rounds.
F3: opponent's inflated ask must NOT raise their inferred reservation floor
    (interval lo/hi directionality).
F4/F5: ops-era failures; covered by deploy markers + supervisor, no game-state
    assert (placeholders kept for JSONL replacement).
F6: constant-claim seller history → buyer uses base-rate EV (buys +EV config
    despite prior burns).
"""

BARGAINING_F1 = {
    "game_id": "fixture-F1",
    "game_family": "bargaining",
    "your_player": "player_2",
    "phase": "decision",
    "valid_actions": {
        "type": "decision",
        "fields": {"decision": "'AcceptOffer', 'RejectOffer', or 'WalkAway'"},
    },
    "opponent": {"type": "hidden", "name": None},
    "prompt": "fixture",
    "game_state": {
        "money_to_divide": 1000.0,
        "round": 1,
        "horizon_known": True,
        "max_rounds": 6,
        "current_player": "player_2",
        "proposer": "player_1",
        "delta_1": 0.95,
        "delta_2": 0.9,
        "messages_allowed": True,
        "complete_information": False,
        "history": [],
        "last_offer": {
            "player_1_gain": 850, "player_2_gain": 150,
            "message": "", "proposer": "player_1", "round": 1,
        },
    },
}

PERSUASION_F2 = {
    "game_id": "fixture-F2",
    "game_family": "persuasion",
    "your_player": "player_2",
    "phase": "buyer_decision",
    "valid_actions": {
        "type": "buyer_decision",
        "fields": {"decision": "'yes', or 'no'"},
    },
    "opponent": {"type": "hidden", "name": None},
    "prompt": "fixture",
    "game_state": {
        "product_price": 10.0, "p": 0.6, "v": 30.0, "u": 0.0,
        "total_rounds": 10, "round": 4,
        "seller_message_type": "binary",
        "seller_message": "yes",
        "seller_total_payoff": 20.0, "buyer_total_payoff": -10.0,
        "history": [
            {"round": 1, "seller_message": "yes", "buyer_decision": "yes",
             "bought": True, "quality": "low", "seller_payoff": 10,
             "buyer_payoff": -10},
            {"round": 2, "seller_message": "yes", "buyer_decision": "no",
             "bought": False},
            {"round": 3, "seller_message": "no", "buyer_decision": "no",
             "bought": False},
        ],
    },
}

NEGOTIATION_F3 = {
    "game_id": "fixture-F3",
    "game_family": "negotiation",
    "your_player": "player_2",
    "phase": "offer",
    "valid_actions": {
        "type": "offer",
        "fields": {"product_price": "number"},
    },
    "opponent": {"type": "hidden", "name": None},
    "prompt": "fixture",
    "game_state": {
        "round": 3, "horizon_known": True, "max_rounds": 8,
        "player_1_role": "seller", "player_2_role": "buyer",
        "player_1_value": 12000, "player_2_value": 15000,
        "current_player": "player_2",
        "messages_allowed": True, "complete_information": False,
        "history": [
            {"round": 1, "offer": {"price": 25000, "from_player": "player_1"},
             "decision": "RejectOffer", "counteroffer": {"price": 12500}},
            {"round": 2, "offer": {"price": 22000, "from_player": "player_1"},
             "decision": "RejectOffer", "counteroffer": {"price": 13000}},
        ],
        "last_offer": {"price": 22000, "message": "", "from_player": "player_1", "round": 2},
    },
}

PERSUASION_F6 = {
    "game_id": "fixture-F6",
    "game_family": "persuasion",
    "your_player": "player_2",
    "phase": "buyer_decision",
    "valid_actions": {
        "type": "buyer_decision",
        "fields": {"decision": "'yes', or 'no'"},
    },
    "opponent": {"type": "hidden", "name": None},
    "prompt": "fixture",
    "game_state": {
        "product_price": 10.0, "p": 0.5, "v": 30.0, "u": 0.0,
        "total_rounds": 10, "round": 5,
        "seller_message_type": "binary",
        "seller_message": "yes",
        "seller_total_payoff": 0.0, "buyer_total_payoff": -10.0,
        "history": [
            {"round": i, "seller_message": "yes", "buyer_decision": "no",
             "bought": False}
            for i in range(1, 5)
        ] + [
            {"round": 1, "seller_message": "yes", "buyer_decision": "no", "bought": False},
        ],
    },
}

F4_PLACEHOLDER = {"note": "ops-era; replace with recorded game_id from games.jsonl"}
F5_PLACEHOLDER = {"note": "ops-era; replace with recorded game_id from games.jsonl"}
