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
        """
        Initialize MeroShare bot.
        driver_path: path to your chromedriver. If None, assumes chromedriver is in PATH.
        """
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

        # Click the DP dropdown placeholder
        self.driver.find_element(By.CLASS_NAME, "select2-selection__placeholder").click()

        # Type and select the DP
        dp_input = self.driver.find_element(By.XPATH, "/html/body/span/span/span[1]/input")
        dp_input.send_keys(dp_name, Keys.ENTER)
        sleep(1)

        # Username and password
        self.driver.find_element(By.ID, "username").send_keys(username)
        self.driver.find_element(By.ID, "password").send_keys(password, Keys.ENTER)
        sleep(2)

        # Verify login succeeded — wait for dashboard URL
        try:
            self.wait.until(EC.url_contains("dashboard"))
        except Exception:
            raise Exception(
                f"Login failed for '{username}'. "
                "Check credentials, DP name, or if MeroShare is slow/down."
            )

    def find_ipo(self, scrip: str = None):
        """
        Navigate to ASBA and click the correct IPO.
        scrip: stock symbol e.g. "KAHL". If None, clicks the first IPO.
        """
        self.driver.get("https://meroshare.cdsc.com.np/#/asba")

        # Wait up to 15s for apply buttons to appear — Angular needs time to render
        try:
            self.wait.until(EC.presence_of_element_located((By.CLASS_NAME, "btn-issue")))
        except Exception:
            raise Exception(
                "No open IPOs found on the ASBA page after waiting 15 seconds. "
                "The IPO may have closed, or the page failed to load."
            )

        buttons = self.driver.find_elements(By.CLASS_NAME, "btn-issue")

        if scrip is None:
            buttons[0].click()
            sleep(1)
            return

        scrip_upper = scrip.strip().upper()

        # Get full page text, split into per-IPO chunks by "Apply" keyword
        # Each chunk corresponds to one button at the same index
        matched_idx = None
        try:
            page_text = self.driver.find_element(By.TAG_NAME, "body").text
            chunks = page_text.split("\nApply")
            for i, chunk in enumerate(chunks):
                if f"({scrip_upper})" in chunk.upper():
                    matched_idx = i
                    break
        except Exception:
            pass

        if matched_idx is not None and matched_idx < len(buttons):
            buttons[matched_idx].click()
            sleep(1)
            return

        # Fallback: walk up two parent levels from each button
        for i, btn in enumerate(buttons):
            try:
                parent = btn.find_element(By.XPATH, "./../..")
                if f"({scrip_upper})" in parent.text.upper():
                    btn.click()
                    sleep(1)
                    return
            except Exception:
                continue

        raise Exception(
            f"Could not find IPO with scrip '{scrip}' on the ASBA page. "
            f"Found {len(buttons)} IPO(s) but none matched."
        )

    def apply_ipo(self, applied_unit, crn):
        """Fill out and submit the IPO application form."""
        sleep(1)

        # Select Bank — one ARROW_DOWN skips the placeholder "Please choose one"
        # and lands on the user's first (and usually only) registered bank
        bank = self.driver.find_element(By.ID, "selectBank")
        bank.click()
        sleep(0.5)
        bank.send_keys(Keys.ARROW_DOWN)
        bank.send_keys(Keys.ENTER)
        sleep(0.5)

        # Applied Kitta
        applied_kitta = self.driver.find_element(By.ID, "appliedKitta")
        applied_kitta.clear()
        applied_kitta.send_keys(str(applied_unit))

        # CRN Number
        self.driver.find_element(By.ID, "crnNumber").send_keys(str(crn))

        # Disclaimer checkbox
        self.driver.find_element(By.ID, "disclaimer").click()

        sleep(2)

        # Click Proceed
        self.driver.find_element(
            By.XPATH,
            '//*[@id="main"]/div/app-edit/div/div/wizard/div/wizard-step[1]/form/div[2]/div/div[4]/div[2]/div/button[1]',
        ).click()

    def enter_pin(self, transaction_pin):
        """Enter the transaction PIN to confirm the application."""
        sleep(1)
        self.driver.find_element(By.ID, "transactionPIN").send_keys(str(transaction_pin))
        sleep(1)
        self.driver.find_element(
            By.XPATH,
            '//*[@id="main"]/div/app-issue/div/wizard/div/wizard-step[2]/div[2]/div/form/div[2]/div/div/div/button[1]/span',
        ).click()
        sleep(2)

    def logout(self):
        """Log out of MeroShare."""
        sleep(2)
        try:
            self.driver.find_element(
                By.XPATH,
                "/html/body/app-dashboard/header/div[2]/div/div/div/ul/li[1]/a/i",
            ).click()
            sleep(1)
        except Exception:
            # If logout fails just navigate away — next login will still work
            self.driver.get("https://meroshare.cdsc.com.np/#/login")

    def quit(self):
        """Close the browser."""
        self.driver.quit()
