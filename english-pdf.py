from selenium import webdriver
from selenium.webdriver.common.by import By
import time
import os
import requests

driver = webdriver.Chrome()

url = "https://www.cmdachennai.gov.in/smp_main.html"
driver.get(url)

time.sleep(5)

os.makedirs("CMDA_PDFs", exist_ok=True)

# find all links
links = driver.find_elements(By.TAG_NAME, "a")

pdf_links = []

for link in links:
    href = link.get_attribute("href")
    text = link.text

    if href and ".pdf" in href.lower():
        pdf_links.append((text, href))

# download
for text, pdf_url in pdf_links:
    try:
        file_name = pdf_url.split("/")[-1]

        r = requests.get(pdf_url)

        with open(f"CMDA_PDFs/{file_name}", "wb") as f:
            f.write(r.content)

        print("✅", file_name)

    except:
        pass

driver.quit()

print("🎉 Done")