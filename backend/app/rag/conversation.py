"""Small conversational replies that do not need a knowledge search or an API key."""

import re

from app.rag.generator import GeneratedAnswer

OWNER_NAME = "Shatakshi Shukla"


def conversational_reply(message: str) -> GeneratedAnswer | None:
    # Match whole messages so "hi, my VPN failed" still reaches troubleshooting.
    text = re.sub(r"[^\w\s]", "", message.lower())
    text = " ".join(text.split())
    reply = None
    if re.fullmatch(r"(?:hi|hello|hey)(?: there| assistant)?(?: how are you)?|how are you", text):
        reply = (
            "Hi! I'm the Incident Platform support assistant. How can I help you today? "
            "Describe an IT issue, search the knowledge base, or ask about the platform."
        )
    elif re.fullmatch(
        r"(?:(?:who|how|what) (?:is|s) (?:your|the|this platforms?) "
        r"(?:owner|oewner|creator|developer)(?:s? name)?"
        r"|(?:your )?(?:owner|oewner|creator)(?:s? name)?"
        r"|who (?:owns|created|made|built|developed) (?:you|this|this platform|the platform)"
        r"|who is shatakshi shukla)",
        text,
    ):
        reply = f"The owner of Incident Platform is {OWNER_NAME}. I'm the platform's AI support assistant."
    elif text in {"who are you", "what can you do", "help", "how do i use this", "how does this work"}:
        reply = (
            f"I'm the Incident Platform support assistant, owned by {OWNER_NAME}. "
            "I help troubleshoot IT issues using knowledge articles and resolved incidents you can access, "
            "with sources you can check. Open Knowledge to search articles, or attach an image, audio, "
            "video, PDF, or text/log file to your message. Media files are saved for reference; "
            "describe their contents in your message so I can help."
        )
    elif text in {"thanks", "thank you", "thanks a lot", "thank you so much"}:
        reply = "You're welcome! Let me know if you need help with anything else."
    if reply is None:
        return None
    return GeneratedAnswer(reply, [], False, "platform_profile", 0)
