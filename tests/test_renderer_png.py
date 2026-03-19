"""Tests for the PNG renderer helpers and protocol."""

from PIL import Image
import pytest

from src.export_dashboard import quantize_image


def test_quantize_image_16_levels():
    """quantize_image should map pixel values to nearest of 16 levels."""
    img = Image.new("L", (4, 4), color=128)
    result = quantize_image(img, levels=16)
    assert result.mode == "L"
    # 128 should map to round(128 / (255/15)) * (255/15) = 8 * 17 = 136
    assert result.getpixel((0, 0)) == 136


def test_quantize_image_returns_new_image():
    """quantize_image must not mutate the input image."""
    img = Image.new("L", (2, 2), color=100)
    result = quantize_image(img, levels=16)
    assert result is not img
    assert img.getpixel((0, 0)) == 100


def test_quantize_image_1_level_returns_black():
    """With 1 level, output should be all zeros (black)."""
    img = Image.new("L", (2, 2), color=200)
    result = quantize_image(img, levels=1)
    assert result.getpixel((0, 0)) == 0


def test_quantize_image_converts_rgb_to_grayscale():
    """RGB input should be converted to grayscale before quantizing."""
    img = Image.new("RGB", (2, 2), color=(128, 128, 128))
    result = quantize_image(img, levels=16)
    assert result.mode == "L"
