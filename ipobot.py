from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from time import sleep


class MeroShare:
    def __init__(self, driver_path=None):
        if driver_path:
            s = Service(driver_path)
            self.driver = webdriver.Chrome(service=s)
        else:
            opts = Options()
            opts.add_argument("--headless=new")
            opts.add_argument("--no-sandbox")
            opts.add_argument("--disable-dev-shm-usage")
            opts.add_argument("--disable-gpu")
            opts.add_argument("--disable-extensions")
            opts.add_argument("--disable-setuid-sandbox")
            opts.add_argument("--remote-debugging-port=9222")
            opts.add_argument("--window-size=1920,1080")
            opts.add_argument("--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
            self.driver = webdriver.Chrome(options=opts)

        self.wait = WebDriverWait(self.driver, 15)

    def login(self, dp_name, username, password):
        """Log in to MeroShare. Raises clearly if login fails."""
        self.driver.get("https://meroshare.cdsc.com.np/#/login")
        sleep(2)

        self.driver.find_element(By.CLASS_NAME, "select2-selection__placeholder").click()
        dp_input = self.driver.find_element(By.XPATH, "/html/body/span/span/span[1]/input")
        dp_input.send_keys(dp_name, Keys.ENTER)
        sleep(1)

        self.driver.find_element(By.ID, "username").send_keys(username)
        self.driver.find_element(By.ID, "password").send_keys(password, Keys.ENTER)
        sleep(2)

        # Verify login succeeded
        try:
            self.wait.until(EC.url_contains("dashboard"))
        except Exception:
            raise Exception(
                f"Login failed for '{username}'. "
                "Check credentials, DP name, or if MeroShare is slow/down."
            )

    def find_ipo(self, scrip: str = None):
        """
        Navigate to ASBA and click the Apply button for the correct IPO.
        scrip: stock symbol e.g. "NRML". If None, clicks the first IPO.
        """
        self.driver.get("https://meroshare.cdsc.com.np/#/asba")

        # Wait for apply buttons to render
        self.wait.until(EC.presence_of_element_located((By.CLASS_NAME, "btn-issue")))
        sleep(1)

        buttons = self.driver.find_elements(By.CLASS_NAME, "btn-issue")

        if not buttons:
            raise Exception("No open IPOs found on the ASBA page.")

        if scrip is None:
            buttons[0].click()
            sleep(2)
            return

        scrip_upper = scrip.strip().upper()
        matched_idx = None

        # Get full page text and log it for debugging
        try:
            page_text = self.driver.find_element(By.TAG_NAME, "body").text
            # Log the ASBA section only — find lines around "Apply"
            lines = page_text.split("\n")
            asba_lines = [l for l in lines if l.strip() and any(
                kw in l.upper() for kw in ["APPLY", "IPO", "FPO", scrip_upper]
            )]
            print(f"[find_ipo] Looking for scrip: '{scrip_upper}'")
            print(f"[find_ipo] Relevant page lines: {asba_lines}")

            chunks = page_text.split("\nApply")
            print(f"[find_ipo] Found {len(chunks)} chunks, {len(buttons)} buttons")
            for i, chunk in enumerate(chunks):
                print(f"[find_ipo] Chunk {i}: {repr(chunk[-200:])}")  # last 200 chars
                if f"({scrip_upper})" in chunk.upper():
                    matched_idx = i
                    break
        except Exception as e:
            print(f"[find_ipo] Page text error: {e}")

        if matched_idx is not None and matched_idx < len(buttons):
            buttons[matched_idx].click()
            sleep(2)
            return

        # Fallback: walk up parent elements
        for btn in buttons:
            try:
                parent = btn.find_element(By.XPATH, "./../..")
                if f"({scrip_upper})" in parent.text.upper():
                    btn.click()
                    sleep(2)
                    return
            except Exception:
                continue

        raise Exception(
            f"Could not find IPO with scrip '{scrip}'. "
            f"Found {len(buttons)} IPO(s) but none matched."
        )

    def apply_ipo(self, applied_unit, crn):
        """
        Fill the application form based on actual UI:
        1. Wait for form to load
        2. Select bank (pre-registered bank, pick first option)
        3. Branch and Account Number auto-fill after bank selection
        4. Applied Kitta is pre-filled with 10 — only change if different
        5. Check disclaimer checkbox FIRST
        6. Enter CRN
        7. Click Proceed
        """
        # Wait for bank dropdown to confirm form is loaded
        self.wait.until(EC.presence_of_element_located((By.ID, "selectBank")))
        sleep(1)

        # Select bank — one ARROW_DOWN from placeholder lands on first registered bank
        bank = self.driver.find_element(By.ID, "selectBank")
        bank.click()
        sleep(0.5)
        bank.send_keys(Keys.ARROW_DOWN)
        bank.send_keys(Keys.ENTER)
        sleep(1)  # Wait for Branch and Account Number to auto-fill

        # Applied Kitta — always clear and fill from secrets value
        kitta_field = self.driver.find_element(By.ID, "appliedKitta")
        kitta_field.click()
        kitta_field.send_keys(Keys.CONTROL + "a")
        kitta_field.send_keys(str(applied_unit))
        sleep(0.5)

        # Disclaimer checkbox FIRST (before CRN entry)
        self.driver.find_element(By.ID, "disclaimer").click()
        sleep(0.5)

        # CRN — enter after checkbox
        crn_field = self.driver.find_element(By.ID, "crnNumber")
        crn_field.clear()
        crn_field.send_keys(str(crn))
        sleep(0.5)

        # Proceed button — find by text, fall back to XPath
        try:
            proceed = self.driver.find_element(
                By.XPATH, "//button[normalize-space(text())='Proceed']"
            )
        except Exception:
            proceed = self.driver.find_element(
                By.XPATH,
                '//*[@id="main"]/div/app-edit/div/div/wizard/div/wizard-step[1]/form/div[2]/div/div[4]/div[2]/div/button[1]'
            )
        proceed.click()
        sleep(2)

    def enter_pin(self, transaction_pin):
        """
        Enter PIN on the confirmation page.

        From the UI screenshot:
        - Simple text input (no ID shown, but visible)
        - Button says "Apply" (not Confirm/Submit)
        - URL is still #/asba/apply/{id}
        """
        # Wait for PIN input to appear
        self.wait.until(EC.presence_of_element_located((By.ID, "transactionPIN")))
        sleep(1)

        self.driver.find_element(By.ID, "transactionPIN").send_keys(str(transaction_pin))
        sleep(1)

        # Apply button — find by text first, fall back to XPath
        try:
            apply_btn = self.driver.find_element(
                By.XPATH, "//button[normalize-space(text())='Apply']"
            )
        except Exception:
            apply_btn = self.driver.find_element(
                By.XPATH,
                '//*[@id="main"]/div/app-issue/div/wizard/div/wizard-step[2]/div[2]/div/form/div[2]/div/div/div/button[1]/span'
            )
        apply_btn.click()
        sleep(3)

        # Confirm success — look for any success indicator on the page
        try:
            page_text = self.driver.find_element(By.TAG_NAME, "body").text
            if any(word in page_text.lower() for word in ["success", "successful", "applied"]):
                return  # Application confirmed
            # If we're still on the PIN page, something went wrong
            if "transaction pin" in page_text.lower():
                raise Exception("PIN was rejected or application failed. Check PIN and CRN.")
        except Exception as e:
            if "PIN was rejected" in str(e):
                raise
            pass  # Page text check failed — proceed anyway

    def logout(self):
        """Log out of MeroShare."""
        sleep(1)
        try:
            self.driver.find_element(
                By.XPATH,
                "/html/body/app-dashboard/header/div[2]/div/div/div/ul/li[1]/a/i",
            ).click()
            sleep(1)
        except Exception:
            self.driver.get("https://meroshare.cdsc.com.np/#/login")

    def quit(self):
        """Close the browser."""
        self.driver.quit()
