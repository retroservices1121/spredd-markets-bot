"""
PnL Card Image Generation Service.
Generates branded PnL cards for sharing on social media.
"""

from io import BytesIO
from decimal import Decimal
from dataclasses import dataclass
from typing import Optional, Tuple
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from src.db.models import Platform
from src.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class PnLStats:
    """Data class for PnL statistics."""
    platform: Platform
    platform_name: str
    platform_emoji: str
    total_pnl: Decimal
    trade_count: int
    total_invested: Decimal

    @property
    def roi_percent(self) -> float:
        """Calculate ROI percentage."""
        if self.total_invested == 0:
            return 0.0
        return float((self.total_pnl / self.total_invested) * 100)

    @property
    def is_profit(self) -> bool:
        """Check if PnL is positive."""
        return self.total_pnl >= 0


class PnLCardGenerator:
    """Generates PnL card images."""

    CARD_WIDTH = 800
    CARD_HEIGHT = 500

    # Unified color theme - Black background with orange accent
    THEME = {
        "background": (13, 13, 13),       # #0D0D0D - Black
        "secondary": (26, 26, 26),        # #1A1A1A - Dark gray for boxes
        "accent": (249, 115, 22),         # #F97316 - Orange
        "text": (255, 255, 255),          # #FFFFFF - White
        "muted": (156, 163, 175),         # #9CA3AF - Gray
        "profit": (0, 255, 136),          # #00FF88 - Green
        "loss": (255, 71, 87),            # #FF4757 - Red
    }

    def __init__(self, assets_path: Path):
        self.assets_path = assets_path
        self.logo = self._load_logo()

    def _load_logo(self) -> Optional[Image.Image]:
        """Load the Spredd logo."""
        logo_path = self.assets_path / "spredd_logo.png"
        if logo_path.exists():
            try:
                logo = Image.open(logo_path).convert("RGBA")
                # Resize to fit in corner (max height 60px)
                max_height = 60
                if logo.height > max_height:
                    ratio = max_height / logo.height
                    new_size = (int(logo.width * ratio), max_height)
                    logo = logo.resize(new_size, Image.Resampling.LANCZOS)
                return logo
            except Exception as e:
                logger.warning("Failed to load logo", error=str(e))
        return None

    def _get_font(self, size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
        """Get a font at the specified size."""
        # Try common font paths
        font_paths = []

        if bold:
            font_paths = [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                "C:/Windows/Fonts/arialbd.ttf",
                "/System/Library/Fonts/Helvetica.ttc",
            ]
        else:
            font_paths = [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
                "C:/Windows/Fonts/arial.ttf",
                "/System/Library/Fonts/Helvetica.ttc",
            ]

        for path in font_paths:
            try:
                if Path(path).exists():
                    return ImageFont.truetype(path, size)
            except (OSError, IOError):
                continue

        # Fallback to default
        try:
            return ImageFont.load_default(size)
        except TypeError:
            return ImageFont.load_default()

    def generate_card(self, stats: PnLStats) -> BytesIO:
        """Generate a PnL card image and return as BytesIO."""
        theme = self.THEME

        # Create image with black background
        img = Image.new("RGB", (self.CARD_WIDTH, self.CARD_HEIGHT), theme["background"])
        draw = ImageDraw.Draw(img)

        # Draw logo in top-left
        if self.logo:
            # Create a new image to paste logo with alpha
            img.paste(self.logo, (30, 25), self.logo if self.logo.mode == 'RGBA' else None)

        # Draw "ALL-TIME" label in top-right
        time_font = self._get_font(16, bold=True)
        draw.text(
            (self.CARD_WIDTH - 30, 35),
            "ALL-TIME",
            font=time_font,
            fill=theme["muted"],
            anchor="ra",
        )

        # Draw platform name with emoji
        platform_font = self._get_font(32, bold=True)
        platform_text = f"{stats.platform_emoji} {stats.platform_name.upper()}"
        draw.text(
            (self.CARD_WIDTH // 2, 100),
            platform_text,
            font=platform_font,
            fill=theme["text"],
            anchor="mm",
        )

        # Draw main P&L value
        pnl_font = self._get_font(72, bold=True)
        pnl_color = theme["profit"] if stats.is_profit else theme["loss"]
        pnl_sign = "+" if stats.is_profit else "-"
        pnl_value = abs(float(stats.total_pnl))
        pnl_text = f"{pnl_sign}${pnl_value:,.2f}"

        draw.text(
            (self.CARD_WIDTH // 2, 220),
            pnl_text,
            font=pnl_font,
            fill=pnl_color,
            anchor="mm",
        )

        # Draw stats boxes
        box_width = 180
        box_height = 70
        box_y = 320
        spacing = 40

        # Trade count box
        box1_x = (self.CARD_WIDTH // 2) - box_width - (spacing // 2)
        draw.rounded_rectangle(
            (box1_x, box_y, box1_x + box_width, box_y + box_height),
            radius=12,
            fill=theme["secondary"],
        )

        # Trade count text
        label_font = self._get_font(14, bold=False)
        value_font = self._get_font(24, bold=True)

        draw.text(
            (box1_x + box_width // 2, box_y + 20),
            "TRADES",
            font=label_font,
            fill=theme["muted"],
            anchor="mm",
        )
        draw.text(
            (box1_x + box_width // 2, box_y + 48),
            str(stats.trade_count),
            font=value_font,
            fill=theme["text"],
            anchor="mm",
        )

        # ROI box
        box2_x = (self.CARD_WIDTH // 2) + (spacing // 2)
        draw.rounded_rectangle(
            (box2_x, box_y, box2_x + box_width, box_y + box_height),
            radius=12,
            fill=theme["secondary"],
        )

        # ROI text
        roi_value = stats.roi_percent
        roi_sign = "+" if roi_value >= 0 else ""
        roi_color = theme["profit"] if roi_value >= 0 else theme["loss"]

        draw.text(
            (box2_x + box_width // 2, box_y + 20),
            "ROI",
            font=label_font,
            fill=theme["muted"],
            anchor="mm",
        )
        draw.text(
            (box2_x + box_width // 2, box_y + 48),
            f"{roi_sign}{roi_value:.1f}%",
            font=value_font,
            fill=roi_color,
            anchor="mm",
        )

        # Draw footer with URL
        footer_font = self._get_font(16, bold=False)
        draw.text(
            (self.CARD_WIDTH // 2, self.CARD_HEIGHT - 40),
            "spredd.markets",
            font=footer_font,
            fill=theme["muted"],
            anchor="mm",
        )

        # Draw orange accent line at bottom
        draw.rectangle(
            [(0, self.CARD_HEIGHT - 4), (self.CARD_WIDTH, self.CARD_HEIGHT)],
            fill=theme["accent"],
        )

        # Save to BytesIO
        buffer = BytesIO()
        img.save(buffer, format="PNG", quality=95)
        buffer.seek(0)
        return buffer


# Singleton instance
_generator: Optional[PnLCardGenerator] = None


def get_pnl_card_generator() -> PnLCardGenerator:
    """Get or create the PnL card generator singleton."""
    global _generator
    if _generator is None:
        assets_path = Path(__file__).parent.parent / "assets"
        assets_path.mkdir(exist_ok=True)
        _generator = PnLCardGenerator(assets_path)
    return _generator


def generate_pnl_card(
    platform: Platform,
    platform_name: str,
    platform_emoji: str,
    total_pnl: Decimal,
    trade_count: int,
    total_invested: Decimal,
) -> BytesIO:
    """
    Generate a PnL card for a specific platform.

    Args:
        platform: Platform enum value
        platform_name: Display name of the platform
        platform_emoji: Emoji for the platform
        total_pnl: Total realized P&L in USD
        trade_count: Number of trades
        total_invested: Total amount invested (for ROI calculation)

    Returns:
        BytesIO containing the PNG image
    """
    generator = get_pnl_card_generator()

    stats = PnLStats(
        platform=platform,
        platform_name=platform_name,
        platform_emoji=platform_emoji,
        total_pnl=total_pnl,
        trade_count=trade_count,
        total_invested=total_invested,
    )

    return generator.generate_card(stats)
