"""Voice picker QA against the running local server on port 8788."""
import json
import os
from pathlib import Path
from playwright.sync_api import expect, sync_playwright


def main():
    artifacts = Path(r"assets\qa\web")
    artifacts.mkdir(parents=True, exist_ok=True)
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width":1440,"height":1100})
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(os.environ.get("NOVEL_AUDIO_TEST_URL", "http://127.0.0.1:8788/"), wait_until="networkidle")
        expect(page.locator("#voice")).to_have_value("Microsoft Huihui Desktop - Chinese (Simplified)")
        expect(page.locator("#generate-button")).to_be_enabled()
        page.locator("#engine-edge").click()
        expect(page.locator("#voice option")).to_have_count(14)
        page.locator("#voice-gender").select_option("Male")
        expect(page.locator("#voice option")).to_have_count(6)
        page.locator("#voice-locale").select_option("zh-CN")
        expect(page.locator("#voice option")).to_have_count(4)
        page.locator("#voice-search").fill("云扬")
        expect(page.locator("#voice")).to_have_value("zh-CN-YunyangNeural")
        expect(page.locator("#preview-button")).to_be_enabled()
        page.locator("#engine-system").click()
        page.locator("#engine-edge").click()
        expect(page.locator("#voice")).to_have_value("zh-CN-YunyangNeural")
        page.locator("#voice-search").fill("no-such-voice")
        expect(page.locator("#voice")).to_be_disabled()
        expect(page.locator("#preview-button")).to_be_disabled()
        page.locator("#voice-search").fill("")
        page.locator("#voice-gender").select_option("all")
        page.locator("#voice-locale").select_option("ja-JP")
        page.locator("#voice").select_option("ja-JP-NanamiNeural")
        expect(page.locator("#voice")).to_have_value("ja-JP-NanamiNeural")
        page.locator("#voice-locale").select_option("all")
        expect(page.locator("#voice option")).to_have_count(318)
        page.route("**/api/voices/refresh", lambda route: route.fulfill(status=400, content_type="application/json", body=json.dumps({"error":"刷新失败，已保留现有音色目录"})))
        page.locator("#refresh-voices").click()
        expect(page.locator("#toast")).to_contain_text("保留")
        expect(page.locator("#voice option")).to_have_count(318)
        page.unroute("**/api/voices/refresh")
        page.locator("#refresh-voices").click()
        expect(page.locator("#toast")).to_contain_text("音色目录已更新", timeout=30000)
        page.locator("#voice-locale").select_option("zh")
        expect(page.locator("#voice option")).to_have_count(14)
        page.locator("#voice").select_option("zh-CN-YunyangNeural")
        page.locator("#toast").wait_for(state="hidden", timeout=10000)
        page.screenshot(path=str(artifacts / "voices-desktop.png"))
        page.set_viewport_size({"width":390,"height":844})
        page.locator("#engine-edge").scroll_into_view_if_needed()
        assert page.evaluate("() => document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(artifacts / "voices-mobile.png"))
        assert not errors, errors
        browser.close()
        print("Voice picker passed: Chinese/region/gender/search, empty results, engine switching, Japanese, all languages, failed/successful refresh, responsive layout. No page errors.")


if __name__ == "__main__":
    main()
