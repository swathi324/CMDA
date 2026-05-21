# CMDA Document Scraper using Selenium

## Project Overview

This project is an automated web scraping and document downloading system developed using Python and Selenium.

The tool extracts and downloads PDF documents from the Chennai Metropolitan Development Authority (CMDA) official website in both English and Tamil versions.

The project automatically navigates through the website, identifies PDF links, and downloads all available documents into organized local folders.

---

# Features

✅ Automated PDF extraction from CMDA website
✅ Supports both English and Tamil documents
✅ Selenium-based browser automation
✅ Bulk PDF downloading
✅ Organized folder structure for downloads
✅ Dynamic link handling
✅ Error handling during downloads
✅ Automatic folder creation

---

# Technologies Used

* Python
* Selenium
* Requests
* Chrome WebDriver
* OS Module
* URL Processing

---

# Project Structure

```text
CMDA-Document-Scraper/
│
├── english-pdf.py
├── tamil-pdf.py
├── CMDA_PDFs/
├── CMDA_TAMIL_PDFs/
│   ├── Volume_1/
│   ├── Volume_2/
│   └── Volume_3/
├── requirements.txt
├── README.md
└── .gitignore


# English Document Scraper

The English scraper:

* Opens the CMDA English SMP webpage
* Finds all PDF links
* Downloads all PDF files automatically
* Stores documents inside the `CMDA_PDFs` folder

Website Used:
https://www.cmdachennai.gov.in/smp_main.html

---

# Tamil Document Scraper

The Tamil scraper:

* Opens the Tamil CMDA SMP webpage
* Identifies Tamil volume sections
* Navigates through each volume
* Extracts all PDF files
* Downloads PDFs into categorized folders

Website Used:
https://www.cmdachennai.gov.in/tamil/SMP_main_t.html

---

# Workflow

```text
Open Website
      ↓
Extract PDF Links
      ↓
Validate Links
      ↓
Download PDFs
      ↓
Save into Local Folders
      ↓
Organize by Language/Volume
```

---

# Installation

## Clone Repository

```bash
git clone https://github.com/swathi324/CMDA-Document-Scraper.git
```

---

# Install Required Packages

```bash
pip install selenium requests
```

---

# Chrome Driver Setup

Download ChromeDriver matching your Chrome browser version:

https://chromedriver.chromium.org/

Add ChromeDriver to System PATH.

---

# Run English Scraper

```bash
python english-pdf.py
```

---

# Run Tamil Scraper

```bash
python tamil-pdf.py
```

---

# Output

The downloaded PDFs will be automatically stored in:

```text
CMDA_PDFs/
CMDA_TAMIL_PDFs/
```

Tamil PDFs are categorized into:

* Volume 1
* Volume 2
* Volume 3

---

# Use Cases

* Government document automation
* Urban planning data collection
* Bulk PDF archival
* Research and data analysis
* Automation learning projects
* Web scraping practice

---

# Future Enhancements

* GUI integration
* Streamlit dashboard
* Database storage
* OCR text extraction from PDFs
* Automatic scheduling
* Metadata extraction
* Search functionality

---

# Learning Outcomes

This project helped in understanding:

* Selenium automation
* Web scraping techniques
* Dynamic webpage handling
* PDF downloading automation
* File handling in Python
* Browser automation workflows

---

# Author

Swathi
Data Processing Analyst  
