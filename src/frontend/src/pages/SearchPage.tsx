/**
 * The search screen.
 *
 * Scaffolding. The inputs, the metadata block, the filters and the image grid
 * are Phase 1-1 and 1-2, and the visual direction is not decided yet. What is
 * here is the part 1-0 needs: the search runs from the button, the result is
 * read from the state above the router, and nothing on this page calls the
 * API directly.
 */

import { useState } from "react";
import { Link } from "react-router";

import { useSearchState } from "../searchState";

export function SearchPage() {
  const { status, result, error, sort, runSearch } = useSearchState();
  const [draft, setDraft] = useState("");

  return (
    <section>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void runSearch(draft.trim());
        }}
      >
        <label htmlFor="keyword">キーワード</label>
        <input
          id="keyword"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        />
        {/* Section 5.2 disables the second submit. The backend does not rely
            on it: single-flight there is what actually holds the promise. */}
        <button type="submit" disabled={status === "loading"}>
          検索
        </button>
      </form>

      {status === "loading" && <p>最大取得範囲を確認中</p>}
      {status === "error" && <p role="alert">取得できませんでした（{error?.kind}）</p>}

      {result && (
        <>
          <p>
            取得 {result.meta.uniqueItemCount}件 / {result.meta.pageCount}ページ
          </p>
          <p>並び: {sort}</p>
          <ul>
            {result.items.map((item) => (
              <li key={item.id}>
                <span>{item.title}</span>
                <Link to={`/sellers/${item.sellerId}`}>Sellerを分析</Link>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
