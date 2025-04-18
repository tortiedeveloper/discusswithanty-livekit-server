import time
import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import NoSuchElementException, TimeoutException, ElementClickInterceptedException
import requests # For downloading PDFs

# --- Impor Firebase ---
import firebase_admin
from firebase_admin import credentials, firestore, storage
import os
from datetime import timedelta

# --- Konfigurasi ---
LOGIN_URL = "https://www.idnfinancials.com/"
EMAIL = "marendra79@gmail.com" # !!! Peringatan Keamanan !!!
PASSWORD = "Tortie112025" # !!! Peringatan Keamanan !!!
SERVICE_ACCOUNT_KEY_PATH = r"E:\DEV\project\discusswithanty-livekit-test\private-key-discusswithanty.json"
FIREBASE_BUCKET_NAME = 'discusswithanty.firebasestorage.app' # <-- Ganti dengan nama ini

# --- Selektor CSS (Tetap sama) ---
# ... (semua selector CSS dari skrip sebelumnya) ...
INITIAL_LOGIN_BUTTON_SELECTOR = "body > header > div.container.l1.d-none.d-md-block > div > div.flex-grow-1.d-flex.align-items-center > div.user-info.pl-3 > a"
EMAIL_INPUT_SELECTOR = "#al-email"
PASSWORD_INPUT_SELECTOR = "#al-password"
COMPANY_NAME_SELECTOR = "#cdc > section.cd-preface > div > div.row.align-items-center > div.col-12.col-md-9.pt-3.pt-md-0 > div > div.cd-pi-name"
SUBMIT_LOGIN_BUTTON_SELECTOR = "#content > div > div > div:nth-child(1) > div > div.widget-body.mt-4 > form > div.d-flex.flex-wrap.align-items-center > button"
CURRENT_PRICE_SELECTOR = "#cdc > section.cd-preface > div > div.row.align-items-center > div.col-12.col-md-9.pt-3.pt-md-0 > div > div.cd-pi-price > span.p"
PRICE_CHANGE_SELECTOR = "#cdc > section.cd-preface > div > div.row.align-items-center > div.col-12.col-md-9.pt-3.pt-md-0 > div > div.cd-pi-price > span.c"
SECTOR_SELECTOR = "#cdc > section.cd-preface > div > div.row.align-items-center > div.col-12.col-md-9.pt-3.pt-md-0 > div > div.cd-pi-si > a:nth-child(2)"
INDUSTRY_SELECTOR = "#cdc > section.cd-preface > div > div.row.align-items-center > div.col-12.col-md-9.pt-3.pt-md-0 > div > div.cd-pi-si > a:nth-child(4)"
OVERVIEW_SELECTOR = "#company-overview > div > div.widget-body > div > div.overview-description > p"
OPEN_PRICE_SELECTOR = "#market-activity > div > div.widget-body > div.dc-wrapper.market-info-wrapper.mt-30 > div.table-responsive > table > tbody > tr:nth-child(1) > td:nth-child(1) > div > span"
OFFER_PRICE_SELECTOR = "#market-activity > div > div.widget-body > div.dc-wrapper.market-info-wrapper.mt-30 > div.table-responsive > table > tbody > tr:nth-child(2) > td:nth-child(1) > div > span"
DAY_LOW_SELECTOR = "#market-activity > div > div.widget-body > div.dc-wrapper.market-info-wrapper.mt-30 > div.table-responsive > table > tbody > tr:nth-child(3) > td:nth-child(1) > div > span"
VOLUME_SELECTOR = "#market-activity > div > div.widget-body > div.dc-wrapper.market-info-wrapper.mt-30 > div.table-responsive > table > tbody > tr:nth-child(4) > td:nth-child(1) > div > span"
FREQUENCY_SELECTOR = "#market-activity > div > div.widget-body > div.dc-wrapper.market-info-wrapper.mt-30 > div.table-responsive > table > tbody > tr:nth-child(5) > td:nth-child(1) > div > span"
PE_RATIO_SELECTOR = "#market-activity > div > div.widget-body > div.dc-wrapper.market-info-wrapper.mt-30 > div.table-responsive > table > tbody > tr:nth-child(6) > td:nth-child(1) > div > span"
MARKET_CAP_RANK_INDUSTRY_SELECTOR = "#market-activity > div > div.widget-body > div.dc-wrapper.market-info-wrapper.mt-30 > div.table-responsive > table > tbody > tr:nth-child(7) > td:nth-child(1) > div > span"
PREV_CLOSE_SELECTOR = "#market-activity > div > div.widget-body > div.dc-wrapper.market-info-wrapper.mt-30 > div.table-responsive > table > tbody > tr:nth-child(1) > td:nth-child(2) > div > span"
BID_PRICE_SELECTOR = "#market-activity > div > div.widget-body > div.dc-wrapper.market-info-wrapper.mt-30 > div.table-responsive > table > tbody > tr:nth-child(2) > td:nth-child(2) > div > span"
DAY_HIGH_SELECTOR = "#market-activity > div > div.widget-body > div.dc-wrapper.market-info-wrapper.mt-30 > div.table-responsive > table > tbody > tr:nth-child(3) > td:nth-child(2) > div > span"
VALUE_SELECTOR = "#market-activity > div > div.widget-body > div.dc-wrapper.market-info-wrapper.mt-30 > div.table-responsive > table > tbody > tr:nth-child(4) > td:nth-child(2) > div > span"
EPS_SELECTOR = "#market-activity > div > div.widget-body > div.dc-wrapper.market-info-wrapper.mt-30 > div.table-responsive > table > tbody > tr:nth-child(5) > td:nth-child(2) > div > span"
MARKET_CAP_VALUE_SELECTOR = "#market-activity > div > div.widget-body > div.dc-wrapper.market-info-wrapper.mt-30 > div.table-responsive > table > tbody > tr:nth-child(6) > td:nth-child(2) > div > div" # Selector untuk div pembungkus market cap
MARKET_CAP_UNIT_SELECTOR = "span"
MARKET_CAP_RANK_ALL_SELECTOR = "#market-activity > div > div.widget-body > div.dc-wrapper.market-info-wrapper.mt-30 > div.table-responsive > table > tbody > tr:nth-child(7) > td:nth-child(2) > div > span"
SUBSIDIARY_TABLE_ROW_SELECTOR_TPL = "#company-overview-subsidiary > div > table > tbody > tr:nth-child({index})"
SUBSIDIARY_NAME_SELECTOR_TPL = SUBSIDIARY_TABLE_ROW_SELECTOR_TPL + " > td:nth-child(1)"
SUBSIDIARY_PERCENTAGE_SELECTOR_TPL = SUBSIDIARY_TABLE_ROW_SELECTOR_TPL + " > td.text-right.text-md-left"
IPO_TABLE_SELECTOR = "#table-ipo-dates > tbody"
IPO_ROW_SELECTOR = "tr"
IPO_LABEL_SELECTOR = "td:nth-child(1)"
IPO_VALUE_SELECTOR = "td.text-right"
MANAGEMENT_LIST_SELECTOR = "#list-management > li"
MANAGEMENT_NAME_SELECTOR = "div > div.info > strong"
MANAGEMENT_POSITION_SELECTOR = "div > div.info > span"
SHAREHOLDER_TABLE_ROW_SELECTOR_TPL = "#table-shareholder > tbody > tr:nth-child({index})"
SHAREHOLDER_NAME_SELECTOR_TPL = SHAREHOLDER_TABLE_ROW_SELECTOR_TPL + " > td:nth-child(1)"
SHAREHOLDER_SHARES_SELECTOR_TPL = SHAREHOLDER_TABLE_ROW_SELECTOR_TPL + " > td:nth-child(2)"
SHAREHOLDER_PAIDUP_SELECTOR_TPL = SHAREHOLDER_TABLE_ROW_SELECTOR_TPL + " > td:nth-child(3)"
SHAREHOLDER_PERCENTAGE_SELECTOR_TPL = SHAREHOLDER_TABLE_ROW_SELECTOR_TPL + " > td:nth-child(4)"
FINANCIAL_REPORT_TAB_SELECTOR = "#tab-fin-rep"
FINANCIAL_REPORT_TABLE_ROW_SELECTOR_TPL = "#table-reports > tbody > tr:nth-child({index})"
FINANCIAL_REPORT_YEAR_SELECTOR_TPL = FINANCIAL_REPORT_TABLE_ROW_SELECTOR_TPL + " > td.w-25.text-center"
FINANCIAL_REPORT_LINKS_CELL_SELECTOR_TPL = FINANCIAL_REPORT_TABLE_ROW_SELECTOR_TPL + " > td.links > div"
FINANCIAL_REPORT_Q1_LINK_SELECTOR = "a:nth-child(1)"
FINANCIAL_REPORT_Q2_LINK_SELECTOR = "a:nth-child(2)"
FINANCIAL_REPORT_Q3_LINK_SELECTOR = "a:nth-child(3)"
FINANCIAL_REPORT_FULLYEAR_LINK_SELECTOR = "a:nth-child(4)"

# --- Global Firebase Bucket ---
firebase_bucket = None

# --- Fungsi Inisialisasi Firebase ---
def initialize_firebase(key_path):
    global firebase_bucket
    try:
        if not os.path.exists(key_path):
             print(f"Error: File kunci service account tidak ditemukan di: {key_path}")
             return None
        cred = credentials.Certificate(key_path)
        if not firebase_admin._apps:
             firebase_admin.initialize_app(cred, {'storageBucket': FIREBASE_BUCKET_NAME})
        else:
             print("Firebase App sudah diinisialisasi sebelumnya.")
        db = firestore.client()
        firebase_bucket = storage.bucket()
        print("Firebase Admin SDK (Firestore & Storage) berhasil diinisialisasi.")
        return db
    except ValueError as ve:
         if "The default Firebase app already exists" in str(ve):
             print("Firebase App sudah diinisialisasi sebelumnya (menangkap ValueError).")
             db = firestore.client()
             firebase_bucket = storage.bucket()
             return db
         else:
            print(f"Error Value saat inisialisasi Firebase: {ve}")
            return None
    except Exception as e:
        print(f"Error Exception saat inisialisasi Firebase: {e}")
        return None

# --- Fungsi Ambil Data dari Firestore ---
def get_tickers_from_firestore(db):
    if not db: return []
    tickers_data = []
    try:
        docs = db.collection('tickers').stream()
        for doc in docs:
            company_info = doc.to_dict()
            if 'ticker' in company_info and 'link' in company_info:
                tickers_data.append({'id': doc.id, 'ticker': company_info['ticker'], 'link': company_info['link']})
            else: print(f"Peringatan: Dokumen {doc.id} di Firestore tidak lengkap. Dilewati.")
        print(f"Berhasil mengambil {len(tickers_data)} data ticker dari Firestore.")
        return tickers_data
    except Exception as e:
        print(f"Error saat mengambil data dari Firestore: {e}")
        return []

# --- Fungsi Download & Upload PDF (MODIFIKASI) ---
def download_and_upload_pdf(requests_session, pdf_url, ticker, year, report_type): # Terima requests_session
    """Download PDF dari URL menggunakan session, upload ke Firebase Storage, return URL Storage."""
    global firebase_bucket
    if not firebase_bucket:
        print("Error: Firebase Storage bucket belum diinisialisasi.")
        return None
    if not requests_session:
        print("Error: Sesi requests tidak disediakan untuk download PDF.")
        return None

    file_name = f"{year}_{report_type.replace(' ', '_')}.pdf"
    storage_path = f"company/{ticker}/financial_reports/{file_name}"

    print(f"  -> Mencoba download PDF: {report_type} {year} dari {pdf_url} (menggunakan session)")
    try:
        # Gunakan requests_session.get()
        response = requests_session.get(pdf_url, stream=True, timeout=60)
        response.raise_for_status()

        content_type = response.headers.get('content-type')
        if not content_type or 'application/pdf' not in content_type:
             print(f"  -> Peringatan: URL {pdf_url} tidak mengembalikan PDF (Content-Type: {content_type}). Dilewati.")
             return None

        pdf_content = response.content
        print(f"  -> PDF {file_name} berhasil didownload ({len(pdf_content)} bytes). Mengupload ke Storage...")

        blob = firebase_bucket.blob(storage_path)
        blob.upload_from_string(pdf_content, content_type='application/pdf')

        # Coba dapatkan URL publik atau signed
        try:
            blob.make_public()
            public_url = blob.public_url
            print(f"  -> Upload berhasil. URL Publik: {public_url}")
            return public_url
        except Exception as e_public:
             print(f"  -> Gagal membuat URL publik (cek aturan Storage?): {e_public}. Mencoba Signed URL...")
             try:
                 signed_url = blob.generate_signed_url(version="v4", expiration=timedelta(days=365*10))
                 print(f"  -> Upload berhasil. Signed URL (10 tahun): {signed_url}")
                 return signed_url
             except Exception as e_signed:
                 print(f"  -> Gagal membuat Signed URL: {e_signed}")
                 return None

    except requests.exceptions.RequestException as e:
        # Cetak status code jika ada
        status_code = e.response.status_code if e.response is not None else 'N/A'
        print(f"  -> Error saat download PDF {pdf_url} [Status: {status_code}]: {e}")
        return None
    except Exception as e:
        print(f"  -> Error saat upload PDF ke Storage {storage_path}: {e}")
        return None


# --- Fungsi setup_driver (Tetap sama) ---
def setup_driver():
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--disable-gpu')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    # User agent ini penting, terutama jika ada deteksi bot
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36") # Contoh User Agent Chrome terbaru
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.maximize_window()
    return driver

# --- Fungsi login (MODIFIKASI: return driver dan session requests) ---
def login(driver, email, password):
    """Melakukan proses login dan mengembalikan driver & session requests jika berhasil."""
    wait = WebDriverWait(driver, 20)
    try:
        driver.get(LOGIN_URL)
        print("Membuka halaman login...")
        initial_login_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, INITIAL_LOGIN_BUTTON_SELECTOR)))
        initial_login_button.click()
        print("Tombol login awal diklik.")
        email_input = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, EMAIL_INPUT_SELECTOR)))
        password_input = driver.find_element(By.CSS_SELECTOR, PASSWORD_INPUT_SELECTOR)
        print("Mengisi email dan password...")
        email_input.clear(); email_input.send_keys(email)
        password_input.clear(); password_input.send_keys(password)
        submit_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, SUBMIT_LOGIN_BUTTON_SELECTOR)))
        submit_button.click()
        print("Tombol submit login diklik.")
        time.sleep(5) # Tunggu redirect / load halaman setelah login

        # --- Membuat Session Requests dan Transfer Cookies ---
        print("Membuat session requests dan mentransfer cookies...")
        requests_session = requests.Session()
        # Set header dasar untuk session requests
        requests_session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "en-US,en;q=0.9,id;q=0.8",
            # Referer mungkin perlu disesuaikan atau ditambahkan nanti jika masih gagal
            # "Referer": LOGIN_URL
        })

        selenium_cookies = driver.get_cookies()
        if not selenium_cookies:
             print("Peringatan: Tidak dapat mengambil cookies dari Selenium setelah login.")
             # Mungkin tetap coba lanjutkan, tapi download PDF kemungkinan gagal
        else:
            for cookie in selenium_cookies:
                # Pastikan domain cookie sesuai atau tidak terlalu spesifik (misal, hilangkan '.' di awal jika ada)
                cookie_domain = cookie['domain']
                if cookie_domain.startswith('.'):
                    cookie_domain = cookie_domain[1:]
                # Hanya tambahkan cookie yang relevan (opsional, tapi bisa membantu)
                # if 'idnfinancials.com' in cookie_domain:
                requests_session.cookies.set(cookie['name'], cookie['value'], domain=cookie_domain, path=cookie.get('path', '/'))
            print(f"Berhasil mentransfer {len(selenium_cookies)} cookies ke session requests.")

        print("Login berhasil.")
        return driver, requests_session # Kembalikan session requests juga

    except Exception as e:
        print(f"Error saat proses login: {e}")
        return None, None # Kembalikan None jika gagal

# --- Fungsi Scrape Utama (MODIFIKASI: terima session requests) ---
# --- Fungsi Scrape Utama (MODIFIKASI: Atasi ElementClickInterceptedException) ---
# --- Fungsi Scrape Utama (MODIFIKASI: Nama Perusahaan & Market Cap) ---
def scrape_company_data(driver, requests_session, company_url, ticker): # Terima requests_session
    """Mengambil SEMUA data yang diminta dari halaman detail perusahaan."""
    wait = WebDriverWait(driver, 15)
    data = {'ticker': ticker, 'url': company_url}

    try:
        print(f"\n--- Mengambil Data untuk Ticker: {ticker} ---")
        print(f"Mengakses: {company_url}")
        driver.get(company_url)
        # Tunggu elemen harga muncul sebagai indikator halaman utama sudah load
        wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, CURRENT_PRICE_SELECTOR)))

        # --- Fungsi helper (Tetap sama) ---
        def get_text_safe(selector, base_element=driver, wait_time=5):
            try:
                element = WebDriverWait(base_element, wait_time).until(EC.visibility_of_element_located((By.CSS_SELECTOR, selector)))
                return element.text.strip()
            except: return None
        def get_element_safe(selector, base_element=driver, wait_time=5):
             try: return WebDriverWait(base_element, wait_time).until(EC.visibility_of_element_located((By.CSS_SELECTOR, selector)))
             except: return None
        def get_elements_safe(selector, base_element=driver, wait_time=5):
             try: return WebDriverWait(base_element, wait_time).until(EC.visibility_of_all_elements_located((By.CSS_SELECTOR, selector)))
             except: return []

        # --- Ambil data dasar & market activity (MODIFIKASI) ---
        print("  - Mengambil data dasar & market activity...")
        # TAMBAHKAN: Ambil Nama Perusahaan
        data['company_name'] = get_text_safe(COMPANY_NAME_SELECTOR)
        data['current_price'] = get_text_safe(CURRENT_PRICE_SELECTOR)
        data['price_change'] = get_text_safe(PRICE_CHANGE_SELECTOR)
        data['sector'] = get_text_safe(SECTOR_SELECTOR)
        data['industry'] = get_text_safe(INDUSTRY_SELECTOR)
        data['overview'] = get_text_safe(OVERVIEW_SELECTOR)
        data['open_price'] = get_text_safe(OPEN_PRICE_SELECTOR)
        data['offer_price'] = get_text_safe(OFFER_PRICE_SELECTOR)
        data['day_low'] = get_text_safe(DAY_LOW_SELECTOR)
        data['volume'] = get_text_safe(VOLUME_SELECTOR)
        data['frequency'] = get_text_safe(FREQUENCY_SELECTOR)
        data['pe_ratio'] = get_text_safe(PE_RATIO_SELECTOR)
        data['market_cap_rank_industry'] = get_text_safe(MARKET_CAP_RANK_INDUSTRY_SELECTOR)
        data['prev_close'] = get_text_safe(PREV_CLOSE_SELECTOR)
        data['bid_price'] = get_text_safe(BID_PRICE_SELECTOR)
        data['day_high'] = get_text_safe(DAY_HIGH_SELECTOR)
        data['value'] = get_text_safe(VALUE_SELECTOR)
        data['eps'] = get_text_safe(EPS_SELECTOR)
        # data['market_cap'] = get_text_safe(MARKET_CAP_SELECTOR) # Hapus atau komentari baris ini

        # UBAH: Logika Pengambilan Market Cap
        market_cap_text = None
        market_cap_div = get_element_safe(MARKET_CAP_VALUE_SELECTOR, wait_time=2)
        if market_cap_div:
            # Ambil teks dari div utama (biasanya berisi angka dan unit)
            full_text = market_cap_div.text.strip()
            # Coba cari unit (span) di dalamnya
            unit_element = None
            try:
                unit_element = market_cap_div.find_element(By.CSS_SELECTOR, MARKET_CAP_UNIT_SELECTOR)
            except NoSuchElementException:
                pass # Tidak ada unit span, mungkin hanya angka

            if unit_element:
                unit_text = unit_element.text.strip()
                # Ambil angka saja (hapus unit dari teks lengkap)
                value_text = full_text.replace(unit_text, '').strip()
                market_cap_text = f"{value_text} {unit_text}" # Gabungkan dengan spasi
            else:
                market_cap_text = full_text # Gunakan teks lengkap jika tidak ada unit terpisah
        data['market_cap'] = market_cap_text
        print(f"    * Market Cap diambil: {market_cap_text}") # Tambahkan log untuk verifikasi

        data['market_cap_rank_all'] = get_text_safe(MARKET_CAP_RANK_ALL_SELECTOR)


        # --- Ambil Subsidiaries (Tetap sama) ---
        # ... (kode subsidiaries tidak berubah) ...
        print("  - Mengambil data Subsidiaries...")
        subsidiaries = []
        index = 1
        while True:
            name_selector = SUBSIDIARY_NAME_SELECTOR_TPL.format(index=index)
            percentage_selector = SUBSIDIARY_PERCENTAGE_SELECTOR_TPL.format(index=index)
            name_element = get_element_safe(name_selector, wait_time=1)
            if not name_element: break
            name = name_element.text.strip()
            percentage = get_text_safe(percentage_selector, wait_time=1)
            if name: subsidiaries.append({'name': name, 'percentage': percentage or 'N/A'})
            index += 1
        data['subsidiaries'] = subsidiaries
        print(f"    * Ditemukan {len(subsidiaries)} subsidiaries.")


        # --- Ambil IPO Details (Tetap sama) ---
        # ... (kode IPO tidak berubah) ...
        print("  - Mengambil data IPO Details...")
        ipo_details = {}
        ipo_tbody = get_element_safe(IPO_TABLE_SELECTOR)
        if ipo_tbody:
            rows = get_elements_safe(IPO_ROW_SELECTOR, base_element=ipo_tbody, wait_time=2)
            for row in rows:
                label = get_text_safe(IPO_LABEL_SELECTOR, base_element=row, wait_time=1)
                value = get_text_safe(IPO_VALUE_SELECTOR, base_element=row, wait_time=1)
                if label and value: ipo_details[label.replace(':', '').strip()] = value
        data['ipo_details'] = ipo_details
        print(f"    * Ditemukan {len(ipo_details)} detail IPO.")


        # --- Ambil Management (Tetap sama) ---
        # ... (kode management tidak berubah) ...
        print("  - Mengambil data Management...")
        management_list = []
        management_items = get_elements_safe(MANAGEMENT_LIST_SELECTOR, wait_time=3)
        for item in management_items:
             name = get_text_safe(MANAGEMENT_NAME_SELECTOR, base_element=item, wait_time=1)
             position = get_text_safe(MANAGEMENT_POSITION_SELECTOR, base_element=item, wait_time=1)
             if name: management_list.append({'name': name, 'position': position or 'N/A'})
        data['management_list'] = management_list
        print(f"    * Ditemukan {len(management_list)} management.")


        # --- Ambil Shareholders (Tetap sama) ---
        # ... (kode shareholders tidak berubah) ...
        print("  - Mengambil data Shareholders...")
        shareholders = []
        index = 1
        while True:
            name_selector = SHAREHOLDER_NAME_SELECTOR_TPL.format(index=index)
            name_element = get_element_safe(name_selector, wait_time=1)
            if not name_element: break
            name = name_element.text.strip()
            shares = get_text_safe(SHAREHOLDER_SHARES_SELECTOR_TPL.format(index=index), wait_time=1)
            paid_up = get_text_safe(SHAREHOLDER_PAIDUP_SELECTOR_TPL.format(index=index), wait_time=1)
            percentage = get_text_safe(SHAREHOLDER_PERCENTAGE_SELECTOR_TPL.format(index=index), wait_time=1)
            if name: shareholders.append({'name': name, 'shares': shares or 'N/A', 'paid_up_capital': paid_up or 'N/A', 'percentage': percentage or 'N/A'})
            index += 1
        data['shareholders_list'] = shareholders
        print(f"    * Ditemukan {len(shareholders)} shareholders.")


        # --- Ambil Financial Reports (Tetap sama, dengan perbaikan klik JS) ---
        # ... (kode financial reports tidak berubah) ...
        print("  - Mengambil data Financial Reports (PDF)...")
        financial_reports = []
        try:
            # 1. Temukan elemen tab (gunakan presence_of_element_located)
            report_tab_element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, FINANCIAL_REPORT_TAB_SELECTOR)))
            print("    * Elemen tab Financial Reports ditemukan.")

            # 2. Scroll elemen ke tengah layar (lebih aman)
            driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'nearest'});", report_tab_element)
            print("    * Scroll ke elemen tab.")
            time.sleep(1) # Beri waktu browser untuk selesai scroll & render

            # 3. Klik menggunakan JavaScript
            driver.execute_script("arguments[0].click();", report_tab_element)
            print("    * Tab Financial Reports diklik (via JavaScript).")
            time.sleep(2) # Waktu load tabel setelah klik

            # --- Kode untuk mengambil link PDF (TETAP SAMA) ---
            index = 1
            while True:
                year_selector = FINANCIAL_REPORT_YEAR_SELECTOR_TPL.format(index=index)
                # Tunggu elemen tahun muncul sebagai indikasi tabel sudah load
                try:
                    year_element = WebDriverWait(driver, 5).until(EC.visibility_of_element_located((By.CSS_SELECTOR, year_selector)))
                except TimeoutException:
                    # Jika elemen tahun pertama tidak muncul setelah klik tab, anggap tidak ada laporan
                    if index == 1:
                        print("    * Tabel laporan tidak muncul atau kosong setelah klik tab.")
                    break # Keluar loop jika baris tidak ditemukan

                year = year_element.text.strip()
                print(f"    * Memproses laporan tahun: {year}")
                links_cell = get_element_safe(FINANCIAL_REPORT_LINKS_CELL_SELECTOR_TPL.format(index=index), wait_time=1)
                if not links_cell:
                     print(f"      - Tidak ditemukan sel link untuk tahun {year}.")
                     index += 1; continue

                full_year_link_element = get_element_safe(FINANCIAL_REPORT_FULLYEAR_LINK_SELECTOR, base_element=links_cell, wait_time=1)
                pdf_downloaded = False
                if full_year_link_element:
                    pdf_url = full_year_link_element.get_attribute('href')
                    if pdf_url:
                        # Panggil dengan requests_session
                        storage_url = download_and_upload_pdf(requests_session, pdf_url, ticker, year, "Full Year")
                        if storage_url:
                            financial_reports.append({'year': year, 'type': 'Full Year', 'url': storage_url})
                            pdf_downloaded = True
                        else: print(f"      - Gagal download/upload Full Year PDF untuk {year}.")
                    else: print(f"      - Link Full Year ditemukan tapi tidak ada href untuk {year}.")

                if not pdf_downloaded:
                    print(f"      - Full Year tidak tersedia/gagal, mencoba Quarterly untuk {year}...")
                    q_links = {
                        'Q1': get_element_safe(FINANCIAL_REPORT_Q1_LINK_SELECTOR, base_element=links_cell, wait_time=0.5),
                        'Q2': get_element_safe(FINANCIAL_REPORT_Q2_LINK_SELECTOR, base_element=links_cell, wait_time=0.5),
                        'Q3': get_element_safe(FINANCIAL_REPORT_Q3_LINK_SELECTOR, base_element=links_cell, wait_time=0.5),
                    }
                    for q_name, q_link_element in q_links.items():
                        if q_link_element:
                            pdf_url = q_link_element.get_attribute('href')
                            if pdf_url:
                                # Panggil dengan requests_session
                                storage_url = download_and_upload_pdf(requests_session, pdf_url, ticker, year, q_name)
                                if storage_url:
                                    financial_reports.append({'year': year, 'type': q_name, 'url': storage_url})
                                else: print(f"      - Gagal download/upload {q_name} PDF untuk {year}.")
                            else: print(f"      - Link {q_name} ditemukan tapi tidak ada href untuk {year}.")

                index += 1
                time.sleep(0.5) # Jeda antar baris

        except TimeoutException as e_tab_find:
             print(f"    * Error: Timeout saat mencari elemen tab Financial Reports: {e_tab_find}")
        except Exception as e_reports:
             print(f"    * Error tidak terduga saat memproses Financial Reports: {e_reports}")
             import traceback
             traceback.print_exc() # Cetak traceback untuk debug

        data['financial_reports'] = financial_reports
        print(f"    * Selesai memproses laporan. Total {len(financial_reports)} PDF diupload.")


        print(f"Data lengkap untuk {ticker} berhasil diambil.")
        return data

    except TimeoutException:
        print(f"Error: Timeout saat menunggu elemen utama di halaman {company_url} untuk ticker {ticker}")
        return data # Kembalikan data yang sudah terkumpul sejauh ini
    except Exception as e:
        print(f"Error besar saat scraping data dari {company_url} untuk ticker {ticker}: {e}")
        import traceback
        traceback.print_exc() # Cetak traceback untuk debug
        return data # Kembalikan data yang sudah terkumpul sejauh ini

# --- Fungsi Print (Tetap sama) ---
def print_company_data_nicely(data):
    # ... (kode print tidak berubah) ...
    if not data or len(data) <= 2: return
    print(f"\n--- Detail untuk Ticker: {data.get('ticker', 'N/A')} ---")
    print(f"URL: {data.get('url', 'N/A')}")
    print("-" * 30)
    print(f"Current Price : {data.get('current_price', 'N/A')}")
    print(f"Price Change  : {data.get('price_change', 'N/A')}")
    print(f"Sector        : {data.get('sector', 'N/A')}")
    print(f"Industry      : {data.get('industry', 'N/A')}")
    print("-" * 30)
    print("Market Activity:")
    print(f"  Open Price    : {data.get('open_price', 'N/A')}")
    print(f"  Previous Close: {data.get('prev_close', 'N/A')}")
    print(f"  Offer Price   : {data.get('offer_price', 'N/A')}")
    print(f"  Bid Price     : {data.get('bid_price', 'N/A')}")
    print(f"  Day Low       : {data.get('day_low', 'N/A')}")
    print(f"  Day High      : {data.get('day_high', 'N/A')}")
    print(f"  Volume        : {data.get('volume', 'N/A')}")
    print(f"  Value         : {data.get('value', 'N/A')}")
    print(f"  Frequency     : {data.get('frequency', 'N/A')}")
    print(f"  EPS           : {data.get('eps', 'N/A')}")
    print(f"  PE Ratio      : {data.get('pe_ratio', 'N/A')}")
    print(f"  Market Cap.   : {data.get('market_cap', 'N/A')}")
    print(f"  MCap Rank (Ind): {data.get('market_cap_rank_industry', 'N/A')}")
    print(f"  MCap Rank (All): {data.get('market_cap_rank_all', 'N/A')}")
    print("-" * 30)
    print("Subsidiaries:")
    subs = data.get('subsidiaries', [])
    if subs:
        for s in subs[:5]: print(f"  - {s.get('name')} ({s.get('percentage')})")
        if len(subs) > 5: print(f"  ... ({len(subs)-5} more)")
    else: print("  N/A")
    print("IPO Details:")
    ipo = data.get('ipo_details', {})
    if ipo:
        for k, v in ipo.items(): print(f"  - {k}: {v}")
    else: print("  N/A")
    print("Management:")
    mgmt = data.get('management_list', [])
    if mgmt:
        for m in mgmt[:5]: print(f"  - {m.get('name')} ({m.get('position')})")
        if len(mgmt) > 5: print(f"  ... ({len(mgmt)-5} more)")
    else: print("  N/A")
    print("Shareholders:")
    sh = data.get('shareholders_list', [])
    if sh:
        for s in sh[:5]: print(f"  - {s.get('name')} ({s.get('percentage')})")
        if len(sh) > 5: print(f"  ... ({len(sh)-5} more)")
    else: print("  N/A")
    print("Financial Reports (Uploaded):")
    fr = data.get('financial_reports', [])
    if fr:
        for r in fr[:5]: print(f"  - {r.get('year')} {r.get('type')}: {r.get('url')[:50]}...")
        if len(fr) > 5: print(f"  ... ({len(fr)-5} more)")
    else: print("  N/A")
    print("-" * 30)
    print("Overview:")
    overview_text = data.get('overview', 'N/A')
    print(f"{overview_text[:200]}..." if overview_text and len(overview_text) > 200 else overview_text)
    print("-" * 30)


# --- Main Execution ---
if __name__ == "__main__":
    db = initialize_firebase(SERVICE_ACCOUNT_KEY_PATH)

    if db:
        driver = None
        req_session = None # Inisialisasi session requests
        try:
            driver = setup_driver()
            # Panggil login yang dimodifikasi
            driver, req_session = login(driver, EMAIL, PASSWORD)

            # Hanya lanjutkan jika login berhasil DAN session requests dibuat
            if driver and req_session:
                print("\nMemulai proses pengambilan data dari Firestore...")
                firestore_data = get_tickers_from_firestore(db)

                if not firestore_data:
                    print("Tidak ada data ticker/link yang valid dari Firestore untuk diproses.")
                else:
                    print("\nMemulai proses scraping dan update data perusahaan...")
                    success_count = 0
                    fail_count = 0
                    for company_info in firestore_data:
                        ticker = company_info.get('ticker')
                        link = company_info.get('link')
                        doc_id = company_info.get('id')

                        if not link or not ticker or not doc_id:
                            print(f"Peringatan: Data tidak lengkap dari Firestore: {company_info}. Dilewati.")
                            fail_count += 1; continue

                        # Panggil scrape dengan session requests
                        scraped_data = scrape_company_data(driver, req_session, link, ticker)

                        print_company_data_nicely(scraped_data)

                        # Update Firestore
                        if len(scraped_data) > 2:
                            try:
                                data_to_update = scraped_data.copy()
                                data_to_update.pop('ticker', None)
                                data_to_update.pop('url', None)
                                data_to_update['last_scraped_at'] = firestore.SERVER_TIMESTAMP
                                db.collection('tickers').document(doc_id).update(data_to_update)
                                print(f"==> Firestore document {doc_id} ({ticker}) berhasil diupdate.")
                                success_count += 1
                            except Exception as e_update:
                                print(f"==> Error saat update Firestore document {doc_id} ({ticker}): {e_update}")
                                fail_count += 1
                        else:
                            print(f"==> Tidak ada data signifikan yang di-scrape untuk {ticker}. Firestore tidak diupdate.")
                            fail_count += 1

                        time.sleep(3)

                    print("\n--- Proses Selesai ---")
                    print(f"Berhasil diupdate: {success_count}")
                    print(f"Gagal/Dilewati  : {fail_count}")

            else:
                print("Login gagal atau session requests tidak dapat dibuat. Proses scraping dibatalkan.")

        except Exception as e_main:
             print(f"\n--- Terjadi Error Fatal di Proses Utama ---")
             print(e_main)
             import traceback
             traceback.print_exc()

        finally:
            if driver:
                print("\nMenutup browser...")
                driver.quit()
    else:
        print("Gagal menginisialisasi Firebase. Skrip dihentikan.")