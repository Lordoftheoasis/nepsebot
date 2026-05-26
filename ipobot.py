from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from time import sleep
import os


class MeroShare:
    def __init__(self, driver_path=None):
        opts = Options()
        opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--window-size=1920,1080")
        opts.add_argument(
            "--user-agent=Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        if driver_path:
            service = Service(driver_path)
        else:
            # Use webdriver_manager to get matching ChromeDriver automatically
            from webdriver_manager.chrome import ChromeDriverManager
            from pathlib import Path
            os.environ["WDM_LOG"] = "0"
            raw_path    = ChromeDriverManager().install()
            driver_path = raw_path
            if not os.access(raw_path, os.X_OK):
                for f in Path(raw_path).parent.iterdir():
                    if f.name.startswith("chromedriver") and os.access(f, os.X_OK):
                        driver_path = str(f)
                        break
            service = Service(driver_path)

        self.driver = webdriver.Chrome(service=service, options=opts)
        self.wait   = WebDriverWait(self.driver, 15)

    def _js_click(self, el):
        """Scroll into view then click via JS."""
        self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        sleep(0.3)
        self.driver.execute_script("arguments[0].click();", el)

    def _js_set_value(self, el, value):
        """
        Set an input value via JS with Angular event dispatching.
        Required for PIN field and any Angular-controlled inputs
        that reject send_keys.
        """
        self.driver.execute_script("""
            var el = arguments[0];
            el.removeAttribute('readonly');
            el.removeAttribute('disabled');
            el.style.display    = 'block';
            el.style.visibility = 'visible';
            el.style.opacity    = '1';
            el.focus();
            var setter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value'
            ).set;
            setter.call(el, arguments[1]);
            el.dispatchEvent(new Event('input',  {bubbles: true}));
            el.dispatchEvent(new Event('change', {bubbles: true}));
            el.dispatchEvent(new KeyboardEvent('keyup', {bubbles: true}));
        """, el, str(value))

    def login(self, dp_name, user_name, password):
        """Log into MeroShare."""
        self.driver.get("https://meroshare.cdsc.com.np/#/login")
        sleep(3)

        self.driver.find_element(By.CLASS_NAME, "select2-selection__placeholder").click()
        dp_input = self.driver.find_element(By.XPATH, "/html/body/span/span/span[1]/input")
        dp_input.send_keys(dp_name, Keys.ENTER)
        sleep(1)

        self.driver.find_element(By.ID, "username").send_keys(user_name)
        self.driver.find_element(By.ID, "password").send_keys(password, Keys.ENTER)
        sleep(3)

        try:
            self.wait.until(EC.url_contains("dashboard"))
            print(f"[login] ✅ Logged in as {user_name}")
        except Exception:
            raise Exception(
                f"Login failed for '{user_name}'. "
                "Check DP name, username, password, or if MeroShare is down."
            )

    def find_ipo(self, scrip: str = None):
        """
        Navigate to ASBA and click the Apply button for the correct IPO.
        scrip: stock symbol e.g. "KAHL". If None, clicks the first IPO.
        """
        self.driver.get("https://meroshare.cdsc.com.np/#/asba")
        self.wait.until(EC.presence_of_element_located((By.CLASS_NAME, "btn-issue")))
        sleep(1)

        buttons = self.driver.find_elements(By.CLASS_NAME, "btn-issue")

        if not buttons:
            raise Exception("No open IPOs found on the ASBA page.")

        if scrip is None:
            print("[find_ipo] No scrip set — clicking first IPO")
            buttons[0].click()
            sleep(2)
            return

        scrip_upper = scrip.strip().upper()
        page_text   = self.driver.find_element(By.TAG_NAME, "body").text

        if f"({scrip_upper})" not in page_text.upper():
            raise Exception(
                f"Could not find IPO with scrip '{scrip}'. "
                f"Found {len(buttons)} IPO(s) but none matched."
            )

        matched_idx = None
        ipo_count   = 0
        for chunk in page_text.split("\nApply"):
            is_ipo = any(kw in chunk.upper() for kw in [
                "\nIPO\n", "\nFPO\n", "\nRIGHT\n",
                "ORDINARY SHARES", "MUTUAL FUND", "DEBENTURE"
            ])
            if is_ipo:
                if f"({scrip_upper})" in chunk.upper():
                    matched_idx = ipo_count
                    break
                ipo_count += 1

        if matched_idx is not None and matched_idx < len(buttons):
            print(f"[find_ipo] ✅ '{scrip_upper}' matched at button index {matched_idx}")
            buttons[matched_idx].click()
            sleep(2)
            return

        if len(buttons) == 1:
            print("[find_ipo] Only 1 button — clicking it")
            buttons[0].click()
            sleep(2)
            return

        raise Exception(
            f"Could not find IPO with scrip '{scrip}'. "
            f"Found {len(buttons)} IPO(s) but none matched."
        )

    def apply_ipo(self, applied_unit, crn):
        """
        Fill the IPO application form.

        Flow (from tested working architecture):
        1. Wait for selectBank
        2. Select bank — 2x ARROW_DOWN, ENTER
        3. Select account number — appears after bank selection, 1x ARROW_DOWN, ENTER
        4. Branch auto-fills after account selection
        5. Set Applied Kitta
        6. Enter CRN
        7. Check disclaimer
        8. Click Proceed
        """
        self.wait.until(EC.presence_of_element_located((By.ID, "selectBank")))
        sleep(1)

        # ── Bank ──────────────────────────────────────────────
        bank = self.driver.find_element(By.ID, "selectBank")
        self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", bank)
        self.driver.execute_script("arguments[0].click();", bank)
        sleep(0.5)
        bank.send_keys(Keys.ARROW_DOWN)
        bank.send_keys(Keys.ARROW_DOWN)
        bank.send_keys(Keys.ENTER)
        sleep(2)
        print("[apply_ipo] ✅ Bank selected")

        # ── Account Number ────────────────────────────────────
        account_field = None
        for account_id in ["accountNumber", "selectAccount", "bankAccountNumber", "accountId"]:
            try:
                account_field = self.driver.find_element(By.ID, account_id)
                print(f"[apply_ipo] ✅ Account field found: '{account_id}'")
                break
            except Exception:
                continue

        if account_field is None:
            for s in self.driver.find_elements(By.TAG_NAME, "select"):
                if s.get_attribute("id") != "selectBank":
                    account_field = s
                    print(f"[apply_ipo] ✅ Account field found by select tag: '{s.get_attribute('id')}'")
                    break

        if account_field is None:
            raise Exception("Could not find account number dropdown after bank selection.")

        self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", account_field)
        self.driver.execute_script("arguments[0].click();", account_field)
        sleep(0.5)
        account_field.send_keys(Keys.ARROW_DOWN)
        account_field.send_keys(Keys.ENTER)
        sleep(2)
        print("[apply_ipo] ✅ Account number selected")

        # ── Applied Kitta ─────────────────────────────────────
        kitta = self.driver.find_element(By.ID, "appliedKitta")
        self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", kitta)
        kitta.clear()
        kitta.send_keys(str(applied_unit))
        print(f"[apply_ipo] ✅ Kitta set: {applied_unit}")

        # ── CRN ───────────────────────────────────────────────
        crn_field = self.driver.find_element(By.ID, "crnNumber")
        self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", crn_field)
        crn_field.send_keys(str(crn))
        print("[apply_ipo] ✅ CRN entered")

        # ── Disclaimer ────────────────────────────────────────
        disclaimer = self.driver.find_element(By.ID, "disclaimer")
        self._js_click(disclaimer)
        sleep(2)
        print("[apply_ipo] ✅ Disclaimer checked")

        # ── Proceed ───────────────────────────────────────────
        proceed = None
        for selector in [
            (By.XPATH, "//button[contains(text(),'Proceed')]"),
            (By.XPATH, "//button[contains(.,'Proceed')]"),
            (By.XPATH, '//*[@id="main"]//button[contains(.,"Proceed")]'),
        ]:
            try:
                proceed = self.driver.find_element(*selector)
                break
            except Exception:
                continue

        if proceed is None:
            all_buttons = self.driver.find_elements(By.TAG_NAME, "button")
            print(f"[apply_ipo] Buttons on page: {[b.text.strip() for b in all_buttons]}")
            raise Exception("Could not find Proceed button.")

        self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", proceed)
        sleep(0.3)
        self.driver.execute_script("arguments[0].click();", proceed)
        print("[apply_ipo] ✅ Proceed clicked")
        sleep(3)

    def enter_pin(self, transaction_password):
        """
        Enter PIN via JS with Angular event dispatching.
        send_keys does not work reliably on this field.
        """
        self.wait.until(EC.presence_of_element_located((By.ID, "transactionPIN")))
        sleep(1)

        pin_field = self.driver.find_element(By.ID, "transactionPIN")
        self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", pin_field)
        sleep(0.5)

        self._js_set_value(pin_field, str(transaction_password))
        sleep(0.5)

        # Verify value was accepted
        entered = self.driver.execute_script("return arguments[0].value;", pin_field)
        print(f"[enter_pin] ✅ PIN entered: {'*' * len(entered)} ({len(entered)} chars)")
        if len(entered) == 0:
            raise Exception("PIN field rejected all input.")

        # ── Apply ─────────────────────────────────────────────
        apply_btn = None
        for selector in [
            (By.XPATH, "//button[contains(text(),'Apply')]"),
            (By.XPATH, "//button[contains(.,'Apply')]"),
            (By.XPATH, '//*[@id="main"]//button[contains(.,"Apply")]'),
        ]:
            try:
                apply_btn = self.driver.find_element(*selector)
                break
            except Exception:
                continue

        if apply_btn is None:
            all_buttons = self.driver.find_elements(By.TAG_NAME, "button")
            print(f"[enter_pin] Buttons on page: {[b.text.strip() for b in all_buttons]}")
            raise Exception("Could not find Apply button on PIN page.")

        self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", apply_btn)
        sleep(0.3)
        self.driver.execute_script("arguments[0].click();", apply_btn)
        print("[enter_pin] ✅ Apply clicked")
        sleep(4)

    def logout(self):
        """Log out of MeroShare."""
        sleep(1)
        try:
            self.driver.find_element(
                By.XPATH,
                "/html/body/app-dashboard/header/div[2]/div/div/div/ul/li[1]/a/i",
            ).click()
            sleep(1)
            print("[logout] ✅ Logged out")
        except Exception:
            self.driver.get("https://meroshare.cdsc.com.np/#/login")
            sleep(1)
            print("[logout] ℹ️  Navigated to login page")

    def quit(self):
        self.driver.quit()
