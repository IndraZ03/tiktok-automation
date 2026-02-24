from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
import time

opts = Options()
opts.add_experimental_option('debuggerAddress', '127.0.0.1:9222')
svc = Service(ChromeDriverManager().install())
driver = webdriver.Chrome(service=svc, options=opts)

textarea = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, "//div[contains(@class, 'ql-editor')]")))
textarea.click()
textarea.send_keys(Keys.CONTROL, 'a')
textarea.send_keys(Keys.BACK_SPACE)
textarea.send_keys('hello')

print('Clicking send...')
send_xpath = "//button[contains(@class, 'send-button')]"
send_btn = driver.find_element(By.XPATH, send_xpath)
print('Class before click:', send_btn.get_attribute('class'))
driver.execute_script('arguments[0].click()', send_btn)

for _ in range(5):
    time.sleep(1)
    try:
        btn_now = driver.find_element(By.XPATH, send_xpath)
        print('Class while generating:', btn_now.get_attribute('class'))
        print('Is displayed:', btn_now.is_displayed(), 'Is enabled:', btn_now.is_enabled())
    except Exception as e:
        print('Button missing:', str(e))

print('Waiting 10s for generation to finish')
time.sleep(10)
try:
    btn_after = driver.find_element(By.XPATH, send_xpath)
    print('Class after finish:', btn_after.get_attribute('class'))
except: pass

responses = driver.find_elements(By.XPATH, "//div[contains(@class,'message-content')] | //model-response")
if responses:
    print('Last response HTML snippet:')
    print(responses[-1].get_attribute('innerHTML')[:500])
    print('Text:', responses[-1].text)
