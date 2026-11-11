import { getPublishedForecasts } from "@/lib/forecast-publication";
import { buildTargetArchitectureManifest } from "./thesis-target-architecture-export";
import { buildTargetArchitectureProjection } from "./thesis-target-architecture";
import { loadPolicyEngineLedger, withResolvedOutcomes } from "./thesis-log";

let targetArchitectureProjectionPromise: ReturnType<
  typeof buildTargetArchitectureProjectionOnce
> | null = null;
let targetArchitectureManifestPromise: ReturnType<
  typeof buildTargetArchitectureManifestOnce
> | null = null;

/** Share one projection across the manifest, table, and chunk static routes. */
export function loadTargetArchitectureProjection() {
  targetArchitectureProjectionPromise ??=
    buildTargetArchitectureProjectionOnce();
  return targetArchitectureProjectionPromise;
}

/** Cache the expensive canonical chunk/root hashing across all static routes. */
export function loadTargetArchitectureManifest() {
  targetArchitectureManifestPromise ??= buildTargetArchitectureManifestOnce();
  return targetArchitectureManifestPromise;
}

export function resetTargetArchitectureProjectionCache() {
  targetArchitectureProjectionPromise = null;
  targetArchitectureManifestPromise = null;
}

async function buildTargetArchitectureProjectionOnce() {
  const ledger = await loadPolicyEngineLedger();
  return buildTargetArchitectureProjection(
    withResolvedOutcomes(getPublishedForecasts(), ledger),
    ledger,
  );
}

async function buildTargetArchitectureManifestOnce() {
  return buildTargetArchitectureManifest(
    await loadTargetArchitectureProjection(),
  );
}
