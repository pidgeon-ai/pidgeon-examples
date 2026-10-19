"""A sign-up page to point the agent at: one file, no database, no other mail provider.

    python site/server.py --port 8765

Sign up (name, email, password) → enter the six-digit code → signed in, with
"Forgot password?" → the reset link → a new password. Both emails go out
through Pidgeon from the site's own address, with a key that can send from
that address and nothing else (`SITE_PIDGEON_API_KEY`; `site/sender.py`
makes one).

Everything lives in memory and is gone when the process stops.
"""

import argparse
import hashlib
import html
import json
import os
import secrets
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

from pidgeon import AuthenticatedClient
from pidgeon.api.identities import identities_list
from pidgeon.api.messages import messages_send
from pidgeon.models import Error, MessagesSendBody

# run.sh sets it, so the site's lines and the agent's share one clock.
START = float(os.environ.get("RUN_STARTED", time.time()))

# email → {"name", "password", "code", "verified", "reset"}
ACCOUNTS: dict[str, dict] = {}
# one-time link token → (purpose, email)
TOKENS: dict[str, tuple[str, str]] = {}


def log(line: str) -> None:
    print(f"{time.time() - START:6.1f}s  site   {line}", flush=True)


def digest(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


class Mailer:
    """Sends from the one address the site's key can send from."""

    def __init__(self) -> None:
        self.client = AuthenticatedClient(
            base_url=os.environ.get("PIDGEON_BASE_URL", "https://pidgeon.ai/api/v1"),
            token=os.environ["SITE_PIDGEON_API_KEY"],
        )
        listed = identities_list.sync(client=self.client)
        if isinstance(listed, Error) or not listed.data:
            sys.exit("SITE_PIDGEON_API_KEY reaches no address. Run `python site/sender.py` to make one.")
        self.address = listed.data[0].email

    def send(self, to: str, subject: str, text: str) -> str | None:
        """None when it went; otherwise what Pidgeon said, for the page and the log."""
        sent = messages_send.sync(
            client=self.client,
            body=MessagesSendBody(from_=self.address, to=to, subject=subject, text=text),
        )
        return sent.error.message if isinstance(sent, Error) else None


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{title} · Acme Demo</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body {{ font: 16px/1.5 system-ui, sans-serif; background: #f6f6f4; color: #1b1b1b; margin: 0; }}
  main {{ max-width: 22rem; margin: 4rem auto; background: #fff; padding: 2rem; border-radius: 12px;
          box-shadow: 0 1px 3px rgb(0 0 0 / 0.08); }}
  h1 {{ font-size: 1.4rem; margin: 0 0 1rem; }}
  label {{ display: block; margin: 0.75rem 0 0.25rem; font-weight: 600; }}
  input {{ width: 100%; box-sizing: border-box; padding: 0.55rem; font: inherit; border: 1px solid #bbb;
           border-radius: 6px; }}
  button {{ margin-top: 1.25rem; width: 100%; padding: 0.6rem; font: inherit; font-weight: 600; border: 0;
            border-radius: 6px; background: #1b1b1b; color: #fff; cursor: pointer; }}
  .note {{ color: #555; font-size: 0.9rem; }} .error {{ color: #b00020; }}
</style></head>
<body><main><h1>{title}</h1>{body}</main></body></html>"""


def field(name: str, label: str, kind: str = "text", value: str = "") -> str:
    return (
        f'<label for="{name}">{label}</label>'
        f'<input id="{name}" name="{name}" type="{kind}" value="{html.escape(value)}" required>'
    )


class Site(BaseHTTPRequestHandler):
    mailer: Mailer
    base: str

    def log_message(self, *_args) -> None:
        pass

    # Rendering

    def page(self, title: str, body: str, status: int = 200) -> None:
        payload = PAGE.format(title=title, body=body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def not_sent(self, reason: str) -> None:
        log(f"could not send: {reason}")
        self.page("We couldn’t send the email", f'<p class="error">{html.escape(reason)}</p>', 503)

    def redirect(self, location: str, cookie: str | None = None) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        if cookie is not None:
            self.send_header("Set-Cookie", f"session={cookie}; Path=/; HttpOnly; SameSite=Lax")
        self.end_headers()

    def form(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length", 0))
        fields = parse_qs(self.rfile.read(length).decode())
        return {key: values[0].strip() for key, values in fields.items()}

    def signed_in(self) -> str | None:
        for part in self.headers.get("Cookie", "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == "session" and value in TOKENS and TOKENS[value][0] == "session":
                return TOKENS[value][1]
        return None

    def sign_in(self, email: str, location: str = "/account") -> None:
        session = secrets.token_urlsafe(16)
        TOKENS[session] = ("session", email)
        self.redirect(location, cookie=session)

    # Routes

    def do_GET(self) -> None:
        url = urlparse(self.path)
        query = {key: values[0] for key, values in parse_qs(url.query).items()}

        if url.path == "/":
            self.page(
                "Create your account",
                '<form method="post" action="/signup">'
                + field("name", "Name")
                + field("email", "Email", "email")
                + field("password", "Password", "password")
                + '<button type="submit">Sign up</button></form>',
            )
        elif url.path == "/verify":
            email = query.get("email", "")
            self.page(
                "Check your email",
                f'<p class="note">We sent a six-digit code to {html.escape(email)}.</p>'
                '<form method="post" action="/verify">'
                f'<input type="hidden" name="email" value="{html.escape(email)}">'
                + field("code", "Verification code")
                + '<button type="submit">Verify</button></form>',
            )
        elif url.path == "/confirm":
            purpose, email = TOKENS.pop(query.get("token", ""), ("", ""))
            if purpose != "confirm":
                return self.page("That link has expired", '<p><a href="/">Start again</a></p>', 400)
            ACCOUNTS[email]["verified"] = True
            log(f"{email} confirmed by link")
            self.sign_in(email)
        elif url.path == "/account":
            email = self.signed_in()
            if not email:
                return self.redirect("/")
            self.page(
                "You’re signed in",
                f"<p>Welcome, {html.escape(ACCOUNTS[email]['name'])}. You are signed in as "
                f"{html.escape(email)}.</p>"
                '<p><a href="/forgot">Forgot password?</a></p>',
            )
        elif url.path == "/forgot":
            self.page(
                "Reset your password",
                '<form method="post" action="/forgot">'
                + field("email", "Email", "email", self.signed_in() or "")
                + '<button type="submit">Send reset link</button></form>',
            )
        elif url.path == "/reset":
            token = query.get("token", "")
            if TOKENS.get(token, ("",))[0] != "reset":
                return self.page("That link has expired", '<p><a href="/forgot">Ask again</a></p>', 400)
            self.page(
                "Choose a new password",
                '<form method="post" action="/reset">'
                f'<input type="hidden" name="token" value="{html.escape(token)}">'
                + field("password", "New password", "password")
                + '<button type="submit">Save password</button></form>',
            )
        elif url.path == "/status":
            # What actually happened, for run.sh to judge the run by.
            account = ACCOUNTS.get(query.get("email", "").lower(), {})
            payload = json.dumps(
                {"verified": bool(account.get("verified")), "reset": bool(account.get("reset"))}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload)
        else:
            self.page("Not found", "", 404)

    def do_POST(self) -> None:
        url = urlparse(self.path)
        data = self.form()
        email = data.get("email", "").lower()

        if url.path == "/signup":
            code = f"{secrets.randbelow(1_000_000):06d}"
            token = secrets.token_urlsafe(16)
            ACCOUNTS[email] = {
                "name": data.get("name", ""),
                "password": digest(data.get("password", "")),
                "code": code,
                "verified": False,
                "reset": False,
            }
            TOKENS[token] = ("confirm", email)
            log(f"sign-up from {email}; sending code {code}")
            failed = self.mailer.send(
                email,
                "Your verification code",
                f"Hi {ACCOUNTS[email]['name']},\n\n"
                f"Your verification code is {code}.\n\n"
                f"Or confirm your email with this link:\n{self.base}/confirm?token={token}\n\n"
                "If you didn’t sign up, ignore this email.\n",
            )
            if failed:
                return self.not_sent(failed)
            self.redirect("/verify?" + urlencode({"email": email}))
        elif url.path == "/verify":
            account = ACCOUNTS.get(email)
            if not account or data.get("code", "").replace(" ", "") != account["code"]:
                log(f"wrong code for {email}")
                return self.page("That code is not right", '<p><a href="javascript:history.back()">Try again</a></p>', 400)
            account["verified"] = True
            log(f"{email} verified with {account['code']}; signed in")
            self.sign_in(email)
        elif url.path == "/forgot":
            token = secrets.token_urlsafe(16)
            if email in ACCOUNTS:
                TOKENS[token] = ("reset", email)
                log(f"password reset requested for {email}")
                failed = self.mailer.send(
                    email,
                    "Reset your password",
                    "Somebody asked to reset the password for this address.\n\n"
                    f"Reset your password:\n{self.base}/reset?token={token}\n\n"
                    "If it wasn’t you, ignore this email.\n",
                )
                if failed:
                    return self.not_sent(failed)
            self.page("Check your email", "<p>If that address has an account, a reset link is on its way.</p>")
        elif url.path == "/reset":
            purpose, email = TOKENS.pop(data.get("token", ""), ("", ""))
            if purpose != "reset":
                return self.page("That link has expired", '<p><a href="/forgot">Ask again</a></p>', 400)
            ACCOUNTS[email]["password"] = digest(data.get("password", ""))
            ACCOUNTS[email]["reset"] = True
            log(f"{email} set a new password")
            self.page("Password changed", "<p>Your new password is saved.</p>")
        else:
            self.page("Not found", "", 404)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=int(os.environ.get("SITE_PORT", 8765)))
    args = parser.parse_args()

    Site.mailer = Mailer()
    Site.base = f"http://localhost:{args.port}"
    log(f"listening on {Site.base}, sending from {Site.mailer.address}")
    ThreadingHTTPServer(("127.0.0.1", args.port), Site).serve_forever()


if __name__ == "__main__":
    main()
