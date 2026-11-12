"""Network-disabled Chromium: every HTTP request is fulfilled by the core's public resolver."""
import asyncio
import base64
import hashlib
import json
import sys
from uuid import uuid4

from playwright.async_api import async_playwright


async def main():
    pending, actions = {}, asyncio.Queue()
    output_lock = asyncio.Lock()

    async def emit(value):
        async with output_lock:
            print(json.dumps(value), flush=True)

    async def reader():
        while raw := await asyncio.to_thread(sys.stdin.buffer.readline, 96_000_000):
            message = json.loads(raw)
            if message.get("kind") == "fetch_result":
                future = pending.get(message.get("id"))
                if future and not future.done():
                    future.set_result(message)
            elif message.get("kind") == "action":
                await actions.put(message)
        await actions.put(None)

    reading = asyncio.create_task(reader())
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True, args=["--disable-dev-shm-usage", "--disable-quic",
                                 "--disable-background-networking", "--disable-extensions"])
        context = await browser.new_context(service_workers="block", accept_downloads=True,
                                            viewport={"width": 1280, "height": 800})
        downloads = []
        pages = set()

        async def route_handler(route):
            key = uuid4().hex
            future = asyncio.get_running_loop().create_future()
            pending[key] = future
            try:
                request = route.request
                await emit({"kind": "fetch", "id": key, "url": request.url,
                            "method": request.method, "headers": await request.all_headers(),
                            "body": base64.b64encode(request.post_data_buffer or b"").decode()})
                response = await asyncio.wait_for(future, 12)
                if response.get("error"):
                    await route.abort("blockedbyclient")
                else:
                    await route.fulfill(status=response["status"], headers=response["headers"],
                                        body=base64.b64decode(response["body"], validate=True))
            except Exception:
                await route.abort("blockedbyclient")
            finally:
                pending.pop(key, None)

        await context.route("**/*", route_handler)
        page = await context.new_page()
        page.set_default_timeout(7000)
        page.on("dialog", lambda dialog: asyncio.create_task(dialog.dismiss()))
        page.on("download", lambda download: downloads.append(download))
        context.on("page", lambda popup: pages.add(popup))

        while command := await actions.get():
            key = command["id"]
            try:
                op = command.get("op")
                if op == "navigate":
                    await page.goto(command["url"], wait_until="domcontentloaded", timeout=20000)
                elif op in {"click", "fill"}:
                    if hashlib.sha256((await page.content()).encode()).hexdigest() != command.get("dom_sha256"):
                        raise ValueError("Page content changed.")
                    selector = command.get("selector", "")
                    locator = page.locator(selector)
                    if await locator.count() != 1:
                        raise ValueError("Choose a selector matching exactly one element.")
                    if op == "fill":
                        if await locator.get_attribute("type") == "password":
                            raise ValueError("Password fields are unavailable to the agent.")
                        await locator.fill(command.get("text", ""))
                    else:
                        await locator.click()
                elif op != "snapshot":
                    raise ValueError("Unsupported browser operation.")
                # Popups cannot silently become the active session.
                for popup in list(pages):
                    if popup != page and not popup.is_closed():
                        await popup.close()
                pages.clear()
                text = (await page.locator("body").inner_text())[:14000]
                elements = await page.locator("a,button,input,textarea,select").evaluate_all("""els => els.slice(0,80).map((e,i) => ({
                    selector: e.id ? '#' + CSS.escape(e.id) : ':is(a,button,input,textarea,select):nth-match(' + (i+1) + ')',
                    tag: e.tagName.toLowerCase(), text: (e.innerText || e.getAttribute('aria-label') || e.getAttribute('placeholder') || e.labels?.[0]?.innerText || e.getAttribute('name') || '').slice(0,160),
                    type: e.getAttribute('type') || '', href: e.tagName === 'A' ? e.href : undefined
                }))""")
                # Stable per-snapshot selectors; never accept arbitrary JavaScript from the model.
                for index, element in enumerate(elements):
                    element["selector"] = f":is(a,button,input,textarea,select) >> nth={index}"
                screenshot = await page.screenshot(type="png", timeout=5000)
                files = [{"name": "browser.png", "content": base64.b64encode(screenshot).decode()}]
                for download in downloads[:5]:
                    path = await download.path()
                    if path:
                        from pathlib import Path
                        target = Path(path)
                        if (await asyncio.to_thread(target.stat)).st_size <= 3_000_000:
                            files.append({"name": download.suggested_filename, "content": base64.b64encode(await asyncio.to_thread(target.read_bytes)).decode()})
                    await download.delete()
                downloads.clear()
                await emit({"id": key, "result": {"url": page.url, "title": (await page.title())[:500],
                            "text": text, "elements": elements, "files": files,
                            "dom_sha256": hashlib.sha256((await page.content()).encode()).hexdigest()}})
            except ValueError as error:
                await emit({"id": key, "error": str(error)[:300], "safe": True})
            except Exception:
                await emit({"id": key, "error": "Browser action failed or timed out. Inspect the current page before another action."})
        await context.close()
        await browser.close()
    reading.cancel()


if __name__ == "__main__":
    asyncio.run(main())
