/**
 * Keeping the listings whose title says one of the reader's words
 * (出品者探索 §13).
 *
 * **Mercari's keyword search is not "contains every word".** A search for
 * `ポケモンカード 押入れ` brought back a NARUTO card lot whose title, text and
 * category nowhere say ポケモン; 押入れ is in its description and カード is
 * everywhere on it (observed 2026-11-19). In Mercari's own app such a listing
 * sinks, because the default order is by relevance. This application asks in
 * 新しい順 so that it can reach back, and there a weak match stands level
 * with a strong one.
 *
 * So what Mercari returned is narrowed here, after the fact, by the one thing
 * a search result carries that the reader can check: the title. **Nothing
 * here sends a request, and nothing is narrowed until the reader names a
 * word.** What is kept back is counted and can be brought back by emptying
 * the field, which is what sets this apart from asking Mercari to exclude a
 * word ([O-7](../../../docs/planning/todo.md)): there the listings never
 * arrive and nobody can say how many there were.
 *
 * The cost is stated on screen and in the specification: a result carries no
 * description, so a listing titled only カード まとめ売り whose description
 * says ポケモン is kept back too.
 */

import type { Item } from "./types/api";

const HIRAGANA = /[ぁ-ゖ]/g;
const HIRAGANA_TO_KATAKANA = 0x60;

/**
 * Fold the differences a reader does not mean.
 *
 * Width (ＰＯＫＥＭＯＮ, ﾎﾟｹﾓﾝ), case, and hiragana against katakana (ぽけか). The
 * title is folded the same way as the word, so the two are compared as the
 * reader hears them rather than as they happen to have been typed.
 */
export function foldForTitle(text: string): string {
  return text
    .normalize("NFKC")
    .toLowerCase()
    .replace(HIRAGANA, (kana) =>
      String.fromCharCode(kana.charCodeAt(0) + HIRAGANA_TO_KATAKANA),
    );
}

/**
 * The words in the field, separated by spaces of either width.
 *
 * **Here a space does separate**, unlike in a keyword: a keyword is one
 * question put to Mercari, and these are alternatives, any one of which is
 * enough. The field's own label says so. A word written twice, or in two
 * spellings that fold to the same thing, is one word.
 */
export function parseTitleTerms(text: string): string[] {
  const seen = new Map<string, string>();
  for (const word of text.normalize("NFKC").split(/\s+/)) {
    const folded = foldForTitle(word);
    if (folded !== "" && !seen.has(folded)) {
      seen.set(folded, word);
    }
  }
  return [...seen.values()];
}

export type TitleNarrowing = {
  kept: Item[];
  heldBack: Item[];
  /**
   * Sellers none of whose listings were kept.
   *
   * Not the sellers of the listings kept back: somebody with one listing
   * kept and one held back is still on the list, and counting them here
   * would say they had gone.
   */
  goneSellerCount: number;
};

/**
 * Split a result into listings whose title contains any of the words, and
 * the rest.
 *
 * No words, no narrowing: everything is kept. Both halves are returned for
 * the same reason `withoutExcluded` returns both — the screen has to be able
 * to say how much it is not showing.
 */
export function withTitleTerms(
  items: readonly Item[],
  terms: readonly string[],
): TitleNarrowing {
  const wanted = terms.map(foldForTitle).filter((term) => term !== "");
  if (wanted.length === 0) {
    return { kept: [...items], heldBack: [], goneSellerCount: 0 };
  }
  const kept: Item[] = [];
  const heldBack: Item[] = [];
  for (const item of items) {
    const title = foldForTitle(item.title);
    (wanted.some((term) => title.includes(term)) ? kept : heldBack).push(item);
  }
  const stillListed = new Set(kept.map((item) => item.sellerId));
  const gone = new Set(
    heldBack
      .map((item) => item.sellerId)
      .filter((sellerId) => !stillListed.has(sellerId)),
  );
  return { kept, heldBack, goneSellerCount: gone.size };
}

/** The words as the screen quotes them: 「ポケモン」「ポケカ」. */
export function quoteTerms(terms: readonly string[]): string {
  return terms.map((term) => `「${term}」`).join("");
}
