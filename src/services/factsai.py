"""
FactsAI service for AI-powered market research.

Provides AI research capabilities for prediction markets using the FactsAI API.
Access is gated by $SPRDD token balance or trading volume requirements.
"""

import json

import httpx
from decimal import Decimal
from typing import Optional
from web3 import Web3
from web3.exceptions import ContractLogicError

from src.config import settings
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Standard ERC20 ABI for balanceOf
ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function",
    },
]


class FactsAIService:
    """Service for FactsAI API integration."""

    def __init__(self):
        self.api_key = settings.factsai_api_key
        self.api_url = settings.factsai_api_url
        self.sprdd_address = settings.sprdd_token_address
        self.min_sprdd_balance = settings.sprdd_min_balance
        self.min_volume = settings.ai_research_min_volume
        self._web3: Optional[Web3] = None
        self._http_client: Optional[httpx.AsyncClient] = None

    @property
    def web3(self) -> Web3:
        """Lazy load Web3 instance for Base chain."""
        if self._web3 is None:
            self._web3 = Web3(Web3.HTTPProvider(settings.base_rpc_url))
        return self._web3

    @property
    def is_configured(self) -> bool:
        """Check if FactsAI is properly configured."""
        return bool(self.api_key)

    def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=60.0,
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5, keepalive_expiry=30),
            )
        return self._http_client

    async def close(self) -> None:
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    async def get_sprdd_balance(self, wallet_address: str) -> Decimal:
        """
        Get $SPRDD token balance for a wallet on Base chain.

        Args:
            wallet_address: The wallet address to check

        Returns:
            Token balance as Decimal
        """
        try:
            if not wallet_address:
                return Decimal("0")

            # Validate address
            if not self.web3.is_address(wallet_address):
                logger.warning("Invalid wallet address for SPRDD check", address=wallet_address)
                return Decimal("0")

            checksum_address = self.web3.to_checksum_address(wallet_address)
            token_address = self.web3.to_checksum_address(self.sprdd_address)

            # Create contract instance
            contract = self.web3.eth.contract(address=token_address, abi=ERC20_ABI)

            # Get decimals (cache this in production)
            try:
                decimals = contract.functions.decimals().call()
            except Exception:
                decimals = 18  # Default to 18 if call fails

            # Get balance
            balance_raw = contract.functions.balanceOf(checksum_address).call()
            balance = Decimal(balance_raw) / Decimal(10 ** decimals)

            logger.info(
                "Checked SPRDD balance",
                wallet=wallet_address[:10] + "...",
                balance=str(balance),
            )

            return balance

        except ContractLogicError as e:
            logger.error("Contract error checking SPRDD balance", error=str(e))
            return Decimal("0")
        except Exception as e:
            logger.error("Failed to check SPRDD balance", error=str(e))
            return Decimal("0")

    async def check_access(
        self,
        wallet_address: Optional[str],
        trading_volume: Decimal,
    ) -> tuple[bool, str]:
        """
        Check if user has access to AI research features.

        Access granted if:
        - User holds >= min_sprdd_balance $SPRDD tokens, OR
        - User has >= min_volume in trading volume

        Args:
            wallet_address: User's EVM wallet address (for token check)
            trading_volume: User's total trading volume in USD

        Returns:
            Tuple of (has_access, reason_message)
        """
        # Check trading volume first (doesn't require RPC call)
        if trading_volume >= Decimal(self.min_volume):
            return True, f"Access granted (${trading_volume:,.0f} trading volume)"

        # Check token balance
        if wallet_address:
            sprdd_balance = await self.get_sprdd_balance(wallet_address)
            if sprdd_balance >= Decimal(self.min_sprdd_balance):
                return True, f"Access granted ({sprdd_balance:,.0f} $SPRDD)"

        # No access
        return False, (
            f"AI Research requires either:\n"
            f"- {self.min_sprdd_balance:,} $SPRDD tokens, or\n"
            f"- ${self.min_volume:,}+ trading volume\n\n"
            f"Your stats:\n"
            f"- $SPRDD: {await self.get_sprdd_balance(wallet_address) if wallet_address else 0:,.0f}\n"
            f"- Volume: ${trading_volume:,.2f}"
        )

    async def research_market(self, market_title: str, market_description: str = "") -> dict:
        """
        Get AI research analysis for a prediction market.

        Args:
            market_title: The market title/question
            market_description: Optional additional context

        Returns:
            Dict with 'answer' and 'citations' from FactsAI
        """
        if not self.is_configured:
            return {
                "error": "AI Research is not configured",
                "answer": None,
                "citations": [],
            }

        # Build the research query
        query = f"Research and analyze this prediction market: {market_title}"
        if market_description:
            query += f"\n\nAdditional context: {market_description}"
        query += "\n\nProvide key facts, recent news, and analysis that would help predict the outcome."

        # Truncate to API limit
        if len(query) > 1000:
            query = query[:997] + "..."

        try:
            client = self._get_client()
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }

            payload = {
                "query": query,
                "text": True,  # Include full text in citations
            }

            print(f"[FactsAI] Request to {self.api_url}/answer, query_length={len(query)}")

            response = await client.post(
                f"{self.api_url}/answer",
                headers=headers,
                json=payload,
            )
            response_text = response.text
            print(f"[FactsAI] Response status={response.status_code}, body_preview={response_text[:500] if response_text else 'empty'}")

            if response.status_code == 401:
                return {
                    "error": "Invalid API key",
                    "answer": None,
                    "citations": [],
                }
            elif response.status_code == 402:
                return {
                    "error": "API credits exhausted",
                    "answer": None,
                    "citations": [],
                }
            elif response.status_code == 429:
                logger.warning("FactsAI rate limited by Cloudflare")
                return {
                    "error": "AI Research is temporarily unavailable due to high demand. Please try again in a few minutes.",
                    "answer": None,
                    "citations": [],
                }
            elif response.status_code == 503:
                return {
                    "error": "AI Research service is temporarily unavailable. Please try again later.",
                    "answer": None,
                    "citations": [],
                }
            elif response.status_code == 500:
                print(f"[FactsAI] ERROR 500: {response_text[:1000] if response_text else 'empty'}")
                # Parse error message if available
                try:
                    err_data = json.loads(response_text)
                    err_msg = err_data.get("error", "Server error")
                except Exception:
                    err_msg = "Server error"
                return {
                    "error": f"FactsAI: {err_msg}. Please try again later.",
                    "answer": None,
                    "citations": [],
                }
            elif response.status_code != 200:
                print(f"[FactsAI] ERROR {response.status_code}: {response_text[:500] if response_text else 'empty'}")
                return {
                    "error": f"API error: {response.status_code}",
                    "answer": None,
                    "citations": [],
                }

            data = json.loads(response_text)

            # Response structure: {"success": true, "data": {"answer": ..., "citations": ...}}
            if data.get("success"):
                inner_data = data.get("data", {})
                answer = inner_data.get("answer", "")
                print(f"[FactsAI] SUCCESS: answer_length={len(answer)}, citations={len(inner_data.get('citations', []))}")
                return {
                    "answer": answer,
                    "citations": inner_data.get("citations", []),
                    "cost": inner_data.get("costDollars", "$0.012"),
                    "error": None,
                }
            else:
                # API returned success: false
                error_msg = data.get("error", data.get("message", "Unknown API error"))
                print(f"[FactsAI] API returned error: {error_msg}")
                return {
                    "error": str(error_msg)[:100],
                    "answer": None,
                    "citations": [],
                }

        except httpx.TimeoutException:
            return {
                "error": "Request timed out",
                "answer": None,
                "citations": [],
            }
        except Exception as e:
            logger.error("FactsAI API error", error=str(e))
            return {
                "error": f"Research failed: {str(e)[:100]}",
                "answer": None,
                "citations": [],
            }


# Singleton instance
factsai_service = FactsAIService()
