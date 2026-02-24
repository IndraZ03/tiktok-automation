"""
Debug: minimal DOM inspection - just dump what's near schedule area.
"""
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import time, json

chrome_options = Options()
chrome_options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
service = Service(ChromeDriverManager().install())
driver = webdriver.Chrome(service=service, options=chrome_options)

print("Connected! Current URL:", driver.current_url)

# Step 1: Check if schedule area is visible
try:
    schedule_text = driver.find_elements(By.XPATH, "//*[contains(text(), 'When to post')]")
    print(f"'When to post' elements: {len(schedule_text)}")
    
    schedule_radio = driver.find_elements(By.XPATH, "//input[@name='postSchedule']")
    print(f"Schedule radio buttons: {len(schedule_radio)}")
    for r in schedule_radio:
        print(f"  value={r.get_attribute('value')}, checked={r.get_attribute('aria-checked')}")
except Exception as e:
    print(f"Error: {e}")

# Step 2: Click time input to open picker
try:
    readonly_inputs = driver.find_elements(By.CSS_SELECTOR, "input[readonly]")
    print(f"\nAll readonly inputs: {len(readonly_inputs)}")
    for ri in readonly_inputs:
        val = ri.get_attribute("value") or ""
        vis = ri.is_displayed()
        print(f"  value='{val}', visible={vis}")
    
    # Click the time input
    for ri in readonly_inputs:
        val = ri.get_attribute("value") or ""
        if ":" in val and ri.is_displayed():
            print(f"\nClicking time input: {val}")
            driver.execute_script("arguments[0].click();", ri)
            time.sleep(2)
            
            # Now find the popup - execute a very targeted JS
            popup_html = driver.execute_script("""
                // Look for the TUX popover content
                var popovers = document.querySelectorAll('[class*="TUXPopover"], [class*="Popover"], [data-popper-placement], [class*="popper"]');
                var result = [];
                for (var p of popovers) {
                    if (p.offsetHeight > 0) {
                        result.push('POPOVER: class=' + p.className.substring(0,200) + ' tag=' + p.tagName + ' html=' + p.outerHTML.substring(0, 3000));
                    }
                }
                
                // Also look for any ul/ol that might be the scroll list
                var lists = document.querySelectorAll('ul, ol');
                for (var l of lists) {
                    var style = window.getComputedStyle(l);
                    if (l.offsetHeight > 30 && style.overflow.indexOf('scroll') !== -1 || style.overflowY.indexOf('scroll') !== -1 || style.overflow.indexOf('auto') !== -1) {
                        result.push('SCROLL_LIST: class=' + l.className.substring(0,200) + ' tag=' + l.tagName + ' childCount=' + l.children.length + ' html=' + l.outerHTML.substring(0, 1500));
                    }
                }
                
                // Also check divs with overflow scroll
                var divs = document.querySelectorAll('div');
                for (var d of divs) {
                    var style = window.getComputedStyle(d);
                    if (d.offsetHeight > 30 && d.offsetHeight < 300 && 
                        (style.overflowY === 'scroll' || style.overflowY === 'auto') &&
                        d.children.length > 3) {
                        var text = d.textContent.trim();
                        if (/^[\\d\\s]+$/.test(text) || text.length < 100) {
                            result.push('SCROLL_DIV: class=' + d.className.substring(0,200) + ' h=' + d.offsetHeight + ' children=' + d.children.length + ' text=' + text.substring(0,200) + ' html=' + d.outerHTML.substring(0, 1500));
                        }
                    }
                }
                
                return result;
            """)
            print(f"\nFound {len(popup_html)} scroll/popover elements:")
            for item in popup_html:
                print(f"\n{item}\n")
            
            break
except Exception as e:
    print(f"Time picker error: {e}")

# Close popup
driver.execute_script("document.body.click();")
time.sleep(1)

# Step 3: Click date input to open calendar
try:
    readonly_inputs = driver.find_elements(By.CSS_SELECTOR, "input[readonly]")
    for ri in readonly_inputs:
        val = ri.get_attribute("value") or ""
        if "-" in val and len(val) == 10 and ri.is_displayed():
            print(f"\nClicking date input: {val}")
            driver.execute_script("arguments[0].click();", ri)
            time.sleep(2)
            
            cal_html = driver.execute_script("""
                var popovers = document.querySelectorAll('[class*="TUXPopover"], [class*="Popover"], [data-popper-placement], [class*="popper"], [class*="calendar"], [class*="Calendar"]');
                var result = [];
                for (var p of popovers) {
                    if (p.offsetHeight > 0) {
                        result.push('CAL_CONTAINER: class=' + p.className.substring(0,200) + ' html=' + p.outerHTML.substring(0, 5000));
                    }
                }
                
                // Also look for tables
                var tables = document.querySelectorAll('table');
                for (var t of tables) {
                    if (t.offsetHeight > 0 && t.offsetWidth > 0) {
                        result.push('TABLE: class=' + t.className.substring(0,200) + ' html=' + t.outerHTML.substring(0, 5000));
                    }
                }
                return result;
            """)
            print(f"\nFound {len(cal_html)} calendar elements:")
            for item in cal_html:
                print(f"\n{item}\n")
            break
except Exception as e:
    print(f"Date picker error: {e}")

print("\nDone!")
