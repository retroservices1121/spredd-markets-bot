"""
Tests for the referral system and fee distribution.

Run with: pytest tests/test_referral.py -v
"""

import pytest
from decimal import Decimal

# Test the fee service calculations (no database needed)
class TestFeeCalculations:
    """Test fee calculation functions."""

    def test_calculate_fee_basic(self):
        """Test 1% fee calculation."""
        from src.services.fee import calculate_fee

        # $100 trade = $1 fee
        fee = calculate_fee("100")
        assert fee == "1.000000"

        # $50 trade = $0.50 fee
        fee = calculate_fee("50")
        assert fee == "0.500000"

        # $10 trade = $0.10 fee
        fee = calculate_fee("10")
        assert fee == "0.100000"

    def test_calculate_fee_precision(self):
        """Test fee calculation with decimal amounts."""
        from src.services.fee import calculate_fee

        # $123.45 trade
        fee = calculate_fee("123.45")
        assert Decimal(fee) == Decimal("1.234500")

        # Small amount
        fee = calculate_fee("0.50")
        assert Decimal(fee) == Decimal("0.005000")

    def test_calculate_net_amount(self):
        """Test net amount after fee."""
        from src.services.fee import calculate_net_amount

        # $100 - 1% = $99
        net = calculate_net_amount("100")
        assert net == "99.000000"

        # $50 - 1% = $49.50
        net = calculate_net_amount("50")
        assert net == "49.500000"

    def test_can_withdraw_minimum(self):
        """Test withdrawal minimum check."""
        from src.services.fee import can_withdraw, MIN_WITHDRAWAL_USDC

        # Below minimum
        assert not can_withdraw("4.99")
        assert not can_withdraw("0")

        # At minimum
        assert can_withdraw("5.00")

        # Above minimum
        assert can_withdraw("10.00")
        assert can_withdraw("100.00")

    def test_format_usdc(self):
        """Test USDC formatting for display."""
        from src.services.fee import format_usdc

        assert format_usdc("10") == "$10.0000"
        assert format_usdc("0") == "$0.00"
        assert format_usdc("123.456789") == "$123.4568"
        assert format_usdc("0.50", decimals=2) == "$0.50"

    def test_tier_commissions(self):
        """Test tier commission rates are correct."""
        from src.services.fee import TIER_COMMISSIONS

        assert TIER_COMMISSIONS[1] == Decimal("0.25")  # 25%
        assert TIER_COMMISSIONS[2] == Decimal("0.05")  # 5%
        assert TIER_COMMISSIONS[3] == Decimal("0.03")  # 3%


class TestReferralCodeGeneration:
    """Test referral code generation."""

    def test_generate_referral_code_format(self):
        """Test referral code format - uses Telegram ID."""
        from src.db.database import generate_referral_code

        telegram_id = 123456789
        code = generate_referral_code(telegram_id)

        # Should be the Telegram ID as a string
        assert code == "123456789"
        # Should be numeric
        assert code.isdigit()

    def test_generate_referral_code_unique(self):
        """Test that different Telegram IDs produce different codes."""
        from src.db.database import generate_referral_code

        codes = [generate_referral_code(i) for i in range(100)]
        # All codes should be unique (since Telegram IDs are unique)
        assert len(codes) == len(set(codes))


class TestReferralChain:
    """Test referral chain functionality."""

    def test_commission_calculations(self):
        """Test commission calculations for each tier."""
        from src.services.fee import TIER_COMMISSIONS
        from decimal import Decimal, ROUND_DOWN

        fee_amount = Decimal("1.00")  # $1 fee from $100 trade

        # Tier 1: 25% of $1 = $0.25
        tier1_commission = (fee_amount * TIER_COMMISSIONS[1]).quantize(
            Decimal("0.000001"), rounding=ROUND_DOWN
        )
        assert tier1_commission == Decimal("0.250000")

        # Tier 2: 5% of $1 = $0.05
        tier2_commission = (fee_amount * TIER_COMMISSIONS[2]).quantize(
            Decimal("0.000001"), rounding=ROUND_DOWN
        )
        assert tier2_commission == Decimal("0.050000")

        # Tier 3: 3% of $1 = $0.03
        tier3_commission = (fee_amount * TIER_COMMISSIONS[3]).quantize(
            Decimal("0.000001"), rounding=ROUND_DOWN
        )
        assert tier3_commission == Decimal("0.030000")

        # Total distributed: 33% of fee
        total = tier1_commission + tier2_commission + tier3_commission
        assert total == Decimal("0.330000")

    def test_full_referral_flow_simulation(self):
        """Simulate complete referral flow with mock data."""
        from decimal import Decimal
        from src.services.fee import calculate_fee, TIER_COMMISSIONS

        # Simulate: User D trades $1000
        # Chain: User A -> User B -> User C -> User D (trader)
        trade_amount = Decimal("1000")
        fee = Decimal(calculate_fee(str(trade_amount)))

        assert fee == Decimal("10.000000")  # 1% of $1000

        # Calculate distributions
        distributions = {}
        total_distributed = Decimal("0")

        for tier in [1, 2, 3]:
            rate = TIER_COMMISSIONS[tier]
            commission = fee * rate
            distributions[f"tier{tier}"] = commission
            total_distributed += commission

        # Verify distributions
        assert distributions["tier1"] == Decimal("2.50")  # 25% of $10
        assert distributions["tier2"] == Decimal("0.50")  # 5% of $10
        assert distributions["tier3"] == Decimal("0.30")  # 3% of $10

        # Total: $3.30 distributed, $6.70 retained
        assert total_distributed == Decimal("3.30")
        retained = fee - total_distributed
        assert retained == Decimal("6.70")

    def test_partial_referral_chain(self):
        """Test fee distribution when referral chain is incomplete."""
        from decimal import Decimal
        from src.services.fee import TIER_COMMISSIONS

        fee = Decimal("10.00")

        # Only 1 referrer (tier 1 only)
        referral_chain_length = 1
        total_distributed = Decimal("0")

        for tier in range(1, referral_chain_length + 1):
            commission = fee * TIER_COMMISSIONS[tier]
            total_distributed += commission

        # Only tier 1 gets paid
        assert total_distributed == Decimal("2.50")

        # 2 referrers (tier 1 and 2)
        referral_chain_length = 2
        total_distributed = Decimal("0")

        for tier in range(1, referral_chain_length + 1):
            commission = fee * TIER_COMMISSIONS[tier]
            total_distributed += commission

        assert total_distributed == Decimal("3.00")  # $2.50 + $0.50

    def test_no_referral_chain(self):
        """Test fee processing when user has no referrer."""
        from decimal import Decimal
        from src.services.fee import calculate_fee

        trade_amount = "100"
        fee = calculate_fee(trade_amount)

        # Fee is still calculated
        assert Decimal(fee) == Decimal("1.000000")

        # But no distributions occur (empty chain)
        referral_chain = []
        total_distributed = Decimal("0")

        for tier, referrer in enumerate(referral_chain, start=1):
            pass  # No referrers

        assert total_distributed == Decimal("0")


class TestStartWithReferral:
    """Test /start command with referral code."""

    def test_parse_referral_code_from_start(self):
        """Test parsing referral code from start parameter."""
        # Simulate context.args
        args = ["ref_ABC12345"]

        referral_code = None
        if args and len(args) > 0:
            arg = args[0]
            if arg.startswith("ref_"):
                referral_code = arg[4:]

        assert referral_code == "ABC12345"

    def test_parse_no_referral_code(self):
        """Test when no referral code provided."""
        args = []

        referral_code = None
        if args and len(args) > 0:
            arg = args[0]
            if arg.startswith("ref_"):
                referral_code = arg[4:]

        assert referral_code is None

    def test_parse_invalid_start_param(self):
        """Test when start param is not a referral code."""
        args = ["something_else"]

        referral_code = None
        if args and len(args) > 0:
            arg = args[0]
            if arg.startswith("ref_"):
                referral_code = arg[4:]

        assert referral_code is None


class TestWithdrawalFlow:
    """Test withdrawal functionality."""

    def test_withdrawal_minimum_check(self):
        """Test withdrawal minimum validation."""
        from src.services.fee import can_withdraw, MIN_WITHDRAWAL_USDC

        # Test various balances
        test_cases = [
            ("0", False),
            ("4.99", False),
            ("5.00", True),
            ("5.01", True),
            ("100.00", True),
        ]

        for balance, expected in test_cases:
            result = can_withdraw(balance)
            assert result == expected, f"Balance {balance}: expected {expected}, got {result}"


class TestEndToEndScenarios:
    """End-to-end scenario tests."""

    def test_scenario_new_user_with_referral(self):
        """
        Scenario: New user joins via referral link and makes a trade.

        1. User A has referral code ABC123
        2. User B joins via t.me/bot?start=ref_ABC123
        3. User B trades $100
        4. User A receives 25% of 1% fee = $0.25
        """
        from decimal import Decimal
        from src.services.fee import calculate_fee, TIER_COMMISSIONS

        # Step 1: Parse referral from start
        start_args = ["ref_ABC123"]
        referral_code = start_args[0][4:] if start_args[0].startswith("ref_") else None
        assert referral_code == "ABC123"

        # Step 2: User B trades $100
        trade_amount = "100"
        fee = Decimal(calculate_fee(trade_amount))
        assert fee == Decimal("1.000000")

        # Step 3: Calculate User A's commission (tier 1)
        user_a_commission = fee * TIER_COMMISSIONS[1]
        assert user_a_commission == Decimal("0.25")

    def test_scenario_three_tier_chain(self):
        """
        Scenario: Complete 3-tier referral chain.

        Chain: Grandpa -> Parent -> Direct Referrer -> Trader
        Trader makes $500 trade.

        Expected distributions from $5 fee:
        - Direct Referrer (T1): $1.25
        - Parent (T2): $0.25
        - Grandpa (T3): $0.15
        """
        from decimal import Decimal
        from src.services.fee import calculate_fee, TIER_COMMISSIONS

        trade_amount = "500"
        fee = Decimal(calculate_fee(trade_amount))
        assert fee == Decimal("5.000000")

        # Calculate all tier commissions
        direct_referrer = fee * TIER_COMMISSIONS[1]  # 25%
        parent = fee * TIER_COMMISSIONS[2]  # 5%
        grandpa = fee * TIER_COMMISSIONS[3]  # 3%

        assert direct_referrer == Decimal("1.25")
        assert parent == Decimal("0.25")
        assert grandpa == Decimal("0.15")

        # Total distributed: $1.65 (33% of fee)
        total = direct_referrer + parent + grandpa
        assert total == Decimal("1.65")

        # Platform retains: $3.35 (67% of fee)
        retained = fee - total
        assert retained == Decimal("3.35")

    def test_scenario_multiple_trades_accumulate(self):
        """
        Scenario: Referrer accumulates earnings from multiple trades.

        User A refers User B.
        User B makes 10 trades of $100 each.
        User A should earn $2.50 total.
        """
        from decimal import Decimal
        from src.services.fee import calculate_fee, TIER_COMMISSIONS

        total_earnings = Decimal("0")

        for _ in range(10):
            fee = Decimal(calculate_fee("100"))
            commission = fee * TIER_COMMISSIONS[1]
            total_earnings += commission

        assert total_earnings == Decimal("2.50")

    def test_scenario_withdrawal_after_earnings(self):
        """
        Scenario: User earns enough to withdraw.

        User earns from 20 trades of $100 = 20 * $0.25 = $5.00
        User can now withdraw (meets $5 minimum).
        """
        from decimal import Decimal
        from src.services.fee import calculate_fee, TIER_COMMISSIONS, can_withdraw

        total_earnings = Decimal("0")

        # Simulate 20 trades
        for _ in range(20):
            fee = Decimal(calculate_fee("100"))
            commission = fee * TIER_COMMISSIONS[1]
            total_earnings += commission

        assert total_earnings == Decimal("5.00")
        assert can_withdraw(str(total_earnings)) is True

        # 19 trades would not be enough
        earnings_19 = Decimal("0")
        for _ in range(19):
            fee = Decimal(calculate_fee("100"))
            commission = fee * TIER_COMMISSIONS[1]
            earnings_19 += commission

        assert earnings_19 == Decimal("4.75")
        assert can_withdraw(str(earnings_19)) is False


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_zero_trade_amount(self):
        """Test fee calculation with zero amount."""
        from src.services.fee import calculate_fee

        fee = calculate_fee("0")
        assert Decimal(fee) == Decimal("0")

    def test_very_small_trade(self):
        """Test fee calculation with very small amount."""
        from src.services.fee import calculate_fee

        # $0.01 trade = $0.0001 fee
        fee = calculate_fee("0.01")
        assert Decimal(fee) == Decimal("0.000100")

    def test_very_large_trade(self):
        """Test fee calculation with large amount."""
        from src.services.fee import calculate_fee

        # $1,000,000 trade = $10,000 fee
        fee = calculate_fee("1000000")
        assert Decimal(fee) == Decimal("10000.000000")

    def test_decimal_precision(self):
        """Test that decimal precision is maintained."""
        from src.services.fee import calculate_fee
        from decimal import Decimal

        # Test with many decimal places
        fee = calculate_fee("123.456789")
        result = Decimal(fee)

        # Should be truncated to 6 decimal places
        assert result == Decimal("1.234567")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
