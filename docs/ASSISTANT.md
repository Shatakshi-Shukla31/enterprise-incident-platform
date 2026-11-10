# Assistant configuration

The platform owner is **Shatakshi Shukla**. The assistant answers greetings, owner questions, and requests for help without a model or an API key. IT troubleshooting searches the user's permitted knowledge articles and resolved incidents and returns cited answers.

## Connect a chat API

Use any service that implements `POST /chat/completions` with OpenAI-compatible request and response bodies. Add these server environment variables locally in `.env`, or on Render under the service's **Environment** settings:

```dotenv
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://your-provider.example/v1
LLM_MODEL=your-provider-model-id
LLM_API_KEY=your-private-provider-key
```

Use the provider's actual base URL and model ID; do not include `/chat/completions` in the base URL. Restart or redeploy the API after changing its environment. The key stays on the server and is never included in frontend code. No key is shipped with this repository. `LLM_PROVIDER=extractive` works without a key, and a failed provider request falls back to cited extractive answers.

## Knowledge

The **Knowledge** button inside the assistant searches articles the current user may read. **Ask about this** copies the selected topic into the message box. Managers can create articles on the main Knowledge page; requesters can search public articles from chat.

The public `backend/data/knowledge/KB-1000.md` article contains the owner and assistant guide. On single-process hosts such as this Render deployment, the knowledge reconciliation job indexes new or changed bundled articles shortly after startup (first scheduled run is after one minute), then hourly while the service is awake. It preserves existing tickets and user-created articles. For local setups, run `python -m scripts.seed_demo` from `backend` against the intended database, as described in LOCAL_SETUP.md, to index changed articles without resetting existing tickets.

## Attachments

The **+** button in the composer opens an **Add** menu with **Image**, **Audio**, **Video**, **PDF**, and **Files** pickers, plus a camera and a voice-note recorder. Choose an option to open its picker. Click outside or press Escape to close the menu; arrow keys move between options. Each message accepts three files, up to 5 MB each. Images display in the chat; audio and video have playback controls; PDFs and text files can be downloaded. Only the uploader can retrieve their files.

Text and log files contribute error lines to the knowledge search. Images, recordings, video, and PDFs are stored for reference, rather than interpreted by the model. Add a description or transcript in the message. Browser speech recognition, when available, can fill in the words of a voice note.

Press Enter to send, or Shift+Enter for a new line. If sending fails, the message and successfully uploaded attachments are restored so they can be retried.
