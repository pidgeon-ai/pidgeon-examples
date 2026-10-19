# signup-agent

A browser agent that signs itself up with an email address it keeps.

It creates its own address on `pidgeon.email`, fills in a sign-up form with it,
waits for the verification email, and types in the code. Then it asks for a
password reset, and the reset arrives at the same address, because the
address is still its own. [Browser Use](https://docs.browser-use.com) drives
the browser. Two tools on the [`pidgeon`](https://pypi.org/project/pidgeon/)
SDK give the model the inbox, in [`agent.py`](agent.py).

It runs against [`site/`](site/server.py), a one-file sign-up page in this
folder that sends its emails through Pidgeon, so it automates nobody's real
service.

## Run it

```sh
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt && playwright install chromium
cp .env.example .env    # then fill in the two keys
./run.sh
```

- `PIDGEON_API_KEY`: make it at
  [pidgeon.ai/app/developers/keys](https://pidgeon.ai/app/developers/keys)
  with **Admin** access. A key always reaches the addresses it creates, so in
  a workspace that holds other mail, give it one address, not every address.
  The first run uses it to give the demo site an address and a send-only key
  of its own.
- `ANTHROPIC_API_KEY` for the model, or `OPENAI_API_KEY` to use OpenAI.

`./run.sh --check` runs the same flow with no model: Playwright clicks, and
the emails are real. Each run deletes the address it made.

## On a real site

Use `--url` only on a site whose terms allow automated sign-ups. The agent
stops at a CAPTCHA instead of trying to solve it.

```sh
python agent.py --url https://example.com/signup
```

How the waiting works: [pidgeon.ai/docs/verification-codes](https://pidgeon.ai/docs/verification-codes).

MIT licensed.
