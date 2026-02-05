"""
ACP Sandbox Test Script.

This script creates a test buyer agent to initiate jobs against the Spredd
seller agent for sandbox testing and graduation.

Requirements:
1. Register a SEPARATE buyer agent on https://app.virtuals.io/acp
2. Fund the buyer agent with USDC on Base
3. Get a GAME API key from https://console.game.virtuals.io/
4. Configure the environment variables below
5. Run this script to execute test jobs

Usage:
    py -3.12 scripts/acp_sandbox_test.py
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()


# Test Buyer Configuration
TEST_BUYER_PRIVATE_KEY = os.getenv("ACP_TEST_BUYER_PRIVATE_KEY")
TEST_BUYER_WALLET_ADDRESS = os.getenv("ACP_TEST_BUYER_WALLET_ADDRESS")
TEST_BUYER_ENTITY_ID = os.getenv("ACP_TEST_BUYER_ENTITY_ID")
GAME_API_KEY = os.getenv("GAME_API_KEY")

# Spredd Seller Agent (target)
SPREDD_ENTITY_ID = os.getenv("ACP_ENTITY_ID")

# Environment
ACP_ENVIRONMENT = os.getenv("ACP_ENVIRONMENT", "sandbox")


def check_config():
    """Verify all required config is set."""
    missing = []

    if not TEST_BUYER_PRIVATE_KEY:
        missing.append("ACP_TEST_BUYER_PRIVATE_KEY")
    if not TEST_BUYER_WALLET_ADDRESS:
        missing.append("ACP_TEST_BUYER_WALLET_ADDRESS")
    if not TEST_BUYER_ENTITY_ID:
        missing.append("ACP_TEST_BUYER_ENTITY_ID")
    if not SPREDD_ENTITY_ID:
        missing.append("ACP_ENTITY_ID")
    if not GAME_API_KEY:
        missing.append("GAME_API_KEY (get from https://console.game.virtuals.io/)")

    if missing:
        print("Missing required environment variables:")
        for var in missing:
            print(f"  - {var}")
        print("\nSee .env.example for configuration details.")
        return False

    return True


async def inspect_sdk():
    """Inspect the ACP Plugin SDK structure."""
    print("\n" + "="*60)
    print("INSPECTING ACP-PLUGIN-GAMESDK")
    print("="*60)

    import inspect

    try:
        from acp_plugin_gamesdk.acp_plugin import AcpPlugin, AcpPluginOptions
        print("\nAcpPlugin imported successfully!")

        # Check AcpPluginOptions
        print("\nAcpPluginOptions fields:")
        sig = inspect.signature(AcpPluginOptions.__init__)
        for p, v in sig.parameters.items():
            if p != 'self':
                default = f" = {v.default}" if v.default != inspect.Parameter.empty else ""
                print(f"  - {p}{default}")

        # Check AcpPlugin methods
        print("\nAcpPlugin methods:")
        for method in dir(AcpPlugin):
            if not method.startswith('_'):
                print(f"  - {method}")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

    # Check virtuals_acp version
    try:
        from virtuals_acp.client import VirtualsACP
        print("\n\nVirtualsACP (virtuals_acp.client) imported successfully!")

        print("\nVirtualsACP.__init__ params:")
        sig = inspect.signature(VirtualsACP.__init__)
        for p, v in sig.parameters.items():
            if p != 'self':
                default = f" = {v.default}" if v.default != inspect.Parameter.empty else ""
                print(f"  - {p}{default}")

        print("\nVirtualsACP methods:")
        for method in dir(VirtualsACP):
            if not method.startswith('_') and callable(getattr(VirtualsACP, method, None)):
                print(f"  - {method}")

    except Exception as e:
        print(f"VirtualsACP error: {e}")


async def test_with_plugin():
    """Test using the ACP Plugin."""
    print("\n" + "="*60)
    print("TEST: Using ACP Plugin")
    print("="*60)

    try:
        from acp_plugin_gamesdk.acp_plugin import AcpPlugin, AcpPluginOptions
        from virtuals_acp.client import VirtualsACP

        print(f"Buyer wallet: {TEST_BUYER_WALLET_ADDRESS}")
        print(f"Buyer entity: {TEST_BUYER_ENTITY_ID}")
        print(f"Target seller: {SPREDD_ENTITY_ID}")
        print(f"Environment: {ACP_ENVIRONMENT}")

        # Create VirtualsACP client first
        print("\nInitializing VirtualsACP client...")
        acp_client = VirtualsACP(
            wallet_private_key=TEST_BUYER_PRIVATE_KEY,
            agent_wallet_address=TEST_BUYER_WALLET_ADDRESS,
            entity_id=int(TEST_BUYER_ENTITY_ID) if TEST_BUYER_ENTITY_ID.isdigit() else TEST_BUYER_ENTITY_ID,
        )

        # Create plugin options
        print("Creating AcpPlugin...")
        options = AcpPluginOptions(
            api_key=GAME_API_KEY,
            acp_client=acp_client,
        )

        plugin = AcpPlugin(options=options)
        print("Plugin created successfully!")

        # Try to browse agents or get offerings
        print("\nBrowsing for Spredd agent...")

        # Check available methods
        print("\nAvailable plugin methods:")
        for method in dir(plugin):
            if not method.startswith('_'):
                print(f"  - {method}")

        return True

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_direct_client():
    """Test using VirtualsACP client directly."""
    print("\n" + "="*60)
    print("TEST: Direct VirtualsACP Client")
    print("="*60)

    try:
        from virtuals_acp.client import VirtualsACP
        from virtuals_acp.contract_clients.contract_client_v2 import ACPContractClientV2
        from virtuals_acp.configs.configs import BASE_MAINNET_CONFIG_V2

        print(f"Buyer wallet: {TEST_BUYER_WALLET_ADDRESS}")
        print(f"Buyer entity: {TEST_BUYER_ENTITY_ID}")
        print(f"Target seller: {SPREDD_ENTITY_ID}")

        # Try creating client with new SDK structure
        print("\nCreating VirtualsACP client (v2 SDK)...")

        # Entity ID must be an integer
        entity_id = int(TEST_BUYER_ENTITY_ID) if TEST_BUYER_ENTITY_ID.isdigit() else TEST_BUYER_ENTITY_ID

        # Create contract client first (v2 requires entity_id as int)
        print(f"Entity ID type: {type(entity_id)} = {entity_id}")

        contract_client = ACPContractClientV2(
            wallet_private_key=TEST_BUYER_PRIVATE_KEY,
            agent_wallet_address=TEST_BUYER_WALLET_ADDRESS,
            entity_id=entity_id,
            config=BASE_MAINNET_CONFIG_V2,
        )

        # Then create the ACP client
        client = VirtualsACP(
            acp_contract_clients=contract_client,
        )

        print("Client created successfully!")

        # Try to browse agents
        print("\nTrying to browse agents...")
        try:
            agents = await client.browse_agents()
            print(f"Found {len(agents) if agents else 0} agents")
            if agents:
                for agent in agents[:5]:
                    print(f"  - {agent}")
        except Exception as e:
            print(f"browse_agents error: {e}")

        # Try to get active jobs
        print("\nTrying to get active jobs...")
        try:
            jobs = client.get_active_jobs()  # Not async
            print(f"Active jobs: {jobs}")
        except Exception as e:
            print(f"get_active_jobs error: {e}")

        # Try to initiate a job to Spredd seller
        # Need the seller's wallet address, not entity ID
        SPREDD_WALLET = os.getenv("ACP_AGENT_WALLET_ADDRESS", "0x3dCA01b4F7De37C60423d4AEe4f36b762c5B10ce")
        print(f"\nTrying to initiate job to seller wallet {SPREDD_WALLET}...")
        try:
            from virtuals_acp.fare import FareAmount
            import json

            # Use USDC fare from the config (not ETH)
            usdc_fare = BASE_MAINNET_CONFIG_V2.base_fare
            print(f"Using USDC fare: {usdc_fare.contract_address}")

            # Check USDC balance first
            from web3 import Web3
            w3 = Web3(Web3.HTTPProvider('https://mainnet.base.org'))
            ERC20_ABI = [{'constant': True, 'inputs': [{'name': '_owner', 'type': 'address'}], 'name': 'balanceOf', 'outputs': [{'name': 'balance', 'type': 'uint256'}], 'type': 'function'}]
            usdc = w3.eth.contract(address=usdc_fare.contract_address, abi=ERC20_ABI)
            usdc_balance = usdc.functions.balanceOf(TEST_BUYER_WALLET_ADDRESS).call()
            print(f"USDC Balance: {usdc_balance / 10**6} USDC")

            if usdc_balance == 0:
                print("ERROR: Need USDC to create jobs!")
                print(f"Fund USDC to: {TEST_BUYER_WALLET_ADDRESS}")
                print(f"USDC contract: {usdc_fare.contract_address}")
                return False

            # Create fare amount (0.001 USDC = 1000 in 6 decimals)
            fare = FareAmount(0.001, usdc_fare)

            # Service requirements as JSON string
            service_req = json.dumps({
                "query": "bitcoin",
                "limit": 5
            })

            job_id = await client.initiate_job(
                provider_address=SPREDD_WALLET,
                service_requirement=service_req,
                fare_amount=fare,
            )
            print(f"Job initiated successfully!")
            print(f"Job ID: {job_id}")
        except Exception as e:
            print(f"initiate_job error: {e}")
            import traceback
            traceback.print_exc()

        return True

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False


async def run_all_tests():
    """Run all tests."""
    print("="*60)
    print("SPREDD ACP SANDBOX TEST SUITE")
    print("="*60)
    print(f"\nEnvironment: {ACP_ENVIRONMENT}")
    print(f"Buyer Entity ID: {TEST_BUYER_ENTITY_ID}")
    print(f"Seller Entity ID: {SPREDD_ENTITY_ID}")

    # First inspect the SDK
    await inspect_sdk()

    # Try direct client
    await test_direct_client()

    # Try plugin
    await test_with_plugin()


async def run_single_test(test_name: str):
    """Run a single test by name."""
    tests = {
        "inspect": inspect_sdk,
        "plugin": test_with_plugin,
        "direct": test_direct_client,
    }

    if test_name not in tests:
        print(f"Unknown test: {test_name}")
        print(f"Available tests: {list(tests.keys())}")
        return False

    return await tests[test_name]()


def main():
    """Main entry point."""
    if not check_config():
        sys.exit(1)

    if len(sys.argv) > 1:
        test_name = sys.argv[1]
        if test_name == "--help":
            print(__doc__)
            print("\nAvailable tests:")
            print("  inspect - Inspect SDK structure")
            print("  plugin  - Test with ACP Plugin")
            print("  direct  - Test with VirtualsACP directly")
            print("\nRun without arguments to execute all tests.")
            sys.exit(0)

        asyncio.run(run_single_test(test_name))
    else:
        asyncio.run(run_all_tests())


if __name__ == "__main__":
    main()
