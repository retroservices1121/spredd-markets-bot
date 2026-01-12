"""
Wallet service for managing Solana and EVM wallets.
Supports one wallet per chain family, shared across platforms.
"""

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Tuple

from eth_account import Account as EthAccount
from eth_account.signers.local import LocalAccount
from solders.keypair import Keypair as SolanaKeypair
from solders.pubkey import Pubkey
from solana.rpc.async_api import AsyncClient as SolanaClient
from solana.rpc.commitment import Confirmed
from web3 import AsyncWeb3
from web3.middleware import ExtraDataToPOAMiddleware

import hashlib

from src.config import settings
from src.db.database import (
    get_wallet,
    create_wallet,
    get_user_wallets,
)
from src.db.models import ChainFamily, Chain
from src.utils.encryption import encrypt, decrypt
from src.utils.logging import get_logger, LoggerMixin

logger = get_logger(__name__)

# Constants
LAMPORTS_PER_SOL = 1_000_000_000
USDC_DECIMALS = 6

# Token addresses
USDC_ADDRESSES = {
    Chain.SOLANA: "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC on Solana
    Chain.POLYGON: "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",  # Native USDC on Polygon
    Chain.BSC: "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d",      # USDC on BSC
    Chain.BASE: "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",     # Native USDC on Base
}

# USDC.e (bridged) address on Polygon - different from native USDC
USDC_E_POLYGON = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"

USDT_ADDRESSES = {
    Chain.BSC: "0x55d398326f99059fF775485246999027B3197955",  # USDT on BSC
}


@dataclass
class WalletInfo:
    """Wallet information without private key."""
    chain_family: ChainFamily
    public_key: str
    
    @property
    def solana_address(self) -> Optional[str]:
        return self.public_key if self.chain_family == ChainFamily.SOLANA else None
    
    @property
    def evm_address(self) -> Optional[str]:
        return self.public_key if self.chain_family == ChainFamily.EVM else None


@dataclass
class Balance:
    """Token balance information."""
    token: str
    symbol: str
    amount: Decimal
    decimals: int
    chain: Chain
    
    @property
    def formatted(self) -> str:
        return f"{self.amount:.{min(self.decimals, 6)}f} {self.symbol}"


class WalletService(LoggerMixin):
    """Service for managing user wallets across chains."""

    def __init__(self):
        self._solana_client: Optional[SolanaClient] = None
        self._polygon_web3: Optional[AsyncWeb3] = None
        self._bsc_web3: Optional[AsyncWeb3] = None
        self._base_web3: Optional[AsyncWeb3] = None

    async def initialize(self) -> None:
        """Initialize blockchain connections."""
        # Solana
        self._solana_client = SolanaClient(settings.solana_rpc_url)

        # Polygon
        self._polygon_web3 = AsyncWeb3(
            AsyncWeb3.AsyncHTTPProvider(settings.polygon_rpc_url)
        )

        # BSC (needs POA middleware)
        self._bsc_web3 = AsyncWeb3(
            AsyncWeb3.AsyncHTTPProvider(settings.bsc_rpc_url)
        )
        self._bsc_web3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

        # Base
        self._base_web3 = AsyncWeb3(
            AsyncWeb3.AsyncHTTPProvider(settings.base_rpc_url)
        )
        
        self.log.info("Wallet service initialized")
    
    async def close(self) -> None:
        """Close blockchain connections."""
        if self._solana_client:
            await self._solana_client.close()
    
    # ===================
    # Wallet Creation
    # ===================
    
    def _generate_solana_keypair(self) -> Tuple[str, bytes]:
        """Generate a new Solana keypair."""
        keypair = SolanaKeypair()
        public_key = str(keypair.pubkey())
        private_key = bytes(keypair)
        return public_key, private_key
    
    def _generate_evm_keypair(self) -> Tuple[str, bytes]:
        """Generate a new EVM keypair."""
        account = EthAccount.create()
        public_key = account.address
        private_key = account.key
        return public_key, private_key

    def _hash_export_pin(self, pin: str, telegram_id: int) -> str:
        """Create a secure hash of the export PIN.

        Uses PBKDF2 with telegram_id as additional salt for security.
        The PIN itself is never stored, only the hash for verification.
        """
        # Create a unique salt using telegram_id and a constant
        salt = f"spredd_export_{telegram_id}".encode()
        # Use PBKDF2 with SHA256
        pin_hash = hashlib.pbkdf2_hmac(
            'sha256',
            pin.encode(),
            salt,
            100000  # iterations
        )
        return pin_hash.hex()

    def verify_export_pin(self, pin: str, telegram_id: int, stored_hash: str) -> bool:
        """Verify a PIN against the stored hash."""
        computed_hash = self._hash_export_pin(pin, telegram_id)
        return computed_hash == stored_hash

    async def create_wallet_for_user(
        self,
        user_id: str,
        telegram_id: int,
        chain_family: ChainFamily,
        user_pin: str = "",
    ) -> WalletInfo:
        """Create a new wallet for a user.

        Args:
            user_id: Database user ID
            telegram_id: Telegram user ID
            chain_family: SOLANA or EVM
            user_pin: PIN for export verification (required for security)

        Returns:
            WalletInfo with public key

        Note:
            - Keys are encrypted WITHOUT PIN (allows PIN-less trading)
            - PIN hash is stored separately for export verification
            - This allows convenient trading while securing key exports
        """
        # Check if wallet already exists
        existing = await get_wallet(user_id, chain_family)
        if existing:
            return WalletInfo(
                chain_family=chain_family,
                public_key=existing.public_key,
            )

        # Generate keypair based on chain family
        if chain_family == ChainFamily.SOLANA:
            public_key, private_key = self._generate_solana_keypair()
        else:
            public_key, private_key = self._generate_evm_keypair()

        # Encrypt private key WITHOUT PIN - allows trading without PIN entry
        # Security comes from master_key + telegram_id combination
        encrypted_key = encrypt(
            private_key,
            settings.encryption_key,
            telegram_id,
            "",  # No PIN in encryption - enables PIN-less trading
        )

        # Hash the PIN for export verification (if provided)
        export_pin_hash = None
        if user_pin:
            export_pin_hash = self._hash_export_pin(user_pin, telegram_id)

        # Store in database
        await create_wallet(
            user_id=user_id,
            chain_family=chain_family,
            public_key=public_key,
            encrypted_private_key=encrypted_key,
            pin_protected=False,  # Trading doesn't require PIN
            export_pin_hash=export_pin_hash,  # Export requires PIN verification
        )

        self.log.info(
            "Created wallet",
            user_id=user_id,
            chain_family=chain_family.value,
            public_key=public_key[:8] + "...",
            has_export_pin=bool(export_pin_hash),
        )

        return WalletInfo(
            chain_family=chain_family,
            public_key=public_key,
        )
    
    async def get_or_create_wallets(
        self,
        user_id: str,
        telegram_id: int,
        user_pin: str = "",
    ) -> dict[ChainFamily, WalletInfo]:
        """Get or create both Solana and EVM wallets for a user.

        Args:
            user_id: Database user ID
            telegram_id: Telegram user ID
            user_pin: PIN for new wallet encryption (only used if creating)

        Returns:
            Dict mapping ChainFamily to WalletInfo
        """
        wallets = {}

        for family in ChainFamily:
            wallets[family] = await self.create_wallet_for_user(
                user_id=user_id,
                telegram_id=telegram_id,
                chain_family=family,
                user_pin=user_pin,
            )

        return wallets

    async def is_wallet_pin_protected(
        self,
        user_id: str,
        chain_family: ChainFamily,
    ) -> bool:
        """Check if a wallet requires PIN to decrypt (legacy - always False now)."""
        # Trading never requires PIN anymore - keys are encrypted without PIN
        return False

    async def has_export_pin(
        self,
        user_id: str,
        chain_family: ChainFamily,
    ) -> bool:
        """Check if a wallet has an export PIN set."""
        wallet = await get_wallet(user_id, chain_family)
        if not wallet:
            return False
        return bool(wallet.export_pin_hash)

    async def get_export_pin_hash(
        self,
        user_id: str,
        chain_family: ChainFamily,
    ) -> Optional[str]:
        """Get the export PIN hash for a wallet."""
        wallet = await get_wallet(user_id, chain_family)
        if not wallet:
            return None
        return wallet.export_pin_hash

    # ===================
    # Key Retrieval
    # ===================

    async def get_solana_keypair(
        self,
        user_id: str,
        telegram_id: int,
        user_pin: str = "",
    ) -> Optional[SolanaKeypair]:
        """Get decrypted Solana keypair for signing.

        Args:
            user_id: Database user ID
            telegram_id: Telegram user ID
            user_pin: PIN if wallet is PIN-protected

        Returns:
            SolanaKeypair or None if wallet not found

        Raises:
            EncryptionError: If PIN is wrong
        """
        wallet = await get_wallet(user_id, ChainFamily.SOLANA)
        if not wallet:
            return None

        private_key = decrypt(
            wallet.encrypted_private_key,
            settings.encryption_key,
            telegram_id,
            user_pin,
        )

        return SolanaKeypair.from_bytes(private_key)

    async def get_evm_account(
        self,
        user_id: str,
        telegram_id: int,
        user_pin: str = "",
    ) -> Optional[LocalAccount]:
        """Get decrypted EVM account for signing.

        Args:
            user_id: Database user ID
            telegram_id: Telegram user ID
            user_pin: PIN if wallet is PIN-protected

        Returns:
            LocalAccount or None if wallet not found

        Raises:
            EncryptionError: If PIN is wrong
        """
        wallet = await get_wallet(user_id, ChainFamily.EVM)
        if not wallet:
            return None

        private_key = decrypt(
            wallet.encrypted_private_key,
            settings.encryption_key,
            telegram_id,
            user_pin,
        )

        return EthAccount.from_key(private_key)

    async def get_private_key(
        self,
        user_id: str,
        telegram_id: int,
        chain_family: ChainFamily,
        user_pin: str = "",
    ):
        """Get private key/keypair for signing transactions.

        Args:
            user_id: Database user ID
            telegram_id: Telegram user ID
            chain_family: SOLANA or EVM
            user_pin: PIN if wallet is PIN-protected

        Returns:
            SolanaKeypair for Solana or LocalAccount for EVM

        Raises:
            EncryptionError: If PIN is wrong
        """
        if chain_family == ChainFamily.SOLANA:
            return await self.get_solana_keypair(user_id, telegram_id, user_pin)
        else:
            return await self.get_evm_account(user_id, telegram_id, user_pin)

    async def export_private_key(
        self,
        user_id: str,
        telegram_id: int,
        chain_family: ChainFamily,
        user_pin: str = "",
    ) -> Optional[str]:
        """Export private key for user backup.

        Args:
            user_id: Database user ID
            telegram_id: Telegram user ID
            chain_family: SOLANA or EVM
            user_pin: PIN if wallet is PIN-protected

        Returns:
            Base58 string for Solana, hex string for EVM

        Raises:
            EncryptionError: If PIN is wrong
        """
        wallet = await get_wallet(user_id, chain_family)
        if not wallet:
            return None

        private_key = decrypt(
            wallet.encrypted_private_key,
            settings.encryption_key,
            telegram_id,
            user_pin,
        )

        if chain_family == ChainFamily.SOLANA:
            # Return base58 encoded for Solana
            import base58
            return base58.b58encode(private_key).decode()
        else:
            # Return hex for EVM
            return "0x" + private_key.hex()
    
    # ===================
    # Balance Queries
    # ===================
    
    async def get_solana_balance(self, public_key: str) -> Balance:
        """Get SOL balance."""
        if not self._solana_client:
            raise RuntimeError("Solana client not initialized")
        
        pubkey = Pubkey.from_string(public_key)
        response = await self._solana_client.get_balance(pubkey, commitment=Confirmed)
        
        lamports = response.value
        sol = Decimal(lamports) / Decimal(LAMPORTS_PER_SOL)
        
        return Balance(
            token="SOL",
            symbol="SOL",
            amount=sol,
            decimals=9,
            chain=Chain.SOLANA,
        )
    
    async def get_solana_usdc_balance(self, public_key: str) -> Balance:
        """Get USDC balance on Solana."""
        if not self._solana_client:
            raise RuntimeError("Solana client not initialized")
        
        from solana.rpc.types import TokenAccountOpts
        
        pubkey = Pubkey.from_string(public_key)
        usdc_mint = Pubkey.from_string(USDC_ADDRESSES[Chain.SOLANA])
        
        response = await self._solana_client.get_token_accounts_by_owner(
            pubkey,
            TokenAccountOpts(mint=usdc_mint),
            commitment=Confirmed,
        )
        
        total = Decimal(0)
        for account in response.value:
            # Parse token account data
            data = account.account.data
            # Token account balance is at offset 64, 8 bytes little endian
            if len(data) >= 72:
                amount = int.from_bytes(data[64:72], "little")
                total += Decimal(amount) / Decimal(10**USDC_DECIMALS)
        
        return Balance(
            token=USDC_ADDRESSES[Chain.SOLANA],
            symbol="USDC",
            amount=total,
            decimals=USDC_DECIMALS,
            chain=Chain.SOLANA,
        )
    
    async def _get_evm_native_balance(
        self,
        web3: AsyncWeb3,
        address: str,
        chain: Chain,
        symbol: str,
    ) -> Balance:
        """Get native token balance on EVM chain."""
        balance_wei = await web3.eth.get_balance(address)
        balance = Decimal(balance_wei) / Decimal(10**18)
        
        return Balance(
            token="native",
            symbol=symbol,
            amount=balance,
            decimals=18,
            chain=chain,
        )
    
    async def _get_erc20_balance(
        self,
        web3: AsyncWeb3,
        address: str,
        token_address: str,
        symbol: str,
        decimals: int,
        chain: Chain,
    ) -> Balance:
        """Get ERC20 token balance."""
        # Minimal ERC20 ABI for balanceOf
        erc20_abi = [
            {
                "constant": True,
                "inputs": [{"name": "_owner", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"name": "balance", "type": "uint256"}],
                "type": "function",
            }
        ]
        
        contract = web3.eth.contract(
            address=web3.to_checksum_address(token_address),
            abi=erc20_abi,
        )
        
        balance_raw = await contract.functions.balanceOf(address).call()
        balance = Decimal(balance_raw) / Decimal(10**decimals)
        
        return Balance(
            token=token_address,
            symbol=symbol,
            amount=balance,
            decimals=decimals,
            chain=chain,
        )
    
    async def get_polygon_balances(self, address: str) -> list[Balance]:
        """Get balances on Polygon."""
        if not self._polygon_web3:
            raise RuntimeError("Polygon client not initialized")

        balances = []

        # MATIC
        matic = await self._get_evm_native_balance(
            self._polygon_web3,
            address,
            Chain.POLYGON,
            "MATIC",
        )
        balances.append(matic)

        # USDC.e (bridged - used by Polymarket)
        try:
            usdc_e = await self._get_erc20_balance(
                self._polygon_web3,
                address,
                USDC_E_POLYGON,
                "USDC.e",
                USDC_DECIMALS,
                Chain.POLYGON,
            )
            balances.append(usdc_e)
        except Exception as e:
            self.log.warning("Failed to get Polygon USDC.e balance", error=str(e))

        # Native USDC (Circle)
        try:
            usdc = await self._get_erc20_balance(
                self._polygon_web3,
                address,
                USDC_ADDRESSES[Chain.POLYGON],
                "USDC",
                USDC_DECIMALS,
                Chain.POLYGON,
            )
            balances.append(usdc)
        except Exception as e:
            self.log.warning("Failed to get Polygon native USDC balance", error=str(e))

        return balances
    
    async def get_bsc_balances(self, address: str) -> list[Balance]:
        """Get balances on BSC."""
        if not self._bsc_web3:
            raise RuntimeError("BSC client not initialized")
        
        balances = []
        
        # BNB
        bnb = await self._get_evm_native_balance(
            self._bsc_web3,
            address,
            Chain.BSC,
            "BNB",
        )
        balances.append(bnb)
        
        # USDT
        try:
            usdt = await self._get_erc20_balance(
                self._bsc_web3,
                address,
                USDT_ADDRESSES[Chain.BSC],
                "USDT",
                18,  # USDT on BSC has 18 decimals
                Chain.BSC,
            )
            balances.append(usdt)
        except Exception as e:
            self.log.warning("Failed to get BSC USDT balance", error=str(e))
        
        # USDC
        try:
            usdc = await self._get_erc20_balance(
                self._bsc_web3,
                address,
                USDC_ADDRESSES[Chain.BSC],
                "USDC",
                18,
                Chain.BSC,
            )
            balances.append(usdc)
        except Exception as e:
            self.log.warning("Failed to get BSC USDC balance", error=str(e))
        
        return balances

    async def get_base_balances(self, address: str) -> list[Balance]:
        """Get balances on Base."""
        if not self._base_web3:
            raise RuntimeError("Base client not initialized")

        balances = []

        # ETH (gas token on Base)
        eth = await self._get_evm_native_balance(
            self._base_web3,
            address,
            Chain.BASE,
            "ETH",
        )
        balances.append(eth)

        # USDC
        try:
            usdc = await self._get_erc20_balance(
                self._base_web3,
                address,
                USDC_ADDRESSES[Chain.BASE],
                "USDC",
                USDC_DECIMALS,
                Chain.BASE,
            )
            balances.append(usdc)
        except Exception as e:
            self.log.warning("Failed to get Base USDC balance", error=str(e))

        return balances

    async def get_all_balances(
        self,
        user_id: str,
    ) -> dict[ChainFamily, list[Balance]]:
        """Get all balances for a user across chains."""
        wallets = await get_user_wallets(user_id)
        
        result = {
            ChainFamily.SOLANA: [],
            ChainFamily.EVM: [],
        }
        
        for wallet in wallets:
            if wallet.chain_family == ChainFamily.SOLANA:
                try:
                    sol = await self.get_solana_balance(wallet.public_key)
                    result[ChainFamily.SOLANA].append(sol)
                    
                    usdc = await self.get_solana_usdc_balance(wallet.public_key)
                    result[ChainFamily.SOLANA].append(usdc)
                except Exception as e:
                    self.log.error("Failed to get Solana balances", error=str(e))
            
            elif wallet.chain_family == ChainFamily.EVM:
                try:
                    polygon = await self.get_polygon_balances(wallet.public_key)
                    result[ChainFamily.EVM].extend(polygon)
                except Exception as e:
                    self.log.error("Failed to get Polygon balances", error=str(e))

                try:
                    base = await self.get_base_balances(wallet.public_key)
                    result[ChainFamily.EVM].extend(base)
                except Exception as e:
                    self.log.error("Failed to get Base balances", error=str(e))

                try:
                    bsc = await self.get_bsc_balances(wallet.public_key)
                    result[ChainFamily.EVM].extend(bsc)
                except Exception as e:
                    self.log.error("Failed to get BSC balances", error=str(e))

        return result


# Singleton instance
wallet_service = WalletService()
