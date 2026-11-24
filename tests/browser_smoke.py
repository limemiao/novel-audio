"""Run against a running local server using the already installed Edge browser."""
import json
import re
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = Path(r"assets\qa\web")


def main():
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        context = browser.new_context(viewport={"width":1440,"height":1100}, device_scale_factor=1)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto("http://127.0.0.1:8788/", wait_until="networkidle")
        expect(page.locator("#hero-books")).not_to_have_text("—")
        expect(page.locator("#generate-button")).to_be_enabled()
        expect(page.locator(".book-card")).to_have_count(12)
        page.screenshot(path=str(ARTIFACTS / "desktop.png"))
        page.screenshot(path=str(ARTIFACTS / "desktop-full.png"), full_page=True)
        page.locator("#search").fill("魔王2099")
        expect(page.locator(".book-card")).to_have_count(4)
        page.locator(".book-card").filter(has_text="第一卷").click()
        expect(page.locator("#chapter-list .chapter-row")).to_have_count(7)
        page.locator("[data-read='0']").click()
        expect(page.locator("#reader-dialog")).to_be_visible()
        expect(page.locator("#reader-text")).to_contain_text("大陆历")
        page.locator("#reader-dialog .dialog-close").click()
        page.locator("#select-all").click()
        expect(page.locator("#chapter-list input:checked")).to_have_count(7)
        page.locator("#select-all").click()
        expect(page.locator("#generate-button")).to_be_disabled()
        page.locator("[data-chapter='0']").check()
        page.locator("#engine-edge").click()
        expect(page.locator("#engine-note")).to_contain_text("微软")
        page.locator("#voice").select_option("zh-CN-YunxiNeural")
        page.locator("#engine-system").click()
        page.locator("#preview-button").click()
        expect(page.locator("#player-title")).to_contain_text("试听", timeout=60000)
        expect(page.locator("#duration")).not_to_have_text("0:00", timeout=15000)
        page.locator("#play-button").click()
        page.locator("#seek").focus()
        page.locator("#seek").press("ArrowRight")
        assert page.locator("#audio").evaluate("el => el.currentTime") > 0
        with page.expect_download() as download:
            page.locator("#player-download").click()
        assert download.value.suggested_filename.endswith(".mp3")
        task_count = int(page.locator("#task-count").inner_text())
        page.locator("#generate-button").click()
        page.locator(".sidebar [data-view='tasks']").click()
        expect(page.locator("#task-count")).to_have_text(str(task_count + 1))
        expect(page.locator("#tasks-list")).to_contain_text("魔王2099")
        expect(page.locator("#tasks-list .status-pill").filter(has_text=re.compile("^(排队中|制作中)$"))).to_have_count(0, timeout=60000)
        page.screenshot(path=str(ARTIFACTS / "tasks.png"), full_page=True)
        page.locator(".sidebar [data-view='audio']").click()
        expect(page.locator(".audio-item").first).to_be_visible()
        page.locator("#audio-filter").select_option("output")
        expect(page.locator("#audio-list")).not_to_contain_text("试听-序章")
        page.screenshot(path=str(ARTIFACTS / "audio.png"), full_page=True)
        page.locator(".sidebar [data-view='library']").click()
        page.locator("#search").fill("不存在的小说XYZ")
        expect(page.locator("#book-grid .empty-state")).to_be_visible()
        page.locator("#search").fill("")
        page.locator("#list-view").click()
        expect(page.locator("#book-grid")).to_have_class("book-grid list-mode")
        page.locator("#grid-view").click()
        page.locator("#next-page").click()
        expect(page.locator("#page-number")).to_contain_text("2 /")
        page.locator("#prev-page").click()
        page.locator("#settings-button").click()
        expect(page.locator("#settings-dialog")).to_contain_text("library")
        page.locator("#settings-dialog .dialog-close").click()
        page.set_viewport_size({"width":390,"height":844})
        page.evaluate("() => window.scrollTo(0, 0)")
        page.wait_for_timeout(300)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "mobile horizontal overflow"
        page.screenshot(path=str(ARTIFACTS / "mobile.png"))
        page.locator("#settings-top").click()
        expect(page.locator("#settings-dialog")).to_be_visible()
        page.locator("#settings-dialog .dialog-close").click()
        page.locator(".sidebar [data-view='audio']").click()
        expect(page.locator("#audio-view")).to_be_visible()
        assert not errors, errors
        print(json.dumps({"browser":"Edge", "desktop":"1440x1100", "mobile":"390x844", "errors":errors, "checks":["library", "covers", "search", "chapter preview", "selection", "voices", "offline preview", "playback", "seek", "download", "chapter export", "tasks", "audio filter", "empty search", "pagination", "settings", "responsive layout"], "artifacts":str(ARTIFACTS)}, ensure_ascii=False, indent=2))
        browser.close()


if __name__ == "__main__":
    main()
