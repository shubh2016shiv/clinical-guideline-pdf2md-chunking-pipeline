"""
openai_image_explanation_check.py

Vision figure-to-Markdown checker for extracted PDF figures.

Key changes from the earlier quick-check script:
  * Uses OPENAI_API_KEY from the environment; no hardcoded secret.
  * Defaults GPT-5 nano to reasoning_effort=minimal so hidden reasoning tokens do
    not consume the whole output budget.
  * Uses the Responses API by default for GPT-5-style reasoning and verbosity
    controls, with a Chat Completions fallback for compatible providers.
  * Lets the model infer domain and figure type from the image itself.
  * Always asks for both a faithful extraction/representation and a separate
    explanation section.
  * Adds deterministic figure_name metadata from image bytes, not page number.
  * Retries empty responses by lowering reasoning effort and raising output budget.

Usage:
  export OPENAI_API_KEY="..."
  uv run openai_image_explanation_check.py path/to/figure.png
  uv run openai_image_explanation_check.py figures/ --output-jsonl out.jsonl
  uv run openai_image_explanation_check.py figures/*.png \
      --model gpt-5-nano --reasoning-effort minimal --verbosity high \
      --max-output-tokens 5000 --detail high --budget careful

Install if needed:
  uv add openai pillow
  # or: pip install openai pillow
"""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import mimetypes
import os
import sys
import tempfile
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

from PIL import Image, ImageOps, UnidentifiedImageError

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - friendliness for direct script usage.
    OpenAI = None  # type: ignore[assignment]

SUPPORTED_IMAGE_SUFFIXES: Final[frozenset[str]] = frozenset(
    {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
)

DEFAULT_MODEL: Final[str] = "gpt-5-nano"
DEFAULT_BASE_URL: Final[str] = "https://api.openai.com/v1"
DEFAULT_REASONING_EFFORT: Final[str] = "minimal"
DEFAULT_VERBOSITY: Final[str] = "high"
DEFAULT_USER_PROMPT: Final[str] = "Analyze this extracted image and convert it into insertion-ready Markdown."

AUTO_DOMAIN_FIGURE_PROMPT: Final[str] = """\
YYou are a figure-to-Markdown converter for document assembly.

You will receive exactly one extracted figure image. You may infer the domain and figure type internally, but do not print diagnostic labels such as inferred domain, figure type, confidence, model name, API name, or analysis metadata.

Your output must be insertion-ready Markdown only.

The Markdown must contain:
1. A figure heading.
2. An extracted representation appropriate to the visual type.
3. A comprehensive explanation.

Choose the extracted representation based on the image:
- If it is a table, produce a Markdown table.
- If it is a flowchart, decision tree, process diagram, system architecture, or model architecture, produce an ASCII diagram in a fenced text block.
- If it is a chart or graph, extract axes, legends, series, and visible values into Markdown tables where possible, then explain the trend or comparison.
- If it is code or pseudocode, transcribe it in a fenced code block, then explain it.
- If it is an equation or formula, transcribe it using LaTeX Markdown, then explain the symbols and relationship.
- If it is a screenshot or UI, describe the visible UI structure and important text, then explain its purpose.
- If it is decorative or low-information, produce a short useful description and explain that it has no substantive data-bearing content.

Required Markdown format:

### Figure: <visible title if present, otherwise deterministic figure name>

#### Extracted representation

<best extraction format>

#### Explanation

<clear, comprehensive explanation>

Faithfulness rules:
- Do not invent values, labels, arrows, or relationships that are not visible.
- Preserve visible labels, numbers, thresholds, units, and abbreviations exactly where legible.
- If text is unreadable, write `illegible`.
- Do not expose internal classification metadata in the Markdown.
"""


@dataclass(frozen=True)
class ImageBudget:
    """Pre-upload image normalization budget."""

    name: str
    max_edge_pixels: int
    max_pixels: int
    jpeg_quality: int
    min_jpeg_quality: int
    max_image_bytes: int


IMAGE_BUDGETS: Final[dict[str, ImageBudget]] = {
    "aggressive": ImageBudget(
        name="aggressive",
        max_edge_pixels=960,
        max_pixels=900_000,
        jpeg_quality=72,
        min_jpeg_quality=48,
        max_image_bytes=450_000,
    ),
    "balanced": ImageBudget(
        name="balanced",
        max_edge_pixels=1600,
        max_pixels=2_200_000,
        jpeg_quality=84,
        min_jpeg_quality=60,
        max_image_bytes=950_000,
    ),
    "careful": ImageBudget(
        name="careful",
        max_edge_pixels=2400,
        max_pixels=5_000_000,
        jpeg_quality=90,
        min_jpeg_quality=70,
        max_image_bytes=2_200_000,
    ),
}


@dataclass(frozen=True)
class PreparedImage:
    source_path: Path
    data_url: str
    source_sha256: str
    figure_name: str
    source_bytes: int
    upload_bytes: int
    original_size: tuple[int, int]
    prepared_size: tuple[int, int]
    jpeg_quality: int


@dataclass(frozen=True)
class VisionResult:
    markdown: str
    model: str
    finish_reason: str
    usage: dict[str, Any]
    api: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Explain image(s) with an OpenAI-compatible vision LLM.")
    parser.add_argument("inputs", nargs="+", help="Image files, directories, or shell-expanded globs.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--api",
        choices=["responses", "chat"],
        default="responses",
        help="Use Responses API by default for GPT-5 reasoning/verbosity controls.",
    )
    parser.add_argument(
        "--budget",
        choices=sorted(IMAGE_BUDGETS),
        default="balanced",
        help="Image resize/compression preset.",
    )
    parser.add_argument(
        "--max-image-bytes",
        type=int,
        default=None,
        help="Override budget upload byte ceiling after JPEG compression.",
    )
    parser.add_argument(
        "--max-output-tokens",
        "--max-tokens",
        dest="max_output_tokens",
        type=int,
        default=5000,
        help=(
            "Caps total generated tokens, including hidden GPT-5 reasoning tokens. "
            "Use reasoning_effort=minimal so most of this budget remains visible output."
        ),
    )
    parser.add_argument(
        "--reasoning-effort",
        choices=["minimal", "low", "medium", "high"],
        default=DEFAULT_REASONING_EFFORT,
        help=f"GPT-5 reasoning effort. Default: {DEFAULT_REASONING_EFFORT}.",
    )
    parser.add_argument(
        "--verbosity",
        choices=["low", "medium", "high"],
        default=DEFAULT_VERBOSITY,
        help=f"GPT-5 Responses API text verbosity. Default: {DEFAULT_VERBOSITY}.",
    )
    parser.add_argument(
        "--retry-empty",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Retry with safer settings if the model returns empty visible text.",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=None,
        help="Optional sampling temperature. Omitted by default for GPT-5 compatibility.",
    )
    parser.add_argument(
        "--top-p",
        type=float,
        default=None,
        help="Optional nucleus sampling value. Omitted by default for GPT-5 compatibility.",
    )
    parser.add_argument(
        "--detail",
        choices=["auto", "low", "high", "original"],
        default="high",
        help="OpenAI-compatible image detail hint. Use high for tiny labels.",
    )
    parser.add_argument(
        "--system-prompt-file",
        type=Path,
        default=None,
        help="Optional text file replacing the built-in auto-domain figure prompt.",
    )
    parser.add_argument("--user-prompt", default=DEFAULT_USER_PROMPT, help="User prompt sent with each image.")
    parser.add_argument("--output-jsonl", type=Path, default=None, help="Write one JSON object per image.")
    parser.add_argument(
        "--output-markdown-dir",
        type=Path,
        default=None,
        help="Write each image explanation to <figure_name>.md in this directory.",
    )
    parser.add_argument("--no-dedupe", action="store_true", help="Do not skip duplicate image byte hashes.")
    parser.add_argument("--dry-run", action="store_true", help="Prepare images only; do not call the API.")
    return parser.parse_args()


def iter_image_paths(inputs: Iterable[str]) -> list[Path]:
    image_paths: list[Path] = []
    for raw_input in inputs:
        input_path = Path(raw_input).expanduser()
        if input_path.is_dir():
            image_paths.extend(
                path
                for path in sorted(input_path.rglob("*"))
                if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES
            )
            continue
        if input_path.is_file() and input_path.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES:
            image_paths.append(input_path)
            continue
        print(f"Skipping non-image input: {input_path}", file=sys.stderr)
    return image_paths


def read_system_prompt(args: argparse.Namespace) -> str:
    if args.system_prompt_file is not None:
        return args.system_prompt_file.read_text(encoding="utf-8").strip()
    return AUTO_DOMAIN_FIGURE_PROMPT


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as image_file:
        for chunk in iter(lambda: image_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def make_figure_name(path: Path, source_sha256: str) -> str:
    # Deterministic and independent of page_number metadata.
    # The stem keeps it human-debuggable; the content hash keeps it stable across folders.
    safe_stem = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in path.stem).strip("_")
    if not safe_stem:
        safe_stem = "figure"
    return f"{safe_stem}_{source_sha256[:10]}"


def prepare_image(path: Path, budget: ImageBudget, max_image_bytes: int | None) -> PreparedImage:
    source_bytes = path.stat().st_size
    source_sha256 = sha256_file(path)
    target_bytes = max_image_bytes or budget.max_image_bytes

    try:
        with Image.open(path) as image:
            image = ImageOps.exif_transpose(image)
            original_size = image.size
            prepared = normalize_image_for_upload(image, budget)
            jpeg_bytes, jpeg_quality = encode_jpeg_under_limit(prepared, budget, target_bytes)
    except UnidentifiedImageError as exc:
        raise ValueError(f"Cannot read image file: {path}") from exc

    data_url = "data:image/jpeg;base64," + base64.b64encode(jpeg_bytes).decode("ascii")
    return PreparedImage(
        source_path=path,
        data_url=data_url,
        source_sha256=source_sha256,
        figure_name=make_figure_name(path, source_sha256),
        source_bytes=source_bytes,
        upload_bytes=len(jpeg_bytes),
        original_size=original_size,
        prepared_size=prepared.size,
        jpeg_quality=jpeg_quality,
    )


def normalize_image_for_upload(image: Image.Image, budget: ImageBudget) -> Image.Image:
    if image.mode in {"RGBA", "LA", "P"}:
        image = image.convert("RGBA")
        background = Image.new("RGBA", image.size, "WHITE")
        background.alpha_composite(image)
        image = background.convert("RGB")
    elif image.mode != "RGB":
        image = image.convert("RGB")

    width, height = image.size
    scale_by_edge = min(1.0, budget.max_edge_pixels / max(width, height))
    scale_by_area = min(1.0, (budget.max_pixels / max(width * height, 1)) ** 0.5)
    scale = min(scale_by_edge, scale_by_area)
    if scale < 1.0:
        new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
        image = image.resize(new_size, Image.Resampling.LANCZOS)
    return image


def encode_jpeg_under_limit(image: Image.Image, budget: ImageBudget, target_bytes: int) -> tuple[bytes, int]:
    best_bytes = b""
    best_quality = budget.jpeg_quality
    with tempfile.SpooledTemporaryFile(max_size=target_bytes * 2) as buffer:
        for quality in range(budget.jpeg_quality, budget.min_jpeg_quality - 1, -5):
            buffer.seek(0)
            buffer.truncate(0)
            image.save(buffer, format="JPEG", quality=quality, optimize=True, progressive=True)
            candidate_size = buffer.tell()
            buffer.seek(0)
            best_bytes = buffer.read()
            best_quality = quality
            if candidate_size <= target_bytes:
                break
    return best_bytes, best_quality


def image_payload_for_responses(prepared: PreparedImage, detail: str) -> dict[str, str]:
    payload = {"type": "input_image", "image_url": prepared.data_url}
    if detail != "auto":
        payload["detail"] = detail
    return payload


def image_payload_for_chat(prepared: PreparedImage, detail: str) -> dict[str, Any]:
    image_url: dict[str, str] = {"url": prepared.data_url}
    if detail != "auto":
        image_url["detail"] = detail
    return {"type": "image_url", "image_url": image_url}


def usage_to_dict(usage: Any) -> dict[str, Any]:
    if usage is None:
        return {}
    if hasattr(usage, "model_dump"):
        return usage.model_dump(mode="json")
    if isinstance(usage, dict):
        return usage
    return json.loads(json.dumps(usage, default=lambda value: getattr(value, "__dict__", str(value))))


def extract_responses_output_text(response: Any) -> str:
    direct_text = getattr(response, "output_text", None)
    if isinstance(direct_text, str) and direct_text.strip():
        return direct_text.strip()

    chunks: list[str] = []
    for item in getattr(response, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            text = getattr(content, "text", None)
            if isinstance(text, str):
                chunks.append(text)
    return "".join(chunks).strip()


def call_responses_api(
    *,
    client: Any,
    args: argparse.Namespace,
    prepared: PreparedImage,
    system_prompt: str,
    max_output_tokens: int,
) -> VisionResult:
    input_text = (
        f"{args.user_prompt}\n\n"
        f"figure_name: {prepared.figure_name}\n"
        "Use this figure_name in the heading if no visible title exists.\n"
        "Infer the domain yourself from the image."
    )
    request_kwargs: dict[str, Any] = {
        "model": args.model,
        "instructions": system_prompt,
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": input_text},
                    image_payload_for_responses(prepared, args.detail),
                ],
            }
        ],
        "reasoning": {"effort": args.reasoning_effort},
        "text": {"verbosity": args.verbosity},
        "max_output_tokens": max_output_tokens,
    }
    if args.temperature is not None:
        request_kwargs["temperature"] = args.temperature
    if args.top_p is not None:
        request_kwargs["top_p"] = args.top_p

    response = client.responses.create(**request_kwargs)
    usage = usage_to_dict(getattr(response, "usage", None))
    status = str(getattr(response, "status", "") or "")
    incomplete = getattr(response, "incomplete_details", None)
    finish_reason = status
    if incomplete is not None:
        reason = getattr(incomplete, "reason", None)
        if reason:
            finish_reason = f"{status}:{reason}"

    return VisionResult(
        markdown=extract_responses_output_text(response),
        model=str(getattr(response, "model", None) or args.model),
        finish_reason=finish_reason,
        usage=usage,
        api="responses",
    )


def call_chat_api(
    *,
    client: Any,
    args: argparse.Namespace,
    prepared: PreparedImage,
    system_prompt: str,
    max_output_tokens: int,
) -> VisionResult:
    user_text = (
        f"{args.user_prompt}\n\n"
        f"figure_name: {prepared.figure_name}\n"
        "Use this figure_name in the heading if no visible title exists.\n"
        "Infer the domain yourself from the image."
    )
    request_kwargs: dict[str, Any] = {
        "model": args.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    image_payload_for_chat(prepared, args.detail),
                ],
            },
        ],
        "max_completion_tokens": max_output_tokens,
        "reasoning_effort": args.reasoning_effort,
    }
    if args.temperature is not None:
        request_kwargs["temperature"] = args.temperature
    if args.top_p is not None:
        request_kwargs["top_p"] = args.top_p

    response = client.chat.completions.create(**request_kwargs)
    choice = response.choices[0]
    return VisionResult(
        markdown=(choice.message.content or "").strip(),
        model=str(response.model or args.model),
        finish_reason=str(choice.finish_reason or ""),
        usage=usage_to_dict(response.usage),
        api="chat",
    )


def explain_image(
    *,
    client: Any,
    args: argparse.Namespace,
    prepared: PreparedImage,
    system_prompt: str,
    max_output_tokens: int,
) -> VisionResult:
    if args.api == "responses":
        return call_responses_api(
            client=client,
            args=args,
            prepared=prepared,
            system_prompt=system_prompt,
            max_output_tokens=max_output_tokens,
        )
    return call_chat_api(
        client=client,
        args=args,
        prepared=prepared,
        system_prompt=system_prompt,
        max_output_tokens=max_output_tokens,
    )


def get_nested_int(data: dict[str, Any], paths: Iterable[tuple[str, ...]]) -> int:
    for path in paths:
        current: Any = data
        for key in path:
            if not isinstance(current, dict) or key not in current:
                current = None
                break
            current = current[key]
        if isinstance(current, int):
            return current
    return 0


def reasoning_token_count(usage: dict[str, Any]) -> int:
    return get_nested_int(
        usage,
        [
            ("completion_tokens_details", "reasoning_tokens"),
            ("output_tokens_details", "reasoning_tokens"),
        ],
    )


def output_token_count(usage: dict[str, Any]) -> int:
    return get_nested_int(usage, [("completion_tokens",), ("output_tokens",)])


def with_retry_settings(args: argparse.Namespace) -> argparse.Namespace:
    retry_args = copy.copy(args)
    retry_args.reasoning_effort = "minimal"
    retry_args.detail = "high" if args.detail == "auto" else args.detail
    retry_args.max_output_tokens = max(args.max_output_tokens * 2, 6500)
    retry_args.verbosity = "high"
    return retry_args


def explain_image_with_empty_retry(
    *,
    client: Any,
    args: argparse.Namespace,
    prepared: PreparedImage,
    system_prompt: str,
) -> VisionResult:
    result = explain_image(
        client=client,
        args=args,
        prepared=prepared,
        system_prompt=system_prompt,
        max_output_tokens=args.max_output_tokens,
    )
    if result.markdown or not args.retry_empty:
        return result

    retry_args = with_retry_settings(args)
    retry_result = explain_image(
        client=client,
        args=retry_args,
        prepared=prepared,
        system_prompt=system_prompt,
        max_output_tokens=retry_args.max_output_tokens,
    )
    if retry_result.markdown:
        return retry_result

    reasoning_tokens = reasoning_token_count(retry_result.usage)
    generated_tokens = output_token_count(retry_result.usage)
    raise RuntimeError(
        "OpenAI returned empty visible text twice. "
        f"api={retry_result.api}, model={retry_result.model}, finish_reason={retry_result.finish_reason}, "
        f"generated_tokens={generated_tokens}, reasoning_tokens={reasoning_tokens}, "
        f"usage={json.dumps(retry_result.usage, ensure_ascii=False)}. "
        "This usually means hidden reasoning consumed the output budget. "
        "Run with --reasoning-effort minimal --max-output-tokens 8000 --detail high, "
        "or promote this figure to gpt-5-mini for a second-pass fallback."
    )


def write_markdown(output_dir: Path, prepared: PreparedImage, markdown: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{prepared.figure_name}.md"
    output_path.write_text(markdown + "\n", encoding="utf-8")
    return output_path


def append_jsonl(output_path: Path, record: dict[str, object]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as output_file:
        output_file.write(json.dumps(record, ensure_ascii=False) + "\n")


def build_record(
    *,
    prepared: PreparedImage,
    status: Literal["ok", "error", "skipped", "prepared"],
    markdown: str = "",
    error: str = "",
    elapsed_seconds: float = 0.0,
    skipped_reason: str = "",
    result: VisionResult | None = None,
) -> dict[str, object]:
    usage = result.usage if result is not None else {}
    return {
        "figure_name": prepared.figure_name,
        "image_path": str(prepared.source_path),
        "status": status,
        "skipped_reason": skipped_reason,
        "source_sha256": prepared.source_sha256,
        "source_bytes": prepared.source_bytes,
        "upload_bytes": prepared.upload_bytes,
        "upload_bytes_saved": max(prepared.source_bytes - prepared.upload_bytes, 0),
        "original_size": list(prepared.original_size),
        "prepared_size": list(prepared.prepared_size),
        "jpeg_quality": prepared.jpeg_quality,
        "mime_type": mimetypes.guess_type(prepared.source_path.name)[0] or "image/*",
        "elapsed_seconds": round(elapsed_seconds, 3),
        "api": result.api if result is not None else "",
        "model": result.model if result is not None else "",
        "finish_reason": result.finish_reason if result is not None else "",
        "reasoning_tokens": reasoning_token_count(usage),
        "generated_tokens": output_token_count(usage),
        "usage": usage,
        "markdown": markdown,
        "error": error,
    }


def create_client(args: argparse.Namespace) -> Any:
    if OpenAI is None:
        raise RuntimeError("Missing dependency: install with `uv add openai pillow` or `pip install openai pillow`.")
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set. Export it instead of hardcoding it in the script.")
    return OpenAI(api_key=api_key, base_url=args.base_url)


def main() -> int:
    args = parse_args()
    image_paths = iter_image_paths(args.inputs)
    if not image_paths:
        print("No supported image files found.", file=sys.stderr)
        return 2

    budget = IMAGE_BUDGETS[args.budget]
    system_prompt = read_system_prompt(args)
    seen_hashes: set[str] = set()

    try:
        client = None if args.dry_run else create_client(args)
    except Exception as exc:  # noqa: BLE001
        print(f"[error] {exc}", file=sys.stderr)
        return 2

    for image_path in image_paths:
        try:
            prepared = prepare_image(image_path, budget, args.max_image_bytes)
        except Exception as exc:  # noqa: BLE001 - CLI should continue through batches.
            print(f"[error] {image_path}: {exc}", file=sys.stderr)
            continue

        if not args.no_dedupe and prepared.source_sha256 in seen_hashes:
            record = build_record(prepared=prepared, status="skipped", skipped_reason="duplicate_sha256")
            print(f"[skip] {image_path} duplicate_sha256 figure_name={prepared.figure_name}")
            if args.output_jsonl is not None:
                append_jsonl(args.output_jsonl, record)
            continue
        seen_hashes.add(prepared.source_sha256)

        if args.dry_run:
            record = build_record(prepared=prepared, status="prepared")
            print(
                "[prepared] "
                f"figure_name={prepared.figure_name} "
                f"{image_path} {prepared.original_size}->{prepared.prepared_size} "
                f"{prepared.source_bytes:,}B->{prepared.upload_bytes:,}B q={prepared.jpeg_quality}"
            )
            if args.output_jsonl is not None:
                append_jsonl(args.output_jsonl, record)
            continue

        assert client is not None
        started = time.perf_counter()
        try:
            result = explain_image_with_empty_retry(
                client=client,
                args=args,
                prepared=prepared,
                system_prompt=system_prompt,
            )
            elapsed = time.perf_counter() - started
            record = build_record(
                prepared=prepared,
                status="ok",
                markdown=result.markdown,
                elapsed_seconds=elapsed,
                result=result,
            )
            print(
                f"\n===== {image_path} =====\n"
                f"figure_name={prepared.figure_name} api={result.api} model={result.model} "
                f"finish_reason={result.finish_reason} "
                f"generated_tokens={record['generated_tokens']} reasoning_tokens={record['reasoning_tokens']}\n\n"
                f"{result.markdown}\n"
            )
            if args.output_markdown_dir is not None:
                output_path = write_markdown(args.output_markdown_dir, prepared, result.markdown)
                print(f"[written] {output_path}")
        except Exception as exc:  # noqa: BLE001 - keep batch moving.
            elapsed = time.perf_counter() - started
            record = build_record(prepared=prepared, status="error", error=str(exc), elapsed_seconds=elapsed)
            print(f"[error] {image_path}: {exc}", file=sys.stderr)

        if args.output_jsonl is not None:
            append_jsonl(args.output_jsonl, record)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
