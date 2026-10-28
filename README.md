# PinkyDocs AI

PinkyDocs AI is a document question-answering application with a Python CLI and a Streamlit web interface. Upload a PDF or TXT file, paste text, select the documents for a conversation, and ask questions grounded in retrieved passages.

**Your documents. Your answers.**

> This project is an interview-ready demo, not an audited identity or document-security product. Do not upload confidential, sensitive, or regulated content without reviewing the service terms and privacy requirements that apply to your use.

## Features

- CLI and Streamlit entry points share the same extraction, chunking, retrieval, and answer services.
- Local PDF text extraction with page metadata, UTF-8 TXT import, and pasted-text documents.
- Explainable BM25-style keyword retrieval across multiple selected documents.
- Gemini answer generation from retrieved passages only, with application-validated citations.
- Clear abstention when no relevant evidence is found.
- Username/password accounts hashed with Argon2id.
- Supabase persistence for documents, private original files, chunks, conversations, and messages.
- Conversation-scoped document selections and recent follow-up context.
- Atomic, database-backed daily per-user and shared question limits.
- An original vector mascot, pink product theme, and private-by-default storage.

## Project structure

    app.py                         Streamlit interface
    cli.py                         Local command-line application
    src/pinkydocs/config.py        Central environment and secrets configuration
    src/pinkydocs/document_loader.py PDF/TXT/pasted text extraction
    src/pinkydocs/chunker.py       Source-aware chunking
    src/pinkydocs/retriever.py     Local BM25-style ranking
    src/pinkydocs/qa_service.py    Grounded answer orchestration
    src/pinkydocs/gemini_client.py Gemini API adapter
    src/pinkydocs/auth_service.py  Argon2id registration and login policy
    src/pinkydocs/supabase_service.py Owner-scoped persistence and RPC calls
    src/pinkydocs/storage_service.py Upload validation and indexing
    supabase/migrations/001_initial_schema.sql Database, RLS, storage, quota RPCs
    assets/pinkydocs_mascot.svg   Original PinkyDocs mascot
    sample_documents/company_leave_policy.txt Sample content for evaluation
    tests/                         Offline unit and service tests

## Architecture and answer flow

1. The browser or CLI loads PDF text locally with pypdf, decodes TXT as UTF-8, or validates pasted text. Uploading a document never calls Gemini.
2. The chunker keeps PDF page numbers and text line or heading metadata. It targets 1,200 characters with 180 characters of overlap by default.
3. The retriever ranks only the selected documents using local BM25-style term matching, term frequency, a phrase boost, and a minimum relevance floor. A short follow-up can include the most recent user question as retrieval context without another model call.
4. If no chunk is relevant, the service returns a not-found answer without calling Gemini or consuming an allowance.
5. For a supported question, the web app atomically reserves a daily allowance in PostgreSQL, then sends the question, a small conversation window, and up to six retrieved excerpts to Gemini.
6. The Gemini prompt treats excerpts as untrusted data, makes conversation history non-authoritative, and requests source IDs. The application maps only returned source IDs to its own retrieved-chunk metadata; model-invented labels are discarded.
7. The answer and trusted citations are saved to the user's conversation. Original files are stored at generated user/document paths in a private Supabase Storage bucket.

The app uses the configured GEMINI_MODEL exactly. It does not silently choose another model, use external search, call paid embedding services, or send documents to Gemini during indexing.

## Example questions

These are expected grounded answers from the included fictional sample policy. They describe the evidence in the sample and are not preloaded production answers; verify live model wording with your configured Gemini account.

| Question | Expected grounded answer |
| --- | --- |
| How many annual leave days do employees receive? | Employees receive 18 annual leave days per calendar year. |
| How many sick leave days are provided? | Employees receive 10 sick leave days per calendar year. |
| Can unused annual leave be carried forward? | Yes. Up to 5 unused annual leave days may be carried forward into the next calendar year. |
| How far in advance should routine leave be requested? | Routine leave requests should be submitted at least 3 working days in advance. |
| How long is the probation period? | The probation period lasts 3 months from the employee's start date. |
| What is the maternity leave entitlement? | The sample policy does not specify a maternity leave entitlement. |

The final question has an explicit not-specified statement in the example policy. For a different document that contains no relevant passages, retrieval abstains before calling Gemini.

## Requirements and local setup

Use Python 3.10 or newer. Python 3.12 is a good default. The project dependencies include Streamlit, pypdf, Google GenAI, Supabase Python, Argon2, python-dotenv, and pytest. There is no Docker requirement.

### Windows PowerShell

    py -3 -m venv .venv
    .\.venv\Scripts\Activate.ps1
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    Copy-Item .env.example .env

### macOS or Linux

    python3 -m venv .venv
    source .venv/bin/activate
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    cp .env.example .env

Edit .env locally. It is ignored by Git. Use placeholders only in committed templates.

### Configure Gemini

1. Create an API key in Google AI Studio and add it to GEMINI_API_KEY in your local .env or Streamlit secrets.
2. Set GEMINI_MODEL to a model identifier currently available to your account and permitted by its free tier. Check Google's model and usage pages before choosing; the app deliberately has no model fallback.
3. The CLI requires GEMINI_API_KEY and GEMINI_MODEL. It does not require Supabase configuration.

The free-tier quota, eligible models, and terms can change. The Gemini API pricing page currently marks free-tier submitted content as used to improve Google's products. Google's additional terms explain how submitted content is handled on unpaid services. Review the current [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing) and [Gemini API Additional Terms](https://ai.google.dev/gemini-api/terms) before sending documents. Do not send confidential, sensitive, or regulated information unless the applicable terms and your privacy obligations allow it. The app does not guarantee confidentiality or perfect answers.

### Configure Supabase for the web app

The CLI works without Supabase. The Streamlit app requires Supabase for username/password accounts, private document persistence, and saved conversations.

1. Create a Supabase project on a plan that fits your demo. A free plan may be suitable, but its quotas and available features can change; review current provider limits and do not assume unlimited use.
2. Open the project's SQL Editor and run supabase/migrations/001_initial_schema.sql.
3. The migration creates a private documents bucket, application tables, indexes, foreign keys, RLS, and server-only RPC functions. The bucket is named documents. Verify in Storage that the bucket is private.
4. Copy the Project URL and service-role key from the Supabase project settings into SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in .env. The service-role key is privileged: keep it only in the Python server environment. Never put it in browser code, a public repository, a screenshot, or a client-side Supabase configuration.
5. The migration enables RLS and deliberately creates no anon/authenticated policies for app data. The Python server uses the service-role key and scopes every private table operation to the authenticated user's UUID. The service-role key bypasses RLS, so server-side ownership checks remain essential.
6. For local UI development, add the service role key and Gemini settings to .env. Never commit .env.

The initial storage bucket and Streamlit server upload cap are both 10 MB to match the default MAX_UPLOAD_MB. If you intentionally raise the application limit, adjust the bucket's file-size limit in Supabase and maxUploadSize in .streamlit/config.toml as well, and keep within your provider plan.

## Run the applications

### CLI

    python cli.py

Choose a PDF, TXT file, or pasted text. For pasted text, enter a line containing END when finished. Then ask multiple questions until typing exit. The CLI requires a Gemini key and a configured model, but no login or Supabase credentials.

### Streamlit

    streamlit run app.py

Register with a username and password, upload documents or paste text, start a conversation, and choose one or more sources. The app keeps conversation history and source excerpts in your account. Forgotten passwords cannot be recovered by email in this initial username-only version.

### Tests

    python -m pytest -q

The unit and service tests do not need a real Gemini key or Supabase account. Gemini and database calls are mocked or exercised through in-memory fakes. Tests do not claim that a live Gemini model or a live Supabase project was contacted.

## Configuration reference

| Setting | Default | Purpose |
| --- | ---: | --- |
| GEMINI_API_KEY | unset | Gemini API key; required to generate answers |
| GEMINI_MODEL | unset | Explicit model available to your account; no fallback |
| SUPABASE_URL | unset | Supabase project URL; required by Streamlit |
| SUPABASE_SERVICE_ROLE_KEY | unset | Server-only Supabase key; required by Streamlit |
| SUPABASE_BUCKET_NAME | documents | Private Storage bucket |
| MAX_UPLOAD_MB | 10 | Per-file application limit |
| MAX_PDF_PAGES | 200 | Maximum PDF page count |
| MAX_TEXT_CHARS | 200000 | Extracted or pasted text ceiling |
| MAX_QUESTION_CHARS | 4000 | Maximum user question length |
| MAX_QUESTIONS_PER_USER_PER_DAY | 15 | Atomic per-user daily generation allowance |
| MAX_QUESTIONS_GLOBAL_PER_DAY | 100 | Atomic shared daily generation allowance |
| MAX_RETRIEVED_CHUNKS | 6 | Maximum evidence excerpts per Gemini request |
| CHUNK_SIZE_CHARS | 1200 | Approximate chunk length |
| CHUNK_OVERLAP_CHARS | 180 | Chunk overlap, smaller than chunk size |
| MAX_CHAT_HISTORY_PAIRS | 4 | Recent conversation pairs sent for follow-up context |
| SESSION_TIMEOUT_MINUTES | 60 | Streamlit inactivity timeout |
| MAX_SESSION_LIFETIME_HOURS | 12 | Maximum time since login before re-authentication |
| REQUEST_TIMEOUT_SECONDS | 35 | Gemini HTTP timeout |
| MAX_ANSWER_TOKENS | 700 | Generation output cap |

The limits are conservative application safeguards, not provider quotas. Limits are configurable, but the Gemini free tier, Supabase plan, and Streamlit hosting can impose separate limits. Daily allowances are reserved atomically before generation. A reservation is consumed if Gemini fails after the reservation; this conservative behavior prevents retries from bypassing the daily cap. No reservation occurs for an empty question or a question with no retrieved evidence.

## Security and privacy choices

- Passwords use Argon2id hashes and are never put in session state, logs, prompts, or URLs.
- Usernames are normalized and unique case-insensitively. Login errors are generic and the server tracks a short rolling login-attempt window.
- Supabase RLS is enabled with no public data policies. The Python application uses the service-role key only server-side and applies owner filters to each private query.
- Storage is private. Server-generated UUID paths are used instead of trusting uploaded filenames as paths.
- PDF and TXT processing is local. Files are not sent to Gemini for extraction.
- The model receives only retrieved excerpts, selected sources, the current question, and a small history window. Document instructions are treated as untrusted content.
- Source labels are resolved from retrieved chunks by the app. Model-generated source names or page numbers are not trusted.
- The app reserves question usage through a transaction-safe PostgreSQL RPC to prevent concurrent requests from exceeding configured limits.

This small custom username/password system is not an audited production identity platform and does not include account recovery. Anyone hosting a public demo should also consider registration abuse, service quotas, backups, and their privacy obligations.

## Limitations

- Scanned PDFs are not OCR-processed; extraction reports that no text was found.
- Keyword retrieval is deterministic and inexpensive, but it can miss relevant passages when wording differs substantially.
- A model can still make mistakes even with strict evidence grounding and source checks.
- Gemini API and hosting free-tier limits can change and are not unlimited.
- Free-tier Gemini data-handling terms differ from paid services. Check the current Google terms before sending private or regulated data.
- The app does not yet support password resets, email, OCR, semantic embeddings, conversation export, or document renaming.
- Supabase Storage and Postgres changes are separate transactions; the service attempts cleanup on failed uploads, but provider failures can leave an orphaned private object that may need manual cleanup.
- Deleting a document removes its original object, extracted chunks, and conversation selection links. Existing messages retain their answer and citation excerpt as a historical snapshot.
- Example answers in this README are evidence-based expectations, not verified live model transcripts.

## Troubleshooting

- **Missing configuration message:** Check .env spelling and restart Streamlit. For Community Cloud, add each key to app Secrets.
- **Gemini rejects the request:** Verify that the API key is active and GEMINI_MODEL is available to that account. No substitute model is tried automatically.
- **Quota reached:** Review Google AI Studio usage and the configured per-user/global app limits. Try again after the provider or app's daily window resets.
- **PDF has no text:** It may be scanned or image-only. OCR is not included; use a text-based PDF or TXT export.
- **Supabase table or RPC missing:** Rerun the migration in the intended project and confirm the project URL matches the environment.
- **Private file upload fails:** Confirm that the private documents bucket exists, its upload limit matches MAX_UPLOAD_MB, and the service-role key belongs to the same Supabase project.
- **Login attempt limit:** Wait for the 15-minute rolling window to expire. Successful login clears that username's attempts.

## Deploy on Streamlit Community Cloud

Deployment requires your own GitHub, Streamlit Community Cloud, Supabase, and Gemini account access. No live deployment is included or claimed by this repository.

1. Push this project to a private or public GitHub repository. Ensure .env and .streamlit/secrets.toml are not tracked.
2. Create the Supabase project, run the SQL migration, and verify the documents bucket is private.
3. In Streamlit Community Cloud, create an app from the repository with app.py as the entry point.
4. In the app's Secrets settings, add values in TOML form:

        GEMINI_API_KEY = "replace_with_your_key"
        GEMINI_MODEL = "replace_with_a_model_available_to_your_account"
        SUPABASE_URL = "https://your-project.supabase.co"
        SUPABASE_SERVICE_ROLE_KEY = "replace_with_your_service_role_key"
        SUPABASE_BUCKET_NAME = "documents"
        MAX_UPLOAD_MB = "10"
        MAX_PDF_PAGES = "200"
        MAX_QUESTIONS_PER_USER_PER_DAY = "15"
        MAX_QUESTIONS_GLOBAL_PER_DAY = "100"
        MAX_RETRIEVED_CHUNKS = "6"
        CHUNK_SIZE_CHARS = "1200"
        CHUNK_OVERLAP_CHARS = "180"
        MAX_CHAT_HISTORY_PAIRS = "4"
        SESSION_TIMEOUT_MINUTES = "60"
        MAX_SESSION_LIFETIME_HOURS = "12"
        MAX_TEXT_CHARS = "200000"
        MAX_QUESTION_CHARS = "4000"
        REQUEST_TIMEOUT_SECONDS = "35"
        MAX_ANSWER_TOKENS = "700"

5. Deploy and verify registration, upload, a supported answer with sources, a not-found response, and a second account's data isolation using fictional test documents.
6. Monitor provider usage and adjust app safeguards downward when needed. Streamlit hosting, Supabase, and Gemini each have separate quotas.

The current repository has not been deployed; account setup, secrets entry, deployment, and live verification remain manual steps.

## Screenshots

The screenshots folder explains how to capture real product screenshots after setup. Replace the placeholder guidance with images from a configured demo. Never include a service key, private document, or personal account information.

## Future improvements

- Optional local OCR for scanned documents with a clear user-controlled path.
- Better multilingual and semantic retrieval without paid services by default.
- Document rename and conversation deletion/export.
- Audited authentication, password reset, account recovery, and production security review.
- More robust cleanup workflows for cross-service storage/database failures.
- Automated end-to-end checks against a disposable Supabase project.

## Suggested Git commits

    feat: add shared document extraction and retrieval core
    feat: add grounded Gemini answers and CLI
    feat: add Supabase auth, private storage, and atomic quotas
    feat: add PinkyDocs Streamlit workspace and mascot
    docs: add setup, privacy, and free deployment guide
