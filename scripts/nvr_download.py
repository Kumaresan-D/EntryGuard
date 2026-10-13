"""Phase 1 of the NVR video pipeline: logs into the NVR's web UI and starts
downloading the previous day's recordings for one channel to this PC via the
NVR's own "Download to PC" mechanism.

This only *triggers* the download - the NVR then saves files locally in the
background under a folder such as C:\\Users\\<you>\\<date>, which can take
hours. Run scripts/upload_downloaded_videos.py afterwards, once those files exist.

    venv\\Scripts\\python -m scripts.nvr_download

Credentials/URL come from environment variables via .env (see .env.example)
- never hardcode them here.

NOTE: this was written without network access to the NVR to test against,
so two things are best-effort and likely to need adjustment on a first run:
  - login(): the login form's markup wasn't available, so its selectors are
    placeholders.
  - set_search_date_range(): the date fields are a 3rd-party picker widget
    (Wdate/laydate) bound through a custom Angular directive rather than a
    plain input, so setting .value directly may not "take."
Runs headless by default (config.NVR_HEADLESS) so it works unattended via
Task Scheduler (see scripts/setup_scheduled_tasks.ps1) - set NVR_HEADLESS=false
in .env while debugging so you can watch it; if a step fails, use
`playwright codegen <NVR_URL>` to record the working selector and swap it
into the corresponding function below.
"""

from datetime import date, timedelta

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

from backend.config import NVR_CHANNEL_LABEL, NVR_HEADLESS, NVR_PASSWORD, NVR_ROWS_TO_DOWNLOAD, NVR_URL, NVR_USERNAME


def target_date() -> str:
    return (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")


def login(page: Page) -> None:
    page.goto(NVR_URL, wait_until="networkidle")
    # TODO: adjust to the NVR's actual login form - these are placeholders,
    # since that page's markup wasn't available while writing this script.
    page.fill("#username", NVR_USERNAME)
    page.fill("#password", NVR_PASSWORD)
    page.click("button.login-btn")
    page.wait_for_load_state("networkidle")


def open_playback(page: Page) -> None:
    page.click("#nav a:has-text('Playback')")
    page.wait_for_load_state("networkidle")


def open_download_page(page: Page) -> Page:
    """Clicks the Download button and returns whichever page the download UI
    ends up on. Some of these NVR UIs open it in a new tab/window (a popup)
    rather than navigating the current tab, so this tries that first and
    falls back to same-page navigation if no popup appears."""
    try:
        with page.expect_popup(timeout=5000) as popup_info:
            page.click("button[title='Download']")
        download_page = popup_info.value
    except PlaywrightTimeoutError:
        download_page = page
    download_page.wait_for_load_state("networkidle")
    return download_page


def select_channel(page: Page, label_substring: str) -> None:
    """Selects the <option> in #channelLink whose text contains label_substring
    (options are labeled like "[A8] North West", so this matches a substring
    rather than requiring the exact bracketed text)."""
    value = page.eval_on_selector_all(
        "#channelLink option",
        """(options, label) => {
            const match = options.find(o => o.textContent.includes(label));
            return match ? match.value : null;
        }""",
        label_substring,
    )
    if value is None:
        raise RuntimeError(f"No channel option matching {label_substring!r} found")
    page.select_option("#channelLink", value=value)


def set_search_date_range(page: Page, day: str) -> None:
    """Sets both the start and end date fields to the same day (a single
    full day's search window). See the module docstring's caveat about this
    being a best-effort approach against a 3rd-party date-picker widget."""
    for dp_model in ("oSearchTime.startTime", "oSearchTime.endTime"):
        page.eval_on_selector(
            f"input[dp-model='{dp_model}']",
            """(el, value) => {
                const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                setter.call(el, value);
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                el.dispatchEvent(new Event('blur', { bubbles: true }));
            }""",
            day,
        )


def search(page: Page) -> None:
    page.click("button.search-btn")
    page.wait_for_selector(".table-body .table-row")


def select_top_rows(page: Page, count: int) -> None:
    """Only selects rows that are actually visible: this table keeps a fixed
    number of row "slots" in the DOM regardless of how many results a search
    returns, and any unused slots stay hidden (not removed) - so counting
    all .checkbox elements overcounts when a search returns few results."""
    checkboxes = page.locator(".table-body .table-row .checkbox:visible")
    available = checkboxes.count()
    if available < count:
        print(f"Only {available} row(s) available (wanted {count}) - selecting all of them.")
    for i in range(min(count, available)):
        checkboxes.nth(i).check(force=True)


def start_download(page: Page) -> None:
    button = page.locator("button:has-text('Download to PC')")
    button.scroll_into_view_if_needed()
    button.click(force=True)


def main() -> None:
    if not (NVR_URL and NVR_USERNAME and NVR_PASSWORD):
        raise SystemExit("Set NVR_URL, NVR_USERNAME, and NVR_PASSWORD (see .env.example) before running this.")

    day = target_date()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=NVR_HEADLESS)
        page = browser.new_page()
        page.on("dialog", lambda dialog: dialog.accept())  # auto-accept any "start download?" confirm popups
        try:
            login(page)
            open_playback(page)
            download_page = open_download_page(page)
            download_page.on("dialog", lambda dialog: dialog.accept())
            select_channel(download_page, NVR_CHANNEL_LABEL)
            set_search_date_range(download_page, day)
            search(download_page)
            select_top_rows(download_page, NVR_ROWS_TO_DOWNLOAD)
            start_download(download_page)
            print(
                f"Download started for {day}. The NVR saves files locally in the background "
                f"(expect several hours) - run scripts/upload_downloaded_videos.py once they've finished."
            )
        finally:
            browser.close()


if __name__ == "__main__":
    main()
