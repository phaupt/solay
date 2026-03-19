#!/usr/bin/env python3
"""Standalone IT8951 hardware validation script.

Usage:
    python scripts/epaper_test.py --vcom -1.48                    # clear display (white)
    python scripts/epaper_test.py --vcom -1.48 --image test.png   # show a PNG
    python scripts/epaper_test.py --vcom -1.48 --partial           # test partial DU update
    python scripts/epaper_test.py --vcom -1.48 --sleep-wake        # test sleep/wake cycle
"""

import argparse
import sys
import time
from pathlib import Path

# Add repo root to sys.path so project imports work if needed.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from IT8951.display import AutoEPDDisplay
    from IT8951 import constants
except ImportError:
    print(
        "ERROR: IT8951 library not found.\n"
        "Install it from source:\n"
        "  git clone https://github.com/GregDMeyer/IT8951.git\n"
        "  pip install ./IT8951[rpi]\n"
    )
    sys.exit(1)

from PIL import Image


def get_display(vcom: float) -> AutoEPDDisplay:
    """Initialize and return the e-paper display."""
    print(f"Initializing display with VCOM={vcom} ...")
    display = AutoEPDDisplay(vcom=vcom)
    width = display.width
    height = display.height
    print(f"Display ready: {width}x{height}")
    return display


def clear_display(display: AutoEPDDisplay) -> None:
    """Clear the display to white using GC16."""
    print("Clearing display to white ...")
    display.clear()
    print("Display cleared.")


def show_image(display: AutoEPDDisplay, image_path: str) -> None:
    """Load a PNG, convert to grayscale, resize to display, show via GC16."""
    print(f"Loading image: {image_path}")
    img = Image.open(image_path).convert("L")
    img = img.resize((display.width, display.height))
    print(f"Resized to {display.width}x{display.height}, displaying (GC16) ...")

    display.frame_buf.paste(img)
    display.draw_full(constants.DisplayModes.GC16)
    print("Image displayed.")


def test_partial(display: AutoEPDDisplay) -> None:
    """Display a 200x200 gray square at (100,100) via DU mode."""
    print("Partial update test: drawing 200x200 gray square at (100,100) via DU ...")
    print("WARNING: DU mode may cause ghosting; a full GC16 clear is needed to remove it.")

    gray = Image.new("L", (200, 200), 128)
    display.frame_buf.paste(gray, (100, 100))
    display.draw_partial(constants.DisplayModes.DU)
    print("Partial update done.")


def test_sleep_wake(display: AutoEPDDisplay) -> None:
    """Clear, sleep 3 seconds, wake, clear again, sleep."""
    clear_display(display)

    print("Putting display to sleep ...")
    display.epd.sleep()
    print("Sleeping 3 seconds ...")
    time.sleep(3)

    print("Waking display ...")
    display.epd.run()
    clear_display(display)

    print("Sleep/wake cycle complete.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="IT8951 e-paper hardware validation script."
    )
    parser.add_argument(
        "--vcom",
        type=float,
        required=True,
        help="VCOM voltage for your display (e.g. -1.48). Check the FPC cable label.",
    )
    parser.add_argument(
        "--image",
        type=str,
        default=None,
        help="Path to a PNG file to display.",
    )
    parser.add_argument(
        "--partial",
        action="store_true",
        help="Test partial DU update with a gray square.",
    )
    parser.add_argument(
        "--sleep-wake",
        action="store_true",
        help="Test sleep/wake cycle.",
    )

    args = parser.parse_args()
    display = get_display(args.vcom)

    if args.image:
        show_image(display, args.image)
    elif args.partial:
        test_partial(display)
    elif args.sleep_wake:
        test_sleep_wake(display)
    else:
        # Default: clear display to white, then sleep.
        clear_display(display)

    print("Putting display to sleep ...")
    display.epd.sleep()
    print("Done.")


if __name__ == "__main__":
    main()
