# Interview Analysis
# © 2026 Dennis Schulmeister-Zimolong <dennis@wpvs.de>
#
# This source code is licensed under the BSD 3-Clause License found in the
# LICENSE file in the root directory of this source tree.

"""
Low-level LLM API wrapper.

This module encapsulates the direct OpenAI SDK calls and provides small helper
functions used by higher-level analysis code.

Environment variables:
    - `LLM_OPENAI_API_KEY`: API key for the OpenAI-compatible endpoint
    - `LLM_OPENAI_MODEL`: Model identifier
    - `LLM_OPENAI_BASE_URL`: Optional explicit base URL (preferred)
    - `LLM_OPENAI_HOST`: Hostname (legacy)
    - `LLM_OPENAI_PATH`: Optional path (legacy)
"""

import json
import os

from typing import Any, TypeAlias, cast

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

JsonValue: TypeAlias = (
    dict[str, "JsonValue"]
    | list["JsonValue"]
    | str
    | int
    | float
    | bool
    | None
)


def _require_env(name: str) -> str:
    """
    Get a required environment variable.

    Args:
        name:
            Environment variable name.

    Returns:
        The environment variable value.

    Raises:
        RuntimeError:
            If the variable is missing or empty.
    """

    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _openai_base_url() -> str:
    """
    Determine the base URL for the OpenAI-compatible endpoint.

    Returns:
        Base URL ending with `/v1`.
    """

    base_url = os.environ.get("LLM_OPENAI_BASE_URL")
    if base_url:
        return base_url.rstrip("/")

    host = _require_env("LLM_OPENAI_HOST")
    path = os.environ.get("LLM_OPENAI_PATH", "")

    # LLM_OPENAI_PATH historically points to the full endpoint (e.g. /v1/chat/completions).
    # The OpenAI SDK expects a base URL that ends with /v1.
    if "/v1" in path:
        prefix = path.split("/v1", 1)[0] + "/v1"
    else:
        prefix = "/v1"

    return f"https://{host}{prefix}"


def _parse_json_content(content: str) -> JsonValue:
    """
    Parse JSON content from the model response.

    Args:
        content:
            Raw string content.

    Returns:
        Parsed JSON value. Returns None for empty responses.
    """

    if not content.strip():
        return None
    return cast(JsonValue, json.loads(content))


def _ensure_json_instruction(messages: list[ChatCompletionMessageParam]) -> list[ChatCompletionMessageParam]:
    """Ensure at least one message contains the word 'json'.

    Some OpenAI-compatible endpoints require that the prompt contains the word
    'json' when using response_format of type json_object/json_schema.
    """

    for m in messages:
        content = m.get("content")
        if isinstance(content, str) and "json" in content.lower():
            return messages

    # Prefer appending to an existing system message to avoid changing turn order.
    if messages:
        first = messages[0]
        if first.get("role") == "system" and isinstance(first.get("content"), str):
            patched = list(messages)
            patched[0] = {
                **first,
                "content": (first.get("content") or "") + " Respond with valid JSON.",
            }
            return patched

    return [
        {"role": "system", "content": "Respond with valid JSON."},
        *messages,
    ]


async def ai_conversation(
    messages: list[ChatCompletionMessageParam],
    *,
    response_format: dict[str, Any] | None = None,
    parse_json: bool = False,
) -> str | JsonValue:
    """
    Run a chat completion call.

    Args:
        messages:
            OpenAI chat message list.
        response_format:
            Optional response format payload passed to the API.
        parse_json:
            If true, attempts to parse the response as JSON and returns a
            `JsonValue`.

    Returns:
        The response content as a string or parsed JSON.

        On API or parsing errors, the function returns a string (when
        `parse_json` is false) or an error object with `_error` and `_raw` fields
        (when `parse_json` is true).
    """

    client = AsyncOpenAI(
        api_key=_require_env("LLM_OPENAI_API_KEY"),
        base_url=_openai_base_url(),
    )

    try:
        completion_kwargs: dict[str, Any] = {}

        if response_format is not None:
            completion_kwargs["response_format"] = response_format

        response = await client.chat.completions.create(
            model=_require_env("LLM_OPENAI_MODEL"),
            messages=messages,
            **completion_kwargs,
        )

        content = response.choices[0].message.content or ""

        if not parse_json:
            return content

        try:
            return _parse_json_content(content)
        except json.JSONDecodeError as error:
            return {
                "_error": f"Invalid JSON response: {error}",
                "_raw": content,
            }
    except Exception as error:
        if parse_json:
            return {
                "_error": f"Error calling the OpenAI API: {error}",
                "_raw": None,
            }
        return f"Error calling the OpenAI API: {error}"


async def ai_conversation_json(
    messages: list[ChatCompletionMessageParam],
    *,
    json_schema: dict[str, Any] | None = None,
) -> JsonValue:
    """
    Run a chat completion call and always return a JSON value.

    Args:
        messages:
            OpenAI chat message list.
        json_schema:
            Optional JSON schema definition for structured outputs.

    Returns:
        Parsed JSON result. Errors are returned as objects with `_error` and
        `_raw` fields.
    """

    response_format: dict[str, Any]
    if json_schema is None:
        response_format = {"type": "json_object"}
    else:
        response_format = {"type": "json_schema", "json_schema": json_schema}

    result = await ai_conversation(
        _ensure_json_instruction(messages),
        response_format=response_format,
        parse_json=True,
    )

    if isinstance(result, str):
        return {"_error": result, "_raw": None}

    return result
