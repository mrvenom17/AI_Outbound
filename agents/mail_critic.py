# agents/mail_critic.py
"""
Mail Critic Agent: evaluates outbound emails before send.
If the email does not meet quality thresholds, returns feedback for rewrite.
"""
import os
import json
from typing import Tuple, Optional
from dotenv import load_dotenv

load_dotenv()


def evaluate_email(
    email_body: str,
    recipient_name: str,
    company: str,
    min_score: float = 0.7,
    strictness: str = "medium",
) -> Tuple[bool, float, str]:
    """
    Critic evaluates the email. Returns (passed, score, feedback).
    
    Args:
        email_body: The draft email body to evaluate
        recipient_name: Recipient name (for context)
        company: Company name (for context)
        min_score: Minimum score (0-1) to pass. From settings.
        strictness: "low", "medium", "high" - affects how strict the critic is. From settings.
    
    Returns:
        (passed: bool, score: float 0-1, feedback: str for rewrite if not passed)
    """
    try:
        from langchain_openai import ChatOpenAI
        from langchain_core.prompts import ChatPromptTemplate
    except ImportError:
        return (True, 1.0, "")  # No LLM available: pass through

    model_name = "meta-llama/llama-3.1-8b-instruct"
    llm = ChatOpenAI(
        model=model_name,
        temperature=0.1,  # Low for consistent evaluation
        api_key=os.getenv("OPENROUTER_API_KEY"),
        base_url="https://openrouter.ai/api/v1",
    )

    strict_instructions = {
        "low": "Be lenient. Only fail for clear spam, links, or extreme length issues.",
        "medium": "Standard quality bar: no marketing hype, no links, 40-90 words, professional tone, at least one specific reference.",
        "high": "Strict: must be concise, evidence-based, no flattery, no assumptions, neutral tone, and clearly relevant to the recipient.",
    }
    strict_text = strict_instructions.get(strictness, strict_instructions["medium"])

    prompt_template = """You are a cold-email CRITIC. Your job is to evaluate outbound B2B emails before they are sent.

Evaluate this draft email for: {recipient_name} at {company}.

DRAFT EMAIL:
---
{email_body}
---

EVALUATION RULES ({strictness}):
{strict_instruction}

Check for:
1. TONE: Professional, neutral, no hype/flattery/marketing language (e.g. no "amazing", "incredible", "best").
2. LENGTH: Roughly 40-90 words, 3-5 sentences. Not too short (avoid generic one-liners) or too long.
3. CONTENT: No links, no URLs, no emojis. Plain text only.
4. RELEVANCE: If possible, should reference something specific (company, role, or context). Generic is OK but slightly penalized.
5. CTA: Should have a clear, low-friction call to action.

You MUST respond with ONLY a single JSON object, no other text:
{{
  "passed": true or false,
  "score": 0.0 to 1.0,
  "feedback": "If passed is false, give 1-3 short bullet points on what to fix. If passed is true, can be empty or brief note."
}}

Minimum score to pass for this run: {min_score}. So passed must be true only if score >= {min_score}.
"""

    prompt = ChatPromptTemplate.from_template(prompt_template)
    chain = prompt | llm

    try:
        response = chain.invoke({
            "email_body": email_body,
            "recipient_name": recipient_name,
            "company": company,
            "strictness": strictness,
            "strict_instruction": strict_text,
            "min_score": min_score,
        })
        content = response.content.strip()

        # Parse JSON (allow markdown code block)
        if content.startswith("```"):
            lines = content.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            content = "\n".join(lines).strip()

        data = json.loads(content)
        passed = bool(data.get("passed", False))
        score = float(data.get("score", 0.0))
        feedback = str(data.get("feedback", "")).strip()

        # Enforce min_score on our side too
        if score < min_score:
            passed = False
        if passed and score < min_score:
            passed = False

        return (passed, score, feedback)
    except Exception as e:
        # On any error, pass through (don't block sending)
        import logging
        logging.getLogger(__name__).warning(f"Mail critic evaluation failed: {e}")
        return (True, 1.0, "")


def rewrite_email_with_feedback(
    email_body: str,
    feedback: str,
    recipient_name: str,
    company: str,
) -> str:
    """
    Rewrite the email taking into account the critic's feedback.
    Returns the revised email body.
    """
    try:
        from langchain_openai import ChatOpenAI
        from langchain_core.prompts import ChatPromptTemplate
    except ImportError:
        return email_body

    model_name = "meta-llama/llama-3.1-8b-instruct"
    llm = ChatOpenAI(
        model=model_name,
        temperature=0.3,
        api_key=os.getenv("OPENROUTER_API_KEY"),
        base_url="https://openrouter.ai/api/v1",
    )

    prompt_template = """You are a cold-email editor. Rewrite this email to address the critic's feedback. Keep the same intent and recipient/company.

ORIGINAL EMAIL (to {recipient_name} at {company}):
---
{email_body}
---

CRITIC FEEDBACK (address these points):
{feedback}

RULES:
- Output ONLY the revised email body. No preamble, no "Here is the revised email:", no explanations.
- Keep it 40-90 words, 3-5 sentences. Plain text. No links, no emojis.
- Professional, neutral tone. No marketing hype.
"""

    prompt = ChatPromptTemplate.from_template(prompt_template)
    chain = prompt | llm

    try:
        response = chain.invoke({
            "email_body": email_body,
            "feedback": feedback,
            "recipient_name": recipient_name,
            "company": company,
        })
        revised = response.content.strip()
        # Strip common LLM wrappers
        for prefix in ("Here is the revised email:", "Revised email:", "Here's the revised version:"):
            if revised.lower().startswith(prefix.lower()):
                revised = revised[len(prefix):].strip()
        if revised.startswith("---"):
            lines = revised.split("\n")
            while lines and lines[0].strip() == "---":
                lines.pop(0)
            while lines and lines[-1].strip() == "---":
                lines.pop()
            revised = "\n".join(lines).strip()
        return revised if revised else email_body
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Mail rewrite failed: {e}")
        return email_body
