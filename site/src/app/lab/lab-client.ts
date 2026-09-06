"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { labProxyPath } from "@/lib/lab-paths";
import { parseLab, type LabModel, type LabModels } from "@/lib/lab-schema";

export type Resource<T> =
  | { state: "loading" }
  | { state: "ready"; data: T }
  | { state: "error"; message: string };
const messages: Record<string, string> = {
  core_api_unconfigured:
    "The lab is not connected to an experiment service on this deployment.",
  core_api_misconfigured:
    "The experiment service connection needs operator attention.",
  upstream_timeout:
    "The experiment service took too long to respond. Try refreshing.",
  upstream_unavailable:
    "The experiment service is unavailable. Existing records have not been changed.",
  upstream_response_too_large:
    "This response exceeds the download limit. Use a smaller page.",
  artifact_too_large:
    "This artifact exceeds the browser download limit and requires operator download.",
};

export async function fetchLab<M extends LabModel>(
  path: string,
  model: M,
  signal?: AbortSignal,
  fetchImpl: typeof fetch = fetch,
): Promise<LabModels[M]> {
  const response = await fetchImpl(labProxyPath(path), {
    method: "GET",
    credentials: "omit",
    cache: "no-store",
    headers: { accept: "application/json" },
    signal,
  });
  const value: unknown = await response.json();
  if (!response.ok) {
    const error =
      value && typeof value === "object" && "error" in value
        ? (value as { error: { code?: string; upstream_status?: number } })
            .error
        : undefined;
    const status = error?.upstream_status ?? response.status;
    throw new Error(
      messages[error?.code ?? ""] ??
        (status === 409
          ? "These records cannot be joined safely. An integrity issue needs operator review."
          : status === 404
            ? "This record is not available in the experiment service."
            : `The request could not be completed (HTTP ${status}).`),
    );
  }
  const data = parseLab(model, value);
  const url = new URL(path, "https://lab.invalid");
  const [, collection, id, child] = url.pathname.slice(1).split("/");
  const mismatch = () => {
    throw new Error(
      "The response belongs to a different record or experiment.",
    );
  };
  if (id && !child && "id" in data && data.id !== id) mismatch();
  if (
    "experiment_id" in data &&
    collection === "experiments" &&
    data.experiment_id !== id
  )
    mismatch();
  if ("items" in data)
    for (const item of data.items) {
      if (
        collection === "forecasts" &&
        child === "comparisons" &&
        "target_id" in item &&
        (item.target_id !== id ||
          ("experiment_id" in item &&
            item.experiment_id !== url.searchParams.get("experiment_id")))
      )
        mismatch();
      if (
        collection === "experiments" &&
        child === "results" &&
        "experiment_id" in item &&
        item.experiment_id !== id
      )
        mismatch();
      if (
        collection === "agents" &&
        child === "experiments" &&
        "forecaster_id" in item &&
        item.forecaster_id !== id
      )
        mismatch();
      if (
        collection === "tasks" &&
        child === "attempts" &&
        "task_id" in item &&
        item.task_id !== id
      )
        mismatch();
    }
  return data;
}

export function useLab<M extends LabModel>(path: string | null, model: M) {
  const [resource, setResource] = useState<Resource<LabModels[M]>>({
    state: "loading",
  });
  const [version, setVersion] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setResource({ state: "loading" });
    if (path)
      void fetchLab(path, model, controller.signal)
        .then((data) => {
          if (!controller.signal.aborted) setResource({ state: "ready", data });
        })
        .catch((error: unknown) => {
          if (!controller.signal.aborted)
            setResource({
              state: "error",
              message:
                error instanceof Error
                  ? error.message
                  : "The experiment service could not be read.",
            });
        });
    return () => controller.abort();
  }, [path, model, version]);
  return { resource, refresh: () => setVersion((v) => v + 1) };
}

export function withQuery(
  path: string,
  key: string,
  value: string | null,
): string {
  const url = new URL(path, "https://lab.invalid");
  if (value === null) url.searchParams.delete(key);
  else url.searchParams.set(key, value);
  return `${url.pathname}${url.search}`;
}

type PageModel =
  | "ForecastPage"
  | "ExperimentPage"
  | "ComparisonPage"
  | "AttemptPage"
  | "AgentPage"
  | "ExperimentResultPage"
  | "OperationsSummary";
type Item<M extends PageModel> = LabModels[M]["items"][number];

/** Keep already loaded rows visible if a later page fails; resets cancel stale requests. */
export function useLabPages<M extends PageModel>(
  path: string | null,
  model: M,
) {
  const [resource, setResource] = useState<Resource<LabModels[M]>>({
    state: "loading",
  });
  const [items, setItems] = useState<readonly Item<M>[]>([]);
  const [loadingMore, setLoadingMore] = useState(false);
  const [pageError, setPageError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const controller = useRef<AbortController | null>(null);
  const cursors = useRef(new Set<string>());
  useEffect(() => {
    const request = new AbortController();
    controller.current = request;
    cursors.current.clear();
    setResource({ state: "loading" });
    setItems([]);
    setPageError(null);
    setLoadingMore(false);
    if (path)
      void fetchLab(path, model, request.signal)
        .then((data) => {
          if (!request.signal.aborted) {
            setResource({ state: "ready", data });
            setItems(data.items as readonly Item<M>[]);
          }
        })
        .catch((error: unknown) => {
          if (!request.signal.aborted)
            setResource({
              state: "error",
              message:
                error instanceof Error
                  ? error.message
                  : "The experiment service could not be read.",
            });
        });
    return () => request.abort();
  }, [path, model, version]);
  const loadMore = useCallback(async () => {
    if (
      !path ||
      resource.state !== "ready" ||
      !resource.data.next_cursor ||
      loadingMore
    )
      return;
    const cursor = resource.data.next_cursor;
    if (cursors.current.has(cursor)) {
      setPageError(
        "The service repeated a page cursor. Refresh to reload the collection.",
      );
      return;
    }
    const signal = controller.current?.signal;
    setLoadingMore(true);
    setPageError(null);
    try {
      const data = await fetchLab(
        withQuery(path, "after", cursor),
        model,
        signal,
      );
      if (signal?.aborted) return;
      cursors.current.add(cursor);
      setItems((old) => [...old, ...(data.items as readonly Item<M>[])]);
      setResource({ state: "ready", data });
    } catch (error) {
      if (!signal?.aborted)
        setPageError(
          error instanceof Error
            ? error.message
            : "The next page could not be read.",
        );
    } finally {
      if (!signal?.aborted) setLoadingMore(false);
    }
  }, [path, model, resource, loadingMore]);
  return {
    resource,
    items,
    loadingMore,
    pageError,
    loadMore,
    refresh: () => setVersion((v) => v + 1),
  };
}
