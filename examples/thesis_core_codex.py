#!/usr/bin/env python3
"""Real Codex CLI transport for the explicitly retrospective core pilot.

The core worker supplies the prompt on stdin. This adapter requests the entire
native 201-point distribution from the model and returns its exact JSON; it
does not manufacture points from a model-produced interval. Existing Codex CLI
authentication is used by the CLI itself. No credentials are inspected here.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from thesis_core.contracts import NumericCdf


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex", default="codex")
    parser.add_argument("--model")
    args = parser.parse_args()
    prompt = sys.stdin.read()
    prompt += (
        "\n\nReturn ONLY one JSON object with a 'distribution' field matching "
        "this schema exactly. Produce all 201 points directly; probabilities "
        "must begin at 0 and end at 1, be nondecreasing, and values must be "
        "strictly increasing. Do not run tools or read files. Do not include "
        "observed_model unless you have actual provider metadata; your model "
        "name is otherwise unknown.\n"
    )
    prompt += json.dumps(NumericCdf.model_json_schema())
    with tempfile.TemporaryDirectory(prefix="codex-response-") as directory:
        response = Path(directory) / "response.json"
        command = [
            args.codex,
            "exec",
            "--ignore-user-config",
            "--skip-git-repo-check",
            "--ephemeral",
            "--sandbox",
            "read-only",
            "--color",
            "never",
            "--output-last-message",
            str(response),
        ]
        if args.model:
            command.extend(["--model", args.model])
        command.append("-")
        completed = subprocess.run(
            command, input=prompt.encode(), stdout=sys.stderr, stderr=sys.stderr
        )
        if completed.returncode:
            return completed.returncode
        sys.stdout.buffer.write(response.read_bytes())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
