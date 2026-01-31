"""
ACP Client.

Main service that handles ACP SDK integration and job lifecycle.
Implements proper phase handling (REQUEST → TRANSACTION) per ACP v2 spec.
"""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Optional

import re

from src.utils.logging import get_logger
from src.config import settings
from src.services.acp.schemas import JobType, JOB_OFFERINGS, get_job_schema
from src.services.acp.handlers import acp_job_handler
from src.services.acp.wallet_manager import acp_wallet_manager

logger = get_logger(__name__)


def _normalize_job_type(job_type_str: str) -> str:
    """
    Normalize job type string from camelCase to snake_case.

    ACP butler sends camelCase (e.g., 'searchMarkets') but our
    internal schema uses snake_case (e.g., 'search_markets').
    """
    if not job_type_str:
        return ""
    # Convert camelCase to snake_case
    # e.g., 'searchMarkets' -> 'search_markets'
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', job_type_str)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()


class SpreddACPService:
    """
    Spredd's ACP Service Provider.

    Handles registration, job discovery, and job execution
    through the Virtuals ACP protocol.

    Job Flow (ACP v2):
    1. Buyer initiates job → on_new_task (phase=REQUEST)
    2. Seller evaluates and creates requirement → job.create_requirement() or job.create_payable_requirement()
    3. Buyer pays (for fund jobs) → on_new_task (phase=TRANSACTION)
    4. Seller executes and delivers → job.deliver() or job.deliver_payable()
    """

    def __init__(self):
        self._initialized = False
        self._acp_client = None
        self._listening = False
        self._job_queue: asyncio.Queue = asyncio.Queue()
        # Track pending jobs awaiting transaction phase
        self._pending_jobs: dict[str, dict] = {}

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
            # Import from correct path per ACP v2
            from virtuals_acp.client import VirtualsACP
            from virtuals_acp.config import BASE_MAINNET_ACP_CONFIG_V2, BASE_TESTNET_ACP_CONFIG_V2

            # Choose config based on environment
            if settings.acp_environment == "production":
                config = BASE_MAINNET_ACP_CONFIG_V2
            else:
                config = BASE_TESTNET_ACP_CONFIG_V2

            # Initialize the client with on_new_task callback
            self._acp_client = VirtualsACP(
                wallet_private_key=settings.acp_agent_wallet_private_key,
                agent_wallet_address=settings.acp_agent_wallet_address,
                entity_id=settings.acp_entity_id,
                config=config,
                on_new_task=self._on_new_task,
            )

            logger.info("ACP SDK client initialized (v2)")

        except ImportError as e:
            logger.warning(
                "virtuals-acp SDK not installed. Running in mock mode. "
                "Install with: pip install virtuals-acp",
                error=str(e)
            )
            self._acp_client = None

        except Exception as e:
            logger.error("Failed to initialize ACP SDK", error=str(e))
            raise

    async def _on_new_task(self, job: Any):
        """
        Callback when a new job/task is received.
        Routes based on job phase (REQUEST or TRANSACTION).
        """
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

                # Process based on phase
                await self._handle_job_by_phase(job)

            except Exception as e:
                logger.error("Job processing error", error=str(e))
                await asyncio.sleep(1)

    async def _handle_job_by_phase(self, job: Any):
        """Handle a job based on its current phase."""
        try:
            # Extract job details
            job_id = getattr(job, "id", None) or getattr(job, "job_id", "unknown")
            phase = getattr(job, "phase", "REQUEST")
            job_type_str = getattr(job, "offering_name", None) or getattr(job, "job_type", "")

            # Handle as string or enum
            if hasattr(phase, "value"):
                phase = phase.value
            phase = str(phase).upper()

            # Normalize for logging
            normalized_type = _normalize_job_type(job_type_str)
            logger.info(
                "Processing ACP job",
                job_id=job_id,
                phase=phase,
                job_type=job_type_str,
                normalized_type=normalized_type,
            )

            if phase == "REQUEST":
                await self._handle_request_phase(job)
            elif phase == "TRANSACTION":
                await self._handle_transaction_phase(job)
            elif phase == "EVALUATION":
                # Self-evaluation: auto-accept delivery
                await self._handle_evaluation_phase(job)
            else:
                logger.warning(f"Unknown job phase: {phase}", job_id=job_id)

        except Exception as e:
            logger.error("Job phase handling failed", error=str(e))
            await self._reject_job(job, str(e))

    async def _handle_request_phase(self, job: Any):
        """
        Handle REQUEST phase: evaluate the job and create requirements.
        For fund transfer jobs, create payable requirements.
        For service jobs, create regular requirements.
        """
        job_id = getattr(job, "id", None) or getattr(job, "job_id", "unknown")
        job_type_str = getattr(job, "offering_name", None) or getattr(job, "job_type", "")
        service_req = getattr(job, "service_requirements", {}) or getattr(job, "requirements", {})
        client_address = getattr(job, "client_address", None) or getattr(job, "buyer_agent_id", "")

        # Normalize job type (camelCase -> snake_case)
        normalized_job_type = _normalize_job_type(job_type_str)

        # Map to our job type
        try:
            job_type = JobType(normalized_job_type)
        except ValueError:
            # Try original string as fallback
            try:
                job_type = JobType(job_type_str)
            except ValueError:
                await self._reject_job(job, f"Unknown job type: {job_type_str}")
                return

        # Get job schema to determine if it's a fund transfer job
        schema = get_job_schema(job_type)
        is_fund_job = schema.get("job_type") == "fund_transfer"

        # Validate requirements
        from src.services.acp.schemas import validate_service_requirements
        is_valid, error = validate_service_requirements(job_type, service_req)
        if not is_valid:
            await self._reject_job(job, error)
            return

        # Store job info for transaction phase
        self._pending_jobs[str(job_id)] = {
            "job_type": job_type,
            "service_req": service_req,
            "client_address": client_address,
        }

        try:
            if is_fund_job:
                # For fund transfer jobs, create payable requirement
                amount = Decimal(str(service_req.get("amount", 0)))
                description = f"Spredd Markets: {job_type.value} for ${amount}"

                # Use job's create_payable_requirement if available
                if hasattr(job, "create_payable_requirement"):
                    from virtuals_acp.memo import MemoType
                    # Import FareAmount if available
                    try:
                        from virtuals_acp.fare import FareAmount
                        fare = FareAmount(float(amount), None)
                    except ImportError:
                        fare = float(amount)

                    await job.create_payable_requirement(
                        content=description,
                        memo_type=MemoType.PAYABLE_REQUEST,
                        amount=fare,
                        recipient=settings.acp_agent_wallet_address,
                    )
                    logger.info("Created payable requirement", job_id=job_id, amount=amount)
                else:
                    # Fallback: accept job for service-style flow
                    await self._accept_job(job, f"Ready to execute {job_type.value}")
            else:
                # For service jobs, create regular requirement (auto-proceeds to transaction)
                if hasattr(job, "create_requirement"):
                    await job.create_requirement(
                        content=f"Spredd Markets: Processing {job_type.value} request"
                    )
                else:
                    await self._accept_job(job, f"Processing {job_type.value}")

        except Exception as e:
            logger.error("Failed to create requirement", job_id=job_id, error=str(e))
            await self._reject_job(job, str(e))

    async def _handle_transaction_phase(self, job: Any):
        """
        Handle TRANSACTION phase: execute the job and deliver results.
        This is called after buyer has paid (for fund jobs).
        """
        job_id = getattr(job, "id", None) or getattr(job, "job_id", "unknown")

        # Get stored job info
        job_info = self._pending_jobs.get(str(job_id))
        if not job_info:
            # Try to extract from job object itself
            job_type_str = getattr(job, "offering_name", None) or getattr(job, "job_type", "")
            service_req = getattr(job, "service_requirements", {}) or getattr(job, "requirements", {})
            client_address = getattr(job, "client_address", None) or getattr(job, "buyer_agent_id", "unknown")

            # Normalize job type (camelCase -> snake_case)
            normalized_job_type = _normalize_job_type(job_type_str)

            try:
                job_type = JobType(normalized_job_type)
            except ValueError:
                # Try original string as fallback
                try:
                    job_type = JobType(job_type_str)
                except ValueError:
                    await self._reject_job(job, f"Unknown job type: {job_type_str}")
                    return

            job_info = {
                "job_type": job_type,
                "service_req": service_req,
                "client_address": client_address,
            }

        job_type = job_info["job_type"]
        service_req = job_info["service_req"]
        agent_id = job_info["client_address"]

        # Get schema to check if fund job
        schema = get_job_schema(job_type)
        is_fund_job = schema.get("job_type") == "fund_transfer"

        try:
            # Execute the job
            deliverable = await acp_job_handler.handle_job(
                job_type=job_type,
                agent_id=agent_id,
                service_requirements=service_req,
            )

            # Deliver the result
            if is_fund_job and hasattr(job, "deliver_payable"):
                # For fund jobs, use deliver_payable
                success = deliverable.get("success", False)
                if success:
                    await job.deliver_payable(
                        deliverable=deliverable,
                        amount=0,  # No additional payment on delivery
                        skip_fee=True,
                    )
                else:
                    # Refund on failure
                    if hasattr(job, "reject_payable"):
                        amount = Decimal(str(service_req.get("amount", 0)))
                        await job.reject_payable(
                            reason=deliverable.get("error", "Job failed"),
                            amount=float(amount),
                        )
                    else:
                        await job.deliver(deliverable=deliverable)
            else:
                # For service jobs, use regular deliver
                if hasattr(job, "deliver"):
                    await job.deliver(deliverable=deliverable)
                else:
                    await self._deliver_job(job, deliverable)

            # Clean up pending job
            self._pending_jobs.pop(str(job_id), None)

            logger.info(
                "ACP job completed",
                job_id=job_id,
                success=deliverable.get("success", True),
            )

        except Exception as e:
            logger.error("Job execution failed", job_id=job_id, error=str(e))

            # Try to refund for fund jobs
            if is_fund_job and hasattr(job, "reject_payable"):
                try:
                    amount = Decimal(str(service_req.get("amount", 0)))
                    await job.reject_payable(reason=str(e), amount=float(amount))
                except Exception as refund_err:
                    logger.error("Refund failed", error=str(refund_err))
            else:
                await self._reject_job(job, str(e))

    async def _handle_evaluation_phase(self, job: Any):
        """Handle EVALUATION phase for self-evaluation jobs."""
        job_id = getattr(job, "id", None) or getattr(job, "job_id", "unknown")

        try:
            if hasattr(job, "evaluate"):
                # Auto-accept our own delivery (self-evaluation)
                await job.evaluate(accept=True, reason="Delivery accepted by Spredd Markets")
                logger.info("Self-evaluated job", job_id=job_id)
        except Exception as e:
            logger.error("Evaluation failed", job_id=job_id, error=str(e))

    async def _accept_job(self, job: Any, reason: str = "Job accepted"):
        """Accept an incoming job request."""
        if hasattr(job, "respond"):
            try:
                await job.respond(accept=True, reason=reason)
            except Exception as e:
                logger.error("Failed to accept job via respond", error=str(e))
        elif self._acp_client:
            try:
                job_id = getattr(job, "id", None) or getattr(job, "job_id", None)
                memo_id = getattr(job, "memo_id", None)
                await self._acp_client.respond_job(
                    job_id=job_id,
                    memo_id=memo_id,
                    accept=True,
                    reason=reason,
                )
            except Exception as e:
                logger.error("Failed to accept job", error=str(e))

    async def _reject_job(self, job: Any, reason: str):
        """Reject a job request."""
        if hasattr(job, "respond"):
            try:
                await job.respond(accept=False, reason=reason)
            except Exception as e:
                logger.error("Failed to reject job via respond", error=str(e))
        elif hasattr(job, "reject"):
            try:
                await job.reject(reason=reason)
            except Exception as e:
                logger.error("Failed to reject job", error=str(e))
        elif self._acp_client:
            try:
                job_id = getattr(job, "id", None) or getattr(job, "job_id", None)
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
        """Deliver job results (fallback method)."""
        if self._acp_client:
            try:
                job_id = getattr(job, "id", None) or getattr(job, "job_id", None)
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
