"""Provider factory — creates the configured StockDataProvider.

Resolution order for the provider name:
    1. Explicit `name` argument passed to create_provider()
    2. STOCK_DATA_PROVIDER environment variable  (via Settings)
    3. Default: "twstock"

Resolution order for the FinMind token:
    1. Explicit `finmind_token` argument
    2. FINMIND_API_TOKEN environment variable  (via Settings)
    3. None — unauthenticated / rate-limited
"""

import logging
from typing import Literal, Optional

from tw_stock_mcp.providers.base import StockDataProvider

logger = logging.getLogger("tw-stock-agent.providers.factory")

ProviderName = Literal["twstock", "finmind"]


def create_provider(
    name: Optional[ProviderName] = None,
    finmind_token: Optional[str] = None,
) -> StockDataProvider:
    """Instantiate and return the configured StockDataProvider.

    Args:
        name: Provider identifier. If None, read from Settings /
              STOCK_DATA_PROVIDER env var.  Defaults to "twstock".
        finmind_token: FinMind API token. If None, read from Settings /
                       FINMIND_API_TOKEN env var.

    Returns:
        An object that satisfies the StockDataProvider Protocol.

    Raises:
        ValueError: Unknown provider name.
    """
    # Lazy import to avoid loading settings / provider deps at module load time
    from tw_stock_mcp.utils.config import get_settings

    settings = get_settings()
    provider_name: str = name or settings.STOCK_DATA_PROVIDER

    logger.info("Creating stock data provider: %s", provider_name)

    if provider_name == "twstock":
        from tw_stock_mcp.providers.twstock_provider import TwstockProvider

        return TwstockProvider()

    if provider_name == "finmind":
        from tw_stock_mcp.providers.finmind_provider import FinMindProvider

        token = finmind_token or settings.FINMIND_API_TOKEN
        if not token:
            logger.warning(
                "FinMind provider selected but FINMIND_API_TOKEN is not set. "
                "Requests will be unauthenticated and rate-limited."
            )
        return FinMindProvider(api_token=token)

    raise ValueError(
        f"Unknown stock data provider: {provider_name!r}. "
        "Valid values: 'twstock', 'finmind'."
    )
