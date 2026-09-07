"""CAPTCHA screenshot capture + OCR solving."""

import io
import re

import pytesseract
from PIL import Image


def solve_captcha(page, tesseract_cmd=None):
    """
    Screenshot the page's #captcha element and OCR it down to digits.

    `tesseract_cmd`, when given, is applied to pytesseract for this call
    so the GUI's Settings panel can point at a non-default install
    without needing a module-level side effect at import time.
    """
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    captcha_img = page.locator("#captcha")
    captcha_img.wait_for(state="visible")

    image_bytes = captcha_img.screenshot()
    image = Image.open(io.BytesIO(image_bytes))

    custom_config = r"--psm 8 -c tessedit_char_whitelist=0123456789"
    captcha_text = pytesseract.image_to_string(image, config=custom_config)
    return re.sub(r"\D", "", captcha_text)
