import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render } from "@testing-library/react";
import { ForecastBrowser } from "@/components/ForecastBrowser";
import type { ForecastCellType } from "@/data/forecast-display";
import type { ForecastListingItem } from "@/data/forecast-listing";

// The order the browser lists its categories in.
const TYPES: ForecastCellType[] = ["data", "policy", "conditional"];

function item(type: ForecastCellType, index: number): ForecastListingItem {
  return {
    slug: `${type}-${index}`,
    title: `${type} forecast ${index}`,
    point: { value: 1, label: "1" },
    interval: {
      lower: { value: 0, label: "0" },
      upper: { value: 2, label: "2" },
    },
    resolutionDate: `2027-01-0${index + 1}`,
    status: "pending",
    country: "US",
    type,
    publisher: null,
    overdue: null,
  };
}

function listing(present: ForecastCellType[]): ForecastListingItem[] {
  return present.flatMap((type) => [item(type, 0), item(type, 1)]);
}

function shownCategories(container: HTMLElement) {
  const nav = container.querySelector('nav[aria-label="Forecast sections"]');
  return {
    nav: [...(nav?.querySelectorAll("a") ?? [])].map((link) =>
      link.getAttribute("href"),
    ),
    sections: [...container.querySelectorAll("section")].map(
      (section) => section.id,
    ),
  };
}

// Every subset of the three forecast types, including none and all.
const SUBSETS: ForecastCellType[][] = Array.from({ length: 8 }, (_, mask) =>
  TYPES.filter((_, bit) => mask & (1 << bit)),
);

describe("ForecastBrowser categories", () => {
  afterEach(cleanup);

  it.each(SUBSETS.map((present) => [present.join(" + ") || "none", present]))(
    "lists exactly the categories that hold a forecast: %s",
    (_name, present) => {
      const { container } = render(
        <ForecastBrowser forecasts={listing(present)} />,
      );
      expect(shownCategories(container)).toEqual({
        nav: present.map((type) => `#${type}-forecasts`),
        sections: present.map((type) => `${type}-forecasts`),
      });
    },
  );

  it("keeps a category whose forecasts a filter hides, with a count of 0", () => {
    const { container } = render(
      <ForecastBrowser forecasts={listing(["data", "conditional"])} />,
    );
    const status = [...container.querySelectorAll("select")].find((select) =>
      [...select.options].some((option) => option.value === "resolved"),
    );
    expect(status).toBeTruthy();
    // Every item in the listing is pending, so this filter hides them all.
    fireEvent.change(status!, { target: { value: "resolved" } });

    expect(shownCategories(container)).toEqual({
      nav: ["#data-forecasts", "#conditional-forecasts"],
      sections: ["data-forecasts", "conditional-forecasts"],
    });
    const counts = [
      ...container.querySelectorAll('nav[aria-label="Forecast sections"] a'),
    ].map((link) => link.querySelector("span:last-child")?.textContent);
    expect(counts).toEqual(["0", "0"]);
  });
});
