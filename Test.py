import requests
import time
import telegram
import os
# from bs4 import BeautifulSoup  # Unused
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import multiprocessing
import io
from datetime import datetime, date  # Import date
import asyncio
import schedule
import re
import random
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from requests.packages.urllib3.exceptions import InsecureRequestWarning
import pycountry  # Unused, but good to keep



# --- CẤU HÌNH ---
TELEGRAM_BOT_TOKEN = '7582640219:AAHzedxZ8WvFQ9CUU4mXiXw3KFVSZLU8Oi8'  # Thay bằng token của bạn
TELEGRAM_CHAT_ID = '-1002318241724'
ADMIN_TELEGRAM_CHAT_ID = '5929440805'  # Optional
CHECK_TIMEOUT = 3
FETCH_TIMEOUT = 5
SCHEDULE_INTERVAL_MINUTES = 60
# MAX_THREADS = multiprocessing.cpu_count() * 200  # Use this in production
MAX_THREADS = 300  # For debugging, keep it lower
MAX_PROXIES_PER_SOURCE = 100
CONNECT_TIMEOUT = 3
DB_IP_API_KEYS = [
    "ac89ee53b354d9ddded0b84878a23cca289856fc",  # Thay bằng API key(s) của bạn
#    "another_api_key",  # Thêm các key khác nếu có
]
DB_IP_TIMEOUT = 3


# --- Danh sách URL kiểm tra ---
CHECK_URLS_HTTP = [
    "http://httpbin.org/get",
    "http://httpbin.org/ip",
]
CHECK_URLS_HTTPS = [
    "https://www.google.com",
    "https://bing.com",
]

# --- Danh sách nguồn proxy ---
PROXY_SOURCES = [
    {
        "url": "https://proxylist.geonode.com/api/proxy-list?protocols=http&google=false&limit=500&page=1&sort_by=lastChecked&sort_type=desc",
        "type": "http",
        "format": "json"
    },
    {
        "url": "https://proxylist.geonode.com/api/proxy-list?protocols=https&google=false&limit=500&page=1&sort_by=lastChecked&sort_type=desc",
        "type": "https",
        "format": "json"
    },
    {
        "url": "https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&protocol=http&proxy_format=ipport&format=text&timeout=3000",
        "type": "http",
        "format": "text"
    },
    {
        "url": "https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&protocol=https&proxy_format=ipport&format=text&timeout=3000",
        "type": "https",
        "format": "text"
    }
]

# --- CÁC HÀM ---

def generate_random_ua():
    """Tạo User-Agent ngẫu nhiên."""
    chrome_version = f"{random.randint(90, 116)}.0.{random.randint(4000, 5000)}.{random.randint(100, 200)}"
    os_versions = {
        "Windows NT 10.0; Win64; x64": 0.7,
        "Macintosh; Intel Mac OS X 10_15_7": 0.2,
        "X11; Linux x86_64": 0.1
    }
    os_choice = random.choices(list(os_versions.keys()), weights=list(os_versions.values()))[0]

    templates = [
        f"Mozilla/5.0 ({os_choice}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version} Safari/537.36",
        f"Mozilla/5.0 ({os_choice}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version} Safari/537.36 Edg/{chrome_version}",  # Edge
    ]
    if "Windows" in os_choice:
        templates.append(
            f"Mozilla/5.0 ({os_choice}; rv:{random.randint(80, 102)}.0) Gecko/20100101 Firefox/{random.randint(80, 102)}.0"
        )

    return random.choice(templates)


async def init_bot():
    """Khởi tạo bot Telegram."""
    try:
        bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)
        bot_info = await bot.get_me()
        print(f"Telegram Bot: {bot_info.username} (ID: {bot_info.id})")
        return bot
    except telegram.error.TelegramError as e:
        print(f"Lỗi khởi tạo Telegram Bot: {e}")
        return None


# Tạo session ở đây (global)
session = requests.Session()
retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
adapter = HTTPAdapter(max_retries=retries)
session.mount('http://', adapter)
session.mount('https://', adapter)
requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)


def make_request(url, proxies=None, timeout=None, headers=None):
    """Thực hiện request, trả về None nếu lỗi."""
    try:
        headers = headers or {}
        headers['User-Agent'] = generate_random_ua()

        # Sử dụng session đã tạo
        if "rootjazz.com" in url.lower():
            session.verify = False  # Tắt kiểm tra SSL cho rootjazz.com
        else:
            session.verify = True  # Bật kiểm tra SSL (mặc định)

        response = session.get(url, proxies=proxies, timeout=timeout, headers=headers)
        response.raise_for_status()
        return response

    except requests.exceptions.RequestException as e:
        return None


def get_short_url(url):
    """Rút gọn URL."""
    try:
        scheme, rest = url.split("://", 1)
        domain = rest.split("/", 1)[0]
        return f"{scheme}://{domain}"
    except:
        return url


def format_proxy_error(error_message, proxy):
    """
    Phân tích và định dạng thông báo lỗi, trả về mã trạng thái.
    """
    # Ưu tiên lấy status_code nếu có (phản hồi từ server)
    match_status = re.search(r"HTTPError\((\d+)", error_message)
    if match_status:
        status_code = int(match_status.group(1))
        return f"CHECK PROXY: {proxy} - LỖI: {status_code}"

    # Nếu không có, kiểm tra ConnectTimeout
    match_timeout = re.search(r"ConnectTimeoutError", error_message)
    if match_timeout:
        return f"CHECK PROXY: {proxy} - LỖI: 0 (Connect Timeout)"

    # Nếu không có, kiểm tra lỗi ProxyError chung (không có timeout)
    match_proxy_error = re.search(r"ProxyError", error_message)
    if match_proxy_error:
        return f"CHECK PROXY: {proxy} - LỖI: (Proxy Error)"

    return None  # Không khớp với pattern nào


def get_country_flag(country_code):
    """Lấy emoji cờ quốc gia từ mã quốc gia."""
    try:
        if country_code and len(country_code) == 2:
            return "".join([chr(ord('🇦') + ord(c) - ord('A')) for c in country_code.upper()])
        return ""  # Trả về chuỗi rỗng nếu không tìm thấy
    except Exception:
        return ""

def get_ip_info(ip_address, api_keys):
    """Lấy thông tin IP từ db-ip.com, sử dụng danh sách API key."""
    api_key = random.choice(api_keys)  # Chọn ngẫu nhiên một API key
    try:
        url = f"http://api.db-ip.com/v2/{api_key}/{ip_address}"
        response = make_request(url, timeout=DB_IP_TIMEOUT)  # Thêm timeout
        if response:
            data = response.json()
            # Kiểm tra lỗi từ API
            if 'error' in data:
                print(f"db-ip.com API Error: {data.get('error')}")
                return None, None, None

            country_code = data.get('countryCode')
            country_name = data.get('countryName') # Lấy tên quốc gia
            return ip_address, country_code, country_name
        else:
            print(f"Lỗi khi truy vấn db-ip.com cho IP: {ip_address}")
            return None, None, None
    except Exception as e:
        print(f"Lỗi khi truy vấn db-ip.com cho IP: {ip_address}: {e}")
        return None, None, None

def get_api_key_info(api_key):
    """Lấy thông tin chi tiết của một API key từ db-ip.com."""
    try:
        url = f"http://api.db-ip.com/v2/{api_key}"  # Không cần IP address
        response = make_request(url, timeout=DB_IP_TIMEOUT)
        if response:
            data = response.json()
            if 'error' in data:
                print(f"db-ip.com API Error: {data.get('error')}")
                return None
            # Thêm expires (giả định là không có, bạn cần tự thêm)
            data['expires'] = 'N/A'  # Placeholder
            return data
        else:
            print(f"Lỗi khi truy vấn thông tin API key: {api_key}")
            return None
    except Exception as e:
        print(f"Lỗi khi truy vấn thông tin API key: {api_key}: {e}")
        return None


def determine_proxy_type(proxy, connect_timeout, check_timeout):
    """
    Xác định loại proxy và thông tin quốc gia.
    """
    ip_address, _ = proxy.split(":")  # Tách IP

    # Kiểm tra IP và lấy thông tin quốc gia *trước* khi kiểm tra proxy
    ip, country_code, country_name = get_ip_info(ip_address, DB_IP_API_KEYS)
    if not ip or not country_code:
        return None, None, None

    def check_single_proxy(proxy_type, check_urls):
        proxies = {
            'http': f'{proxy_type}://{proxy}',
            'https': f'{proxy_type}://{proxy}'
        }
        for check_url in check_urls:
            try:
                response = make_request(check_url, proxies=proxies, timeout=(connect_timeout, check_timeout),
                                        headers={'User-Agent': generate_random_ua()})
                if response:
                    return True
            except requests.exceptions.RequestException as e:
                formatted_error = format_proxy_error(str(e), proxy)
                if formatted_error:
                    print(formatted_error)
                return False
        return False

    proxy_types = []  # Lưu trữ các loại proxy hoạt động
    # Kiểm tra HTTP
    if check_single_proxy("http", CHECK_URLS_HTTP):
        proxy_types.append("http")
        # Nếu HTTP hoạt động, kiểm tra HTTPS
        if check_single_proxy("https", CHECK_URLS_HTTPS):
            proxy_types.append("https")

    if proxy_types:
      return proxy_types, country_code, country_name  # Trả về danh sách các loại
    else:
      return None, None, None

def fetch_proxies_from_url(source):
    """Lấy proxy từ URL."""
    url = source['url']
    proxy_type = source['type']
    data_format = source.get('format', 'text')
    all_proxies = []
    seen_proxies = set()
    total_fetched_from_this_source = 0
    short_url = get_short_url(url)

    try:
        if data_format == 'json' and "geonode" in url.lower():
            page = 1
            max_pages = 30
            while True:
                paginated_url = re.sub(r"page=\d+", f"page={page}", url)
                response = make_request(paginated_url, timeout=FETCH_TIMEOUT)

                if not response:
                    print(f"Lỗi khi lấy dữ liệu từ {short_url} (page {page})")
                    break

                try:
                    json_response = response.json()
                    if not isinstance(json_response, dict) or 'data' not in json_response or not isinstance(
                            json_response['data'], list):
                        print(f"Dữ liệu JSON không hợp lệ từ {short_url} (page {page})")
                        break

                    proxy_list_page = json_response['data']
                    if not proxy_list_page:
                        print(f"Không có proxy ở trang {page} từ {short_url}.")
                        break

                    for proxy_item in proxy_list_page:
                        if 'ip' in proxy_item and 'port' in proxy_item:
                            proxy_string = f"{proxy_item['ip']}:{proxy_item['port']}"
                            if proxy_string not in seen_proxies:
                                all_proxies.append((proxy_string, proxy_type))
                                seen_proxies.add(proxy_string)
                                total_fetched_from_this_source += 1

                    if len(proxy_list_page) < 500:
                        break
                    page += 1
                    if page > max_pages:
                        break
                except (ValueError, KeyError) as e:
                    print(f"Lỗi khi xử lý JSON từ {short_url} (page {page}): {e}")
                    break

        elif data_format == 'text':
            if "github.com" in url:
                if url.startswith("github.com"):
                    url = "www." + url
                # Regex cho cả hai định dạng GitHub
                url = re.sub(r"(www\.)?github\.com/([^/]+)/([^/]+)/(blob|tree|refs/heads)/([^/]+)/",
                             r"raw.githubusercontent.com/\2/\3/\5/", url)

            response = make_request(url, timeout=FETCH_TIMEOUT)
            if not response:
                print(f"Lỗi khi lấy dữ liệu từ {short_url}")
                return []

            response.encoding = 'utf-8'
            for line in response.text.splitlines():
                line = line.strip()
                line = re.sub(r"^(http:\/\/|https:\/\/)", "", line)

                ip_port_match = re.search(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d{1,5}', line)
                if ip_port_match:
                    extracted_proxy = ip_port_match.group(0)
                    if re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d{1,5}$', extracted_proxy):
                        if extracted_proxy not in seen_proxies:
                            if proxy_type:
                                all_proxies.append((extracted_proxy, proxy_type))
                            else:
                                all_proxies.append((extracted_proxy, 'http'))
                                all_proxies.append((extracted_proxy, 'https'))
                            seen_proxies.add(extracted_proxy)
                            total_fetched_from_this_source += 1

        else:
            print(f"Định dạng không hỗ trợ: {data_format} for URL {short_url}")
            return []

        if total_fetched_from_this_source > MAX_PROXIES_PER_SOURCE:
            print(f"Đã lấy hơn {MAX_PROXIES_PER_SOURCE} proxy từ {short_url}. Bỏ qua.")
            return []

        print(f"Đã lấy được {total_fetched_from_this_source} proxy từ {short_url}")
        return all_proxies

    except Exception as e:
        print(f"Lỗi khi lấy hoặc xử lý proxy từ {short_url}: {e}")
        return []


def process_proxies():
    """Lấy, kiểm tra và trả về proxy live."""
    print("--- Bắt đầu xử lý proxy ---")
    combined_proxies_to_check = []
    failed_urls = []

    for source in PROXY_SOURCES:
        try:
            proxies = fetch_proxies_from_url(source)
            if proxies is not None:
                combined_proxies_to_check.extend(proxies)
            else:
                failed_urls.append(get_short_url(source["url"]))
        except Exception as e:
            print(f"Lỗi khi lấy proxy từ {get_short_url(source['url'])}: {e}")
            failed_urls.append(get_short_url(source["url"]))

    live_proxies_lists = {'http': [], 'https': []}
    live_proxies_count = {'http': 0, 'https': 0}
    # Lưu trữ thông tin quốc gia và số lượng theo quốc gia
    proxy_info = {}  # Dạng: {proxy: (type, country_code, country_name)}
    country_counts = {}

    if not CHECK_URLS_HTTP and not CHECK_URLS_HTTPS:
        print("Không có URL kiểm tra.")
        return live_proxies_lists, live_proxies_count, failed_urls, proxy_info, country_counts

    with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        futures = [
            executor.submit(determine_proxy_type, proxy, CONNECT_TIMEOUT, CHECK_TIMEOUT)
            for proxy, _ in combined_proxies_to_check
        ]

        for future in as_completed(futures):
            proxy_index = futures.index(future)
            proxy, proxy_type_expected = combined_proxies_to_check[proxy_index]
            try:
                proxy_types, country_code, country_name = future.result()  # Chú ý: proxy_types là một list
                if proxy_types:
                    for proxy_type in proxy_types:  # Duyệt qua danh sách các loại proxy
                        live_proxies_lists[proxy_type].append(proxy)
                        live_proxies_count[proxy_type] += 1
                        # Lưu thông tin (chỉ lưu một lần, với loại đầu tiên)
                        if proxy not in proxy_info:
                            proxy_info[proxy] = (proxy_type, country_code, country_name)
                    # Cập nhật số lượng quốc gia
                    if country_code:
                         country_counts[country_code] = country_counts.get(country_code, 0) + 1

                    print(f"IP: {proxy} ({country_name}) - {', '.join(proxy_types).upper()}") # In ra các loại

            except Exception as e:
                # print(f"Lỗi khi kiểm tra proxy {proxy}: {e}")  # Đã xử lý trong determine_proxy_type
                pass
    print("--- Hoàn tất xử lý proxy ---")
    return live_proxies_lists, live_proxies_count, failed_urls, proxy_info, country_counts


async def upload_to_telegram(bot, live_proxies_lists, live_proxies_count, failed_urls, proxy_info, country_counts, api_keys_info):
    """Tải proxy lên Telegram, với định dạng mới, bao gồm thông tin API."""
    print("--- Bắt đầu upload lên Telegram ---")
    try:
        # --- Tạo thông báo API ---
        api_message = "✨️ TOTAL API LIMIT 1/DAY ✨️\n\n"

        for i, api_key_data in enumerate(api_keys_info):
            status = api_key_data.get('status', 'Unknown')
            status = status.lower()  # Chuyển về chữ thường để so sánh

            # Thêm icon dựa trên trạng thái
            if status in ("trial", "active"):
                status_icon = "✅️"
            elif status == "canceled":
                status_icon = "❌️"
            else:
                status_icon = "❓️"

            api_message += f"{status_icon} STATUS: {status.upper()}\n"  # Icon + STATUS viết hoa
            queries_left = api_key_data.get('queriesLeft', 'N/A')
            expires = api_key_data.get('expires', 'N/A')  # Vẫn giữ trường expires, dù giá trị là N/A
            api_message += f"⚡️API {i+1}: {queries_left} REQUEST | EXPIRES: {expires}\n"

        # --- Tạo thông báo chính (Proxy) ---
        message = api_message + "\n" + "📊 PROXY LIVE (HTTP/HTTPS) 📊\n\n"
        message += f"- HTTP: {live_proxies_count['http']} PROXY\n"
        message += f"- HTTPS: {live_proxies_count['https']} PROXY\n"
        message += "\n🌐 LIST OF PROXY COUNTRY 🌐\n\n"

        # Thêm thống kê quốc gia
        country_list = []
        for code, count in country_counts.items():
            name = "Unknown"  # Giá trị mặc định
            # Tìm tên quốc gia (duyệt qua proxy_info để tìm, tối ưu hơn)
            for _, info in proxy_info.items():
                if info[1] == code:
                    name = info[2]
                    break
            flag = get_country_flag(code)
            country_list.append(f"{flag} {name}: {count}")

        # Chia danh sách quốc gia thành các nhóm (mỗi nhóm 3 phần tử)
        n = 3
        grouped_countries = [country_list[i:i + n] for i in range(0, len(country_list), n)]
        message += " | ".join(grouped_countries[0])  # Dòng đầu tiên
        for group in grouped_countries[1:]:
            message += "\n" + " | ".join(group)  # Các dòng tiếp theo (xuống dòng)

        total_proxies = sum(live_proxies_count.values())
        message += f"\n\n🔥 TOTAL PROXY LIVE: {total_proxies} 🔥\n"

        if failed_urls:
            message += "\n\n⚠️ Các URL sau bị lỗi:\n"
            for url in failed_urls:
                message += f"- {url}\n"

        # --- Gửi tin nhắn văn bản ---
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)

        # --- Upload file HTTP (nếu có) ---
        if live_proxies_lists['http']:
            http_proxy_list_string = "\n".join(live_proxies_lists['http'])
            http_proxy_file = io.StringIO(http_proxy_list_string)
            http_proxy_file.name = "HTTP_LIVE.txt"
            await bot.send_document(chat_id=TELEGRAM_CHAT_ID, document=http_proxy_file,
                                    caption=f"📦 HTTP PROXY LIVE ({live_proxies_count['http']})")
            print("Đã upload file HTTP lên Telegram.")
        else:
            print("Không có proxy HTTP live.")

        # --- Upload file HTTPS (nếu có) ---
        if live_proxies_lists['https']:
            https_proxy_list_string = "\n".join(live_proxies_lists['https'])
            https_proxy_file = io.StringIO(https_proxy_list_string)
            https_proxy_file.name = "HTTPS_LIVE.txt"
            await bot.send_document(chat_id=TELEGRAM_CHAT_ID, document=https_proxy_file,
                                    caption=f"📦 HTTPS PROXY LIVE ({live_proxies_count['https']})")
            print("Đã upload file HTTPS lên Telegram.")
        else:
            print("Không có proxy HTTPS live.")

    except telegram.error.TelegramError as e:
        print(f"Lỗi Telegram: {e}")  # Xử lý lỗi Telegram cụ thể
        # Có thể gửi thông báo lỗi lên Telegram cho admin
        if bot and ADMIN_TELEGRAM_CHAT_ID:
            await send_admin_notification(bot, f"Lỗi Telegram trong upload_to_telegram: {e}")
    except Exception as e:
        print(f"Lỗi chung trong upload_to_telegram: {e}")  # Xử lý các lỗi khác
        if bot and ADMIN_TELEGRAM_CHAT_ID:
              await send_admin_notification(bot, f"Lỗi trong upload_to_telegram: {e}")

async def send_admin_notification(bot, message):
    """Gửi thông báo cho admin."""
    if ADMIN_TELEGRAM_CHAT_ID:
        try:
            await bot.send_message(chat_id=ADMIN_TELEGRAM_CHAT_ID, text=message)
        except telegram.error.TelegramError as e:
            print(f"Lỗi gửi thông báo admin: {e}")

async def main_job():
    """Công việc chính."""
    job_start_time = datetime.now()
    print(f"BẮT ĐẦU: {job_start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    bot = await init_bot()
    if not bot:
        print("Không thể khởi tạo bot.")
        return

    await send_admin_notification(bot, f"🔄 Bắt đầu: {job_start_time.strftime('%Y-%m-%d %H:%M:%S')}")

    try:
        # --- Lấy thông tin API key ---
        api_keys_info = []
        for api_key in DB_IP_API_KEYS:
            api_key_data = get_api_key_info(api_key)
            if api_key_data:
                api_keys_info.append(api_key_data)

        live_proxies_lists, live_proxies_count, failed_urls, proxy_info, country_counts = process_proxies()

        #Truyền api_keys_info vào hàm upload
        await upload_to_telegram(bot, live_proxies_lists, live_proxies_count, failed_urls, proxy_info, country_counts, api_keys_info)


        job_end_time = datetime.now()
        duration = job_end_time - job_start_time
        print(f"--- HOÀN THÀNH: {job_end_time.strftime('%Y-%m-%d %H:%M:%S')}. Thời gian: {duration.total_seconds():.2f}s ---")
        await send_admin_notification(bot, f"✅ Hoàn thành: {duration.total_seconds():.2f}s")


    except Exception as e:
        error_end_time = datetime.now()
        error_duration = error_end_time - job_start_time
        error_message = f"❌ LỖI: {error_end_time.strftime('%Y-%m-%d %H:%M:%S')}. Thời gian: {error_duration.total_seconds():.2f}s. Lỗi: {e}"
        print(error_message)
        await send_admin_notification(bot, error_message)

async def main():
    """Hàm main."""
    print(f"Chạy mỗi {SCHEDULE_INTERVAL_MINUTES} phút. Tối đa {MAX_THREADS} luồng.")
    await main_job()  # Chạy ngay lần đầu
    schedule.every(SCHEDULE_INTERVAL_MINUTES).minutes.do(lambda: asyncio.create_task(main_job()))
    while True:
        schedule.run_pending()
        await asyncio.sleep(60)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Dừng bởi người dùng.")
    except Exception as e:
        print(f"Lỗi: {e}")
