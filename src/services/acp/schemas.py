"""
ACP Job Offering Schemas.

Defines the service requirements and deliverable schemas for each
job type that Spredd offers through the ACP marketplace.
"""

from enum import Enum
from typing import Any


class JobType(str, Enum):
    """Available job types offered by Spredd."""
    EXECUTE_TRADE = "execute_trade"
    GET_QUOTE = "get_quote"
    SEARCH_MARKETS = "search_markets"
    GET_PORTFOLIO = "get_portfolio"
    BRIDGE_USDC = "bridge_usdc"


# ===================
# Job Offering: Execute Trade
# ===================
EXECUTE_TRADE_SCHEMA = {
    "name": "execute_trade",
    "description": "Execute a prediction market trade on any supported platform (Kalshi, Polymarket, Opinion Labs, Limitless, Myriad)",
    "price_usdc": 0.01,  # Minimum, actual is 0.5% of trade
    "price_type": "percentage",  # 0.5% of trade amount
    "price_percentage": 0.5,
    "job_type": "fund_transfer",
    "service_requirements": {
        "type": "object",
        "properties": {
            "platform": {
                "type": "string",
                "enum": ["kalshi", "polymarket", "opinion", "limitless", "myriad"],
                "description": "Target prediction market platform"
            },
            "market_id": {
                "type": "string",
                "description": "Platform-specific market identifier"
            },
            "outcome": {
                "type": "string",
                "enum": ["yes", "no"],
                "description": "Outcome to trade (yes or no)"
            },
            "side": {
                "type": "string",
                "enum": ["buy", "sell"],
                "description": "Trade direction"
            },
            "amount": {
                "type": "number",
                "minimum": 0.01,
                "description": "USDC amount to trade"
            },
            "max_slippage_bps": {
                "type": "number",
                "default": 100,
                "description": "Maximum slippage in basis points (100 = 1%)"
            }
        },
        "required": ["platform", "market_id", "outcome", "side", "amount"]
    },
    "deliverable_requirements": {
        "type": "object",
        "properties": {
            "success": {
                "type": "boolean",
                "description": "Whether the trade was successful"
            },
            "tx_hash": {
                "type": "string",
                "description": "Transaction hash on the blockchain"
            },
            "input_amount": {
                "type": "number",
                "description": "Actual USDC spent"
            },
            "output_amount": {
                "type": "number",
                "description": "Tokens received"
            },
            "price": {
                "type": "number",
                "description": "Execution price"
            },
            "explorer_url": {
                "type": "string",
                "description": "Block explorer URL for the transaction"
            },
            "error": {
                "type": "string",
                "description": "Error message if trade failed"
            }
        },
        "required": ["success"]
    }
}


# ===================
# Job Offering: Get Quote
# ===================
GET_QUOTE_SCHEMA = {
    "name": "get_quote",
    "description": "Get a price quote for a prediction market trade without executing",
    "price_usdc": 0.001,
    "price_type": "fixed",
    "job_type": "service",
    "service_requirements": {
        "type": "object",
        "properties": {
            "platform": {
                "type": "string",
                "enum": ["kalshi", "polymarket", "opinion", "limitless", "myriad"],
                "description": "Target prediction market platform"
            },
            "market_id": {
                "type": "string",
                "description": "Platform-specific market identifier"
            },
            "outcome": {
                "type": "string",
                "enum": ["yes", "no"],
                "description": "Outcome to quote"
            },
            "side": {
                "type": "string",
                "enum": ["buy", "sell"],
                "description": "Trade direction"
            },
            "amount": {
                "type": "number",
                "minimum": 0.01,
                "description": "USDC amount to quote"
            }
        },
        "required": ["platform", "market_id", "outcome", "side", "amount"]
    },
    "deliverable_requirements": {
        "type": "object",
        "properties": {
            "input_amount": {
                "type": "number",
                "description": "USDC amount for the trade"
            },
            "expected_output": {
                "type": "number",
                "description": "Expected tokens to receive"
            },
            "price": {
                "type": "number",
                "description": "Expected execution price"
            },
            "price_impact_bps": {
                "type": "number",
                "description": "Price impact in basis points"
            },
            "fee_amount": {
                "type": "number",
                "description": "Platform fee in USDC"
            },
            "expires_at": {
                "type": "string",
                "description": "ISO timestamp when quote expires"
            }
        },
        "required": ["input_amount", "expected_output", "price"]
    }
}


# ===================
# Job Offering: Search Markets
# ===================
SEARCH_MARKETS_SCHEMA = {
    "name": "search_markets",
    "description": "Search prediction markets across all supported platforms",
    "price_usdc": 0.001,
    "price_type": "fixed",
    "job_type": "service",
    "service_requirements": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query (e.g., 'Bitcoin price', 'Trump election')"
            },
            "platforms": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional list of platforms to search (default: all)"
            },
            "limit": {
                "type": "number",
                "default": 10,
                "maximum": 50,
                "description": "Maximum number of results"
            }
        },
        "required": ["query"]
    },
    "deliverable_requirements": {
        "type": "object",
        "properties": {
            "markets": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "platform": {"type": "string"},
                        "market_id": {"type": "string"},
                        "title": {"type": "string"},
                        "yes_price": {"type": "number"},
                        "no_price": {"type": "number"},
                        "volume_24h": {"type": "number"},
                        "end_date": {"type": "string"}
                    }
                },
                "description": "List of matching markets"
            }
        },
        "required": ["markets"]
    }
}


# ===================
# Job Offering: Get Portfolio
# ===================
GET_PORTFOLIO_SCHEMA = {
    "name": "get_portfolio",
    "description": "Get current prediction market positions and P&L for the agent",
    "price_usdc": 0.001,
    "price_type": "fixed",
    "job_type": "service",
    "service_requirements": {
        "type": "object",
        "properties": {
            "platforms": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional list of platforms to query (default: all)"
            }
        },
        "required": []
    },
    "deliverable_requirements": {
        "type": "object",
        "properties": {
            "positions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "platform": {"type": "string"},
                        "market_id": {"type": "string"},
                        "market_title": {"type": "string"},
                        "outcome": {"type": "string"},
                        "amount": {"type": "number"},
                        "entry_price": {"type": "number"},
                        "current_price": {"type": "number"},
                        "pnl": {"type": "number"}
                    }
                },
                "description": "List of open positions"
            },
            "total_value": {
                "type": "number",
                "description": "Total portfolio value in USDC"
            },
            "total_pnl": {
                "type": "number",
                "description": "Total profit/loss in USDC"
            }
        },
        "required": ["positions", "total_value", "total_pnl"]
    }
}


# ===================
# Job Offering: Bridge USDC
# ===================
BRIDGE_USDC_SCHEMA = {
    "name": "bridge_usdc",
    "description": "Bridge USDC between chains (Base, Polygon, Arbitrum, Optimism, Ethereum)",
    "price_usdc": 0.50,
    "price_type": "fixed",
    "job_type": "fund_transfer",
    "service_requirements": {
        "type": "object",
        "properties": {
            "source_chain": {
                "type": "string",
                "enum": ["base", "polygon", "arbitrum", "optimism", "ethereum"],
                "description": "Source blockchain"
            },
            "dest_chain": {
                "type": "string",
                "enum": ["base", "polygon", "arbitrum", "optimism", "ethereum"],
                "description": "Destination blockchain"
            },
            "amount": {
                "type": "number",
                "minimum": 1.0,
                "description": "USDC amount to bridge"
            }
        },
        "required": ["source_chain", "dest_chain", "amount"]
    },
    "deliverable_requirements": {
        "type": "object",
        "properties": {
            "success": {
                "type": "boolean",
                "description": "Whether the bridge was successful"
            },
            "source_tx_hash": {
                "type": "string",
                "description": "Transaction hash on source chain"
            },
            "dest_tx_hash": {
                "type": "string",
                "description": "Transaction hash on destination chain"
            },
            "amount_sent": {
                "type": "number",
                "description": "USDC sent from source"
            },
            "amount_received": {
                "type": "number",
                "description": "USDC received on destination"
            },
            "explorer_url": {
                "type": "string",
                "description": "Block explorer URL"
            }
        },
        "required": ["success"]
    }
}


# All job offerings
JOB_OFFERINGS: dict[JobType, dict[str, Any]] = {
    JobType.EXECUTE_TRADE: EXECUTE_TRADE_SCHEMA,
    JobType.GET_QUOTE: GET_QUOTE_SCHEMA,
    JobType.SEARCH_MARKETS: SEARCH_MARKETS_SCHEMA,
    JobType.GET_PORTFOLIO: GET_PORTFOLIO_SCHEMA,
    JobType.BRIDGE_USDC: BRIDGE_USDC_SCHEMA,
}


def get_job_schema(job_type: JobType) -> dict[str, Any]:
    """Get the schema for a job type."""
    return JOB_OFFERINGS.get(job_type, {})


def validate_service_requirements(job_type: JobType, requirements: dict) -> tuple[bool, str]:
    """
    Validate service requirements against the schema.
    Returns (is_valid, error_message).
    """
    schema = get_job_schema(job_type)
    if not schema:
        return False, f"Unknown job type: {job_type}"

    req_schema = schema.get("service_requirements", {})
    required_fields = req_schema.get("required", [])
    properties = req_schema.get("properties", {})

    # Check required fields
    for field in required_fields:
        if field not in requirements:
            return False, f"Missing required field: {field}"

    # Validate field types and values
    for field, value in requirements.items():
        if field not in properties:
            continue  # Allow extra fields

        prop = properties[field]
        prop_type = prop.get("type")

        # Type validation
        if prop_type == "string" and not isinstance(value, str):
            return False, f"Field '{field}' must be a string"
        elif prop_type == "number" and not isinstance(value, (int, float)):
            return False, f"Field '{field}' must be a number"
        elif prop_type == "boolean" and not isinstance(value, bool):
            return False, f"Field '{field}' must be a boolean"
        elif prop_type == "array" and not isinstance(value, list):
            return False, f"Field '{field}' must be an array"

        # Enum validation
        if "enum" in prop and value not in prop["enum"]:
            return False, f"Field '{field}' must be one of: {prop['enum']}"

        # Min/max validation
        if prop_type == "number":
            if "minimum" in prop and value < prop["minimum"]:
                return False, f"Field '{field}' must be >= {prop['minimum']}"
            if "maximum" in prop and value > prop["maximum"]:
                return False, f"Field '{field}' must be <= {prop['maximum']}"

    return True, ""
