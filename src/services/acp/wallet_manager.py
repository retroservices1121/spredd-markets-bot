"""
ACP Wallet Manager.

Manages per-agent wallet balances and positions for ACP fund-transfer jobs.
Each AI agent that uses Spredd's services has isolated balance tracking.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional, Union

from eth_account import Account
from eth_account.signers.local import LocalAccount

from src.utils.logging import get_logger
from src.config import settings

logger = get_logger(__name__)


class ACPWalletManager:
    """
    Manages per-agent wallet balances for ACP jobs.

    For security, each agent's funds are tracked separately.
    The actual USDC is held in Spredd's ACP wallet, with per-agent
    accounting in the database.
    """

    def __init__(self):
        self._initialized = False
        self._acp_wallet: Optional[LocalAccount] = None
        self._solana_keypair = None  # Solana Keypair for Kalshi

    def initialize(self):
        """Initialize the ACP wallets from config."""
        if self._initialized:
            return

        # Initialize EVM wallet
        if settings.acp_agent_wallet_private_key:
            try:
                pk = settings.acp_agent_wallet_private_key
                if not pk.startswith("0x"):
                    pk = "0x" + pk
                self._acp_wallet = Account.from_key(pk)
                logger.info("ACP EVM wallet initialized", address=self._acp_wallet.address)
            except Exception as e:
                logger.error("Failed to initialize ACP EVM wallet", error=str(e))

        # Initialize Solana wallet for Kalshi
        if settings.acp_solana_private_key:
            try:
                from solders.keypair import Keypair
                import base58

                # Decode base58 private key
                secret_key = base58.b58decode(settings.acp_solana_private_key)
                self._solana_keypair = Keypair.from_bytes(secret_key)
                logger.info("ACP Solana wallet initialized", pubkey=str(self._solana_keypair.pubkey()))
            except Exception as e:
                logger.error("Failed to initialize ACP Solana wallet", error=str(e))

        self._initialized = True

    @property
    def acp_wallet_address(self) -> Optional[str]:
        """Get the ACP EVM wallet address."""
        if self._acp_wallet:
            return self._acp_wallet.address
        return settings.acp_agent_wallet_address

    @property
    def acp_solana_address(self) -> Optional[str]:
        """Get the ACP Solana wallet address."""
        if self._solana_keypair:
            return str(self._solana_keypair.pubkey())
        return None

    async def get_agent_balance(self, agent_id: str, chain: str) -> Decimal:
        """Get an agent's deposited balance on a specific chain."""
        from src.db.database import get_acp_agent_balance

        balance = await get_acp_agent_balance(agent_id, chain)
        return balance or Decimal(0)

    async def deposit_funds(
        self,
        agent_id: str,
        agent_wallet: str,
        amount: Decimal,
        chain: str,
    ) -> bool:
        """
        Record funds deposited by an agent via ACP escrow.
        Called when ACP releases escrow funds to Spredd.
        """
        from src.db.database import upsert_acp_agent_balance

        try:
            current = await self.get_agent_balance(agent_id, chain)
            new_balance = current + amount

            await upsert_acp_agent_balance(
                agent_id=agent_id,
                agent_wallet=agent_wallet,
                chain=chain,
                balance=new_balance,
            )

            logger.info(
                "ACP funds deposited",
                agent_id=agent_id,
                amount=float(amount),
                chain=chain,
                new_balance=float(new_balance),
            )
            return True

        except Exception as e:
            logger.error("Failed to deposit ACP funds", error=str(e))
            return False

    async def deduct_for_trade(
        self,
        agent_id: str,
        amount: Decimal,
        chain: str,
    ) -> bool:
        """Deduct funds after a trade execution."""
        from src.db.database import upsert_acp_agent_balance, get_acp_agent_wallet

        try:
            current = await self.get_agent_balance(agent_id, chain)
            if current < amount:
                logger.warning(
                    "Insufficient balance for deduction",
                    agent_id=agent_id,
                    balance=float(current),
                    amount=float(amount),
                )
                return False

            new_balance = current - amount
            agent_wallet = await get_acp_agent_wallet(agent_id)

            await upsert_acp_agent_balance(
                agent_id=agent_id,
                agent_wallet=agent_wallet or "",
                chain=chain,
                balance=new_balance,
            )

            logger.info(
                "ACP funds deducted",
                agent_id=agent_id,
                amount=float(amount),
                chain=chain,
                new_balance=float(new_balance),
            )
            return True

        except Exception as e:
            logger.error("Failed to deduct ACP funds", error=str(e))
            return False

    async def withdraw_funds(
        self,
        agent_id: str,
        amount: Decimal,
        chain: str,
        destination_address: str,
    ) -> Optional[str]:
        """
        Withdraw funds back to the agent's wallet.
        Returns transaction hash if successful.
        """
        # This would involve actual blockchain transfer
        # For now, just update the balance
        current = await self.get_agent_balance(agent_id, chain)
        if current < amount:
            logger.warning("Insufficient balance for withdrawal")
            return None

        # TODO: Implement actual USDC transfer
        # For now, just log the intent
        logger.info(
            "ACP withdrawal requested",
            agent_id=agent_id,
            amount=float(amount),
            chain=chain,
            destination=destination_address,
        )

        return None

    async def get_agent_private_key(
        self,
        agent_id: str,
        chain: str,
    ) -> Optional[Union[LocalAccount, "Keypair"]]:
        """
        Get the private key for executing trades on behalf of an agent.

        For simplicity, all agents use Spredd's ACP wallet for execution.
        Per-agent balance tracking ensures fund isolation.

        Returns EVM LocalAccount for EVM chains, Solana Keypair for Solana.
        """
        self.initialize()

        if chain.lower() == "solana":
            return self._solana_keypair
        else:
            return self._acp_wallet

    async def get_agent_positions(self, agent_id: str) -> list[dict[str, Any]]:
        """Get all positions for an agent."""
        from src.db.database import get_acp_agent_positions

        try:
            positions = await get_acp_agent_positions(agent_id)
            return positions or []
        except Exception as e:
            logger.error("Failed to get agent positions", error=str(e))
            return []

    async def create_position(
        self,
        agent_id: str,
        platform: str,
        market_id: str,
        market_title: str,
        outcome: str,
        amount: Decimal,
        entry_price: Decimal,
    ) -> bool:
        """Record a new position for an agent."""
        from src.db.database import create_acp_position

        try:
            await create_acp_position(
                agent_id=agent_id,
                platform=platform,
                market_id=market_id,
                market_title=market_title,
                outcome=outcome,
                amount=amount,
                entry_price=entry_price,
            )
            return True
        except Exception as e:
            logger.error("Failed to create ACP position", error=str(e))
            return False

    async def get_all_agent_balances(self, agent_id: str) -> dict[str, Decimal]:
        """Get all balances for an agent across chains."""
        from src.db.database import get_all_acp_agent_balances

        try:
            return await get_all_acp_agent_balances(agent_id)
        except Exception as e:
            logger.error("Failed to get agent balances", error=str(e))
            return {}

    def get_acp_wallet_balance(self, chain: str) -> dict[str, Decimal]:
        """
        Get actual on-chain balances for Spredd's ACP wallet.
        Returns dict with 'usdc' (or 'usdt' for BSC) and 'gas' balances.
        """
        self.initialize()

        chain_lower = chain.lower()

        # Handle Solana separately
        if chain_lower == "solana":
            return self._get_solana_balance()

        if not self._acp_wallet:
            return {"usdc": Decimal(0), "gas": Decimal(0)}

        try:
            from src.services.bridge import bridge_service, BridgeChain

            if not bridge_service._initialized:
                bridge_service.initialize()

            chain_map = {
                "base": BridgeChain.BASE,
                "polygon": BridgeChain.POLYGON,
                "bsc": BridgeChain.BSC,
                "arbitrum": BridgeChain.ARBITRUM,
                "optimism": BridgeChain.OPTIMISM,
                "ethereum": BridgeChain.ETHEREUM,
            }

            bridge_chain = chain_map.get(chain_lower)
            if not bridge_chain:
                return {"usdc": Decimal(0), "gas": Decimal(0)}

            # Get USDC/USDT balance
            if chain_lower == "bsc":
                usdc_balance = bridge_service.get_bsc_usdt_balance(self._acp_wallet.address)
            else:
                usdc_balance = bridge_service.get_usdc_balance(bridge_chain, self._acp_wallet.address)

            # Get native gas token balance
            gas_balance = bridge_service.get_native_balance(bridge_chain, self._acp_wallet.address)

            return {
                "usdc": usdc_balance,
                "usdt": usdc_balance if chain_lower == "bsc" else Decimal(0),
                "gas": gas_balance,
            }

        except Exception as e:
            logger.error(f"Failed to get ACP wallet balance on {chain}", error=str(e))
            return {"usdc": Decimal(0), "gas": Decimal(0)}

    def _get_solana_balance(self) -> dict[str, Decimal]:
        """Get Solana wallet balances (SOL and USDC)."""
        if not self._solana_keypair:
            return {"usdc": Decimal(0), "gas": Decimal(0)}

        try:
            from solana.rpc.api import Client
            from solders.pubkey import Pubkey
            from spl.token.constants import TOKEN_PROGRAM_ID

            client = Client(settings.solana_rpc_url)
            pubkey = self._solana_keypair.pubkey()

            # Get SOL balance
            sol_response = client.get_balance(pubkey)
            sol_balance = Decimal(sol_response.value) / Decimal(10**9)

            # Get USDC balance
            usdc_mint = Pubkey.from_string(settings.usdc_mint_solana)
            usdc_balance = Decimal(0)

            try:
                # Find associated token account
                from spl.token.instructions import get_associated_token_address
                ata = get_associated_token_address(pubkey, usdc_mint)
                token_response = client.get_token_account_balance(ata)
                if token_response.value:
                    usdc_balance = Decimal(token_response.value.amount) / Decimal(10**6)
            except Exception:
                pass  # No USDC account yet

            return {
                "usdc": usdc_balance,
                "gas": sol_balance,
            }

        except Exception as e:
            logger.error("Failed to get Solana balance", error=str(e))
            return {"usdc": Decimal(0), "gas": Decimal(0)}

    def check_chain_liquidity(self, chain: str, amount: Decimal) -> tuple[bool, str]:
        """
        Check if ACP wallet has sufficient liquidity on target chain.
        Returns (has_liquidity, error_message).
        """
        self.initialize()
        chain_lower = chain.lower()

        # Check if wallet is configured for this chain
        if chain_lower == "solana":
            if not self._solana_keypair:
                return False, "Solana wallet not configured for ACP"
        else:
            if not self._acp_wallet:
                return False, "EVM wallet not configured for ACP"

        balances = self.get_acp_wallet_balance(chain)

        # Minimum gas requirements by chain
        min_gas = {
            "base": Decimal("0.0001"),      # ~$0.01 ETH
            "polygon": Decimal("0.1"),       # ~$0.05 MATIC
            "bsc": Decimal("0.001"),         # ~$0.50 BNB
            "solana": Decimal("0.01"),       # ~$1 SOL
            "arbitrum": Decimal("0.0001"),   # ~$0.01 ETH
            "optimism": Decimal("0.0001"),   # ~$0.01 ETH
        }

        # Check gas
        required_gas = min_gas.get(chain_lower, Decimal("0.001"))
        if balances.get("gas", Decimal(0)) < required_gas:
            gas_token = "BNB" if chain_lower == "bsc" else "SOL" if chain_lower == "solana" else "ETH" if chain_lower != "polygon" else "MATIC"
            return False, f"Insufficient {gas_token} for gas on {chain}. Need {required_gas}, have {balances.get('gas', 0)}"

        # Check USDC/USDT
        collateral = balances.get("usdt" if chain_lower == "bsc" else "usdc", Decimal(0))
        if collateral < amount:
            token = "USDT" if chain_lower == "bsc" else "USDC"
            return False, f"Insufficient {token} on {chain}. Need ${amount}, have ${collateral}"

        return True, ""

    def get_supported_chains_status(self) -> dict[str, dict]:
        """Get liquidity status for all supported chains."""
        chains = ["base", "polygon", "bsc", "solana"]
        status = {}

        min_gas = {
            "base": Decimal("0.0001"),
            "polygon": Decimal("0.1"),
            "bsc": Decimal("0.001"),
            "solana": Decimal("0.01"),
        }

        for chain in chains:
            balances = self.get_acp_wallet_balance(chain)
            required_gas = min_gas.get(chain, Decimal("0.001"))

            status[chain] = {
                "usdc": float(balances.get("usdc", 0)),
                "usdt": float(balances.get("usdt", 0)) if chain == "bsc" else 0,
                "gas": float(balances.get("gas", 0)),
                "ready": balances.get("gas", Decimal(0)) >= required_gas,
                "configured": self._is_chain_configured(chain),
            }

        return status

    def _is_chain_configured(self, chain: str) -> bool:
        """Check if a chain has wallet configured."""
        if chain.lower() == "solana":
            return self._solana_keypair is not None
        else:
            return self._acp_wallet is not None


# Singleton instance
acp_wallet_manager = ACPWalletManager()
