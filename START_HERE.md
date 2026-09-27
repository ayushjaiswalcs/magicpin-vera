# Start here — Ayush's magicpin challenge project

## 1. What the company is asking for

Build a bot called Vera that helps business owners. The company sends your bot
information about a business and an event. Your bot decides what message to send.
Then the company pretends to be the owner or customer and replies. Your bot must
remember the conversation and respond correctly.

Example: a dentist's calls have fallen. Vera explains the actual numbers and
asks whether the dentist wants an action plan. If the dentist says YES, Vera
provides the plan. If the dentist says STOP, Vera stops.

You submit a **public server URL** in the form shown in your screenshot.
The company then calls your API endpoints. You do not need to connect your
personal WhatsApp or send messages to real people for this challenge.

## 2. What is already built

- All five required API endpoints, plus an endpoint to clear test state.
- The required `compose()` function and multi-turn reply handling in `bot.py`.
- The company's generated dataset: 5 categories, 50 merchants, 200 customers,
  100 triggers, and 30 canonical test pairs.
- A local browser demo with research, performance, customer and review scenarios.
- Duplicate-message prevention, trigger expiry, opt-out, consent and version handling.
- Automated tests, a HTTP smoke test, Dockerfile and Render deployment settings.
- `submission.jsonl`, containing 30 decisions from the unmodified generated pairs.

This is a **rule-based implementation**. It does not secretly use ChatGPT or
another LLM. That makes it free to run locally, fast and repeatable. It is less
flexible on unfamiliar messages than a well-tested LLM implementation. Do not
claim that it uses an LLM or that it has received a company judge score.

## 3. Run on your Mac

1. Download and extract the ZIP.
2. Move the extracted `magicpin-vera` folder to your Desktop.
3. Open Terminal.
4. Run these commands:

```bash
cd "$HOME/Desktop/magicpin-vera"
python3 --version
DEMO_MODE=1 python3 bot.py
```

Use Python **3.11 or newer**. No `npm install` or `pip install` is needed.
This is a Python project, so it has no `package.json`.

If the folder is somewhere else, type `cd ` in Terminal, drag the folder into
Terminal, and press Return. Then run the Python command.

5. Leave Terminal running.
6. Open **http://localhost:8080** in your browser.
7. Choose a scenario and press **Start scenario**.
8. Try **YES**, **Auto-reply**, and **STOP**. Restart the scenario to try a different path.

The page displays both a chat preview and the API's actual response. Demo state
is separate from judge state. Nothing is sent to WhatsApp.

Stop the server with **Control + C**.

If port 8080 is already being used:

```bash
PORT=8081 DEMO_MODE=1 python3 bot.py
```

Then open http://localhost:8081. If Python is missing, install Python 3.11+ from
https://www.python.org/downloads/ before continuing.

## 4. Run the tests

Open a second Terminal window while the server remains running:

```bash
cd "$HOME/Desktop/magicpin-vera"
python3 -m unittest discover -s tests -v
python3 scripts/smoke_test.py
```

The smoke test loads the dataset into your local API, checks conversations, and
clears state afterwards. **Never run it against the live bot during company judging.**
If using a different port, add `--url http://localhost:8081`.

To rebuild the static output file:

```bash
python3 scripts/build_submission.py
```

The company's seeds have missing facts and inconsistent dates. The 30 rows
currently contain 19 composed messages and 11 explicitly marked suppressions.
An empty suppressed body is a record of a decision, not a message to send.
`/v1/tick` never returns it as an outbound action. Confirm with the organiser if
a separate static submission requires a different representation of skipped rows.
The screenshot's primary submission is the live base URL.

## 5. Put the bot online

Your laptop's `localhost` URL will not work for the company. Deploy the server to
an account you control. A Render configuration is included; deployment has **not**
been performed from this workspace.

### Upload the project to GitHub

1. Sign in to https://github.com/ and create a repository named `magicpin-vera`.
2. Upload the **contents** of the extracted `magicpin-vera` folder. `bot.py` must
   be at the repository root, next to `README.md` and `render.yaml`.
3. Keep `static`, `scripts`, `tests`, `dataset` and `official` folders intact.
4. Do not upload any `.env` file or private API key. This bot requires no key.

If you already use Git, you can commit and push the folder instead of uploading
in the browser. The GitHub repository address is a source-code link, not the
submission URL.

### Create the Render web service

1. Sign in to https://render.com/.
2. Create a **Web Service** and connect your `magicpin-vera` repository.
3. Use these settings:

| Setting | Value |
| --- | --- |
| Runtime | Python 3 |
| Root directory | Leave blank if `bot.py` is at the repository root |
| Build command | `python -m compileall -q bot.py` |
| Start command | `python bot.py` |
| Health check path | `/v1/healthz` |
| Number of instances | 1 |

4. Add environment variables:

| Variable | Value |
| --- | --- |
| `TEAM_NAME` | Your chosen team name, or `Vera Context` |
| `TEAM_MEMBERS` | `Ayush Jaiswal` — edit if your actual team differs |
| `CONTACT_EMAIL` | Your own contact email |
| `DEMO_MODE` | `0` |
| `PYTHON_VERSION` | `3.12.12` |
| `SUBMITTED_AT` | Actual submission timestamp in ISO format; set when known |

Do not set `PORT` manually on Render; the platform supplies it.

5. Choose a hosting plan after reviewing its cost. For the assessed window, use
   a service that stays running. Render's free service can sleep after 15 minutes
   of inactivity; restarting also loses this bot's in-memory contexts. A free
   service is useful for a practice deployment but has reliability risks for judging.
6. Deploy. Wait for the live service URL shown by Render. It will look similar to
   `https://your-service-name.onrender.com`. That example is not your actual URL.
7. Open `YOUR-ACTUAL-URL/v1/healthz`. You should see `"status": "ok"`.
8. Open `YOUR-ACTUAL-URL/v1/metadata`. Confirm your team name and email.
9. Before the judging window, test once using:

```bash
python3 scripts/smoke_test.py --url https://YOUR-ACTUAL-SERVICE.onrender.com
```

Replace the example URL. The test clears state and should be run **before** the
company loads its judging data. Do not deploy changes, restart, scale to multiple
instances, or run teardown during the test window. After judging, clear runtime
state with `/v1/teardown` or stop the instance, and stop paid hosting if no longer needed.

Official hosting documentation checked while preparing this package:
- https://render.com/docs/web-services
- https://render.com/docs/health-checks
- https://render.com/docs/free

## 6. Fill the company form

| Form field | What to enter |
| --- | --- |
| Full name | Ayush Jaiswal |
| Email | Your actual email address |
| Phone number | Your actual phone number |
| Submission URL | Your live **base URL**, e.g. `https://your-service.onrender.com` |
| LinkedIn URL | Your profile URL, if you want to include it |

Do not copy `magicpin`, `vera@magicpin.com`, `9999999999`, or the sample submission
URL from the screenshot. Those are sample values.

Do not enter `/v1/healthz`, a GitHub link, a ZIP download link, or `localhost` as
the submission URL. Enter only the live server base URL. The fifth portal screen
was not included in your attachments; follow its actual confirmation instructions.

Keep `bot.py`, `submission.jsonl` and `README.md` ready if the organiser separately
asks for files. The screenshot currently asks for the live URL.

## 7. What to say if they ask you to explain it

The bot combines four inputs: category, merchant, event and optional customer.
It first checks whether it should send anything. It checks consent, expiry,
previous messages and opt-out state. Then it chooses a relevant message using
facts from the inputs. It keeps conversation state so YES gives a useful next
step, automated replies cause a wait, and STOP ends outreach. Updated context
replaces old context, including during a conversation.

The main tradeoff is predictable behaviour versus flexibility: rules are easy to
test, but an LLM could understand a wider range of phrasing. There are no real
booking or posting integrations. Drafts are delivered immediately; external
actions are not falsely reported as completed.

## 8. Important limits

- This is tested locally, not deployed or submitted yet.
- It has no official LLM quality score. Passing API tests does not guarantee selection.
- Hindi-English support is limited; other regional-language preferences fall back to English.
- Free-text booking and arbitrary new trigger kinds are not fully supported.
- All research, compliance and business examples are synthetic company fixtures;
  they are not independently verified medical, legal or market facts.
- Mock template names fulfil the simulation convention. They are not actual
  Meta-approved WhatsApp templates.
- The bot stores runtime contexts in memory only and clears them on teardown.
- The public API is unauthenticated because the company contract specifies no
  authentication. It is for synthetic challenge data only, behind a TLS proxy.
