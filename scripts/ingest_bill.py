#!/usr/bin/env python3
"""Extract and map a bill with Codex; retain proposal-only, reproducible drafts.

Run on GitHub, with subscription authentication provisioned outside the draft
directory. No saved-response, mock, arbitrary command, admission or publishing
mode is exposed. Failed executions retain their trace and return exit status 1.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import io
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from urllib.parse import urlsplit

import map_bill_metrics as mapper
from run_thesis_analyst import prepare_codex_home, redact_text

ROOT = pathlib.Path(__file__).resolve().parents[1]
AGENT_DIR = ROOT / "agents" / "bill-analyst"
DRAFT_ROOT = ROOT / "drafts" / "bill-ingestion"
DEFAULT_MODEL = "gpt-5.5"
MAX_TEXT_BYTES = 2 * 1024 * 1024
MAX_JSON_BYTES = 25 * 1024 * 1024
NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,119}")
META_KEYS = {
    "slug",
    "bill_number",
    "title",
    "resolved_via",
    "source_url",
    "version_label",
    "format",
    "text_sha256",
    "source_fetched_at",
    "retrieved_at",
    "text_file",
    "source_file",
    "axiomBillId",
    "axiomDashboardUrl",
    "statuteMap",
}


class IngestionError(ValueError):
    """Untrusted or incomplete input cannot become a bill proposal."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_name(value: str, label: str) -> str:
    if not isinstance(value, str) or not NAME_RE.fullmatch(value):
        raise IngestionError(f"invalid {label}: use lowercase letters, digits, hyphens")
    return value


def reject_symlinks(path: pathlib.Path) -> None:
    if ".." in path.parts or any(p.is_symlink() for p in (path, *path.parents)):
        raise IngestionError(f"path traversal or symlink refused: {path}")


def read_bytes(path: pathlib.Path, limit: int) -> bytes:
    reject_symlinks(path)
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise IngestionError(f"input exceeds {limit} bytes: {path}")
    return data


def strict_json(text: str) -> object:
    def pairs(items: list[tuple[str, object]]) -> dict:
        result: dict = {}
        for key, value in items:
            if key in result:
                raise IngestionError(f"duplicate JSON field: {key}")
            result[key] = value
        return result

    def bad_constant(value: str) -> None:
        raise IngestionError(f"nonfinite JSON value: {value}")

    return json.loads(text, object_pairs_hook=pairs, parse_constant=bad_constant)


def official_url(value: str) -> str:
    if not isinstance(value, str):
        raise IngestionError("source URL must be a string")
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    allowed = any(
        host == domain or host.endswith("." + domain)
        for domain in ("congress.gov", "house.gov", "senate.gov", "govinfo.gov")
    )
    if (
        parsed.scheme != "https"
        or not allowed
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.fragment
        or redact_text(value) != value
    ):
        raise IngestionError("source must be a public HTTPS congressional document URL")
    return value


def validate_meta(meta: object, text: bytes, slug: str) -> dict:
    if not isinstance(meta, dict) or set(meta) - META_KEYS:
        raise IngestionError("source metadata has unknown fields or is not an object")
    for field in ("slug", "source_url", "text_sha256", "resolved_via"):
        if not isinstance(meta.get(field), str) or not meta[field]:
            raise IngestionError(f"source metadata requires {field}")
    if meta["slug"] != slug:
        raise IngestionError("source metadata slug does not match requested slug")
    if meta["text_sha256"] != digest(text):
        raise IngestionError("source metadata text_sha256 does not match source bytes")
    official_url(meta["source_url"])
    for field in ("title", "version_label"):
        if meta.get(field) is not None and not isinstance(meta[field], str):
            raise IngestionError(f"source metadata {field} must be string or null")
    for field in ("text_file", "source_file"):
        name = meta.get(field)
        if name is not None and (
            not isinstance(name, str)
            or not name
            or name in (".", "..")
            or pathlib.PurePath(name).name != name
            or "\\" in name
        ):
            raise IngestionError(f"source metadata {field} must be a basename")
    return meta


def fetch_source(args: argparse.Namespace) -> tuple[bytes, bytes, bytes | None]:
    """Reuse the bill fetcher without its writes or asynchronous backfill."""
    if args.text_path:
        text = read_bytes(args.text_path, MAX_TEXT_BYTES)
        meta_bytes = read_bytes(args.meta_path, MAX_JSON_BYTES)
        meta = validate_meta(strict_json(meta_bytes.decode("utf-8")), text, args.slug)
        if meta.get("text_file") not in (None, args.text_path.name):
            raise IngestionError("metadata text_file does not identify --text-path")
        original = None
        if meta.get("source_file"):
            original = read_bytes(
                args.meta_path.parent / meta["source_file"], 100 * 1024 * 1024
            )
        return text, meta_bytes, original

    # Import lazily: explicit text/meta ingestion needs only the standard library.
    from bills import fetch_bill

    if args.url:
        official_url(args.url)
    else:
        # fetch_bill's URL parser searches; reject extra prefixes/suffixes here.
        if not re.fullmatch(r"\d{2,3}/[a-z]+/\d+", args.ref):
            official_url(args.ref)
            if not re.fullmatch(
                r"https://(?:www\.)?congress\.gov/bill/\d{2,3}(?:st|nd|rd|th)-"
                r"congress/[a-z-]+/\d+/?",
                args.ref,
            ):
                raise IngestionError("invalid Congress bill reference URL")
        ref = fetch_bill.parse_bill_ref(args.ref)
        if ref is None:
            raise IngestionError("invalid bill reference")

    def validate_request(request: object) -> None:
        # Axiom is the one non-congressional service in the fetcher's fixed chain.
        url = str(request.url)
        if urlsplit(url).hostname == "tgohtgoqkjyrvwbvsspx.supabase.co":
            if urlsplit(url).scheme == "https":
                return
        # Congress's authenticated API query is transport-only, never provenance.
        parsed = urlsplit(url)
        official_url(parsed._replace(query="").geturl())

    with fetch_bill.httpx.Client(
        timeout=60,
        follow_redirects=True,
        headers={"User-Agent": "thesis-bills/0.1"},
        event_hooks={"request": [validate_request]},
    ) as client:
        if args.url:
            result = fetch_bill.fetch_from_url(client, args.url)
        else:
            result = fetch_bill.fetch_from_axiom(client, *ref)
            if result is None:
                result = fetch_bill.fetch_from_congress_api(client, *ref)
    if result is None:
        raise IngestionError("bill text could not be fetched")
    text = result["text"].encode("utf-8")
    meta = {
        "slug": args.slug,
        "bill_number": result.get("bill_number"),
        "title": result.get("title"),
        "resolved_via": result["resolved_via"],
        "source_url": result["source_url"],
        "version_label": result.get("version_label"),
        "format": result["format"],
        "text_sha256": result["text_sha256"],
        "source_fetched_at": result.get("source_fetched_at"),
        "retrieved_at": utc_now(),
        "text_file": "source.txt",
        "source_file": "source.bin" if result.get("source_bytes") else None,
    }
    if result.get("axiom_bill_id"):
        meta["axiomBillId"] = result["axiom_bill_id"]
    if result.get("statute_map"):
        meta["statuteMap"] = result["statute_map"]
    validate_meta(meta, text, args.slug)
    return (
        text,
        (json.dumps(meta, indent=2) + "\n").encode(),
        result.get("source_bytes"),
    )


def validate_schema(value: object, schema: dict, at: str = "$") -> None:
    """Validate the closed extraction schema without an optional SDK dependency."""
    kinds = schema["type"]
    kinds = [kinds] if isinstance(kinds, str) else kinds
    valid = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": type(value) is int,
        "null": value is None,
    }
    if not any(valid[kind] for kind in kinds):
        raise IngestionError(f"{at}: expected {kinds}")
    if "enum" in schema and value not in schema["enum"]:
        raise IngestionError(f"{at}: unsupported value")
    if isinstance(value, dict):
        if set(value) != set(schema["required"]):
            raise IngestionError(f"{at}: missing or unknown fields")
        for key, child in value.items():
            validate_schema(child, schema["properties"][key], f"{at}.{key}")
    elif isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            raise IngestionError(f"{at}: too few items")
        for index, child in enumerate(value):
            validate_schema(child, schema["items"], f"{at}[{index}]")
    elif isinstance(value, str):
        if len(value.strip()) < schema.get("minLength", 0):
            raise IngestionError(f"{at}: empty string")
        if "pattern" in schema and not re.fullmatch(schema["pattern"], value):
            raise IngestionError(f"{at}: invalid string")
    elif type(value) is int and value < schema.get("minimum", value):
        raise IngestionError(f"{at}: below minimum")


def validate_artifact(
    artifact: object, text: str, identity: dict, schema: dict
) -> dict:
    validate_schema(artifact, schema)
    if artifact["slug"] != identity["slug"]:
        raise IngestionError("root slug differs from source identity")
    for field, expected in identity.items():
        if expected is not None and artifact["bill"][field] != expected:
            raise IngestionError(f"bill.{field} differs from source identity")
    for index, provision in enumerate(artifact["provisions"]):
        if provision["quote"] not in text:
            raise IngestionError(
                f"provision {index} quote is not an exact source substring"
            )
        if not any(metric["layer"] == "outcome" for metric in provision["metrics"]):
            raise IngestionError(f"provision {index} requires an outcome metric")
        for metric in provision["metrics"]:
            goals = sorted(stance["goal"] for stance in metric["stances"])
            if goals != list(range(len(provision["goals"]))):
                raise IngestionError(
                    f"provision {index} metric stances must cover every goal"
                )
        # Codex requires required nullable properties; BillArtifact uses optional
        # string context. The original nullable model response remains archived.
        if provision["context"] is None:
            provision.pop("context")
    return artifact


def map_proposal(artifact: dict, registered: list[str], catalog: list[dict]) -> tuple:
    mapped, _ = mapper.map_artifact(
        copy.deepcopy(artifact), registered, catalog, proposed_from=artifact["slug"]
    )
    decisions, requests = [], []
    for pi, provision in enumerate(mapped["provisions"]):
        for mi, metric in enumerate(provision["metrics"]):
            hint = metric["series_hint"]
            docket_candidates = (
                mapper.registered_match_candidates(hint, registered) if hint else []
            )
            catalog_candidates = (
                mapper.catalog_match_candidates(hint, catalog) if hint else []
            )
            catalog_match = mapper.match_catalog_series(hint, catalog) if hint else None
            canonical_candidates = (
                mapper.registered_match_candidates(catalog_match["concept"], registered)
                if catalog_match is not None
                else []
            )
            ambiguous = len(docket_candidates) > 1 or (
                metric["registry"] == "not-yet" and bool(catalog_candidates)
            )
            stage = (
                "admitted"
                if metric["registry"] == "reachable"
                else "disambiguate-series"
                if ambiguous
                else "docket-admission"
                if metric["registry"] == "ledger"
                else "catalog-ingestion"
                if hint
                else "identify-series"
            )
            decision = {
                "provisionIndex": pi,
                "metricIndex": mi,
                "seriesHint": hint,
                "registry": metric["registry"],
                "stage": stage,
                "matchedSeries": metric.get("matched_series"),
                "ledgerUuid": metric.get("ledger_uuid"),
                "docketCandidates": docket_candidates,
                "canonicalDocketCandidates": canonical_candidates,
                "catalogCandidates": catalog_candidates,
            }
            decisions.append(decision)
            if stage != "admitted":
                requests.append(
                    {
                        "id": f"{artifact['slug']}-p{pi + 1}-m{mi + 1}",
                        "status": "open",
                        "stage": stage,
                        "proposedFrom": artifact["slug"],
                        "provisionIndex": pi,
                        "metricIndex": mi,
                        "proposed_concept": hint or None,
                        "metricText": metric["text"],
                        "mapping": decision,
                        "requiredWork": [
                            "Verify exact official concept, geography, entity, "
                            "unit and cadence",
                            "Capture witnessed first-print observation history "
                            "in Chronicle",
                            "Implement or reuse a resolvable adapter with "
                            "official-source tests",
                            "Independently verify anchors and review docket admission",
                            "Preregister the policy pair before any "
                            "conditional forecasts",
                        ],
                    }
                )
    return mapped, decisions, requests


def codex_command(workdir: pathlib.Path, schema_path: pathlib.Path) -> list[str]:
    # The repository's established default is gpt-5.5. This is not a latest-model claim.
    return [
        "codex",
        "exec",
        "--json",
        "--ignore-user-config",
        "--skip-git-repo-check",
        "--disable",
        "shell_tool",
        "-c",
        'web_search="disabled"',
        "-c",
        'model_reasoning_effort="high"',
        "-m",
        DEFAULT_MODEL,
        "--output-schema",
        str(schema_path),
        "-o",
        str(workdir / "last-message.json"),
        "-s",
        "read-only",
        "-C",
        str(workdir),
        "-",
    ]


def run_ingestion(
    args: argparse.Namespace,
    *,
    command_runner: Callable = subprocess.run,
    source_fetcher: Callable = fetch_source,
) -> pathlib.Path:
    safe_name(args.slug, "slug")
    run_id = safe_name(
        args.run_id or f"{args.slug[:100]}-{uuid.uuid4().hex[:16]}", "run ID"
    )
    reject_symlinks(DRAFT_ROOT)
    run_dir = DRAFT_ROOT / run_id
    # Exclusive creation prevents replacing a prior run or any source artifact.
    run_dir.mkdir(parents=True, exist_ok=False)
    manifest = {
        "schemaVersion": "thesis_bill_ingestion_v1",
        "runId": run_id,
        "status": "running",
        "proposalOnly": True,
        "slug": args.slug,
        "startedAt": utc_now(),
        "model": DEFAULT_MODEL,
        "trust": "unreviewed-agent-proposal",
        "error": None,
        "workflow": {
            "repository": os.environ.get("GITHUB_REPOSITORY"),
            "runId": os.environ.get("GITHUB_RUN_ID"),
            "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "sourceGitSha": os.environ.get("GITHUB_SHA"),
            "ref": os.environ.get("GITHUB_REF"),
        },
    }

    def write_text(name: str, value: str) -> None:
        (run_dir / name).write_text(redact_text(value), encoding="utf-8")

    def write_json(name: str, value: object) -> None:
        write_text(name, json.dumps(value, indent=2, ensure_ascii=False) + "\n")

    for name in (
        "prompt.md",
        "stdout.txt",
        "stderr.txt",
        "raw_response.txt",
        "fetch.log",
    ):
        write_text(name, "")
    write_json("command.json", {"status": "not-started"})
    try:
        if not re.fullmatch(r"[0-9a-f]{40}", args.catalog_commit):
            raise IngestionError("--catalog-commit must be a full lowercase commit SHA")
        catalog_bytes = read_bytes(args.catalog, MAX_JSON_BYTES)
        docket_bytes = read_bytes(args.docket, MAX_JSON_BYTES)
        # Reject duplicate keys before the existing mapper reads its snapshot.
        strict_json(catalog_bytes.decode("utf-8"))
        strict_json(docket_bytes.decode("utf-8"))
        (run_dir / "catalog.json").write_bytes(catalog_bytes)
        (run_dir / "docket.json").write_bytes(docket_bytes)
        catalog = mapper.load_catalog_series(run_dir / "catalog.json")
        registered = mapper.load_registered_series(run_dir / "docket.json")
        manifest["catalog"] = {
            "repository": "PolicyEngine/chronicle",
            "commit": args.catalog_commit,
            "sha256": digest(catalog_bytes),
            "bytes": len(catalog_bytes),
        }
        manifest["docket"] = {
            "sha256": digest(docket_bytes),
            "bytes": len(docket_bytes),
        }
        fetch_log = io.StringIO()
        try:
            with (
                contextlib.redirect_stdout(fetch_log),
                contextlib.redirect_stderr(fetch_log),
            ):
                text_bytes, meta_bytes, original = source_fetcher(args)
        finally:
            write_text("fetch.log", fetch_log.getvalue())
        if not text_bytes or len(text_bytes) > MAX_TEXT_BYTES:
            raise IngestionError(
                "source text is empty or exceeds extraction size limit"
            )
        text = text_bytes.decode("utf-8")
        meta = validate_meta(
            strict_json(meta_bytes.decode("utf-8")), text_bytes, args.slug
        )
        # Bill/meta bytes are the evidence; never silently normalize or redact them.
        if (
            redact_text(text) != text
            or redact_text(meta_bytes.decode()) != meta_bytes.decode()
        ):
            raise IngestionError(
                "source contains credential-shaped data; refusing public trace"
            )
        (run_dir / "source.txt").write_bytes(text_bytes)
        (run_dir / "source.meta.json").write_bytes(meta_bytes)
        manifest["source"] = {
            "textSha256": digest(text_bytes),
            "metaSha256": digest(meta_bytes),
            "sourceUrl": meta["source_url"],
            "resolvedVia": meta["resolved_via"],
            "originalBytesSha256": digest(original) if original is not None else None,
        }
        if original is not None:
            (run_dir / "source.bin").write_bytes(original)
        identity = {
            "slug": args.slug,
            "analysisDate": manifest["startedAt"][:10],
            "sourceUrl": meta["source_url"],
            "name": meta.get("title") or None,
            "status": meta.get("version_label") or "Source version not specified",
            "pages": 0,
        }
        schema_bytes = read_bytes(AGENT_DIR / "output.schema.json", MAX_JSON_BYTES)
        schema = strict_json(schema_bytes.decode())
        (run_dir / "output.schema.json").write_bytes(schema_bytes)
        system = read_bytes(AGENT_DIR / "system.md", MAX_JSON_BYTES).decode()
        write_text("system.md", system)
        prompt = (
            system
            + "\n\nUntrusted evidence envelope (JSON):\n"
            + json.dumps(
                {
                    "identity": identity,
                    "sourceText": text,
                    "catalogCommit": args.catalog_commit,
                    "catalogSha256": digest(catalog_bytes),
                    "docketSeries": registered,
                    "catalogSeries": catalog,
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        if redact_text(prompt) != prompt:
            raise IngestionError("prompt contains credential-shaped data")
        write_text("prompt.md", prompt)
        # Empty cwd/home avoid repository skills, instructions and personal files.
        with tempfile.TemporaryDirectory(prefix="thesis-bill-extraction-") as temp:
            workdir = pathlib.Path(temp)
            isolated_home = workdir / "home"
            isolated_home.mkdir()
            codex_home = prepare_codex_home(workdir / "codex-home")
            local_schema = workdir / "output.schema.json"
            shutil.copyfile(run_dir / "output.schema.json", local_schema)
            command = codex_command(workdir, local_schema)
            env = {
                key: os.environ[key]
                for key in ("PATH", "LANG", "LC_ALL")
                if key in os.environ
            }
            env.update({"HOME": str(isolated_home), "CODEX_HOME": str(codex_home)})
            write_json(
                "command.json",
                {
                    "argv": command,
                    "stdin": "prompt.md",
                    "cwd": str(workdir),
                    "environmentKeys": sorted(env),
                    "timeoutSeconds": args.timeout,
                    "shell": False,
                    "tools": "shell and web search disabled",
                },
            )
            try:
                completed = command_runner(
                    command,
                    input=prompt,
                    capture_output=True,
                    text=True,
                    check=False,
                    shell=False,
                    cwd=workdir,
                    env=env,
                    timeout=args.timeout,
                )
                write_text("stdout.txt", completed.stdout or "")
                write_text("stderr.txt", completed.stderr or "")
                manifest["returnCode"] = completed.returncode
            except subprocess.TimeoutExpired as error:
                for name, value in (
                    ("stdout.txt", error.stdout),
                    ("stderr.txt", error.stderr),
                ):
                    write_text(
                        name,
                        value.decode(errors="replace")
                        if isinstance(value, bytes)
                        else value or "",
                    )
                raise IngestionError("Codex extraction timed out") from error
            finally:
                last_message = workdir / "last-message.json"
                if last_message.exists():
                    write_text(
                        "raw_response.txt",
                        read_bytes(last_message, MAX_JSON_BYTES).decode(),
                    )
            if completed.returncode != 0:
                raise IngestionError(
                    f"Codex extraction exited with {completed.returncode}"
                )
            if not last_message.exists():
                raise IngestionError("Codex did not write its final response")
        raw = (run_dir / "raw_response.txt").read_text(encoding="utf-8")
        artifact = validate_artifact(strict_json(raw), text, identity, schema)
        write_json("bill.json", artifact)
        mapped, decisions, requests = map_proposal(artifact, registered, catalog)
        write_json("bill.mapped.json", mapped)
        write_json("mapping.json", decisions)
        write_json("ingestion-requests.json", requests)
        manifest.update({"status": "proposed", "openIngestionRequests": len(requests)})
        write_json(
            "validation.json", {"valid": True, "quoteCheck": "exact-source-substrings"}
        )
    except Exception as error:
        manifest.update(
            {"status": "failed", "error": f"{type(error).__name__}: {error}"}
        )
        write_json("validation.json", {"valid": False, "error": manifest["error"]})
    finally:
        manifest["finishedAt"] = utc_now()
        manifest["artifacts"] = [
            {
                "path": p.name,
                "sha256": digest(p.read_bytes()),
                "bytes": p.stat().st_size,
            }
            for p in sorted(run_dir.iterdir())
            if p.name != "manifest.json"
        ]
        write_json("manifest.json", manifest)
    return run_dir


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("ref", nargs="?", help="119/hr/818 or Congress bill-page URL")
    parser.add_argument("--url", help="Direct public congressional text/PDF URL")
    parser.add_argument("--text-path", type=pathlib.Path)
    parser.add_argument("--meta-path", type=pathlib.Path)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--catalog", type=pathlib.Path, required=True)
    parser.add_argument("--catalog-commit", required=True)
    parser.add_argument("--docket", type=pathlib.Path, default=mapper.DEFAULT_DOCKET)
    parser.add_argument("--run-id")
    parser.add_argument("--timeout", type=int, default=1200)
    args = parser.parse_args(argv)
    if sum(bool(value) for value in (args.ref, args.url, args.text_path)) != 1:
        parser.error("choose exactly one bill reference, --url, or --text-path")
    if bool(args.text_path) != bool(args.meta_path):
        parser.error("--text-path and --meta-path must be supplied together")
    if not 1 <= args.timeout <= 3600:
        parser.error("--timeout must be between 1 and 3600 seconds")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    run_dir = run_ingestion(args)
    manifest = json.loads((run_dir / "manifest.json").read_text())
    print(f"bill ingestion {manifest['status']}: {run_dir / 'manifest.json'}")
    return 0 if manifest["status"] == "proposed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
