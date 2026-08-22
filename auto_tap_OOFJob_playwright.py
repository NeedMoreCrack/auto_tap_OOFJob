from pathlib import Path
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

import random
import time

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


# =========================================================
# 基本設定
# =========================================================

LOG_MAX_JOBS = 1000
MAX_JOBS = 1000
MAX_PAGES = 100

CDP_URL = "http://127.0.0.1:9222"

SCRIPT_DIR = Path(__file__).resolve().parent
LOG_DIR = SCRIPT_DIR / "log"

CARD_SELECTORS = [
    "div.job-summary[data-job-no]",
    "div.job-mobile[data-job-no]",
]

LINK_SELECTORS = [
    "a.info-job__text",
    "a.info-job",
    "a.js-job-link",
]


# =========================================================
# LOG
# =========================================================

def ensure_log_directory():
    LOG_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    print(f"LOG 資料夾：{LOG_DIR}")


def create_log_file():
    while True:
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")

        log_path = (
                LOG_DIR
                / f"OOF_{timestamp}.log"
        )

        if not log_path.exists():
            break

        time.sleep(1)

    log_path.touch(
        exist_ok=False
    )

    print(
        f"建立新的 LOG：{log_path.name}"
    )

    return log_path


def write_log(
        log_path,
        message=""
):
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
# Playwright / Chrome
# =========================================================

def attach_to_existing_chrome(playwright):
    """
    連線到已經手動啟動，且開啟 remote debugging 的 Chrome。

    Windows：
    chrome.exe --remote-debugging-port=9222 --user-data-dir="..."

    macOS：
    /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome \
      --remote-debugging-port=9222 \
      --user-data-dir="$HOME/selenium-chrome-profile"
    """

    browser = playwright.chromium.connect_over_cdp(
        CDP_URL
    )

    if not browser.contexts:
        raise RuntimeError(
            "已連線 Chrome，但沒有找到 BrowserContext。"
        )

    context = browser.contexts[0]

    return browser, context


def get_current_page(context):
    """
    取得目前 Chrome 中要交給程式使用的分頁。

    優先找目前有焦點的頁面。
    如果 Chrome 不在前景，document.hasFocus() 可能全部為 False，
    此時退回使用 context.pages[-1]。

    不檢查網址。
    不寫死 104 網址。
    不使用 bring_to_front()。
    """

    pages = context.pages

    if not pages:
        raise RuntimeError(
            "目前 Chrome 沒有任何可用分頁。"
        )

    focused_page = None

    for page in pages:
        try:
            if page.evaluate("() => document.hasFocus()"):
                focused_page = page
                break
        except Exception:
            continue

    page = focused_page or pages[-1]

    print()
    print(
        "=" * 100
    )
    print(
        "使用目前 Chrome 分頁"
    )
    print(
        f"頁面標題：{page.title()}"
    )
    print(
        f"頁面網址：{page.url}"
    )

    if focused_page is None:
        print(
            "目前沒有偵測到有焦點的分頁，"
            "改用 Chrome Context 中最後一個分頁。"
        )

    print(
        "=" * 100
    )
    print()

    return page


# =========================================================
# URL / 分頁
# =========================================================

def get_page_number(url):
    """
    取得 URL 中的 page 參數。
    沒有時視為第 1 頁。
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
    保留原本搜尋條件，只修改 page 參數。
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


# =========================================================
# 職缺列表
# =========================================================

def wait_for_job_cards(
        page,
        timeout=10000
):
    """
    等待至少一種職缺卡片出現。
    """

    for selector in CARD_SELECTORS:

        try:

            page.locator(
                selector
            ).first.wait_for(
                state="attached",
                timeout=timeout
            )

            return selector

        except PlaywrightTimeoutError:
            continue

    return None


def extract_jobs_from_current_page(page):
    """
    一次用 JavaScript 從 DOM 把：

    job_no
    href

    全部取回來。

    避免 Selenium / Playwright 一張卡一張卡跨程序呼叫，
    尤其在 macOS 上 DOM 很大時會非常慢。
    """

    result = page.evaluate(
        """
        ({ cardSelectors, linkSelectors }) => {

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
        }
        """,
        {
            "cardSelectors": CARD_SELECTORS,
            "linkSelectors": LINK_SELECTORS
        }
    )

    jobs = []

    for item in result:

        job_no = item.get(
            "jobNo"
        )

        href = item.get(
            "href"
        )

        if not job_no:
            continue

        if not href:
            continue

        jobs.append(
            (
                str(job_no),
                href
            )
        )

    return jobs


def collect_job_links(
        page,
        max_jobs=MAX_JOBS,
        max_pages=MAX_PAGES
):
    """
    用 求職網 本身的 page= 分頁收集職缺。

    不再使用：
        無限往下滾
        document.body.scrollHeight
        bounce
        smooth scroll
        每張 card 各自 find_element()

    這樣 Windows / macOS 都會穩定很多。
    """

    print(
        "目前頁面網址：",
        page.url
    )

    print(
        "目前頁面標題：",
        page.title()
    )

    base_url = page.url
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

    empty_or_duplicate_pages = 0

    for offset in range(
            max_pages
    ):

        if len(seen) >= max_jobs:
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

        # -------------------------------------------------
        # 第一次就是目前頁時，不必重複導航
        # -------------------------------------------------

        if page.url != target_url:

            try:

                page.goto(
                    target_url,
                    wait_until="domcontentloaded",
                    timeout=30000
                )

            except PlaywrightTimeoutError:

                print(
                    "  頁面導航逾時，"
                    "但繼續檢查目前 DOM"
                )

        # -------------------------------------------------
        # 等職缺卡片
        # -------------------------------------------------

        selector = wait_for_job_cards(
            page,
            timeout=10000
        )

        if selector is None:

            print(
                "  找不到職缺卡片"
            )

            empty_or_duplicate_pages += 1

            if empty_or_duplicate_pages >= 3:

                print(
                    "  連續 3 頁沒有有效職缺，停止收集。"
                )

                break

            continue

        print(
            f"  使用卡片選擇器：{selector}"
        )

        # -------------------------------------------------
        # 讓頁面上的前端 JS 稍微穩定
        # -------------------------------------------------

        time.sleep(
            random.uniform(
                0.8,
                1.5
            )
        )

        jobs = extract_jobs_from_current_page(
            page
        )

        print(
            f"  此頁找到 {len(jobs)} 張職缺卡片"
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
            f"  本頁新增 {new_count} 筆"
        )

        print(
            f"  目前總數："
            f"{len(seen)}/{max_jobs}"
        )

        if new_count == 0:

            empty_or_duplicate_pages += 1

            print(
                f"  本頁沒有新職缺 "
                f"({empty_or_duplicate_pages}/3)"
            )

        else:

            empty_or_duplicate_pages = 0

        if empty_or_duplicate_pages >= 3:

            print(
                "  連續 3 頁沒有新增職缺，停止收集。"
            )

            break

        # -------------------------------------------------
        # 模擬一般使用者換頁間隔
        # -------------------------------------------------

        if len(seen) < max_jobs:

            delay = random.uniform(
                1.2,
                2.5
            )

            print(
                f"  前往下一頁前等待 "
                f"{delay:.1f} 秒"
            )

            time.sleep(
                delay
            )

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

    if text is None:
        return ""

    return " ".join(
        text.split()
    ).strip()


def safe_get_text(
        page,
        selectors
):
    """
    依序嘗試多個 CSS selector，
    找到第一個有文字的元素就回傳。
    """

    for selector in selectors:

        try:

            locator = page.locator(
                selector
            )

            count = locator.count()

            for index in range(
                    count
            ):

                text = clean_text(
                    locator.nth(
                        index
                    ).inner_text(
                        timeout=2000
                    )
                )

                if text:
                    return text

        except Exception:
            continue

    return None


# =========================================================
# 詳細頁文字解析
# =========================================================

def get_page_lines(page):

    try:

        text = page.locator(
            "body"
        ).inner_text(
            timeout=5000
        )

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

    for index, line in enumerate(
            lines
    ):

        for label in labels:

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

            if line == label:

                for offset in range(
                        1,
                        max_lookahead + 1
                ):

                    next_index = (
                            index
                            + offset
                    )

                    if next_index >= len(
                            lines
                    ):
                        break

                    value = clean_text(
                        lines[
                            next_index
                        ]
                    )

                    if value:
                        return value

    return None


def extract_multi_value_after_label(
        lines,
        labels,
        max_lines=3
):
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

            if line == label:

                values = []

                for offset in range(
                        1,
                        max_lines + 1
                ):

                    next_index = (
                            index
                            + offset
                    )

                    if next_index >= len(
                            lines
                    ):
                        break

                    value = clean_text(
                        lines[
                            next_index
                        ]
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


def extract_job_name(
        page,
        lines
):
    selectors = [
        "h1",
        "h1[class*='job']",
        "[data-qa='job-title']",
    ]

    value = safe_get_text(
        page,
        selectors
    )

    if value:
        return value

    title = page.title()

    if title:

        if "｜" in title:

            title = title.split(
                "｜"
            )[0]

        return clean_text(
            title
        )

    return "未取得"


def extract_job_location(
        page,
        lines
):
    value = extract_value_after_label(
        lines,
        [
            "工作地點",
            "上班地點"
        ]
    )

    return value or "未取得"


def extract_education(
        page,
        lines
):
    value = extract_value_after_label(
        lines,
        [
            "學歷要求",
            "學歷"
        ]
    )

    return value or "未取得"


def extract_salary(
        page,
        lines
):
    value = extract_value_after_label(
        lines,
        [
            "工作待遇",
            "薪資待遇",
            "薪資"
        ]
    )

    return value or "未取得"


def extract_technologies(
        page,
        lines
):
    technologies = []

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


def extract_job_detail(page):

    lines = get_page_lines(
        page
    )

    return {
        "job_name": extract_job_name(
            page,
            lines
        ),
        "location": extract_job_location(
            page,
            lines
        ),
        "technologies": extract_technologies(
            page,
            lines
        ),
        "education": extract_education(
            page,
            lines
        ),
        "salary": extract_salary(
            page,
            lines
        ),
    }


# =========================================================
# 模擬閱讀
# =========================================================

def simulate_reading(
        page,
        total_duration_range=(10, 30)
):
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

    elapsed += (
        initial_pause
    )

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

        if action == "scroll_down":

            distance = random.randint(
                300,
                600
            )

            page.evaluate(
                "(distance) => window.scrollBy(0, distance)",
                distance
            )

        elif action == "scroll_down_small":

            distance = random.randint(
                100,
                250
            )

            page.evaluate(
                "(distance) => window.scrollBy(0, distance)",
                distance
            )

        elif action == "scroll_up":

            distance = random.randint(
                100,
                300
            )

            page.evaluate(
                "(distance) => window.scrollBy(0, -distance)",
                distance
            )

        step_pause = random.uniform(
            1.2,
            3.5
        )

        time.sleep(
            step_pause
        )

        elapsed += (
            step_pause
        )


# =========================================================
# 逐筆瀏覽職缺
# =========================================================

def visit_jobs(
        page,
        job_links,
        view_duration_range=(10, 30),
        batch_size_range=(10, 15),
        long_break_range=(30, 60)
):
    next_batch_target = random.randint(
        *batch_size_range
    )

    count_since_break = 0

    total_jobs = len(
        job_links
    )

    jobs_in_current_log = 0

    current_log = create_log_file()

    print()

    print(
        "=" * 100
    )

    print(
        "職缺連結已全部收集完成。"
    )

    print(
        "接下來使用同一個 Chrome Tab 依序瀏覽。"
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

        if jobs_in_current_log >= LOG_MAX_JOBS:

            print()

            print(
                "=" * 100
            )

            print(
                f"目前 LOG 已達 {LOG_MAX_JOBS} 筆，"
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

            try:

                page.goto(
                    href,
                    wait_until="domcontentloaded",
                    timeout=30000
                )

            except PlaywrightTimeoutError:

                print(
                    "  頁面載入逾時，"
                    "但繼續嘗試讀取目前 DOM"
                )

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

            page.evaluate(
                "() => window.scrollTo(0, 0)"
            )

            detail = extract_job_detail(
                page
            )

            job_name = detail[
                "job_name"
            ]

            location = detail[
                "location"
            ]

            technologies = detail[
                "technologies"
            ]

            education = detail[
                "education"
            ]

            salary = detail[
                "salary"
            ]

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

            simulate_reading(
                page,
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

            jobs_in_current_log += 1

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

        if (
                count_since_break
                >= next_batch_target
                and idx < total_jobs
        ):

            break_duration = random.uniform(
                *long_break_range
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

def main():

    print(
        "=" * 100
    )

    print(
        "OOF Playwright 自動職缺瀏覽程式"
    )

    print(
        "=" * 100
    )

    print()

    print(
        "檢查 LOG 資料夾..."
    )

    ensure_log_directory()

    print(
        "LOG 資料夾確認完成"
    )

    print()

    print(
        "連接 Chrome..."
    )

    with sync_playwright() as playwright:

        browser, context = (
            attach_to_existing_chrome(
                playwright
            )
        )

        print(
            "Chrome 連接成功"
        )

        # -------------------------------------------------
        # 直接使用目前 Chrome 的頁面。
        #
        # 不寫死 104 網址，
        # 不使用 bring_to_front()，
        # 避免主動把 Chrome 拉到最前面。
        # -------------------------------------------------

        page = get_current_page(
            context
        )

        print(
            "開始收集職缺連結..."
        )

        # -------------------------------------------------
        # 使用搜尋列表分頁收集所有職缺 URL
        # -------------------------------------------------

        job_links = collect_job_links(
            page,
            max_jobs=MAX_JOBS,
            max_pages=MAX_PAGES
        )

        print()

        print(
            f"共收集到 "
            f"{len(job_links)} 筆職缺"
        )

        if len(job_links) == 0:

            print()

            print(
                "沒有收集到任何職缺。"
            )

            print(
                "請確認："
            )

            print(
                "1. 是否停留在 104 搜尋列表"
            )

            print(
                "2. Cloudflare 是否已通過"
            )

            print(
                "3. 104 DOM 是否改版"
            )

            return

        # =================================================
        # 搜尋列表使用完畢
        #
        # 搜尋列表跑過大量 page= 分頁，
        # 可能累積：
        #
        # DOM
        # JavaScript Context
        # Cache
        # Renderer Memory
        #
        # 所以收集完後直接捨棄這個 Page。
        # =================================================

        print()

        print(
            "=" * 100
        )

        print(
            "職缺連結收集完成"
        )

        print(
            "準備切換到新的瀏覽分頁..."
        )

        print(
            "=" * 100
        )

        job_list_page = page

        # -------------------------------------------------
        # 只建立這一次新的 Page
        #
        # 後面的 1 ~ 1000 筆職缺，
        # 全部使用同一個 Page。
        # -------------------------------------------------

        page = context.new_page()

        try:

            page.goto(
                "about:blank",
                wait_until="commit",
                timeout=10000
            )

        except Exception:
            pass

        # -------------------------------------------------
        # 關閉原本搜尋列表 Page
        #
        # 讓 Chrome 有機會直接銷毀舊 Renderer，
        # 釋放前面收集職缺時累積的記憶體。
        # -------------------------------------------------

        try:

            job_list_page.close()

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
        # 給 Chrome 一點時間處理舊 Renderer
        # -------------------------------------------------

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

        # -------------------------------------------------
        # 後續：
        #
        # job1
        #   ↓
        # page.goto()
        #   ↓
        # job2
        #   ↓
        # page.goto()
        #   ↓
        # job3
        #
        # 始終使用相同 Page。
        # -------------------------------------------------

        visit_jobs(
            page,
            job_links,
            view_duration_range=(
                10,
                30
            ),
            batch_size_range=(
                10,
                15
            ),
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


if __name__ == "__main__":
    main()


# =========================================================
# 安裝方式
# =========================================================
#
# macOS:
#
#   python3 -m pip install playwright
#
# 因為這版是 connect_over_cdp() 接到已經開啟的 Google Chrome，
# 通常不需要另外執行：
#
#   playwright install
#
#
# =========================================================
# Chrome 啟動方式
# =========================================================
#
# macOS:
r"""
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
   --remote-debugging-port=9222 \
   --user-data-dir="$HOME/selenium-chrome-profile"
"""
#
# Windows PowerShell:
r"""
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
   --remote-debugging-port=9222 `
   --user-data-dir="C:\Users\User\selenium-chrome-profile"
"""
#
# 啟動後：
#
# 1. 手動開 求職網 搜尋頁
# 2. 手動通過 Cloudflare
# 3. 執行這支 Python
#
# =========================================================
