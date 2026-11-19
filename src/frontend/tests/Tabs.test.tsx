/**
 * The tabs the screens use to keep one thing in front of the reader.
 *
 * Checked by role, the way a screen reader meets them. Two things can be
 * wrong while the tabs still look right: every tab sitting in the tab order,
 * and a closed panel still being rendered behind the open one.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { Tabs } from "../src/components/Tabs";

type Key = "items" | "sellers";

function Example() {
  const [active, setActive] = useState<Key>("items");
  return (
    <Tabs<Key>
      label="検索結果の見方"
      tabs={[
        { key: "items", label: "商品", count: 1200 },
        { key: "sellers", label: "出品者" },
      ]}
      active={active}
      onChange={setActive}
    >
      {active === "items" ? <p>商品の一覧</p> : <p>出品者の一覧</p>}
    </Tabs>
  );
}

describe("Tabs", () => {
  it("names the set, marks the open tab and labels the panel with it", () => {
    render(<Example />);

    expect(screen.getByRole("tablist", { name: "検索結果の見方" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /商品/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("tabpanel", { name: /商品/ })).toHaveTextContent(
      "商品の一覧",
    );
  });

  it("prints a count where one was given, grouped the Japanese way", () => {
    render(<Example />);

    expect(screen.getByRole("tab", { name: /商品/ })).toHaveTextContent("1,200");
    expect(screen.getByRole("tab", { name: "出品者" })).toBeInTheDocument();
  });

  it("renders only the open panel", async () => {
    render(<Example />);
    expect(screen.queryByText("出品者の一覧")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("tab", { name: "出品者" }));

    expect(screen.getByText("出品者の一覧")).toBeInTheDocument();
    expect(screen.queryByText("商品の一覧")).not.toBeInTheDocument();
  });

  it("keeps only the open tab in the tab order", () => {
    render(<Example />);

    expect(screen.getByRole("tab", { name: /商品/ })).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("tab", { name: "出品者" })).toHaveAttribute(
      "tabindex",
      "-1",
    );
  });

  it("moves with the arrow keys, wrapping at either end", async () => {
    render(<Example />);
    screen.getByRole("tab", { name: /商品/ }).focus();

    await userEvent.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "出品者" })).toHaveFocus();
    expect(screen.getByText("出品者の一覧")).toBeInTheDocument();

    await userEvent.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: /商品/ })).toHaveFocus();

    await userEvent.keyboard("{ArrowLeft}");
    expect(screen.getByRole("tab", { name: "出品者" })).toHaveFocus();
  });
});
