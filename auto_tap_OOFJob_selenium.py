from selenium import webdriver
from selenium.webdriver.common.by import By

from pathlib import Path
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

import time
import random


# =========================================================
# LOG 設定
# =========================================================

LOG_MAX_JOBS = 1000

# 每瀏覽幾筆職缺後做一次記憶體清理。
# 不建立新分頁、不切換分頁，因此不會因清理動作搶視窗焦點。
MEMORY_CLEANUP_INTERVAL = 20

# 阻擋對職缺文字解析沒有必要、但容易增加 Chrome RAM 的大型資源。
BLOCK_HEAVY_RESOURCES = True

# 目前這支 Python Script 所在目錄
SCRIPT_DIR = Path(__file__).resolve().parent

# log 資料夾
LOG_DIR = SCRIPT_DIR / "log"


def ensure_log_directory():
    """
    確認目前 Python Script 目錄下是否存在 log 資料夾。

    不存在：
        自動建立

    存在：
        直接使用
    """

    LOG_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    print(f"LOG 資料夾：{LOG_DIR}")


def create_log_file():
    """
    建立新的 LOG 檔案。

    檔名格式：

    OOF_yyyyMMddHHmmSS.log

    例如：

    OOF_20260809031520.log
    """

    while True:

        timestamp = datetime.now().strftime(
            "%Y%m%d%H%M%S"
        )

        log_path = (
                LOG_DIR
                / f"OOF_{timestamp}.log"
        )

        # 避免極端情況下同一秒建立兩個 LOG
        if not log_path.exists():
            break

        time.sleep(1)

    # 建立空 LOG
    log_path.touch(
        exist_ok=False
    )

    print(
        f"建立新的 LOG：{log_path.name}"
    )

    return log_path


def write_log(log_path, message=""):
    """
    寫入 LOG。

    使用 UTF-8，
    避免繁體中文亂碼。
    """

    with open(
            log_path,
            "a",
            encoding="utf-8"
    ) as file:

        file.write(
            message + "\n"
        )


def write_job_log(
        log_path,
        job_no,
        job_name,
        location,
        technologies,
        education,
        salary,
        href
):
    """
    將一筆職缺資訊寫入 LOG。
    """

    separator = "=" * 100

    lines = [
        separator,
        f"職缺編號：{job_no}",
        f"職缺名稱：{job_name}",
        f"工作地點：{location}",
        f"需要技術：{technologies}",
        f"學歷限制：{education}",
        f"薪資範圍：{salary}",
        f"職缺網址：{href}",
        separator,
        ""
    ]

    with open(
            log_path,
            "a",
            encoding="utf-8"
    ) as file:

        for line in lines:
            file.write(
                line + "\n"
            )


# =========================================================
# Chrome
# =========================================================

def attach_to_existing_chrome():
    """
    接上已經手動開啟、
    且通過 Cloudflare 驗證的 Chrome。

    Chrome 必須使用：

    --remote-debugging-port=9222

    啟動。
    """

    options = webdriver.ChromeOptions()

    options.add_experimental_option(
        "debuggerAddress",
        "127.0.0.1:9222"
    )

    return webdriver.Chrome(
        options=options
    )


def configure_low_memory_mode(driver):
    """
    啟用低記憶體模式。

    這些操作不會開新分頁，也不會把 Chrome 視窗拉到前景：
    1. 關閉瀏覽器網路快取
    2. 阻擋圖片 / 影片 / 字型等非必要大型資源

    注意：
    - 不清 Cookie / LocalStorage / SessionStorage
    - 不影響既有登入狀態
    """

    try:
        driver.execute_cdp_cmd(
            "Network.enable",
            {}
        )

        driver.execute_cdp_cmd(
            "Network.setCacheDisabled",
            {
                "cacheDisabled": True
            }
        )

        if BLOCK_HEAVY_RESOURCES:
            driver.execute_cdp_cmd(
                "Network.setBlockedURLs",
                {
                    "urls": [
                        "*.png",
                        "*.jpg",
                        "*.jpeg",
                        "*.gif",
                        "*.webp",
                        "*.avif",
                        "*.svg",
                        "*.mp4",
                        "*.webm",
                        "*.mov",
                        "*.avi",
                        "*.woff",
                        "*.woff2",
                        "*.ttf",
                        "*.otf"
                    ]
                }
            )

        print(
            "Chrome 低記憶體模式已啟用"
        )

    except Exception as e:
        print(
            f"啟用 Chrome 低記憶體模式失敗："
            f"{type(e).__name__}: {e}"
        )


def cleanup_browser_memory(driver):
    """
    清除目前分頁可安全回收的瀏覽器記憶體。

    不關閉分頁、不建立新分頁、不切換分頁，
    因此不會因這個函式把 Chrome 視窗搶到前景。
    """

    print(
        "  執行 Chrome 記憶體清理..."
    )

    # 清 Browser Cache。
    try:
        driver.execute_cdp_cmd(
            "Network.clearBrowserCache",
            {}
        )
    except Exception:
        pass

    # 要求 V8 / Renderer 執行垃圾回收。
    try:
        driver.execute_cdp_cmd(
            "HeapProfiler.collectGarbage",
            {}
        )
    except Exception:
        pass

    # 部分 Chrome 版本支援這個 Memory Domain 指令。
    # 不支援時直接忽略即可。
    try:
        driver.execute_cdp_cmd(
            "Memory.forciblyPurgeJavaScriptMemory",
            {}
        )
    except Exception:
        pass


# 使用目前分頁
def get_current_page(driver):
    """
    直接使用 Selenium 目前所控制的 Chrome 分頁。

    不檢查網址。
    不寫死 求職網網址。
    不掃描其他分頁。
    不使用 switch_to.window() 去尋找特定頁面。

    使用方式：
    1. 手動開啟 Chrome
    2. 切到希望程式開始收集職缺的頁面
    3. 再執行這支 Python
    """

    try:

        current_handle = driver.current_window_handle

    except Exception as e:

        raise RuntimeError(
            f"無法取得目前 Chrome 分頁："
            f"{type(e).__name__}: {e}"
        )

    print()

    print(
        "=" * 100
    )

    print(
        "使用目前 Chrome 分頁"
    )

    print(
        f"分頁 Handle："
        f"{current_handle}"
    )

    print(
        f"頁面標題："
        f"{driver.title}"
    )

    print(
        f"頁面網址："
        f"{driver.current_url}"
    )

    print(
        "=" * 100
    )

    print()

    return current_handle


# =========================================================
# 求職網 職缺列表
# =========================================================

CARD_SELECTORS = [

    # PC
    "div.job-summary[data-job-no]",

    # Mobile
    "div.job-mobile[data-job-no]",
]


LINK_SELECTORS = [

    # PC
    "a.info-job__text",

    # Mobile
    "a.info-job",

    # 備用
    "a.js-job-link",
]


def find_cards(driver):
    """
    找出目前畫面上的職缺卡片。
    """

    for selector in CARD_SELECTORS:

        cards = driver.find_elements(
            By.CSS_SELECTOR,
            selector
        )

        if cards:

            return cards, selector

    return [], None


def find_link_in_card(card):
    """
    從職缺卡片中找到職缺 URL。
    """

    for selector in LINK_SELECTORS:

        try:

            link_el = card.find_element(
                By.CSS_SELECTOR,
                selector
            )

            href = link_el.get_attribute(
                "href"
            )

            if href:

                return href

        except Exception:

            continue

    return None

def scroll_to_bottom_and_trigger_load(driver):
    """
    模擬比較自然的方式接近頁面底部，
    避免一次瞬間到底導致 Lazy Load / IntersectionObserver 沒有觸發。

    流程：
    1. 分段往下
    2. 接近底部時放慢
    3. 到達底部等待
    4. 往上回彈一小段
    5. 再次回到底部
    """

    # =====================================================
    # 1. 取得目前位置
    # =====================================================

    current_y = driver.execute_script(
        "return window.pageYOffset;"
    )

    page_height = driver.execute_script(
        "return document.body.scrollHeight;"
    )

    viewport_height = driver.execute_script(
        "return window.innerHeight;"
    )

    bottom_y = page_height - viewport_height

    print(
        f"  目前位置：{int(current_y)} / "
        f"{int(bottom_y)}"
    )

    # =====================================================
    # 2. 分段往底部移動
    # =====================================================

    while current_y < bottom_y:

        remaining = bottom_y - current_y

        # 離底部還很遠
        if remaining > 2500:
            distance = random.randint(
                700,
                1100
            )

        # 開始接近底部
        elif remaining > 1000:
            distance = random.randint(
                400,
                700
            )

        # 最後一小段慢慢滑
        else:
            distance = random.randint(
                150,
                350
            )

        driver.execute_script(
            "window.scrollBy(0, arguments[0]);",
            distance
        )

        time.sleep(
            random.uniform(
                0.15,
                0.4
            )
        )

        current_y = driver.execute_script(
            "return window.pageYOffset;"
        )

        # 頁面可能在滾動期間又增加高度
        page_height = driver.execute_script(
            "return document.body.scrollHeight;"
        )

        viewport_height = driver.execute_script(
            "return window.innerHeight;"
        )

        bottom_y = (
                page_height
                - viewport_height
        )

    # =====================================================
    # 3. 確實到底
    # =====================================================

    driver.execute_script(
        "window.scrollTo(0, document.body.scrollHeight);"
    )

    bottom_pause = random.uniform(
        1.0,
        2.0
    )

    print(
        f"  已抵達底部，等待 "
        f"{bottom_pause:.1f} 秒"
    )

    time.sleep(
        bottom_pause
    )

    # =====================================================
    # 4. 往上回彈
    #
    # 有些網站如果第一次到底沒有觸發 lazy load，
    # 往上一點再回到底部比較容易觸發
    # =====================================================

    bounce_distance = random.randint(
        400,
        800
    )

    driver.execute_script(
        "window.scrollBy(0, arguments[0]);",
        -bounce_distance
    )

    bounce_pause = random.uniform(
        0.6,
        1.2
    )

    print(
        f"  往上回彈 {bounce_distance}px，"
        f"等待 {bounce_pause:.1f} 秒"
    )

    time.sleep(
        bounce_pause
    )

    # =====================================================
    # 5. 再次慢慢到底
    # =====================================================

    driver.execute_script(
        """
        window.scrollTo({
            top: document.body.scrollHeight,
            behavior: 'smooth'
        });
        """
    )

    time.sleep(
        random.uniform(
            1.0,
            1.8
        )
    )

    # 最後保險
    driver.execute_script(
        "window.scrollTo(0, document.body.scrollHeight);"
    )


def get_page_number(url):
    """
    取得 URL 中的 page 參數。
    沒有 page 時視為第 1 頁。
    """
    parts = urlsplit(url)

    query = dict(
        parse_qsl(
            parts.query,
            keep_blank_values=True
        )
    )

    try:
        return int(
            query.get(
                "page",
                "1"
            )
        )
    except ValueError:
        return 1


def set_page_number(
        url,
        page_number
):
    """
    保留目前 求職網 搜尋條件，
    只修改 page= 分頁參數。
    """
    parts = urlsplit(url)

    query_pairs = parse_qsl(
        parts.query,
        keep_blank_values=True
    )

    new_pairs = []
    page_replaced = False

    for key, value in query_pairs:

        if key == "page":

            new_pairs.append(
                (
                    "page",
                    str(page_number)
                )
            )

            page_replaced = True

        else:

            new_pairs.append(
                (
                    key,
                    value
                )
            )

    if not page_replaced:

        new_pairs.append(
            (
                "page",
                str(page_number)
            )
        )

    new_query = urlencode(
        new_pairs,
        doseq=True
    )

    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            new_query,
            parts.fragment
        )
    )


def extract_jobs_from_current_page(driver):
    """
    一次從目前 DOM 取出整頁職缺的：

    job_no
    href

    不再對每一張 WebElement 分別呼叫：
    get_attribute()
    find_element()
    get_attribute()

    可大幅降低 ChromeDriver 與 Renderer 之間的大量 IPC 呼叫。
    """
    jobs = driver.execute_script(
        """
        const cardSelectors = arguments[0];
        const linkSelectors = arguments[1];

        let cards = [];

        for (const selector of cardSelectors) {

            const found = Array.from(
                document.querySelectorAll(selector)
            );

            if (found.length > 0) {
                cards = found;
                break;
            }
        }

        return cards.map(card => {

            const jobNo = card.getAttribute(
                'data-job-no'
            );

            let link = null;

            for (const selector of linkSelectors) {

                link = card.querySelector(
                    selector
                );

                if (link) {
                    break;
                }
            }

            return {
                jobNo: jobNo,
                href: link ? link.href : null
            };
        });
        """,
        CARD_SELECTORS,
        LINK_SELECTORS
    )

    result = []

    for job in jobs:

        job_no = job.get(
            "jobNo"
        )

        href = job.get(
            "href"
        )

        if not job_no:
            continue

        if not href:
            continue

        result.append(
            (
                str(job_no),
                href
            )
        )

    return result


def wait_for_job_cards(
        driver,
        timeout=10
):
    """
    等待目前頁面的職缺卡片出現。

    回傳實際找到的 selector。
    找不到則回傳 None。
    """
    start_time = time.time()

    while (
            time.time() - start_time
            < timeout
    ):

        cards, selector = find_cards(
            driver
        )

        if cards:
            return selector

        time.sleep(
            0.5
        )

    return None


def collect_job_links(
        driver,
        max_jobs=1000,
        max_pages=100,
        pause_range=(1.2, 2.5)
):
    """
    使用 求職網 本身的 page= 分頁收集職缺。

    已完全取消原本的：
    1. 無限往下 Scroll
    2. scrollHeight 判斷
    3. bounce 回彈
    4. smooth scroll
    5. 每張 card 個別 find_element()

    流程：
    1. 取得目前搜尋頁 URL
    2. 讀取目前 page= 頁碼
    3. 從目前頁開始逐頁修改 page=
    4. 每一頁一次從 DOM 取得所有 job_no / href
    5. 收滿 max_jobs 或連續 3 頁沒有新職缺就停止
    """

    print(
        "目前頁面網址：",
        driver.current_url
    )

    print(
        "目前頁面標題：",
        driver.title
    )

    base_url = driver.current_url

    start_page = get_page_number(
        base_url
    )

    print(
        f"從第 {start_page} 頁開始收集"
    )

    print(
        "=" * 100
    )

    seen = {}

    stagnant_pages = 0

    for offset in range(
            max_pages
    ):

        if len(seen) >= max_jobs:

            print()

            print(
                "=" * 100
            )

            print(
                f"已收集 {len(seen)} 筆職缺，"
                f"達到上限 {max_jobs} 筆。"
            )

            print(
                "=" * 100
            )

            break

        current_page_number = (
                start_page
                + offset
        )

        target_url = set_page_number(
            base_url,
            current_page_number
        )

        print()

        print(
            f"[Page {current_page_number}] "
            f"目前已收集 "
            f"{len(seen)}/{max_jobs} 筆"
        )

        # =============================================
        # 只有 URL 不同時才切頁
        # =============================================

        if driver.current_url != target_url:

            try:

                driver.get(
                    target_url
                )

            except Exception as e:

                print(
                    f"  切換頁面失敗："
                    f"{type(e).__name__}: "
                    f"{e}"
                )

                stagnant_pages += 1

                if stagnant_pages >= 3:

                    print(
                        "  連續 3 頁無法取得有效內容，停止收集。"
                    )

                    break

                continue

        # =============================================
        # 等職缺卡片出現
        # =============================================

        used_selector = wait_for_job_cards(
            driver,
            timeout=10
        )

        if used_selector is None:

            print(
                "  找不到職缺卡片"
            )

            stagnant_pages += 1

            if stagnant_pages >= 3:

                print(
                    "  連續 3 頁沒有有效職缺，停止收集。"
                )

                break

            continue

        print(
            f"  使用卡片選擇器："
            f"{used_selector}"
        )

        # =============================================
        # 稍微等待前端 DOM 穩定
        # =============================================

        settle_pause = random.uniform(
            0.8,
            1.5
        )

        time.sleep(
            settle_pause
        )

        # =============================================
        # 一次從 DOM 抓完整頁 job_no / href
        # =============================================

        jobs = extract_jobs_from_current_page(
            driver
        )

        print(
            f"  此頁找到 "
            f"{len(jobs)} 張職缺卡片"
        )

        count_before = len(
            seen
        )

        for job_no, href in jobs:

            if job_no in seen:
                continue

            seen[job_no] = href

            if len(seen) >= max_jobs:
                break

        new_count = (
                len(seen)
                - count_before
        )

        print(
            f"  本頁新增 "
            f"{new_count} 筆"
        )

        print(
            f"  目前總數："
            f"{len(seen)}/{max_jobs}"
        )

        # =============================================
        # 只以「有沒有新增 job_no」判斷是否停滯
        # 不再使用頁面高度
        # =============================================

        if new_count == 0:

            stagnant_pages += 1

            print(
                f"  本頁沒有新增職缺 "
                f"({stagnant_pages}/3)"
            )

        else:

            stagnant_pages = 0

        if stagnant_pages >= 3:

            print()

            print(
                "=" * 100
            )

            print(
                "連續 3 頁都沒有新增職缺，停止收集。"
            )

            print(
                "=" * 100
            )

            break

        # =============================================
        # 切下一頁前稍微等待
        # =============================================

        if len(seen) < max_jobs:

            page_pause = random.uniform(
                *pause_range
            )

            print(
                f"  前往下一頁前等待 "
                f"{page_pause:.1f} 秒"
            )

            time.sleep(
                page_pause
            )

    # =============================================
    # 最終保險
    # =============================================

    if len(seen) > max_jobs:

        seen = dict(
            list(
                seen.items()
            )[:max_jobs]
        )

    print()

    print(
        "=" * 100
    )

    print(
        f"職缺連結收集完成，"
        f"總共 {len(seen)} 筆"
    )

    print(
        "=" * 100
    )

    return seen


# =========================================================
# 通用文字處理
# =========================================================

def clean_text(text):
    """
    清理文字。
    """

    if text is None:
        return ""

    return " ".join(
        text.split()
    ).strip()


def safe_get_text(
        driver,
        selectors
):
    """
    依序嘗試多個 CSS Selector。

    找到第一個有文字的元素就回傳。
    """

    for selector in selectors:

        try:

            elements = driver.find_elements(
                By.CSS_SELECTOR,
                selector
            )

            for element in elements:

                text = clean_text(
                    element.text
                )

                if text:

                    return text

        except Exception:

            continue

    return None


# =========================================================
# 求職網 詳細頁文字解析
# =========================================================

def get_page_lines(driver):
    """
    將整個 求職網 職缺頁面拆成一行一行文字。

    主要作為 selector 抓不到資料時的備援。
    """

    try:

        body = driver.find_element(
            By.TAG_NAME,
            "body"
        )

        text = body.text

        lines = []

        for line in text.splitlines():

            line = clean_text(
                line
            )

            if line:

                lines.append(
                    line
                )

        return lines

    except Exception:

        return []


def extract_value_after_label(
        lines,
        labels,
        max_lookahead=3
):
    """
    從整頁文字中找：

    工作待遇
    月薪 50,000~70,000

    或：

    工作待遇：月薪 50,000~70,000

    這類資料。
    """

    for index, line in enumerate(
            lines
    ):

        for label in labels:

            # =============================================
            # 情況 1
            #
            # 工作待遇：月薪 50000
            # =============================================

            if line.startswith(
                    label + "："
            ):

                value = line[
                    len(label) + 1:
                ]

                value = clean_text(
                    value
                )

                if value:

                    return value

            # =============================================
            # 情況 2
            #
            # 工作待遇
            # 月薪 50000
            # =============================================

            if line == label:

                for offset in range(
                        1,
                        max_lookahead + 1
                ):

                    next_index = (
                            index + offset
                    )

                    if next_index >= len(
                            lines
                    ):
                        break

                    value = clean_text(
                        lines[next_index]
                    )

                    if value:

                        return value

    return None


def extract_multi_value_after_label(
        lines,
        labels,
        max_lines=3
):
    """
    用於擅長工具 / 工作技能這種可能多行的欄位。

    例如：

    擅長工具
    Java
    Spring Boot
    SQL
    """

    stop_labels = {

        "工作技能",
        "其他條件",
        "具備駕照",
        "具備證照",
        "歡迎身分",
        "公司福利",
        "聯絡方式",
        "工作經歷",
        "學歷要求",
        "科系要求",
        "語文條件",
        "上班時段",
        "休假制度",
        "可上班日",
        "需求人數",
        "工作地點",
        "工作待遇",
        "職務類別"
    }

    for index, line in enumerate(
            lines
    ):

        for label in labels:

            # =============================================
            # 同一行
            # =============================================

            if line.startswith(
                    label + "："
            ):

                value = clean_text(
                    line[
                        len(label) + 1:
                    ]
                )

                if value:

                    return value

            # =============================================
            # 下一行開始
            # =============================================

            if line == label:

                values = []

                for offset in range(
                        1,
                        max_lines + 1
                ):

                    next_index = (
                            index + offset
                    )

                    if next_index >= len(
                            lines
                    ):
                        break

                    value = clean_text(
                        lines[next_index]
                    )

                    if not value:
                        continue

                    if value in stop_labels:
                        break

                    values.append(
                        value
                    )

                if values:

                    return "、".join(
                        values
                    )

    return None


# =========================================================
# 抓職缺名稱
# =========================================================

def extract_job_name(
        driver,
        lines
):
    """
    抓職缺名稱。
    """

    selectors = [

        # 常見 H1
        "h1",

        # 可能的職缺名稱 class
        "h1[class*='job']",

        "[data-qa='job-title']",
    ]

    value = safe_get_text(
        driver,
        selectors
    )

    if value:

        return value

    # 最後備援
    if driver.title:

        title = driver.title

        # 避免整個網頁 title 太長
        if "｜" in title:

            title = title.split(
                "｜"
            )[0]

        return clean_text(
            title
        )

    return "未取得"


# =========================================================
# 工作地點
# =========================================================

def extract_job_location(
        driver,
        lines
):
    """
    抓工作地點。
    """

    value = extract_value_after_label(
        lines,
        [
            "工作地點",
            "上班地點"
        ]
    )

    if value:

        return value

    return "未取得"


# =========================================================
# 學歷要求
# =========================================================

def extract_education(
        driver,
        lines
):
    """
    抓學歷要求。
    """

    value = extract_value_after_label(
        lines,
        [
            "學歷要求",
            "學歷"
        ]
    )

    if value:

        return value

    return "未取得"


# =========================================================
# 薪資
# =========================================================

def extract_salary(
        driver,
        lines
):
    """
    抓工作待遇 / 薪資。
    """

    value = extract_value_after_label(
        lines,
        [
            "工作待遇",
            "薪資待遇",
            "薪資"
        ]
    )

    if value:

        return value

    return "未取得"


# =========================================================
# 技術
# =========================================================

def extract_technologies(
        driver,
        lines
):
    """
    求職網 上技術相關資訊通常可能存在：

    擅長工具
    工作技能

    所以兩個都抓，
    最後合併。
    """

    technologies = []

    # =============================================
    # 擅長工具
    # =============================================

    tools = extract_multi_value_after_label(
        lines,
        [
            "擅長工具",
            "電腦專長"
        ],
        max_lines=5
    )

    if tools:

        technologies.append(
            tools
        )

    # =============================================
    # 工作技能
    # =============================================

    skills = extract_multi_value_after_label(
        lines,
        [
            "工作技能"
        ],
        max_lines=5
    )

    if skills:

        technologies.append(
            skills
        )

    if technologies:

        # 去除完全重複
        unique_values = []

        for value in technologies:

            if value not in unique_values:

                unique_values.append(
                    value
                )

        return "、".join(
            unique_values
        )

    return "未取得"


# =========================================================
# 一次取得完整職缺資訊
# =========================================================

def extract_job_detail(
        driver
):
    """
    從目前開啟的 求職網 職缺詳細頁取得：

    職缺名稱
    工作地點
    技術
    學歷
    薪資
    """

    lines = get_page_lines(
        driver
    )

    job_name = extract_job_name(
        driver,
        lines
    )

    location = extract_job_location(
        driver,
        lines
    )

    technologies = extract_technologies(
        driver,
        lines
    )

    education = extract_education(
        driver,
        lines
    )

    salary = extract_salary(
        driver,
        lines
    )

    return {
        "job_name": job_name,
        "location": location,
        "technologies": technologies,
        "education": education,
        "salary": salary,
    }

def wait_for_new_content(
        driver,
        old_height,
        timeout=5
):
    """
    等待頁面因 Lazy Load 而增加高度。

    有增加：
        return 新高度

    timeout 都沒增加：
        return 原本高度
    """

    start_time = time.time()

    while (
            time.time() - start_time
            < timeout
    ):

        new_height = driver.execute_script(
            "return document.body.scrollHeight"
        )

        if new_height > old_height:

            print(
                f"  偵測到頁面高度增加："
                f"{old_height} -> {new_height}"
            )

            return new_height

        time.sleep(
            0.5
        )

    return driver.execute_script(
        "return document.body.scrollHeight"
    )

# =========================================================
# 模擬閱讀
# =========================================================

def simulate_reading(
        driver,
        total_duration_range=(10, 30)
):
    """
    模擬閱讀：

    大滾動
    小滾動
    往回滾
    停頓
    """

    total_duration = random.uniform(
        *total_duration_range
    )

    elapsed = 0

    initial_pause = random.uniform(
        1,
        2
    )

    time.sleep(
        initial_pause
    )

    elapsed += initial_pause

    print(
        f"  預計閱讀："
        f"{total_duration:.1f} 秒"
    )

    while elapsed < total_duration:

        action = random.choices(

            [
                "scroll_down",
                "scroll_down_small",
                "scroll_up",
                "pause"
            ],

            weights=[
                45,
                30,
                10,
                15
            ]

        )[0]

        # =============================================
        # 大幅往下
        # =============================================

        if action == "scroll_down":

            distance = random.randint(
                300,
                600
            )

            driver.execute_script(
                "window.scrollBy(0, arguments[0]);",
                distance
            )

        # =============================================
        # 小幅往下
        # =============================================

        elif action == "scroll_down_small":

            distance = random.randint(
                100,
                250
            )

            driver.execute_script(
                "window.scrollBy(0, arguments[0]);",
                distance
            )

        # =============================================
        # 往上
        # =============================================

        elif action == "scroll_up":

            distance = random.randint(
                100,
                300
            )

            driver.execute_script(
                "window.scrollBy(0, arguments[0]);",
                -distance
            )

        # =============================================
        # 停頓
        # =============================================

        step_pause = random.uniform(
            1.2,
            3.5
        )

        time.sleep(
            step_pause
        )

        elapsed += step_pause


# =========================================================
# 瀏覽職缺
# =========================================================

def visit_jobs(
        driver,
        job_links,
        view_duration_range=(10, 30),
        batch_size_range=(10, 15),
        long_break_range=(30, 60)
):
    """
    逐筆瀏覽職缺。

    這個版本不再每一筆建立 / 關閉新的 Tab。

    流程：
    1. collect_job_links() 先把所有職缺網址收集完成
    2. 直接使用目前這一個 Chrome Tab
    3. 每筆透過 driver.get(href) 切換到下一個職缺
    4. 不使用 new_window()
    5. 不使用 close()
    6. 不使用 switch_to.window()

    這樣可以大幅降低 macOS 因為 Chrome Tab 開關、
    切換而把 Chrome 視窗強制拉到前景的情況。

    每筆抓：
        職缺名稱
        工作地點
        技術
        學歷
        薪資

    每 50 筆：
        建立新的 LOG
    """

    next_batch_target = random.randint(
        *batch_size_range
    )

    count_since_break = 0

    total_jobs = len(
        job_links
    )

    # =============================================
    # LOG 目前筆數
    # =============================================

    jobs_in_current_log = 0

    # =============================================
    # 建立第一個 LOG
    # =============================================

    current_log = create_log_file()

    print()

    print(
        "=" * 100
    )

    print(
        "職缺連結已全部收集完成。"
    )

    print(
        "接下來使用同一個 Chrome Tab 依序瀏覽，"
        "不再建立 / 關閉新分頁。"
    )

    print(
        "=" * 100
    )

    for idx, (
            job_no,
            href
    ) in enumerate(
        job_links.items(),
        1
    ):

        # =========================================
        # 每 50 筆建立新 LOG
        # =========================================

        if jobs_in_current_log >= LOG_MAX_JOBS:

            print()

            print(
                "=" * 100
            )

            print(
                "目前 LOG 已達 50 筆，"
                "建立新的 LOG"
            )

            print(
                "=" * 100
            )

            current_log = (
                create_log_file()
            )

            jobs_in_current_log = 0

        print()

        print(
            "=" * 100
        )

        print(
            f"[{idx}/{total_jobs}] "
            f"瀏覽職缺：{job_no}"
        )

        print(
            f"URL：{href}"
        )

        try:

            # =====================================
            # 使用目前同一個 Tab 開啟職缺。
            #
            # 使用 driver.get() 讓 Selenium / ChromeDriver
            # 正常等待 navigation 完成，避免用 location.replace()
            # 造成頁面切換期間的 execution context / readyState race。
            #
            # 不建立新分頁、不關閉分頁、不切換分頁。
            # =====================================

            driver.get(
                href
            )

            # =====================================
            # 等待初步載入
            # =====================================

            initial_load_pause = random.uniform(
                1.5,
                3
            )

            print(
                f"  等待頁面載入..."
                f"{initial_load_pause:.1f} 秒"
            )

            time.sleep(
                initial_load_pause
            )

            # =====================================
            # 確保從頁面頂部開始
            # =====================================

            driver.execute_script(
                "window.scrollTo(0, 0);"
            )

            # =====================================
            # 抓取職缺詳細資料
            # =====================================

            detail = extract_job_detail(
                driver
            )

            job_name = (
                detail["job_name"]
            )

            location = (
                detail["location"]
            )

            technologies = (
                detail["technologies"]
            )

            education = (
                detail["education"]
            )

            salary = (
                detail["salary"]
            )

            # =====================================
            # Console 顯示
            # =====================================

            print(
                f"職缺名稱："
                f"{job_name}"
            )

            print(
                f"工作地點："
                f"{location}"
            )

            print(
                f"需要技術："
                f"{technologies}"
            )

            print(
                f"學歷限制："
                f"{education}"
            )

            print(
                f"薪資範圍："
                f"{salary}"
            )

            print(
                "=" * 100
            )

            # =====================================
            # 寫入 LOG
            # =====================================

            write_job_log(

                current_log,

                job_no=job_no,

                job_name=job_name,

                location=location,

                technologies=technologies,

                education=education,

                salary=salary,

                href=href
            )

            jobs_in_current_log += 1

            print(
                f"  已寫入 LOG："
                f"{current_log.name}"
            )

            print(
                f"  此 LOG 已有 "
                f"{jobs_in_current_log}/"
                f"{LOG_MAX_JOBS} 筆"
            )

            # =====================================
            # 模擬閱讀
            # =====================================

            simulate_reading(
                driver,
                view_duration_range
            )

            print(
                "  瀏覽完成"
            )

            # =====================================
            # 定期清理 Chrome 記憶體
            #
            # 不開新分頁、不關閉分頁、不切換分頁。
            # =====================================

            if (
                    MEMORY_CLEANUP_INTERVAL > 0
                    and idx % MEMORY_CLEANUP_INTERVAL == 0
            ):
                cleanup_browser_memory(
                    driver
                )

        except Exception as e:

            print(
                f"  瀏覽失敗："
                f"{type(e).__name__}: "
                f"{e}"
            )

            # =====================================
            # 失敗資訊也寫 LOG
            # =====================================

            write_log(
                current_log,
                "=" * 100
            )

            write_log(
                current_log,
                f"職缺編號：{job_no}"
            )

            write_log(
                current_log,
                f"職缺網址：{href}"
            )

            write_log(
                current_log,
                "狀態：讀取失敗"
            )

            write_log(
                current_log,
                (
                    f"錯誤："
                    f"{type(e).__name__}: "
                    f"{e}"
                )
            )

            write_log(
                current_log,
                "=" * 100
            )

            write_log(
                current_log
            )

            # 失敗也算一筆
            jobs_in_current_log += 1

        # =========================================
        # 單筆瀏覽之間隨機等待
        # =========================================

        count_since_break += 1

        if idx < total_jobs:

            short_break = random.uniform(
                2,
                5
            )

            print(
                f"下一筆前等待："
                f"{short_break:.1f} 秒"
            )

            time.sleep(
                short_break
            )

        # =========================================
        # 每一批長休息
        # =========================================

        if (
                count_since_break
                >= next_batch_target
                and idx < total_jobs
        ):

            break_duration = (
                random.uniform(
                    *long_break_range
                )
            )

            print()

            print(
                f"已連續瀏覽 "
                f"{count_since_break} 筆"
            )

            print(
                f"休息中..."
                f"約 {break_duration:.0f} 秒"
            )

            time.sleep(
                break_duration
            )

            count_since_break = 0

            next_batch_target = (
                random.randint(
                    *batch_size_range
                )
            )

# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":

    print(
        "=" * 100
    )

    print(
        "OOF Selenium 自動職缺瀏覽程式"
    )

    print(
        "=" * 100
    )

    # =====================================================
    # 1. 確認 LOG 資料夾
    # =====================================================

    print()

    print(
        "檢查 LOG 資料夾..."
    )

    ensure_log_directory()

    print(
        "LOG 資料夾確認完成"
    )

    # =====================================================
    # 2. 連線 Chrome
    # =====================================================

    print()

    print(
        "連接 Chrome..."
    )

    driver = (
        attach_to_existing_chrome()
    )

    print(
        "Chrome 連接成功"
    )

    configure_low_memory_mode(
        driver
    )

    # =====================================================
    # 3. 直接使用目前分頁
    #
    # 不再：
    # - 掃描所有分頁
    # - 比對固定網址
    # - switch_to.window() 尋找職缺列表
    #
    # 執行程式前，
    # 手動停在希望開始收集的搜尋結果頁即可。
    # =====================================================

    current_handle = get_current_page(
        driver
    )

    # =====================================================
    # 4. 收集職缺
    # =====================================================

    print(
        "開始收集職缺連結..."
    )

    job_links = (
        collect_job_links(
            driver
        )
    )

    print()

    print(
        f"共收集到 "
        f"{len(job_links)} 筆職缺"
    )

    # =====================================================
    # 5. 判斷有沒有職缺
    # =====================================================

    if len(job_links) == 0:

        print()

        print(
            "沒有收集到任何職缺。"
        )

        print(
            "請確認："
        )

        print(
            "1. 執行程式前是否已停在正確的職缺搜尋結果頁"
        )

        print(
            "2. Cloudflare 是否已通過"
        )

        print(
            "3. 求職網站 DOM 是否改版"
        )

    else:

        # =================================================
        # 6. 收集完成後建立「一次」新的瀏覽分頁
        #
        # 目的：
        # - 原搜尋列表頁跑過大量 page= 分頁
        # - 可能累積 DOM / JS / Cache / Renderer Memory
        # - 收集完成後直接關閉舊列表頁
        #
        # 後續所有職缺只使用這個新分頁。
        # 不再建立其他 Tab。
        # =================================================

        print()

        print(
            "=" * 100
        )

        print(
            "職缺連結收集完成"
        )

        print(
            "建立新的瀏覽分頁，"
            "並關閉原本職缺列表分頁..."
        )

        print(
            "=" * 100
        )

        # 收集完成時目前所在的搜尋列表分頁
        job_list_handle = (
            driver.current_window_handle
        )

        # -------------------------------------------------
        # 只建立這一次新 Tab
        #
        # Selenium 4 的 new_window("tab") 會：
        # 1. 建立新分頁
        # 2. 自動切換到新分頁
        #
        # 後續不再 new_window()
        # -------------------------------------------------

        driver.switch_to.new_window(
            "tab"
        )

        browse_handle = (
            driver.current_window_handle
        )

        try:

            driver.get(
                "about:blank"
            )

        except Exception:
            pass

        # -------------------------------------------------
        # 關閉舊搜尋列表分頁
        #
        # 這裡只在「收集完成」時做一次分頁切換。
        # 後續 visit_jobs() 不會再切換分頁。
        # -------------------------------------------------

        try:

            driver.switch_to.window(
                job_list_handle
            )

            driver.close()

            print(
                "原職缺列表分頁已關閉"
            )

        except Exception as e:

            print(
                f"關閉原職缺列表分頁失敗："
                f"{type(e).__name__}: "
                f"{e}"
            )

        # -------------------------------------------------
        # 回到剛才建立的新瀏覽分頁
        #
        # 這是最後一次 switch_to.window()。
        # 後續全部都在同一分頁 driver.get(href)。
        # -------------------------------------------------

        driver.switch_to.window(
            browse_handle
        )

        # 新建立的瀏覽 Tab 重新套用低記憶體設定。
        configure_low_memory_mode(
            driver
        )

        # 給 Chrome 一點時間處理舊 Renderer
        time.sleep(
            2
        )

        print()

        print(
            "新的瀏覽分頁建立完成"
        )

        print(
            "後續全部職缺都會使用同一個分頁。"
        )

        print(
            "不會再建立新的 Tab。"
        )

        print()

        print(
            "開始逐一瀏覽職缺..."
        )

        # =================================================
        # 7. 開始瀏覽
        #
        # 後續：
        #
        # job1
        #   ↓
        # driver.get()
        #   ↓
        # job2
        #   ↓
        # driver.get()
        #   ↓
        # job3
        #
        # 始終使用同一個 Tab。
        # =================================================

        visit_jobs(

            driver,

            job_links,

            # 每篇瀏覽時間
            view_duration_range=(
                10,
                30
            ),

            # 每幾篇休息
            batch_size_range=(
                10,
                15
            ),

            # 長休息時間
            long_break_range=(
                30,
                60
            )
        )

        print()

        print(
            "=" * 100
        )

        print(
            "全部瀏覽完成"
        )

        print(
            f"LOG 位置："
            f"{LOG_DIR}"
        )

        print(
            "=" * 100
        )


# =========================================================
# 使用方式
# =========================================================
#
# 1.
# 關閉所有原本 Chrome
#
# 2.
# PowerShell：
r"""
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
    --remote-debugging-port=9222 `
    --user-data-dir="C:\Users\User\selenium-chrome-profile" `
    --disable-features=BackForwardCache
"""
#
# Mac Terminal:
r"""
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/selenium-chrome-profile" \
  --disable-features=BackForwardCache
"""
#
# 3.
# Chrome 中：
# - 通過 Cloudflare
# - 手動停在希望程式開始收集職缺的搜尋結果頁
#
# 4.
# 執行 Python Script
#
# =========================================================
