# Frutiger LM

[Português](README.pt-BR.md) · **English**

Study notebooks built from your own sources, a chat that cites them, and an **anchored
knowledge graph** — what you study becomes concept linked to concept, with a trail back
to the source.

> **Independent project**, not affiliated with Monotype. "Frutiger" here refers to the
> aesthetic lineage that inspires the interface — the future we were promised.
>
> **Architecture and roadmap:** see [PROJETO.md](PROJETO.md), the project's living
> document — every structural decision is recorded there, with status and reasoning.
> It is written in Portuguese, as is [AGENTS.md](AGENTS.md) (the guide for anyone
> touching the code).
>
> **About to work on the code?** Read [AGENTS.md](AGENTS.md): commands, the rules that
> are not negotiable, the file map, and the traps that already cost time.

If you have used Google's NotebookLM, this starts from the same place but with one
difference underneath: NotebookLM is a **consumer of sources** (drop material in, chat,
generate an output, and it dies there). Frutiger LM is a **knowledge builder that
persists and connects**. No images, no audio — study structure only.

> **Status: its own engine.** The agent is a LangGraph graph living inside the app:
> no engine or external service to run — just an **API key** from a provider, or a local
> model on your machine.

## How it works today

```
   ┌──────────────────────────────────────────────────────────┐
   │  Frutiger LM                                             │
   │                                                          │
   │  FastAPI + vanilla UI        ┌────────────────────────┐  │
   │  notebooks, sources,         │  agent (engine/)       │  │
   │  outputs, SQLite             │  LangGraph + tools     │  │
   │                              │  + checkpointer        │  │
   │                              └───────────┬────────────┘  │
   └──────────────────────────────────────────┼───────────────┘
                                              │ OpenAI-compatible
                                              ▼
                              OpenAI · DeepSeek · OpenRouter · Groq
                              LM Studio · llama.cpp · vLLM · Ollama
```

Where each concept lives:

| Concept        | Lives in                                                     |
|---|---|
| Notebook       | a row in SQLite + a `thread_id` in the checkpointer          |
| Sources        | `.txt` files in `data/notebooks/<id>/fontes/` + SQLite        |
| Chat           | SSE streaming from the agent, translated in `engine/agent.py` |
| Knowledge      | a chat conclusion can become a concept in the graph, anchored to the literal excerpt of that answer |
| Outputs        | saved Markdown; the compiled document comes from the graph, not the model |
| Model + key    | `data/model.json` (0600) or `LLM_AGENT` in `.env`             |
| Embeddings     | same file (`embed_*`), optional — only for similarity edges   |
| Login          | `data/auth.json` (0600): password hash and session secret    |

The **similarity edges** are the only thing in the graph the app **infers** instead of
reading from your material: it embeds each concept (name + excerpts) and links what talks
about the same thing **when the material never linked them**. So an inferred edge never
disguises itself as an assertion — dashed line, lilac label carrying the score
("similar 87%"), and provenance `inferida por <model>`. The threshold was **measured** on
real material, not guessed: with a median cosine of 0.56 in this domain, only the top of
the distribution tells you anything. And the vector is stored with the model and the text
that produced it, so re-running is instant.

## Requirements

- Linux, macOS or Windows
- [uv](https://docs.astral.sh/uv/) (or Python 3.11+ and pip)
- An **API key** from any OpenAI-compatible provider — or a local model
  (LM Studio, llama.cpp). Without any key the app still organizes notebooks;
  only the chat tells you the model is missing.

## Install

### 1. Run the app

```bash
git clone https://github.com/victormedrado99/frutiger-lm.git && cd frutiger-lm
uv sync
uv run frutiger-lm
```

Open http://127.0.0.1:8765.

### 2. Configure the model

Click **Modelo** in the top bar: pick the provider from the select (it fills in the
address), confirm the model name, paste your key, and hit **Test connection**. The test
makes a real minimal call — that is the difference between "saved" and "works".

The key lives in `data/model.json` with `600` permissions and is **never** sent back to
the browser. If you would rather keep the config in version control, use `LLM_AGENT` in
`.env` (see `.env.example`) — the UI wins when both exist.

### 3. (Optional, Linux) Keep it running

The unit ships in `deploy/frutiger-lm.service`:

```bash
install -m 644 deploy/frutiger-lm.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now frutiger-lm.service
```

It depends on no other service, and `Restart=always` brings the app back on its own if it
dies (tested with `kill -9`).

Adjust the project path in the unit if you did not clone into `~/Projetos/caderno`.
To survive logout, linger has to be enabled:

```bash
loginctl enable-linger $USER
```

> **A historical note that is still useful.** This unit once had `After=` and `Wants=`
> pointing at the old engine's service, and that caused a real restart loop: that service
> could have been started **outside** systemd, so every app start fired a start that failed
> with `already running` — and the other one's `Restart=always` restarted forever. It is
> recorded here because the same pattern shows up in any service that depends on another
> one able to come up outside systemd.

On macOS and Windows there is no systemd — there the path is launchd / Task Scheduler, or
simply `uv run frutiger-lm` when you need it.

## Hosting it on a server (login)

The app was born local: it listens on `127.0.0.1`, and whoever is at the machine is already
the owner. Hosted, it needs a closed door — because what is inside is not just readable: it
is your notebooks, your conversations, and the **model's API key**.

Set the user and the password (the password is prompted without echo and **never** goes
through the command line):

```bash
uv run frutiger-lm --senha
#   Usuário [dono]: victor
#   Senha (mínimo 8 caracteres):
#   Repita a senha:
```

That writes the hash — never the password — to `data/auth.json`, mode `0600`, the same
contract as `model.json`. Then just start it facing outwards:

```bash
uv run frutiger-lm --host 0.0.0.0 --port 8765
```

**With no password set, the app refuses to start on anything but loopback**, and prints the
command that fixes it. There is no "I forgot to switch security on".

How it works:

- **Session in a signed cookie** (`HttpOnly`, `SameSite=Lax`, 30 days), with a sliding
  expiry: the browser remembers you, and there is no token table.
- **Five wrong attempts** from the same origin and the wait starts doubling, up to 15 min.
- **Changing the password drops every session** — that is how you throw someone out,
  without needing a revocation table.
- To go back to open mode (only sensible on a local machine): `uv run frutiger-lm --sem-login`.

**TLS is not the app's job.** Whoever hosts puts nginx/Caddy in front, and the certificate
lives there. The app reads `X-Forwarded-Proto` and marks the cookie `Secure` by itself —
an nginx example:

```nginx
location / {
    proxy_pass http://127.0.0.1:8765;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_buffering off;          # the chat is SSE: without this the reply arrives all at once
    proxy_read_timeout 300s;
}
```

What is **out of scope on purpose**: multi-user, sign-up, invites, roles, and OAuth/SSO —
the audience is one person. To serve several, the path is one instance per person (each
with its own data directory and its own key), and each one's login protects its own.

## Using it

1. **Notebooks** — the first screen lists them. "Novo caderno" creates one. In the bottom
   bar, **"Ask all your notebooks"**: a chat that sees everything at once, searches every
   notebook, and shows what connects to what — always saying which notebook each piece
   came from.
2. Opening a notebook gives you three columns:
   - **Sources** (left): add a link, a PDF, a YouTube video, or pasted text. Every source
     has a switch: turn it off to take it out of context without deleting it.
   - **Chat** (middle): ask. Answers cite the sources (`[1]`, `[2]`) and you can watch
     which tools the agent used while working. When an answer is worth keeping, there is
     **"virar conhecimento"** under it: the model re-reads the answer, extracts the
     concepts, and each one enters the graph anchored to the **literal excerpt of that
     answer**. The answer stops dying in the chat — and the concept screen marks those
     mentions as **"said by the model"**, so they can never pass for a source excerpt.
   - **Panel** (right), two tabs:
     - **Generate** — the **compiled document**: your material gathered into one file, with
       every concept next to the literal excerpt that supports it, the gaps, what each
       source contributed, and an appendix with all citations. Only the summary and the
       narrative are written by the model; the rest is a query against the graph, and every
       section says where it came from. From here you also get the print sheet (to save as
       PDF from the browser), the **Anki** cards, and the **Obsidian** notes. The seven text
       templates below are what the model writes on its own. Compilation runs **outside the
       turn**: ask for it from the button or from the chat, and it appears here while it is
       being written — same compilation, same code.
     - **Study** — cards generated from concepts (excerpt on the back), the day's review
       with four grades, the checkable gaps, and per-concept notes.

### How the agent "reads" your sources

Two strategies, chosen automatically:

- **Small notebook** (default: up to 24,000 characters ≈ 6k tokens of sources): the entire
  content goes into the prompt. Faster and cheaper.
- **Large notebook**: the prompt carries only the index (title, kind, size, file path) and
  the agent uses its reading tools to fetch what it needs, when it needs it.

The limit is `FRUTIGER_INLINE_LIMIT` in `.env`.

### Cost

The system prompt is **ours** and small: the conduct rules, the notebook context, and the
schema of the tools exposed in that context (`listar_fontes`, `ler_fonte`,
`buscar_nas_fontes`, `web_extract`, the three graph tools, the study tools, and the
compilation one). No generic tool catalog loaded every turn — the exposed set is curated
per notebook.

What dominates cost, then, is the size of your sources: a small notebook goes into the
prompt whole; a large one sends the index and the agent reads by tool.

## Configuration

The model (address, name, key) is configured from the **Modelo** button and lives in
`data/model.json`. The rest is in `.env.example`:

| Variable | Default | What it is for |
|---|---|---|
| `LLM_AGENT` | — | model configuration via `.env` (instead of the UI) |
| `LLM_EMBED` | — | the **embedding** model via `.env` (optional; same format `openai\|url\|model\|key`) |
| `FRUTIGER_DATA_DIR` | `./data` | database, source files, model config and login |
| `FRUTIGER_PORT` | `8765` | app port |
| `FRUTIGER_INLINE_LIMIT` | `24000` | when to stop inlining and start using tools |

> `data/` holds your API key and your password hash. Do not version it or share it.

**Embeddings are optional**, and the app says so instead of pretending: without them
everything works, you just get no similarity edges (the button explains what is missing
rather than failing silently). They are configured in the same modal, in the "Embeddings"
block, with a test button that returns the vector dimension. And they **do not have to be
the same provider as the chat**: DeepSeek, for instance, offers no embeddings — if you want
that feature, run a local server:

```bash
# llama.cpp serving an embedding model, exactly as proven here
llama-server --embeddings --pooling mean \
  --model nomic-embed-text-v1.5.Q4_K_M.gguf --port 8080 --ctx-size 4096
# and in the modal: http://127.0.0.1:8080/v1 · nomic-embed-text-v1.5 · (no key)
```

The `frutiger-embed.service` unit (systemd --user) exists and ships **disabled** — turning
it on is the machine owner's call, because it uses memory and holds the port:

```bash
pkill -f 'llama-server.*--embeddings'          # if one is already on 8080
systemctl --user enable --now frutiger-embed.service
```

If you would rather use LM Studio (graphical), leave the unit off and point the
"Embeddings" block at its port. The app cannot tell the difference.

The embedding block carries one client trap worth knowing, because the error blames the
model: LangChain's client tokenizes the text **with OpenAI's tokenizer** by default and
sends IDs instead of text — a local server answers `400 Prompt contains invalid tokens`.
The app already sends text (`check_embedding_ctx_length=False`); if you write your own
client, send text.

## Architecture notes

- **Sources are real files on disk.** You can open them, grep them, version them with git,
  or back them up without talking to the app.
- **The conversation lives in our SQLite**, not in an external service: a notebook is a
  `thread_id` in the checkpointer (`data/checkpoints.db`). Deleting the notebook deletes the
  conversation with it, and "New conversation" deletes only the conversation.
- **Sources do not enter the conversation history.** The notebook context is rebuilt every
  turn from the database and the files; what is persisted is the conversation. So toggling a
  source changes what the agent knows **without** invalidating the conversation's memory.
- **Outputs do not go through the chat agent.** They are generated outside it, so producing
  a study guide does not pollute the history or burn accumulated context.
- **Every tool that reads a file limits its own output** and says where it stopped. A tool
  able to dump 400k characters into the context breaks the turn.
- **The login is a single middleware**, in front of every route: no route knows it exists,
  and the one somebody forgets to mark cannot become a door.

## Development

```bash
uv sync                     # dependencies + dev tools
uv run ruff check .         # lint
uv run pytest               # tests: 366, ~5 s, no network and no key
uv run frutiger-lm --reload # server with auto-reload
```

The tests cover what is ours: database, context assembly, ingestion, prompts, conversation
persistence, the tools, the agent's event translation, the routes, and the login. Nothing
touches the network: the model is a fake (`engine/fake.py`) and it **has parity between
block and stream**, which is what makes it possible to test the app's real path — streaming.

The fake is ours rather than the library's because the library's does not drive the agent
loop (its `bind_tools` raises `NotImplementedError`) nor survive streaming a message that
only carries a tool call. Both limitations were found by testing.

Real LLM behaviour is not deterministically testable — that is validated separately, against
the real provider.

## License

MIT — see [LICENSE](LICENSE).
