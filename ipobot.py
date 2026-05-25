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
        """Log in to MeroShare."""
        self.driver.get("https://meroshare.cdsc.com.np/#/login")
        sleep(1)

        self.driver.find_element(By.CLASS_NAME, "select2-selection__placeholder").click()

        depository_participant = self.driver.find_element(
            By.XPATH, "/html/body/span/span/span[1]/input"
        )
        depository_participant.send_keys(dp_name, Keys.ENTER)

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
        scrip: stock symbol e.g. "KAHL". If None, clicks the first IPO.
        """
        sleep(1)
        self.driver.get("https://meroshare.cdsc.com.np/#/asba")
        self.wait.until(EC.presence_of_element_located((By.CLASS_NAME, "btn-issue")))
        sleep(1)

        buttons = self.driver.find_elements(By.CLASS_NAME, "btn-issue")

        if not buttons:
            raise Exception("No open IPOs found on the ASBA page.")

        if scrip is None:
            # Original behaviour — click first IPO
            self.driver.find_element(By.CLASS_NAME, "btn-issue").click()
            return

        scrip_upper = scrip.strip().upper()
        matched_idx = None

        try:
            page_text = self.driver.find_element(By.TAG_NAME, "body").text

            if f"({scrip_upper})" not in page_text.upper():
                raise Exception(
                    f"Could not find IPO with scrip '{scrip}'. "
                    f"Found {len(buttons)} IPO(s) but none matched."
                )

            # Split by "\nApply" and only count chunks that are actual IPO entries
            chunks = page_text.split("\nApply")
            ipo_count = 0
            for chunk in chunks:
                is_ipo_chunk = any(
                    kw in chunk.upper()
                    for kw in ["\nIPO\n", "\nFPO\n", "\nRIGHT\n",
                               "ORDINARY SHARES", "MUTUAL FUND", "DEBENTURE"]
                )
                if is_ipo_chunk:
                    if f"({scrip_upper})" in chunk.upper():
                        matched_idx = ipo_count
                        break
                    ipo_count += 1

            print(f"[find_ipo] Scrip '{scrip_upper}' matched at button index: {matched_idx}")

        except Exception as e:
            if "Could not find" in str(e):
                raise
            print(f"[find_ipo] Error: {e}")

        if matched_idx is not None and matched_idx < len(buttons):
            buttons[matched_idx].click()
            sleep(1)
            return

        # If only 1 button and scrip is confirmed on page — click it
        if len(buttons) == 1:
            print(f"[find_ipo] Only 1 button found, clicking it")
            buttons[0].click()
            sleep(1)
            return

        raise Exception(
            f"Could not find IPO with scrip '{scrip}'. "
            f"Found {len(buttons)} IPO(s) but none matched."
        )

    def apply_ipo(self, applied_unit, crn):
        """
        Fill the IPO application form.
        Follows original source exactly — only the Proceed button
        selector is updated since the wizard XPath no longer exists.
        """
        sleep(1)

        # Select bank — original source uses 2x ARROW_DOWN
        bank = self.driver.find_element(By.ID, "selectBank")
        bank.click()
        bank.send_keys(Keys.ARROW_DOWN)
        bank.send_keys(Keys.ARROW_DOWN)
        bank.send_keys(Keys.ENTER)

        # Applied Kitta — original source clears then sends
        applied_kitta = self.driver.find_element(By.ID, "appliedKitta")
        applied_kitta.clear()
        applied_kitta.send_keys(applied_unit)

        # CRN
        self.driver.find_element(By.ID, "crnNumber").send_keys(crn)

        # Disclaimer
        self.driver.find_element(By.ID, "disclaimer").click()

        sleep(2)

        # Proceed button — wizard XPath removed, try text-based selectors
        # If none work, log all available buttons for debugging
        proceed = None
        for selector in [
            (By.XPATH, "//button[contains(text(),'Proceed')]"),
            (By.XPATH, "//button[contains(.,'Proceed')]"),
            (By.XPATH, '//*[@id="main"]//button[contains(.,"Proceed")]'),
        ]:
            try:
                proceed = self.driver.find_element(*selector)
                print(f"[apply_ipo] Proceed found via: {selector[1]}")
                break
            except Exception:
                continue

        if proceed is None:
            all_buttons = self.driver.find_elements(By.TAG_NAME, "button")
            print(f"[apply_ipo] Buttons on page: {[b.text.strip() for b in all_buttons]}")
            raise Exception("Could not find Proceed button.")

        proceed.click()

    def enter_pin(self, transaction_pin):
        """
        Enter transaction PIN.
        Follows original source exactly — only the confirm button
        selector is updated since the wizard XPath no longer exists.
        """
        sleep(1)

        self.driver.find_element(By.ID, "transactionPIN").send_keys(str(transaction_pin))
        sleep(1)

        # Confirm button — original said "button[1]/span" inside wizard
        # Current UI says "Apply" — try text-based selectors
        apply_btn = None
        for selector in [
            (By.XPATH, "//button[contains(text(),'Apply')]"),
            (By.XPATH, "//button[contains(.,'Apply')]"),
            (By.XPATH, '//*[@id="main"]//button[contains(.,"Apply")]'),
        ]:
            try:
                apply_btn = self.driver.find_element(*selector)
                print(f"[enter_pin] Apply button found via: {selector[1]}")
                break
            except Exception:
                continue

        if apply_btn is None:
            all_buttons = self.driver.find_elements(By.TAG_NAME, "button")
            print(f"[enter_pin] Buttons on page: {[b.text.strip() for b in all_buttons]}")
            raise Exception("Could not find Apply button on PIN page.")

        apply_btn.click()
        sleep(2)

    def logout(self):
        """Log out — original source."""
        sleep(2)
        self.driver.find_element(
            By.XPATH,
            "/html/body/app-dashboard/header/div[2]/div/div/div/ul/li[1]/a/i",
        ).click()

    def quit(self):
        self.driver.quit()
