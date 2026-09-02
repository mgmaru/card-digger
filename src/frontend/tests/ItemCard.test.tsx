/**
 * The card (MVP specification section 5.6).
 *
 * The badge assertions are the ones that matter. Section 2.5 of the visual
 * direction calls it the hardest constraint on the screen: `形式不明` shown as
 * `通常出品` puts a bid in progress next to a price someone can just pay.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { ItemCard } from "../src/components/ItemCard";
import type { Item, SaleFormat } from "../src/types/api";

const COLLECTED_AT = "2026-09-02T14:03:00+09:00";
const daysBefore = (n: number) =>
  new Date(new Date(COLLECTED_AT).getTime() - n * 86_400_000).toISOString();

function item(patch: Partial<Item> = {}): Item {
  return {
    id: "m1",
    title: "ポケモンカード 引退品 まとめ売り 約2000枚",
    priceYen: 48000,
    url: "https://jp.mercari.com/item/m1",
    imageUrls: ["https://example.invalid/1.jpg"],
    createdAt: daysBefore(376),
    updatedAt: daysBefore(357),
    listingStatus: "on_sale",
    saleFormat: "fixed_price",
    sellerId: "s1",
    ...patch,
  };
}

function mount(patch: Partial<Item> = {}) {
  return render(
    <MemoryRouter>
      <ItemCard item={item(patch)} collectedAt={COLLECTED_AT} />
    </MemoryRouter>,
  );
}

const bar = (container: HTMLElement) =>
  container.querySelector("p[title^='最後に更新されてから'] > span") as HTMLElement;

describe("sale format", () => {
  const cases: { format: SaleFormat; badge: string; price: string }[] = [
    { format: "fixed_price", badge: "通常出品", price: "価格" },
    { format: "auction", badge: "オークション", price: "現在価格（取得時点）" },
    { format: "unknown", badge: "形式不明", price: "価格（取得時点）" },
  ];

  it.each(cases)("shows $badge with its own price label", ({ format, badge, price }) => {
    mount({ saleFormat: format });
    expect(screen.getByText(badge)).toBeInTheDocument();
    expect(screen.getByText(price)).toBeInTheDocument();
  });

  it("never labels an unknown format as an ordinary listing", () => {
    mount({ saleFormat: "unknown" });
    expect(screen.queryByText("通常出品")).not.toBeInTheDocument();
    // Its price is marked as a snapshot, not an amount anyone can just pay.
    expect(screen.getByText("価格（取得時点）")).toBeInTheDocument();
  });

  it("gives the three badges three different classes", () => {
    const classFor = (format: SaleFormat) => {
      const view = mount({ saleFormat: format });
      const node = screen.getByText(
        { fixed_price: "通常出品", auction: "オークション", unknown: "形式不明" }[format],
      );
      const className = node.className;
      view.unmount();
      return className;
    };
    const [fixed, auction, unknown] = (
      ["fixed_price", "auction", "unknown"] as const
    ).map(classFor);
    expect(new Set([fixed, auction, unknown]).size).toBe(3);
  });
});

describe("dates", () => {
  it("shows the listing date and the days since, counted to the snapshot", () => {
    mount();
    expect(screen.getByText("2025-08-22")).toBeInTheDocument();
    expect(screen.getByText("376日前")).toBeInTheDocument();
  });

  it("shows the update time as an elapsed time", () => {
    mount();
    expect(screen.getByText("11か月前")).toBeInTheDocument();
  });
});

describe("the untouched-for bar", () => {
  it("grows with the time since the last update", () => {
    const { container } = mount({ updatedAt: daysBefore(182) });
    expect(bar(container).style.width).toBe("49.86301369863014%"); // 182/365
  });

  it("is nearly empty for a listing touched yesterday", () => {
    const { container } = mount({ updatedAt: daysBefore(1) });
    expect(Number.parseFloat(bar(container).style.width)).toBeLessThan(1);
  });

  it("stops at the axis, and squares its end to say it was cut short", () => {
    const { container } = mount({ updatedAt: daysBefore(900) });
    const fill = bar(container);
    expect(fill.style.width).toBe("100%");
    expect(fill.className).toMatch(/Capped/);
  });

  it("keeps a rounded end below the axis", () => {
    const { container } = mount({ updatedAt: daysBefore(100) });
    expect(bar(container).className).not.toMatch(/Capped/);
  });

  it("is hidden from assistive technology, because the line above says it", () => {
    const { container } = mount();
    const wrapper = container.querySelector("p[title^='最後に更新されてから']");
    expect(wrapper).toHaveAttribute("aria-hidden", "true");
    expect(wrapper).toHaveAttribute("title", "最後に更新されてから357日");
  });
});

describe("image", () => {
  it("shows the first image", () => {
    mount({ imageUrls: ["https://example.invalid/a.jpg", "https://example.invalid/b.jpg"] });
    expect(screen.getByRole("presentation")).toHaveAttribute(
      "src",
      "https://example.invalid/a.jpg",
    );
  });

  it("falls back to a placeholder when there is no image", () => {
    mount({ imageUrls: [] });
    expect(screen.getByText("画像を取得できませんでした")).toBeInTheDocument();
  });

  it("falls back to a placeholder when the image fails to load", async () => {
    mount();
    const image = screen.getByRole("presentation");
    image.dispatchEvent(new Event("error"));
    expect(
      await screen.findByText("画像を取得できませんでした"),
    ).toBeInTheDocument();
  });
});

describe("links", () => {
  it("opens Mercari in a new tab without leaking the referrer", () => {
    mount();
    const link = screen.getByRole("link", { name: "Mercariで商品を見る" });
    expect(link).toHaveAttribute("href", "https://jp.mercari.com/item/m1");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noreferrer");
  });

  it("keeps the whole title reachable when it is clamped", async () => {
    const user = userEvent.setup();
    const long = "ポケモンカード ".repeat(20);
    mount({ title: long });
    const link = screen.getByRole("link", { name: long.trim() });
    expect(link).toHaveAttribute("title", long);
    await user.tab();
    expect(document.activeElement).toBe(link);
  });

  it("routes to the seller inside the application", () => {
    mount();
    expect(screen.getByRole("link", { name: "Sellerを分析" })).toHaveAttribute(
      "href",
      "/sellers/s1",
    );
  });
});
