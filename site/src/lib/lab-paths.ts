/** Closed path vocabulary shared by the lab browser and the server proxy. */
export const LAB_DIGEST = /^[0-9a-f]{64}$/;
export const LAB_MODEL = /^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$/;

export interface LabRoute {
  queries: readonly string[];
  required?: readonly string[];
  limits?: Readonly<Record<string, number>>;
}

export function labRoute(segments: readonly string[]): LabRoute | null {
  if (segments[0] !== "lab") return null;
  const [, collection, id, child] = segments;
  const page = { queries: ["limit", "after"] };
  if (segments.length === 2 && collection === "conditionals")
    return { queries: ["limit", "after", "requested_model"] };
  if (
    segments.length === 2 &&
    ["forecasts", "experiments", "agents", "operations"].includes(collection)
  )
    return page;
  if (!LAB_DIGEST.test(id ?? "")) return null;
  if (
    segments.length === 3 &&
    ["forecasts", "conditionals", "experiments", "agents"].includes(collection)
  )
    return { queries: [] };
  if (segments.length !== 4) return null;
  if (collection === "forecasts" && child === "experiments") return page;
  if (collection === "forecasts" && child === "comparisons")
    return {
      queries: ["experiment_id", "limit", "after"],
      required: ["experiment_id"],
    };
  if (collection === "tasks" && child === "attempts") return page;
  if (collection === "agents" && child === "experiments") return page;
  if (collection === "experiments" && child === "results") return page;
  if (collection === "experiments" && child === "matrix")
    return {
      queries: ["limit", "after", "method_limit", "method_after"],
      limits: { limit: 20, method_limit: 10 },
    };
  return null;
}

export function validLabQuery(
  name: string,
  value: string,
  route: LabRoute,
): boolean {
  if (name === "requested_model") return LAB_MODEL.test(value);
  if (["after", "method_after", "experiment_id"].includes(name))
    return LAB_DIGEST.test(value);
  if (name === "limit" || name === "method_limit")
    return (
      /^[1-9][0-9]{0,2}$/.test(value) &&
      Number(value) <= (route.limits?.[name] ?? 100)
    );
  return false;
}

/** API-provided paths must be exact relative paths, never URL destinations. */
export function isLabApiPath(path: unknown): path is string {
  if (typeof path !== "string" || !path.startsWith("/") || /[\\#]/.test(path))
    return false;
  const url = new URL(path, "https://lab.invalid");
  if (
    url.origin !== "https://lab.invalid" ||
    url.pathname.includes("%") ||
    url.pathname !== path.split("?")[0]
  )
    return false;
  if (/^\/(records|artifacts)\/[0-9a-f]{64}$/.test(path)) return true;
  const route = labRoute(url.pathname.slice(1).split("/"));
  if (!route) return false;
  if (
    (path.split("?")[1] ?? "")
      .split("&")
      .some(
        (part) => part.includes("%") && !part.startsWith("requested_model="),
      )
  )
    return false;
  for (const key of url.searchParams.keys()) {
    if (
      !route.queries.includes(key) ||
      url.searchParams.getAll(key).length !== 1 ||
      !validLabQuery(key, url.searchParams.get(key)!, route)
    )
      return false;
  }
  return (route.required ?? []).every((key) => url.searchParams.has(key));
}

export function labProxyPath(path: string): string {
  if (!isLabApiPath(path)) throw new Error("Invalid lab API path");
  return `/api/core${path}`;
}
