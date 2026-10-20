"""The same run with no model: Playwright clicks, and Pidgeon does the rest.

    ./run.sh --check

What CI runs on every push. The Pidgeon calls, the site and both emails are
the real ones; only the decisions are scripted. If this passes and the agent
does not, the model is the problem, not the inbox.
"""

import asyncio
import os
import secrets
import sys

import httpx
from playwright.async_api import async_playwright

from agent import Inbox, log


async def sent(page) -> None:
    """Fails now, with the site's reason, rather than after two minutes of waiting."""
    heading = await page.get_by_role("heading").first.inner_text()
    if heading != "Check your email":
        raise RuntimeError(await page.locator("main").inner_text())


async def received(inbox: Inbox):
    """The next email, or a failure that says nothing came."""
    email = await inbox.next(timeout=120)
    if email is None:
        raise RuntimeError(f"No email reached {inbox.email} in two minutes.")
    return email


async def main() -> int:
    url = os.environ.get("SITE_URL", "http://localhost:8765")
    inbox = Inbox()
    await inbox.sweep()

    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch()
            page = await browser.new_page()

            email = await inbox.create("Ada Agent")
            log(f"created {email}; waiting for mail from now on")

            await page.goto(url)
            await page.get_by_label("Name").fill("Ada Agent")
            await page.get_by_label("Email").fill(email)
            await page.get_by_label("Password").fill(f"First-{secrets.token_hex(4)}")
            await page.get_by_role("button", name="Sign up").click()
            await sent(page)

            code = await received(inbox)
            log(f"read code {code.codes[0]}")
            await page.get_by_label("Verification code").fill(code.codes[0])
            await page.get_by_role("button", name="Verify").click()
            await page.get_by_text("You’re signed in").wait_for()

            await page.get_by_role("link", name="Forgot password?").click()
            await page.get_by_role("button", name="Send reset link").click()
            await sent(page)

            reset = await received(inbox)
            log(f"read link {reset.links[0]}")
            await page.goto(reset.links[0])
            await page.get_by_label("New password").fill(f"Second-{secrets.token_hex(4)}")
            await page.get_by_role("button", name="Save password").click()
            await page.get_by_text("Password changed").wait_for()

            await browser.close()
    finally:
        await inbox.delete()

    status = httpx.get(f"{url}/status", params={"email": email}).json()
    log(f"site says: verified={status['verified']}, reset={status['reset']}")
    return 0 if status["verified"] and status["reset"] else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
