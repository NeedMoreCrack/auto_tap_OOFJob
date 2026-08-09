from selenium import webdriver
from selenium.webdriver.common.by import By

from pathlib import Path
from datetime import datetime

import time
import random


# =========================================================
# LOG 設定
# =========================================================

LOG_MAX_JOBS = 50

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


# 切換回職缺表
def switch_to_job_list_page(
        driver,
        url_keyword="求職網.com.tw/jobs/search"
):
    """
    列出目前所有分頁，
    自動切換到 求職網 職缺搜尋列表。
    """

    print("目前所有分頁:")

    matched_handle = None

    for handle in driver.window_handles:

        driver.switch_to.window(
            handle
        )

        print(
            f"  - {handle} | "
            f"{driver.current_url}"
        )

        if (
                url_keyword in driver.current_url
                and matched_handle is None
        ):
            matched_handle = handle

    if matched_handle:

        driver.switch_to.window(
            matched_handle
        )

        print(
            f"\n已切換到職缺列表："
            f"{driver.current_url}\n"
        )

    else:

        print(
            "\n警告：找不到 求職網 職缺搜尋列表。\n"
        )

    return driver


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


def collect_job_links(
        driver,
        max_jobs=500, # 最大職缺數
        max_scrolls=100,
        pause_range=(2, 4)
):
    """
    持續滾動到頁面最下方，觸發 求職網 載入更多職缺。

    停止條件：
    1. 收集到 max_jobs 筆
    2. 達到 max_scrolls
    3. 連續 3 次：
       - 沒有新增職缺
       - 頁面高度沒有增加
    """

    print("目前頁面網址：", driver.current_url)
    print("目前頁面標題：", driver.title)

    test_cards, used_selector = find_cards(driver)

    print(
        f"實際使用的卡片選擇器：{used_selector}，"
        f"找到 {len(test_cards)} 張卡片"
    )

    if test_cards:

        sample_href = find_link_in_card(
            test_cards[0]
        )

        print(
            f"範例職缺連結：{sample_href}"
        )

    print("=" * 100)

    seen = {}

    stagnant_rounds = 0

    # =====================================================
    # 先收集一開始畫面已有的職缺
    # =====================================================

    cards, _ = find_cards(driver)

    for card in cards:

        job_no = card.get_attribute(
            "data-job-no"
        )

        if not job_no:
            continue

        if job_no in seen:
            continue

        href = find_link_in_card(card)

        if href:
            seen[job_no] = href

        if len(seen) >= max_jobs:
            break

    print(
        f"初始職缺數量："
        f"{len(seen)}/{max_jobs}"
    )

    # =====================================================
    # 初始頁面高度
    # =====================================================

    last_page_height = driver.execute_script(
        "return document.body.scrollHeight"
    )

    # =====================================================
    # 開始滾動
    # =====================================================

    for i in range(
        1,
        max_scrolls + 1
    ):

        # =================================================
        # 已達最大筆數，不再滾動
        # =================================================

        if len(seen) >= max_jobs:

            print()

            print("=" * 100)

            print(
                f"已收集 {len(seen)} 筆職缺，"
                f"達到上限 {max_jobs} 筆。"
            )

            print(
                "停止繼續載入。"
            )

            print("=" * 100)

            break

        # =================================================
        # 記錄這一輪開始前的數量
        # =================================================

        count_before_scroll = len(seen)

        print()

        print(
            f"[Scroll {i}] "
            f"目前已收集 "
            f"{count_before_scroll}/{max_jobs} 筆"
        )

        # =================================================
        # 滾到最下方
        # =================================================

        driver.execute_script(
            """
            window.scrollTo({
                top: document.body.scrollHeight,
                behavior: 'smooth'
            });
            """
        )

        # 等 smooth scroll
        time.sleep(
            random.uniform(
                1.0,
                1.8
            )
        )

        # 再強制到底
        driver.execute_script(
            "window.scrollTo(0, document.body.scrollHeight);"
        )

        # =================================================
        # 等待 求職網 AJAX / DOM 載入
        # =================================================

        load_pause = random.uniform(
            *pause_range
        )

        print(
            f"  已滾到底部，"
            f"等待新職缺載入... "
            f"{load_pause:.1f} 秒"
        )

        time.sleep(
            load_pause
        )

        # =================================================
        # 新頁面高度
        # =================================================

        new_page_height = driver.execute_script(
            "return document.body.scrollHeight"
        )

        print(
            f"  頁面高度："
            f"{last_page_height} -> "
            f"{new_page_height}"
        )

        # =================================================
        # 滾動完成後，再掃描目前 DOM
        # =================================================

        cards, _ = find_cards(driver)

        for card in cards:

            job_no = card.get_attribute(
                "data-job-no"
            )

            if not job_no:
                continue

            if job_no in seen:
                continue

            href = find_link_in_card(card)

            if href:
                seen[job_no] = href

            # =============================================
            # 精確限制最多 max_jobs
            # =============================================

            if len(seen) >= max_jobs:
                break

        # =================================================
        # 計算這一整輪實際新增多少
        # =================================================

        round_new_count = (
            len(seen)
            - count_before_scroll
        )

        if round_new_count > 0:

            print(
                f"  新內容載入成功，"
                f"本輪新增 "
                f"{round_new_count} 筆"
            )

            print(
                f"  目前總數："
                f"{len(seen)}/{max_jobs}"
            )

        else:

            print(
                "  本輪沒有找到新的職缺"
            )

        # =================================================
        # 判斷是否停止
        # =================================================

        if (
            round_new_count == 0
            and new_page_height == last_page_height
        ):

            stagnant_rounds += 1

            print(
                f"  頁面沒有變化 "
                f"({stagnant_rounds}/3)"
            )

        else:

            stagnant_rounds = 0

        last_page_height = (
            new_page_height
        )

        # =================================================
        # 連續 3 次沒有任何新資料
        # =================================================

        if stagnant_rounds >= 3:

            print()

            print("=" * 100)

            print(
                "連續 3 次滾到底部後，"
                "都沒有新增職缺，"
                "頁面高度也沒有變化。"
            )

            print(
                "判斷沒有更多職缺，"
                "停止收集。"
            )

            print("=" * 100)

            break

    # =====================================================
    # 最終保險
    # =====================================================

    if len(seen) > max_jobs:

        seen = dict(
            list(
                seen.items()
            )[:max_jobs]
        )

    print()

    print("=" * 100)

    print(
        f"職缺連結收集完成，"
        f"總共 {len(seen)} 筆"
    )

    print("=" * 100)

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
    逐筆開啟職缺。

    新增功能：

    每筆抓：
        職缺名稱
        工作地點
        技術
        學歷
        薪資

    每 50 筆：
        建立新的 LOG
    """

    main_window = (
        driver.current_window_handle
    )

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
            # 建立新 Tab
            # =====================================

            driver.switch_to.new_window(
                "tab"
            )

            # =====================================
            # 開啟職缺
            # =====================================

            driver.get(
                href
            )

            # 等待初步載入
            time.sleep(
                random.uniform(
                    1.5,
                    3
                )
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

        except Exception as e:

            print(
                f"  瀏覽失敗："
                f"{type(e).__name__}: "
                f"{e}"
            )

            # 失敗資訊也寫 LOG
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

        finally:

            # =====================================
            # 關閉職缺 Tab
            # =====================================

            try:

                if (
                        driver.current_window_handle
                        != main_window
                ):

                    driver.close()

            except Exception as e:

                print(
                    f"  關閉分頁失敗："
                    f"{type(e).__name__}: "
                    f"{e}"
                )

            # =====================================
            # 切回 求職網 搜尋頁
            # =====================================

            try:

                driver.switch_to.window(
                    main_window
                )

            except Exception as e:

                print(
                    f"  無法切回搜尋頁："
                    f"{type(e).__name__}: "
                    f"{e}"
                )

                break

        # =========================================
        # 單筆瀏覽之間隨機等待
        # =========================================

        count_since_break += 1

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
        "OneO4 自動職缺瀏覽程式"
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

    # =====================================================
    # 3. 找 求職網 職缺列表
    # =====================================================

    switch_to_job_list_page(
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
            "1. 是否停留在 求職網 搜尋列表"
        )

        print(
            "2. Cloudflare 是否已通過"
        )

        print(
            "3. 求職網 DOM 是否改版"
        )

    else:

        # =================================================
        # 6. 開始瀏覽
        # =================================================

        print()

        print(
            "開始逐一瀏覽職缺..."
        )

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
    --user-data-dir="C:\Users\User\selenium-chrome-profile"
"""
#
# Mac Terminal:
r"""
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/selenium-chrome-profile"
"""
#
# 3.
# Chrome 中：
# - 通過 Cloudflare
#
# 4.
# 執行 Python Script
#
# =========================================================
