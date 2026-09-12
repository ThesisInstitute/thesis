"""Prepare a real-source replay cohort without hand-authoring scientific JSON.

This is deliberately a retrospective exercise: target selection and captures
happen after the outcome, and no prospective claim can result from this helper.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Callable, Sequence

from .adapters import HttpRequest, HttpResponse, observation_availability
from .canonical import canonical_bytes
from .contracts import EvaluationTask, Experiment, ForecasterVersion, TargetVersion
from .evaluation import build_normalization
from .evidence import build_evidence_bundle
from .resolution import capture_source

if TYPE_CHECKING:
    from .store import Store

PILOT_VERSION = "thesis-core-pilot-v1"


def prepare_replay(
    store: Store,
    adapter_id: str = "statcan-cpi-yoy",
    *,
    fetch: Callable[[HttpRequest], HttpResponse] | None = None,
    argv: Sequence[str] | None = None,
) -> Experiment:
    """Freeze a persistence baseline and optional explicitly configured model.

    Sources lacking three eligible historical values or a known target release
    refuse. The initial StatCan official fixture supports this whole loop.
    BEA's single-quarter fixture and ABS's unknown publication timing do not.
    """
    from .execution import EXECUTION_PROTOCOL, PERSISTENCE_BASELINE_VERSION
    from .security import is_credential_key, redact_value
    from .service import context_for_store

    captured = capture_source(store, adapter_id, fetch=fetch, mode="replay")
    if captured.status != "captured" or not captured.observations:
        raise ValueError("replay source capture failed: " + "; ".join(captured.errors))
    source = captured.source
    observations = sorted(captured.observations, key=lambda o: o.measurement_period)
    outcome = observations[-1]
    exchanges = {exchange.id: exchange for exchange in captured.exchanges}
    availability = observation_availability(outcome, source, exchanges, store.artifacts)
    if availability is None or outcome.publication_evidence is None:
        raise ValueError(
            "replay pilot requires authenticated target publication timing"
        )
    cutoff = availability.lower - timedelta(minutes=2)
    deadline = availability.lower - timedelta(minutes=1)
    historical = [
        o for o in observations if o.measurement_period < outcome.measurement_period
    ]
    bundle = build_evidence_bundle(
        source,
        historical,
        exchanges,
        store.artifacts,
        information_cutoff=cutoff,
        mode="replay",
        committed_at=store.committed_at,
    )
    if len(bundle.observation_ids) < 3:
        raise ValueError(
            "replay pilot requires at least three eligible historical observations"
        )
    target = TargetVersion(
        target_id=f"{adapter_id}:{outcome.measurement_period}:replay",
        source_series_id=source.id,
        measurement_period=outcome.measurement_period,
        unit=source.unit,
        resolution_policy="fixed_vintage",
        vintage_date=outcome.publication_evidence.raw_value[:10],
        resolution_rule=(
            "registered-source-vintage-v1: exact period, unit, source binding "
            "and official vintage date"
        ),
        submission_deadline=deadline,
    )
    with store.transaction() as transaction:
        transaction.put(target)
        transaction.put(bundle)
    context = context_for_store(store)
    selected_history = [store.get(identity) for identity in bundle.observation_ids]
    normalization = build_normalization(
        target, selected_history, cutoff, mode="replay", context=context
    )
    if normalization.scale is None:
        raise ValueError(
            "replay pilot normalization unavailable: "
            + str(normalization.unavailable_reason)
        )
    prompt = store.artifacts.put_bytes(
        b"Forecast the target using only the eligible observation values supplied "
        b'in this request. Return exactly one JSON object with a "distribution" '
        b"field containing a numeric_cdf_v1 object with 201 CDF points, and an "
        b'optional "observed_model" string. Do not inspect custody source bodies '
        b"or seek later observations. This is retrospective replay, not a "
        b"prospective performance claim.\n"
    )
    system = store.artifacts.put_bytes(
        b"Use the frozen evidence projection and exact target unit. Report a "
        b"predictive distribution, not merely an interval.\n"
    )
    baseline_policy = store.artifacts.put_bytes(
        canonical_bytes(
            {
                "execution_policy": "baseline",
                "implementation": "persistence-v1",
                "mode": "replay",
                "network": False,
                "source_input": "eligible_observation_projection_only",
            }
        )
    )
    baseline = ForecasterVersion(
        provider="thesis",
        model_request="persistence-v1",
        inference_settings={},
        agent_version=PERSISTENCE_BASELINE_VERSION,
        harness_version="generic-stdin-json-v1",
        prompt_template_hash=prompt,
        system_prompt_hash=system,
        tool_policy_hash=baseline_policy,
        retry_policy="none",
        execution_policy="baseline",
    )
    forecasters = [baseline]
    if argv is not None:
        if not argv or any(
            not isinstance(argument, str) or not argument or "\x00" in argument
            for argument in argv
        ):
            raise ValueError("operator argv must contain nonempty literal arguments")
        if redact_value(list(argv)) != list(argv) or any(
            argument.startswith("-")
            and is_credential_key(argument.lstrip("-").split("=", 1)[0])
            for argument in argv
        ):
            raise ValueError(
                "operator argv cannot contain credential-bearing arguments"
            )
        policy = store.artifacts.put_bytes(
            canonical_bytes(
                {
                    "execution_policy": "operator_subprocess",
                    "mode": "replay",
                    "requested_permissions": {
                        "input": "frozen_eligible_observation_projection_only",
                        "later_data": "forbidden",
                        "external_access": "operator_controlled",
                    },
                    "isolation_guarantee": (
                        "none; operator subprocess access is declared, not proved"
                    ),
                }
            )
        )
        forecasters.append(
            ForecasterVersion(
                provider="operator",
                model_request="operator-configured",
                inference_settings={
                    "argv": list(argv),
                    "execution_protocol": EXECUTION_PROTOCOL,
                },
                agent_version=PILOT_VERSION,
                harness_version="generic-stdin-json-v1",
                prompt_template_hash=prompt,
                system_prompt_hash=system,
                tool_policy_hash=policy,
                retry_policy="none",
                execution_policy="operator_subprocess",
            )
        )
    tasks = tuple(
        EvaluationTask(
            target_version_id=target.id,
            forecaster_version_id=forecaster.id,
            evidence_bundle_id=bundle.id,
            information_cutoff=cutoff,
            submission_deadline=deadline,
            max_attempts=1,
            execution_policy=forecaster.execution_policy,
            mode="replay",
        )
        for forecaster in forecasters
    )
    experiment = Experiment(
        task_ids=tuple(task.id for task in tasks),
        target_version_ids=(target.id,),
        forecaster_version_ids=tuple(forecaster.id for forecaster in forecasters),
        baseline_forecaster_id=baseline.id,
        normalization_ids=(normalization.id,),
        registration_deadline=cutoff - timedelta(seconds=1),
        mode="replay",
    )
    with store.transaction() as transaction:
        for forecaster in forecasters:
            transaction.put(forecaster)
        transaction.put(normalization)
        for task in tasks:
            transaction.put(task)
        transaction.put(experiment)
    return experiment
