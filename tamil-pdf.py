from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
import time
import os
import requests
from urllib.parse import urljoin

# setup driver
driver = webdriver.Chrome()
driver.get("https://www.cmdachennai.gov.in/tamil/SMP_main_t.html")

time.sleep(5)

base = "https://www.cmdachennai.gov.in/"

os.makedirs("CMDA_TAMIL_PDFs", exist_ok=True)

# find தொகுப்பு links
volume_elements = driver.find_elements(By.TAG_NAME, "a")

volume_links = {}

for el in volume_elements:
    text = el.text.strip()
    href = el.get_attribute("href")

    if "தொகுப்பு 1" in text:
        volume_links["Volume_1"] = href
    elif "தொகுப்பு 2" in text:
        volume_links["Volume_2"] = href
    elif "தொகுப்பு 3" in text:
        volume_links["Volume_3"] = href

print("Volumes:", volume_links)

# loop volumes
for vol, link in volume_links.items():
    print(f"\n📂 Opening {vol}")

    driver.get(link)
    time.sleep(5)

    folder = os.path.join("CMDA_TAMIL_PDFs", vol)
    os.makedirs(folder, exist_ok=True)

    # find pdf links
    elements = driver.find_elements(By.TAG_NAME, "a")

    for e in elements:
        href = e.get_attribute("href")

        if href and ".pdf" in href.lower():
            try:
                file_name = href.split("/")[-1]

                r = requests.get(href, timeout=20)

                if r.status_code == 200:
                    with open(os.path.join(folder, file_name), "wb") as f:
                        f.write(r.content)

                    print(f"✅ {file_name}")

            except:
                pass

driver.quit()

print("\n🎉 All PDFs Downloaded")