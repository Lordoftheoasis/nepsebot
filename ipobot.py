from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
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
            self.driver = webdriver.Chrome()

        self.driver.maximize_window()
        self.wait = WebDriverWait(self.driver, 10)

    def login(self, dp_name, username, password):
        """Log in to MeroShare."""
        self.driver.get("https://meroshare.cdsc.com.np/#/login")
        sleep(2)

        # Click the DP dropdown placeholder
        self.driver.find_element(By.CLASS_NAME, "select2-selection__placeholder").click()

        # Type and select the DP
        dp_input = self.driver.find_element(By.XPATH, "/html/body/span/span/span[1]/input")
        dp_input.send_keys(dp_name, Keys.ENTER)
        sleep(1)

        # Username
        self.driver.find_element(By.ID, "username").send_keys(username)

        # Password
        self.driver.find_element(By.ID, "password").send_keys(password, Keys.ENTER)
        sleep(2)

    def find_ipo(self, scrip: str = None):
        """
        Navigate to ASBA and click the correct IPO.

        scrip: the stock symbol/scrip of the IPO to apply for
               e.g. "NABIL", "UPPER"
               If None or not found, falls back to clicking the first IPO.
        """
        self.driver.get("https://meroshare.cdsc.com.np/#/asba")
        sleep(2)

        buttons = self.driver.find_elements(By.CLASS_NAME, "btn-issue")

        if not buttons:
            raise Exception("No open IPOs found on the ASBA page.")

        if scrip is None:
            # No scrip specified — click the first one (original behaviour)
            buttons[0].click()
            sleep(1)
            return

        # Try to find the button whose parent row contains the scrip text
        scrip_upper = scrip.strip().upper()
        matched = None

        for btn in buttons:
            try:
                # Walk up to the row container and check its text
                row = btn.find_element(By.XPATH, "./ancestor::tr")
                if scrip_upper in row.text.upper():
                    matched = btn
                    break
            except Exception:
                pass

        if matched:
            matched.click()
        else:
            # Scrip not found in any row — raise clearly so the caller knows
            raise Exception(
                f"Could not find IPO with scrip '{scrip}' on the ASBA page. "
                f"Found {len(buttons)} IPO(s) but none matched."
            )

        sleep(1)

    def apply_ipo(self, applied_unit, crn):
        """Fill out and submit the IPO application form."""
        sleep(1)

        # Select Bank (selects the first bank in the list)
        bank = self.driver.find_element(By.ID, "selectBank")
        bank.click()
        bank.send_keys(Keys.ARROW_DOWN)
        bank.send_keys(Keys.ARROW_DOWN)
        bank.send_keys(Keys.ENTER)

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
        self.driver.find_element(
            By.XPATH,
            "/html/body/app-dashboard/header/div[2]/div/div/div/ul/li[1]/a/i",
        ).click()
        sleep(1)

    def quit(self):
        """Close the browser."""
        self.driver.quit()
