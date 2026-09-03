import time
import re
import io
from datetime import datetime, timedelta
from pathlib import Path
from playwright.sync_api import sync_playwright
import pytesseract
from PIL import Image

# Point pytesseract directly to the Windows executable
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

URL = "https://www.judiciary.karnataka.gov.in/rep_judgment.php"

def solve_captcha(page):
    # Locate and screenshot the CAPTCHA image
    captcha_img = page.locator("#captcha")
    captcha_img.wait_for(state="visible")
    
    image_bytes = captcha_img.screenshot()
    image = Image.open(io.BytesIO(image_bytes))
    
    # Configure tesseract to look for a single block of text and only digits
    custom_config = r'--psm 8 -c tessedit_char_whitelist=0123456789'
    captcha_text = pytesseract.image_to_string(image, config=custom_config)
    
    # Clean the string to ensure only digits are returned
    return re.sub(r'\D', '', captcha_text)

with sync_playwright() as p:
    # 1. Launch browser maximized using Chromium arguments
    browser = p.chromium.launch(
        headless=False,
        args=["--start-maximized"]
    )

    # 2. Set no_viewport=True so the page fills the maximized browser window completely
    context = browser.new_context(no_viewport=True)
    page = context.new_page()
    page.goto(URL, wait_until="networkidle")

    # Select Principal Bench At Bengaluru
    page.locator("#db_bench").select_option("B")
    page.wait_for_timeout(2000)

    # Enter BBMP ONLY as Respondent Name
    page.locator("#respondname").wait_for(state="visible")
    page.locator("#respondname").fill("BBMP")

    # Calculate and Fill the Date of Order (Max 3 Months / < 92 days)
    to_date = datetime.now()
    from_date = to_date - timedelta(days=90) 
    
    page.locator("#dp1").fill(from_date.strftime("%Y-%m-%d"))
    page.locator("#dp2").fill(to_date.strftime("%Y-%m-%d"))
    
    print(f"Filled Date Range: {from_date.strftime('%Y-%m-%d')} to {to_date.strftime('%Y-%m-%d')}")

    # Automate CAPTCHA
    max_attempts = 5
    success = False
    
    for attempt in range(max_attempts):
        print(f"Attempting CAPTCHA OCR (Attempt {attempt + 1})...")
        captcha_text = solve_captcha(page)
        
        if len(captcha_text) == 6:
            print(f"Entering extracted CAPTCHA: {captcha_text}")
            page.locator("#vercode").fill(captcha_text)
            page.locator("#generate").click()
            
            try:
                # Wait for the results div/modal to become visible
                results = page.locator("#dynamic-content-year")
                results.wait_for(state="visible", timeout=10000)
                
                # Verify no inline CAPTCHA error is triggered
                error_locator = page.locator("#captcha_error")
                if error_locator.is_visible() and error_locator.inner_text().strip():
                    raise Exception("CAPTCHA Error returned by site")
                
                success = True
                break
            except Exception:
                page.locator("#reload-button").click()
                page.wait_for_timeout(2000)
        else:
            page.locator("#reload-button").click()
            page.wait_for_timeout(2000)

    # Save Results & Keep Browser Open
    if success:
        html = results.inner_html()
        text = results.inner_text()
        Path("bbmp_results.html").write_text(html, encoding="utf-8")
        Path("bbmp_results.txt").write_text(text, encoding="utf-8")
        print("\nSearch Successful. Results saved.")
    else:
        print("\nCould not successfully read CAPTCHA after multiple attempts.")
        Path("bbmp_debug.html").write_text(page.content(), encoding="utf-8")

    # THIS KEEPS THE BROWSER OPEN
    print("\n" + "="*50)
    print("Browser is held open. Check the results popup.")
    print("="*50)
    input("Press Enter in this terminal window to close the browser and end the script...")
    
    browser.close()