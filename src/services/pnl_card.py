"""
PnL Card Image Generation Service.
Generates branded PnL cards for sharing on social media.
"""

from io import BytesIO
from decimal import Decimal
from dataclasses import dataclass
from typing import Optional, Tuple
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter

from src.db.models import Platform
from src.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class PnLStats:
    """Data class for PnL statistics."""
    platform: Platform
    platform_name: str
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


@dataclass
class PositionWinStats:
    """Data class for individual winning position."""
    platform: Platform
    platform_name: str
    market_title: str
    outcome: str  # "YES" or "NO"
    profit_amount: Decimal
    profit_percent: float
    entry_price: Decimal
    exit_price: Decimal


class PnLCardGenerator:
    """Generates premium PnL card images."""

    CARD_WIDTH = 800
    CARD_HEIGHT = 500

    # Premium color theme
    THEME = {
        "background": (8, 8, 12),          # Near black with slight blue
        "card_bg": (16, 16, 22),            # Slightly lighter for card
        "accent": (234, 110, 20),            # #EA6E14 - Orange
        "accent_glow": (249, 115, 22, 80),  # Orange with alpha for glow
        "text": (255, 255, 255),            # #FFFFFF - White
        "text_secondary": (180, 180, 190),  # Light gray
        "muted": (100, 100, 110),           # Muted gray
        "profit": (16, 185, 129),           # #10B981 - Emerald green
        "profit_glow": (16, 185, 129, 60),  # Green with alpha
        "loss": (239, 68, 68),              # #EF4444 - Red
        "loss_glow": (239, 68, 68, 60),     # Red with alpha
        "stat_box": (24, 24, 32),           # Dark box background
        "stat_box_border": (40, 40, 50),    # Subtle border
    }

    def __init__(self, assets_path: Path):
        self.assets_path = assets_path
        self.logo = self._load_logo()
        self.custom_bg = self._load_custom_background()

    def _load_custom_background(self) -> Optional[Image.Image]:
        """Load custom background image if it exists."""
        bg_path = self.assets_path / "pnl_card_bg.png"
        if not bg_path.exists():
            bg_path = self.assets_path / "pnl_card_bg.jpg"

        if bg_path.exists():
            try:
                bg = Image.open(bg_path).convert("RGBA")
                # Resize to card dimensions if needed
                if bg.size != (self.CARD_WIDTH, self.CARD_HEIGHT):
                    bg = bg.resize((self.CARD_WIDTH, self.CARD_HEIGHT), Image.Resampling.LANCZOS)
                logger.info("Loaded custom background", path=str(bg_path))
                return bg
            except Exception as e:
                logger.warning("Failed to load custom background", error=str(e))
        return None

    def _load_logo(self) -> Optional[Image.Image]:
        """Load the Spredd logo."""
        logo_path = self.assets_path / "spredd_logo.png"
        if logo_path.exists():
            try:
                logo = Image.open(logo_path).convert("RGBA")
                # Resize to fit nicely (max height 80px for premium look)
                max_height = 80
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

        try:
            return ImageFont.load_default(size)
        except TypeError:
            return ImageFont.load_default()

    def _draw_rounded_rect(
        self,
        draw: ImageDraw.ImageDraw,
        coords: Tuple[int, int, int, int],
        radius: int,
        fill: Tuple[int, ...],
        outline: Optional[Tuple[int, ...]] = None,
        outline_width: int = 1,
    ) -> None:
        """Draw a rounded rectangle with optional outline."""
        x1, y1, x2, y2 = coords
        draw.rounded_rectangle(coords, radius=radius, fill=fill)
        if outline:
            draw.rounded_rectangle(
                coords, radius=radius, fill=None, outline=outline, width=outline_width
            )

    def _create_glow_layer(
        self, text: str, font: ImageFont.FreeTypeFont, color: Tuple[int, ...], blur_radius: int = 15
    ) -> Image.Image:
        """Create a glow effect layer for text."""
        # Get text bounding box
        bbox = font.getbbox(text)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        # Create larger canvas for glow
        padding = blur_radius * 3
        glow_img = Image.new(
            "RGBA",
            (text_width + padding * 2, text_height + padding * 2),
            (0, 0, 0, 0),
        )
        glow_draw = ImageDraw.Draw(glow_img)

        # Draw text in glow color
        glow_color = (*color[:3], 120) if len(color) == 3 else color
        glow_draw.text((padding, padding - bbox[1]), text, font=font, fill=glow_color)

        # Apply blur
        glow_img = glow_img.filter(ImageFilter.GaussianBlur(radius=blur_radius))

        return glow_img

    def generate_card(self, stats: PnLStats) -> BytesIO:
        """Generate a premium PnL card image and return as BytesIO."""
        theme = self.THEME

        # Use custom background if available, otherwise generate default
        if self.custom_bg:
            img = self.custom_bg.copy()
            draw = ImageDraw.Draw(img)
            using_custom_bg = True
        else:
            # Create base image with default design
            img = Image.new("RGBA", (self.CARD_WIDTH, self.CARD_HEIGHT), theme["background"])
            draw = ImageDraw.Draw(img)
            using_custom_bg = False

            # Draw subtle gradient overlay (darker at edges)
            for i in range(self.CARD_HEIGHT):
                alpha = int(20 * (1 - abs(i - self.CARD_HEIGHT / 2) / (self.CARD_HEIGHT / 2)))
                draw.line([(0, i), (self.CARD_WIDTH, i)], fill=(*theme["card_bg"], alpha))

            # Draw main card area with subtle border
            card_margin = 20
            self._draw_rounded_rect(
                draw,
                (card_margin, card_margin, self.CARD_WIDTH - card_margin, self.CARD_HEIGHT - card_margin),
                radius=16,
                fill=theme["card_bg"],
                outline=theme["stat_box_border"],
                outline_width=1,
            )

            # Draw orange accent line at top of card
            accent_y = card_margin
            draw.rounded_rectangle(
                (card_margin, accent_y, self.CARD_WIDTH - card_margin, accent_y + 4),
                radius=2,
                fill=theme["accent"],
            )

        # Draw logo and badge only if not using custom background
        if not using_custom_bg:
            logo_x = 45
            logo_y = 40
            if self.logo:
                img.paste(self.logo, (logo_x, logo_y), self.logo if self.logo.mode == "RGBA" else None)

            # Draw "ALL-TIME" badge in top-right
            badge_font = self._get_font(12, bold=True)
            badge_text = "ALL-TIME"
            badge_bbox = badge_font.getbbox(badge_text)
            badge_width = badge_bbox[2] - badge_bbox[0] + 20
            badge_height = 24
            badge_x = self.CARD_WIDTH - 20 - badge_width - 25
            badge_y = 45

            self._draw_rounded_rect(
                draw,
                (badge_x, badge_y, badge_x + badge_width, badge_y + badge_height),
                radius=4,
                fill=theme["stat_box"],
                outline=theme["stat_box_border"],
            )
            draw.text(
                (badge_x + badge_width // 2, badge_y + badge_height // 2),
                badge_text,
                font=badge_font,
                fill=theme["muted"],
                anchor="mm",
            )

        # Draw platform name (large, centered)
        platform_font = self._get_font(36, bold=True)
        platform_text = stats.platform_name.upper()
        draw.text(
            (self.CARD_WIDTH // 2, 130),
            platform_text,
            font=platform_font,
            fill=theme["text"],
            anchor="mm",
        )

        # Draw "PROFIT & LOSS" label in orange
        label_font = self._get_font(14, bold=False)
        draw.text(
            (self.CARD_WIDTH // 2, 170),
            "PROFIT & LOSS",
            font=label_font,
            fill=theme["accent"],
            anchor="mm",
        )

        # Main P&L value with glow effect
        pnl_font = self._get_font(64, bold=True)
        pnl_color = theme["profit"] if stats.is_profit else theme["loss"]
        pnl_sign = "+" if stats.is_profit else "-"
        pnl_value = abs(float(stats.total_pnl))
        pnl_text = f"{pnl_sign}${pnl_value:,.2f}"

        # Create and paste glow
        glow_color = theme["profit"] if stats.is_profit else theme["loss"]
        glow_layer = self._create_glow_layer(pnl_text, pnl_font, glow_color, blur_radius=20)

        # Calculate position for glow
        pnl_bbox = pnl_font.getbbox(pnl_text)
        pnl_width = pnl_bbox[2] - pnl_bbox[0]
        glow_x = (self.CARD_WIDTH - glow_layer.width) // 2
        glow_y = 210 - glow_layer.height // 2

        img.paste(glow_layer, (glow_x, glow_y), glow_layer)

        # Draw P&L text on top
        draw = ImageDraw.Draw(img)  # Refresh draw object after paste
        draw.text(
            (self.CARD_WIDTH // 2, 230),
            pnl_text,
            font=pnl_font,
            fill=pnl_color,
            anchor="mm",
        )

        # Stats boxes - only draw boxes if not using custom background
        box_width = 160
        box_height = 80
        box_y = 320
        box_spacing = 30
        total_boxes_width = box_width * 2 + box_spacing
        box1_x = (self.CARD_WIDTH - total_boxes_width) // 2

        if not using_custom_bg:
            # Trade count box
            self._draw_rounded_rect(
                draw,
                (box1_x, box_y, box1_x + box_width, box_y + box_height),
                radius=12,
                fill=theme["stat_box"],
                outline=theme["stat_box_border"],
            )

        stat_label_font = self._get_font(12, bold=False)
        stat_value_font = self._get_font(28, bold=True)

        draw.text(
            (box1_x + box_width // 2, box_y + 25),
            "TRADES",
            font=stat_label_font,
            fill=theme["accent"],
            anchor="mm",
        )
        draw.text(
            (box1_x + box_width // 2, box_y + 55),
            str(stats.trade_count),
            font=stat_value_font,
            fill=theme["text"],
            anchor="mm",
        )

        # ROI box
        box2_x = box1_x + box_width + box_spacing
        if not using_custom_bg:
            self._draw_rounded_rect(
                draw,
                (box2_x, box_y, box2_x + box_width, box_y + box_height),
                radius=12,
                fill=theme["stat_box"],
                outline=theme["stat_box_border"],
            )

        roi_value = stats.roi_percent
        roi_sign = "+" if roi_value >= 0 else ""
        roi_color = theme["profit"] if roi_value >= 0 else theme["loss"]

        draw.text(
            (box2_x + box_width // 2, box_y + 25),
            "ROI",
            font=stat_label_font,
            fill=theme["accent"],
            anchor="mm",
        )
        draw.text(
            (box2_x + box_width // 2, box_y + 55),
            f"{roi_sign}{roi_value:.1f}%",
            font=stat_value_font,
            fill=roi_color,
            anchor="mm",
        )

        # Footer - only if not using custom background
        if not using_custom_bg:
            footer_font = self._get_font(14, bold=False)
            draw.text(
                (self.CARD_WIDTH // 2, self.CARD_HEIGHT - 45),
                "spredd.markets",
                font=footer_font,
                fill=theme["muted"],
                anchor="mm",
            )

        # Convert to RGB for PNG save (remove alpha)
        img_rgb = Image.new("RGB", img.size, theme["background"])
        img_rgb.paste(img, mask=img.split()[3] if img.mode == "RGBA" else None)

        # Save to BytesIO
        buffer = BytesIO()
        img_rgb.save(buffer, format="PNG", quality=95)
        buffer.seek(0)
        return buffer

    def generate_position_win_card(self, stats: PositionWinStats) -> BytesIO:
        """Generate a winning position card image and return as BytesIO."""
        theme = self.THEME

        # Use custom background if available, otherwise generate default
        if self.custom_bg:
            img = self.custom_bg.copy()
            draw = ImageDraw.Draw(img)
            using_custom_bg = True
        else:
            # Create base image with default design
            img = Image.new("RGBA", (self.CARD_WIDTH, self.CARD_HEIGHT), theme["background"])
            draw = ImageDraw.Draw(img)
            using_custom_bg = False

            # Draw subtle gradient overlay
            for i in range(self.CARD_HEIGHT):
                alpha = int(20 * (1 - abs(i - self.CARD_HEIGHT / 2) / (self.CARD_HEIGHT / 2)))
                draw.line([(0, i), (self.CARD_WIDTH, i)], fill=(*theme["card_bg"], alpha))

            # Draw main card area with subtle border
            card_margin = 20
            self._draw_rounded_rect(
                draw,
                (card_margin, card_margin, self.CARD_WIDTH - card_margin, self.CARD_HEIGHT - card_margin),
                radius=16,
                fill=theme["card_bg"],
                outline=theme["stat_box_border"],
                outline_width=1,
            )

            # Draw green accent line at top for winning position
            accent_y = card_margin
            draw.rounded_rectangle(
                (card_margin, accent_y, self.CARD_WIDTH - card_margin, accent_y + 4),
                radius=2,
                fill=theme["profit"],
            )

        # Draw logo if not using custom background
        if not using_custom_bg:
            logo_x = 45
            logo_y = 40
            if self.logo:
                img.paste(self.logo, (logo_x, logo_y), self.logo if self.logo.mode == "RGBA" else None)

            # Draw "WINNER" badge in top-right
            badge_font = self._get_font(12, bold=True)
            badge_text = "WINNER"
            badge_bbox = badge_font.getbbox(badge_text)
            badge_width = badge_bbox[2] - badge_bbox[0] + 20
            badge_height = 24
            badge_x = self.CARD_WIDTH - 20 - badge_width - 25
            badge_y = 45

            self._draw_rounded_rect(
                draw,
                (badge_x, badge_y, badge_x + badge_width, badge_y + badge_height),
                radius=4,
                fill=theme["profit"],
            )
            draw.text(
                (badge_x + badge_width // 2, badge_y + badge_height // 2),
                badge_text,
                font=badge_font,
                fill=theme["text"],
                anchor="mm",
            )

        # Draw platform name
        platform_font = self._get_font(18, bold=True)
        draw.text(
            (self.CARD_WIDTH // 2, 100),
            stats.platform_name.upper(),
            font=platform_font,
            fill=theme["muted"],
            anchor="mm",
        )

        # Draw market title (wrapped if too long)
        title_font = self._get_font(24, bold=True)
        market_title = stats.market_title

        # Wrap title if too long
        max_chars_per_line = 40
        if len(market_title) > max_chars_per_line:
            # Split into multiple lines
            words = market_title.split()
            lines = []
            current_line = ""
            for word in words:
                if len(current_line + " " + word) <= max_chars_per_line:
                    current_line = (current_line + " " + word).strip()
                else:
                    if current_line:
                        lines.append(current_line)
                    current_line = word
            if current_line:
                lines.append(current_line)

            # Limit to 2 lines max
            if len(lines) > 2:
                lines = lines[:2]
                lines[1] = lines[1][:max_chars_per_line - 3] + "..."

            y_offset = 140
            for line in lines:
                draw.text(
                    (self.CARD_WIDTH // 2, y_offset),
                    line,
                    font=title_font,
                    fill=theme["text"],
                    anchor="mm",
                )
                y_offset += 30
        else:
            draw.text(
                (self.CARD_WIDTH // 2, 150),
                market_title,
                font=title_font,
                fill=theme["text"],
                anchor="mm",
            )

        # Draw outcome badge (YES/NO)
        outcome_font = self._get_font(14, bold=True)
        outcome_text = stats.outcome.upper()
        outcome_color = theme["profit"] if stats.outcome.upper() == "YES" else theme["loss"]

        outcome_bbox = outcome_font.getbbox(outcome_text)
        outcome_width = outcome_bbox[2] - outcome_bbox[0] + 16
        outcome_height = 22
        outcome_x = (self.CARD_WIDTH - outcome_width) // 2
        outcome_y = 195

        self._draw_rounded_rect(
            draw,
            (outcome_x, outcome_y, outcome_x + outcome_width, outcome_y + outcome_height),
            radius=4,
            fill=outcome_color,
        )
        draw.text(
            (outcome_x + outcome_width // 2, outcome_y + outcome_height // 2),
            outcome_text,
            font=outcome_font,
            fill=theme["text"],
            anchor="mm",
        )

        # Main profit percentage with glow effect
        profit_font = self._get_font(72, bold=True)
        profit_text = f"+{stats.profit_percent:.1f}%"

        # Create and paste glow
        glow_layer = self._create_glow_layer(profit_text, profit_font, theme["profit"], blur_radius=25)
        glow_x = (self.CARD_WIDTH - glow_layer.width) // 2
        glow_y = 240 - glow_layer.height // 2

        img.paste(glow_layer, (glow_x, glow_y), glow_layer)

        # Draw profit text on top
        draw = ImageDraw.Draw(img)
        draw.text(
            (self.CARD_WIDTH // 2, 270),
            profit_text,
            font=profit_font,
            fill=theme["profit"],
            anchor="mm",
        )

        # Draw profit amount
        amount_font = self._get_font(28, bold=True)
        amount_text = f"+${float(stats.profit_amount):,.2f}"
        draw.text(
            (self.CARD_WIDTH // 2, 340),
            amount_text,
            font=amount_font,
            fill=theme["profit"],
            anchor="mm",
        )

        # Stats boxes for entry/exit prices
        if not using_custom_bg:
            box_width = 160
            box_height = 65
            box_y = 380
            box_spacing = 30
            total_boxes_width = box_width * 2 + box_spacing
            box1_x = (self.CARD_WIDTH - total_boxes_width) // 2

            # Entry price box
            self._draw_rounded_rect(
                draw,
                (box1_x, box_y, box1_x + box_width, box_y + box_height),
                radius=12,
                fill=theme["stat_box"],
                outline=theme["stat_box_border"],
            )

            stat_label_font = self._get_font(11, bold=False)
            stat_value_font = self._get_font(22, bold=True)

            draw.text(
                (box1_x + box_width // 2, box_y + 20),
                "ENTRY",
                font=stat_label_font,
                fill=theme["muted"],
                anchor="mm",
            )
            draw.text(
                (box1_x + box_width // 2, box_y + 45),
                f"{float(stats.entry_price) * 100:.1f}¢",
                font=stat_value_font,
                fill=theme["text"],
                anchor="mm",
            )

            # Exit price box
            box2_x = box1_x + box_width + box_spacing
            self._draw_rounded_rect(
                draw,
                (box2_x, box_y, box2_x + box_width, box_y + box_height),
                radius=12,
                fill=theme["stat_box"],
                outline=theme["stat_box_border"],
            )

            draw.text(
                (box2_x + box_width // 2, box_y + 20),
                "EXIT",
                font=stat_label_font,
                fill=theme["muted"],
                anchor="mm",
            )
            draw.text(
                (box2_x + box_width // 2, box_y + 45),
                f"{float(stats.exit_price) * 100:.1f}¢",
                font=stat_value_font,
                fill=theme["profit"],
                anchor="mm",
            )

        # Footer
        if not using_custom_bg:
            footer_font = self._get_font(14, bold=False)
            draw.text(
                (self.CARD_WIDTH // 2, self.CARD_HEIGHT - 35),
                "spredd.markets",
                font=footer_font,
                fill=theme["muted"],
                anchor="mm",
            )

        # Convert to RGB for PNG save
        img_rgb = Image.new("RGB", img.size, theme["background"])
        img_rgb.paste(img, mask=img.split()[3] if img.mode == "RGBA" else None)

        # Save to BytesIO
        buffer = BytesIO()
        img_rgb.save(buffer, format="PNG", quality=95)
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
        platform_emoji: Emoji for the platform (unused, kept for compatibility)
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
        total_pnl=total_pnl,
        trade_count=trade_count,
        total_invested=total_invested,
    )

    return generator.generate_card(stats)


def generate_position_win_card(
    platform: Platform,
    platform_name: str,
    market_title: str,
    outcome: str,
    profit_amount: Decimal,
    profit_percent: float,
    entry_price: Decimal,
    exit_price: Decimal,
) -> BytesIO:
    """
    Generate a winning position card for sharing.

    Args:
        platform: Platform enum value
        platform_name: Display name of the platform
        market_title: Title of the market
        outcome: "YES" or "NO"
        profit_amount: Profit in USD
        profit_percent: Profit percentage (e.g., 150.0 for +150%)
        entry_price: Entry price (0-1 scale)
        exit_price: Exit price (0-1 scale, typically 1.0 for winners)

    Returns:
        BytesIO containing the PNG image
    """
    generator = get_pnl_card_generator()

    stats = PositionWinStats(
        platform=platform,
        platform_name=platform_name,
        market_title=market_title,
        outcome=outcome,
        profit_amount=profit_amount,
        profit_percent=profit_percent,
        entry_price=entry_price,
        exit_price=exit_price,
    )

    return generator.generate_position_win_card(stats)
