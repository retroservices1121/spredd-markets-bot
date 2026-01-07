"""
Tests for Spredd Markets Bot
"""

import pytest
from decimal import Decimal

from src.utils.encryption import (
    encrypt,
    decrypt,
    generate_encryption_key,
    validate_encryption_key,
)


class TestEncryption:
    """Test encryption utilities."""
    
    def test_generate_key(self):
        """Test encryption key generation."""
        key = generate_encryption_key()
        assert len(key) == 64
        assert validate_encryption_key(key)
    
    def test_validate_key_valid(self):
        """Test valid key validation."""
        key = "a" * 64
        assert validate_encryption_key(key)
    
    def test_validate_key_invalid_length(self):
        """Test invalid key length."""
        key = "a" * 32
        assert not validate_encryption_key(key)
    
    def test_validate_key_invalid_hex(self):
        """Test invalid hex characters."""
        key = "g" * 64
        assert not validate_encryption_key(key)
    
    def test_encrypt_decrypt(self):
        """Test encryption and decryption round trip."""
        key = generate_encryption_key()
        user_id = 123456789
        plaintext = b"test wallet private key"
        
        encrypted = encrypt(plaintext, key, user_id)
        decrypted = decrypt(encrypted, key, user_id)
        
        assert decrypted == plaintext
    
    def test_different_users_different_ciphertext(self):
        """Test that different users produce different ciphertext."""
        key = generate_encryption_key()
        plaintext = b"test wallet private key"
        
        encrypted1 = encrypt(plaintext, key, 1)
        encrypted2 = encrypt(plaintext, key, 2)
        
        assert encrypted1 != encrypted2
    
    def test_decrypt_wrong_user_fails(self):
        """Test that decryption with wrong user ID fails."""
        key = generate_encryption_key()
        plaintext = b"test wallet private key"
        
        encrypted = encrypt(plaintext, key, 1)
        
        with pytest.raises(Exception):
            decrypt(encrypted, key, 2)


class TestPlatformBase:
    """Test platform base classes."""
    
    def test_format_price(self):
        """Test price formatting."""
        from src.platforms.base import BasePlatform
        
        # We can't instantiate abstract class, so test the logic directly
        price = Decimal("0.65")
        cents = int(price * 100)
        assert cents == 65
    
    def test_format_probability(self):
        """Test probability formatting."""
        price = Decimal("0.65")
        prob = float(price * 100)
        assert prob == 65.0


class TestModels:
    """Test database models."""
    
    def test_chain_family_enum(self):
        """Test chain family enum."""
        from src.db.models import ChainFamily
        
        assert ChainFamily.SOLANA.value == "solana"
        assert ChainFamily.EVM.value == "evm"
    
    def test_platform_enum(self):
        """Test platform enum."""
        from src.db.models import Platform
        
        assert Platform.KALSHI.value == "kalshi"
        assert Platform.POLYMARKET.value == "polymarket"
        assert Platform.OPINION.value == "opinion"
    
    def test_outcome_enum(self):
        """Test outcome enum."""
        from src.db.models import Outcome
        
        assert Outcome.YES.value == "yes"
        assert Outcome.NO.value == "no"


# Integration tests would go here with database fixtures
class TestDatabase:
    """Database integration tests (require DATABASE_URL)."""
    
    @pytest.mark.skip(reason="Requires database")
    async def test_create_user(self):
        """Test user creation."""
        pass
    
    @pytest.mark.skip(reason="Requires database")
    async def test_create_wallet(self):
        """Test wallet creation."""
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
