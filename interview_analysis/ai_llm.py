# Forschungsprojekt KoLLI: Dashboard
# © 2024 DHBW Karlsruhe / Studiengang Wirtschaftsinformatik
# Dennis Schulmeister-Zimolong <dennis@wpvs.de>
#
# This source code is licensed under the BSD 3-Clause License found in the
# LICENSE file in the root directory of this source tree.

import asyncio
import json
import os

from collections.abc   import AsyncIterator
from typing            import Any, Coroutine, TypeAlias, cast
from openai            import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam
from shiny             import reactive

JsonValue: TypeAlias = (
    dict[str, "JsonValue"]
    | list["JsonValue"]
    | str
    | int
    | float
    | bool
    | None
)

def ai_conversation_available():
    try:
        return True if os.environ["LLM_OPENAI_API_KEY"] else False
    except KeyError:
        return False

def ai_message(
    text: str,
    messages: list[ChatCompletionMessageParam] | None = None,
) -> list[ChatCompletionMessageParam]:
    if messages is None:
        messages = [
            cast(ChatCompletionMessageParam, {
                "role": "system",
                "content": "Wir haben verschiedene Umfragen unter den Studierenden gemacht, "
                           "weil wir die Studierenden partizipativ in Entscheidungen und die "
                           "Mitgestaltung ihrer Vorlesungen einbeziehen wollen. Wir wollen also "
                           "nicht nur Lernaktivitäten fördern, sondern darüber hinaus den Studierenden "
                           "gezielte Einflussname ermöglichen. Bitte hilf uns bei der Beantwortung "
                           "folgender Fragen zur Auswertung der Ergebnisse. Bitte beachte, dass es sich "
                           "hierbei um Äußerungen zu mehreren Veranstaltungen von unterschiedlichen Lehrpersonen "
                           "mit unterschiedlichen Inhalten und unterschiedlichen Arten und Tiefe der "
                           "Einflussnahme handelt."
            })
        ]

    messages.append(cast(ChatCompletionMessageParam, {
        "role": "user",
        "content": text,
    }))

    return messages

def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise KeyError(name)
    return value

def _openai_base_url() -> str:
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
    if not content.strip():
        return None
    return cast(JsonValue, json.loads(content))

async def ai_conversation(
    messages: list[ChatCompletionMessageParam],
    *,
    response_format:       dict[str, Any] | None = None,
    parse_json:            bool = False,
) -> str | JsonValue:
    client = AsyncOpenAI(
        api_key=_require_env("LLM_OPENAI_API_KEY"),
        base_url=_openai_base_url(),
    )

    try:
        completion_kwargs = {}

        if response_format is not None:
            completion_kwargs["response_format"] = response_format

        response = await client.chat.completions.create(
            model    = _require_env("LLM_OPENAI_MODEL"),
            messages = messages,
            **completion_kwargs,
        )

        content = response.choices[0].message.content or ""

        if not parse_json:
            return content

        try:
            return _parse_json_content(content)
        except json.JSONDecodeError as error:
            return {
                "_error": f"Ungültige JSON-Antwort: {error}",
                "_raw": content,
            }
    except Exception as error:
        return f"Fehler beim Aufruf der OpenAI API. Die Antwort war: {error}"

async def ai_conversation_json(
    messages: list[ChatCompletionMessageParam],
    *,
    json_schema:           dict[str, Any] | None = None,
) -> JsonValue:
    response_format: dict[str, Any]
    if json_schema is None:
        response_format = {"type": "json_object"}
    else:
        response_format = {"type": "json_schema", "json_schema": json_schema}

    result = await ai_conversation(
        messages,
        response_format = response_format,
        parse_json      = True,
    )

    if isinstance(result, str):
        return {"_error": result, "_raw": None}

    return result

async def ai_conversation_stream(
    messages: list[ChatCompletionMessageParam],
) -> AsyncIterator[str]:
    client = AsyncOpenAI(
        api_key=_require_env("LLM_OPENAI_API_KEY"),
        base_url=_openai_base_url(),
    )

    accumulated = ""

    try:
        stream = await client.chat.completions.create(
            model=_require_env("LLM_OPENAI_MODEL"),
            messages=messages,
            stream=True,
        )

        async for chunk in stream:
            delta = chunk.choices[0].delta.content or ""

            if not delta:
                continue

            accumulated += delta
            yield accumulated
    except Exception as error:
        yield f"Fehler beim Aufruf der OpenAI API. Die Antwort war: {error}"

ai_tasks: dict[str, asyncio.Task] = {}

def start_ai_task(*, coro: Coroutine[Any, Any, Any], task_name: str) -> None:
    current_task = ai_tasks.get(task_name)

    if current_task is not None:
        current_task.cancel()

    task = asyncio.create_task(coro)

    ai_tasks[task_name] = task

    def _on_done(done_task: asyncio.Task):
        if ai_tasks.get(task_name) is done_task:
            del ai_tasks[task_name]

    task.add_done_callback(_on_done)

def cancel_ai_stream(task_name: str) -> None:
    task = ai_tasks.get(task_name)
    if task is None:
        return

    task.cancel()

    # Remove immediately so a new task can be started right away.
    if ai_tasks.get(task_name) is task:
        del ai_tasks[task_name]

def start_ai_stream(*, question: str, target_md: reactive.Value, task_name: str) -> None:
    async def _run_stream():
        try:
            target_md.set("<span class='text-secondary'>Antwort wird generiert …</span>")

            async for partial in ai_conversation_stream(ai_message(question)):
                target_md.set(partial)
                await reactive.flush()
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            raise

    start_ai_task(coro=_run_stream(), task_name=task_name)