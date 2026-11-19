/**
 * Narrowing a result by the words in its titles (出品者探索 §13).
 *
 * This removes listings from view, which is the one thing this application
 * is most careful about. So what is checked is that it removes nothing until
 * asked, removes only what the reader's words say, and can always say how
 * much it removed.
 */

import { describe, expect, it } from "vitest";

import {
  foldForTitle,
  parseTitleTerms,
  quoteTerms,
  withTitleTerms,
} from "../src/titleTerms";
import type { Item } from "../src/types/api";

function item(id: string, sellerId: string, title: string): Item {
  return {
    id,
    title,
    priceYen: 1000,
    url: `https://jp.mercari.com/item/${id}`,
    imageUrls: [],
    createdAt: "2026-01-01T00:00:00+09:00",
    updatedAt: "2026-01-02T00:00:00+09:00",
    listingStatus: "on_sale",
    saleFormat: "fixed_price",
    sellerId,
    itemCondition: null,
  };
}

// What a search for ポケモンカード 押入れ brought back on 2026-11-19: the
// second title is the listing that was reported, and nothing on its page
// said ポケモン.
const POKEMON = item("a", "home", "ポケモンカードゲーム モンスターボール　旧裏");
const NARUTO = item("b", "attic", "NARUTO カードゲーム まとめ売り ② 初期 ナルト");
const POKECA = item("c", "shop", "ポケカ まとめ 引退品");
const VAGUE = item("d", "home", "カード まとめ売り");

describe("the words in the field", () => {
  it("are separated by spaces of either width", () => {
    expect(parseTitleTerms("ポケモン ポケカ")).toEqual(["ポケモン", "ポケカ"]);
    expect(parseTitleTerms("ポケモン　ポケカ")).toEqual(["ポケモン", "ポケカ"]);
    expect(parseTitleTerms("  ポケモン \n ポケカ  ")).toEqual(["ポケモン", "ポケカ"]);
  });

  it("are none when the field is empty", () => {
    expect(parseTitleTerms("")).toEqual([]);
    expect(parseTitleTerms(" 　 ")).toEqual([]);
  });

  it("count a word once however it is spelled", () => {
    expect(parseTitleTerms("ポケカ ぽけか ﾎﾟｹｶ")).toEqual(["ポケカ"]);
    expect(parseTitleTerms("Pokemon ＰＯＫＥＭＯＮ pokemon")).toEqual(["Pokemon"]);
  });

  it("are quoted on screen the way they were typed", () => {
    expect(quoteTerms(["ポケモン", "ポケカ"])).toBe("「ポケモン」「ポケカ」");
  });
});

describe("folding", () => {
  it.each([
    ["ＰＯＫＥＭＯＮ Card", "pokemon card"],
    ["ﾎﾟｹﾓﾝｶｰﾄﾞ", "ポケモンカード"],
    ["ぽけもんかーど", "ポケモンカード"],
    ["ポケモンカード　旧裏", "ポケモンカード 旧裏"],
  ])("%s → %s", (raw, folded) => {
    expect(foldForTitle(raw)).toBe(folded);
  });
});

describe("narrowing by title", () => {
  const found = [POKEMON, NARUTO, POKECA, VAGUE];

  it("keeps everything when no word is given", () => {
    expect(withTitleTerms(found, [])).toEqual({
      kept: found,
      heldBack: [],
      goneSellerCount: 0,
    });
  });

  it("keeps the listings whose title says any one of the words", () => {
    const narrowed = withTitleTerms(found, ["ポケモン", "ポケカ"]);

    expect(narrowed.kept).toEqual([POKEMON, POKECA]);
    expect(narrowed.heldBack).toEqual([NARUTO, VAGUE]);
  });

  it("keeps back the listing that was reported", () => {
    expect(withTitleTerms([NARUTO], ["ポケモン", "ポケカ"]).kept).toEqual([]);
  });

  it("does not ask for every word, only one", () => {
    // The reader's words are alternatives. ポケモンカード and ポケカ are two
    // ways sellers write the same thing, and nobody writes both.
    expect(withTitleTerms([POKECA], ["ポケモン", "ポケカ"]).kept).toEqual([POKECA]);
  });

  it("finds a word inside a longer one, and across widths and kana", () => {
    expect(withTitleTerms([POKEMON], ["ポケモン"]).kept).toEqual([POKEMON]);
    expect(withTitleTerms([POKEMON], ["ぽけもん"]).kept).toEqual([POKEMON]);
    expect(withTitleTerms([NARUTO], ["naruto"]).kept).toEqual([NARUTO]);
    expect(
      withTitleTerms([item("e", "s", "ﾎﾟｹｶ まとめ")], ["ポケカ"]).kept,
    ).toHaveLength(1);
  });

  it("keeps back a listing that names the game only in its description", () => {
    // The cost of narrowing by title, and the reason the screen counts what
    // it keeps back: a search result carries no description to look in.
    expect(withTitleTerms([VAGUE], ["ポケモン", "ポケカ"]).heldBack).toEqual([VAGUE]);
  });

  it("counts as gone only the sellers with nothing left", () => {
    // `home` has one listing kept and one kept back, and is still on the
    // list. `attic` had only the listing kept back.
    const narrowed = withTitleTerms(found, ["ポケモン", "ポケカ"]);

    expect(narrowed.goneSellerCount).toBe(1);
  });

  it("leaves what it was given untouched", () => {
    const before = [...found];
    withTitleTerms(found, ["ポケモン"]);

    expect(found).toEqual(before);
  });
});
