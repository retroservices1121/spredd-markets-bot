"""
ACP Client.

Main service that handles ACP SDK integration and job lifecycle.
"""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Optional

from src.utils.logging import get_logger
from src.config import settings
from src.services.acp.schemas import JobType, JOB_OFFERINGS
from src.services.acp.handlers import acp_job_handler
from src.services.acp.wallet_manager import acp_wallet_manager

logger = get_logger(__name__)


class SpreddACPService:
    """
    Spredd's ACP Service Provider.

    Handles registration, job discovery, and job execution
    through the Virtuals ACP protocol.
    """

    def __init__(self):
        self._initialized = False
        self._acp_client = None
        self._listening = False
        self._job_queue: asyncio.Queue = asyncio.Queue()

    async def initialize(self) -> bool:
        """Initialize the ACP client and register job offerings."""
        if self._initialized:
            return True

        if not settings.acp_enabled:
            logger.info("ACP service is disabled")
            return False

        # Validate required config
        if not settings.acp_agent_wallet_private_key:
            logger.warning("ACP wallet private key not configured")
            return False

        if not settings.acp_entity_id:
            logger.warning("ACP entity ID not configured")
            return False

        try:
            # Initialize wallet manager
            acp_wallet_manager.initialize()

            # Initialize the ACP SDK client
            # Note: virtuals-acp SDK integration
            await self._init_acp_sdk()

            # Set up handlers
            acp_job_handler.set_wallet_manager(acp_wallet_manager)

            self._initialized = True
            logger.info(
                "ACP service initialized",
                environment=settings.acp_environment,
                wallet=settings.acp_agent_wallet_address,
            )
            return True

        except Exception as e:
            logger.error("Failed to initialize ACP service", error=str(e))
            return False

    async def _init_acp_sdk(self):
        """Initialize the ACP SDK client."""
        try:
            # Try to import the ACP SDK
            from virtuals_acp import VirtualsACP
            from virtuals_acp.config import BASE_MAINNET_ACP_CONFIG_V2, BASE_TESTNET_ACP_CONFIG_V2

            # Choose config based on environment
            if settings.acp_environment == "production":
                config = BASE_MAINNET_ACP_CONFIG_V2
            else:
                config = BASE_TESTNET_ACP_CONFIG_V2

            # Initialize the client
            self._acp_client = VirtualsACP(
                wallet_private_key=settings.acp_agent_wallet_private_key,
                agent_wallet_address=settings.acp_agent_wallet_address,
                entity_id=settings.acp_entity_id,
                config=config,
                on_new_task=self._on_new_job,
            )

            logger.info("ACP SDK client initialized")

        except ImportError:
            logger.warning(
                "virtuals-acp SDK not installed. Running in mock mode. "
                "Install with: pip install virtuals-acp"
            )
            self._acp_client = None

        except Exception as e:
            logger.error("Failed to initialize ACP SDK", error=str(e))
            raise

    async def _on_new_job(self, job: Any):
        """Callback when a new job request is received."""
        await self._job_queue.put(job)

    async def start_listening(self):
        """Start listening for incoming job requests."""
        if not self._initialized:
            logger.warning("Cannot start listening - ACP not initialized")
            return

        self._listening = True
        logger.info("ACP service started listening for jobs")

        # Start job processing loop
        asyncio.create_task(self._process_jobs())

        # If we have an SDK client, start its event loop
        if self._acp_client:
            try:
                await self._acp_client.start()
            except Exception as e:
                logger.error("ACP client start failed", error=str(e))

    async def stop_listening(self):
        """Stop listening for jobs."""
        self._listening = False
        if self._acp_client:
            try:
                await self._acp_client.stop()
            except Exception:
                pass
        logger.info("ACP service stopped")

    async def _process_jobs(self):
        """Process jobs from the queue."""
        while self._listening:
            try:
                # Wait for a job with timeout
                try:
                    job = await asyncio.wait_for(
                        self._job_queue.get(),
                        timeout=5.0
                    )
                except asyncio.TimeoutError:
                    continue

                # Process the job
                await self._handle_job(job)

            except Exception as e:
                logger.error("Job processing error", error=str(e))
                await asyncio.sleep(1)

    async def _handle_job(self, job: Any):
        """Handle a single job request."""
        try:
            # Extract job details
            job_id = getattr(job, "job_id", None) or getattr(job, "id", "unknown")
            job_type_str = getattr(job, "job_type", None) or getattr(job, "offering_name", "")
            agent_id = getattr(job, "buyer_agent_id", None) or getattr(job, "client_id", "unknown")
            service_req = getattr(job, "service_requirements", {}) or getattr(job, "requirements", {})

            logger.info(
                "Processing ACP job",
                job_id=job_id,
                job_type=job_type_str,
                agent_id=agent_id,
            )

            # Map to our job type
            try:
                job_type = JobType(job_type_str)
            except ValueError:
                await self._reject_job(job, f"Unknown job type: {job_type_str}")
                return

            # Accept the job
            await self._accept_job(job)

            # Execute the job
            deliverable = await acp_job_handler.handle_job(
                job_type=job_type,
                agent_id=agent_id,
                service_requirements=service_req,
            )

            # Deliver the result
            await self._deliver_job(job, deliverable)

            logger.info(
                "ACP job completed",
                job_id=job_id,
                success=deliverable.get("success", False),
            )

        except Exception as e:
            logger.error("Job handling failed", error=str(e))
            await self._reject_job(job, str(e))

    async def _accept_job(self, job: Any):
        """Accept an incoming job request."""
        if self._acp_client:
            try:
                job_id = getattr(job, "job_id", None) or getattr(job, "id", None)
                memo_id = getattr(job, "memo_id", None)
                await self._acp_client.respond_job(
                    job_id=job_id,
                    memo_id=memo_id,
                    accept=True,
                    reason="Job accepted by Spredd Markets",
                )
            except Exception as e:
                logger.error("Failed to accept job", error=str(e))

    async def _reject_job(self, job: Any, reason: str):
        """Reject a job request."""
        if self._acp_client:
            try:
                job_id = getattr(job, "job_id", None) or getattr(job, "id", None)
                memo_id = getattr(job, "memo_id", None)
                await self._acp_client.respond_job(
                    job_id=job_id,
                    memo_id=memo_id,
                    accept=False,
                    reason=reason,
                )
            except Exception as e:
                logger.error("Failed to reject job", error=str(e))

    async def _deliver_job(self, job: Any, deliverable: dict[str, Any]):
        """Deliver job results."""
        if self._acp_client:
            try:
                job_id = getattr(job, "job_id", None) or getattr(job, "id", None)
                await self._acp_client.deliver_job(
                    job_id=job_id,
                    deliverable=deliverable,
                )
            except Exception as e:
                logger.error("Failed to deliver job", error=str(e))

    def get_job_offerings(self) -> list[dict[str, Any]]:
        """Get all job offerings for registration."""
        return [
            {
                "name": schema["name"],
                "description": schema["description"],
                "price_usdc": schema["price_usdc"],
                "price_type": schema.get("price_type", "fixed"),
                "job_type": schema.get("job_type", "service"),
                "service_requirements": schema["service_requirements"],
                "deliverable_requirements": schema["deliverable_requirements"],
            }
            for schema in JOB_OFFERINGS.values()
        ]

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @property
    def is_listening(self) -> bool:
        return self._listening


# Singleton instance
acp_service = SpreddACPService()
