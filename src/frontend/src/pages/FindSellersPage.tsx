/**
 * Going looking for sellers
 * ([出品者探索 §12](../../../../docs/product/seller-discovery-spec.md)).
 *
 * The search screen starts from listings. This starts from the question the
 * reader actually has — who sells cards among clothes and household things —
 * and does the collecting for them: search each keyword, then look at the
 * sellers those searches turned up, from one press.
 *
 * What comes back is sorted into four piles behind tabs, so that the pile
 * the reader came for is the one in front of them: sellers whose shelf is
 * partly or mostly something else, sellers with only a few listings, sellers
 * who look like specialists, and the rest.
 *
 * **The press is the only thing that reaches Mercari, and it says what it can
 * cost before it is pressed.** Opening this screen, typing in it and changing
 * tabs send nothing.
 */

import { useId, useMemo, useState, type FormEvent } from "react";

import type { ApiFailureKind } from "../api/client";
import { SEARCH_PAGE_LIMIT, rangeNote } from "../collectionRange";
import { FailureNotice } from "../components/FailureNotice";
import { EXAMPLES } from "../components/SearchForm";
import {
  SellerCandidateLimits,
  SellerCandidateList,
} from "../components/SellerCandidates";
import { SellerListError } from "../components/SellerListNote";
import { Tabs } from "../components/Tabs";
import { TitleTermsField } from "../components/TitleTermsField";
import {
  REQUESTS_PER_EVALUATION,
  excludedSellerIds,
  sellerCandidates,
  sortCandidates,
  withoutExcluded,
  type SellerCandidate,
} from "../sellerCandidates";
import { useSellerDiscovery } from "../sellerDiscoveryState";
import {
  DEFAULT_SELLER_BUDGET,
  HUNT_PILES,
  MAX_KEYWORDS,
  SELLER_BUDGETS,
  huntCeiling,
  keywordsFrom,
  pileOf,
  type HuntPile,
} from "../sellerHunt";
import { parseTitleTerms, quoteTerms, withTitleTerms } from "../titleTerms";
import { useSellerHunt, type KeywordOutcome } from "../sellerHuntState";
import { NO_BAND, validateSearch, type PriceBand } from "../validation";

import styles from "./FindSellersPage.module.css";

const people = (value: number) => `${value.toLocaleString("ja-JP")}人`;
const count = (value: number) => `${value.toLocaleString("ja-JP")}件`;

/** The same wording the other screens use for the failures that end a run. */
const RUN_ENDED: Partial<Record<ApiFailureKind, { message: string; retryable: boolean }>> = {
  safety_stop: {
    message:
      "続けて拒否されたため取得を止めました。自動では再試行しません。時間を置いてからお試しください",
    retryable: false,
  },
  rate_limited: {
    message: "Mercariが一時的に応答を制限しています。時間を置いてください",
    retryable: true,
  },
  network: {
    message: "Backendへ接続できませんでした。起動しているか確認してください",
    retryable: true,
  },
};

/**
 * The wait in words, rounded up: a wait is better overstated.
 *
 * Two seconds a request is the interval alone. The time each request takes
 * sits on top, so the screen writes 以上 after it, as the 出品者 tab does
 * (出品者探索 §4.2).
 */
function durationHint(seconds: number): string {
  return seconds < 60
    ? `約${seconds}秒`
    : `約${Math.ceil(seconds / 60).toLocaleString("ja-JP")}分`;
}

type FormErrors = { keywords?: string; minPriceYen?: string; maxPriceYen?: string };

const PILES: Record<HuntPile, { label: string; about: string; empty: string }> = {
  candidates: {
    label: "候補",
    about: "TCG以外も出品している出品者です。出品の幅が「広い」か「中」の人を出しています。",
    empty: "候補になる出品者は、まだ見つかっていません",
  },
  few: {
    label: "少数出品",
    about:
      "TCGが中心ですが、調べた出品が30件に満たない出品者です。引退や整理で数点だけ出している人がここに入ります。専門かどうかは、この件数では判断できません。",
    empty: "ここに入る出品者は、まだ見つかっていません",
  },
  specialists: {
    label: "専門らしい",
    about:
      "調べた出品が30件以上あり、その半分以上がTCGの出品者です。除外リストへ入れると、次からは調べる対象に入りません。",
    empty: "専門らしい出品者は、まだ見つかっていません",
  },
  others: {
    label: "その他",
    about:
      "まだ調べていない出品者、取得できなかった出品者、出品が無く判定できなかった出品者です。",
    empty: "ここに入る出品者はいません",
  },
};

function KeywordRecord({ outcome }: { outcome: KeywordOutcome }) {
  const said =
    outcome.status === "waiting"
      ? "順番待ち"
      : outcome.status === "searching"
        ? "検索しています"
        : outcome.status === "failed" || outcome.meta === null
          ? "取得できませんでした"
          : // Said per keyword, like every collection: 825件 with more to come
            // found some of the sellers behind this word, not all of them.
            `${count(outcome.itemCount)} / ${outcome.meta.pageCount.toLocaleString("ja-JP")}ページ（${rangeNote(outcome.meta)}）`;
  return (
    <li className={styles.keyword}>
      <span className={styles.word}>{outcome.keyword}</span>
      <span className={styles.said}>{said}</span>
    </li>
  );
}

export function FindSellersPage() {
  const hunt = useSellerHunt();
  const {
    entries,
    evaluations,
    run,
    listSeller,
    listBusy,
    listsStatus,
    titleTermsText,
  } = useSellerDiscovery();

  // One field to begin with, which is the search screen's own form. A second
  // search is a field the reader adds, never something a keystroke starts.
  const [fields, setFields] = useState<string[]>(() =>
    hunt.request && hunt.request.keywords.length > 0
      ? [...hunt.request.keywords]
      : [""],
  );
  const [minPriceYen, setMinPriceYen] = useState(
    () => hunt.request?.band.minPriceYen?.toString() ?? "",
  );
  const [maxPriceYen, setMaxPriceYen] = useState(
    () => hunt.request?.band.maxPriceYen?.toString() ?? "",
  );
  const [budget, setBudget] = useState<number>(
    () => hunt.request?.sellerBudget ?? DEFAULT_SELLER_BUDGET,
  );
  const [errors, setErrors] = useState<FormErrors>({});
  const [pile, setPile] = useState<HuntPile>("candidates");
  const id = useId();

  const typed = keywordsFrom(fields);
  // The ceiling follows what is typed, so the cost is on screen before the
  // press and changes as a keyword is added or the budget is raised.
  const ceiling = huntCeiling(Math.max(typed.length, 1), budget);
  const busy = hunt.phase === "searching" || hunt.phase === "looking";
  const blocked = busy || run.active;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const found: FormErrors = {};
    if (typed.length === 0) {
      found.keywords = "検索するキーワードを入力してください";
    }

    // The band is the same for every keyword, so it is judged once, by the
    // search screen's own rule. A stand-in keyword keeps a keyword error from
    // being reported here as well as below.
    let band: PriceBand = NO_BAND;
    const banded = validateSearch({ keyword: "x", minPriceYen, maxPriceYen });
    if (banded.ok) {
      band = banded.band;
    } else {
      if (banded.errors.minPriceYen) {
        found.minPriceYen = banded.errors.minPriceYen;
      }
      if (banded.errors.maxPriceYen) {
        found.maxPriceYen = banded.errors.maxPriceYen;
      }
    }

    // Each keyword by that same rule. The first one that fails is named,
    // because "one of these is too long" leaves the reader to find which.
    if (!found.keywords) {
      for (const keyword of typed) {
        const checked = validateSearch({ keyword, minPriceYen: "", maxPriceYen: "" });
        if (!checked.ok && checked.errors.keyword) {
          found.keywords = `「${keyword.slice(0, 20)}」: ${checked.errors.keyword}`;
          break;
        }
      }
    }

    setErrors(found);
    if (Object.keys(found).length > 0) {
      return;
    }
    setPile("candidates");
    hunt.start({ keywords: typed, band, sellerBudget: budget });
  };

  // The excluded list is applied to what is shown, live. Somebody excluded
  // from the 専門らしい tab leaves it at once, and the count below says where
  // they went.
  const held = useMemo(
    () => withoutExcluded(hunt.items, excludedSellerIds(entries)),
    [hunt.items, entries],
  );
  // Then the reader's words, live as well. The run applied them when it
  // chose whom to look at; here they decide who is on the list, so emptying
  // the field brings back the sellers it kept off — not yet looked at, and
  // said to be so.
  const titleTerms = useMemo(() => parseTitleTerms(titleTermsText), [titleTermsText]);
  const titled = useMemo(
    () => withTitleTerms(held.kept, titleTerms),
    [held.kept, titleTerms],
  );
  const candidates = useMemo(() => sellerCandidates(titled.kept), [titled.kept]);
  const piles = useMemo(() => {
    const sorted: Record<HuntPile, SellerCandidate[]> = {
      candidates: [],
      few: [],
      specialists: [],
      others: [],
    };
    // Widest shelf first within a pile, which only orders the first one:
    // the other two hold a single band or none.
    for (const candidate of sortCandidates(candidates, "breadth", evaluations)) {
      sorted[pileOf(evaluations.get(candidate.sellerId))].push(candidate);
    }
    return sorted;
  }, [candidates, evaluations]);

  const lookEnded = !run.active && run.endedBy ? RUN_ENDED[run.endedBy.kind] : null;
  const searchEnded = hunt.endedBy ? RUN_ENDED[hunt.endedBy.kind] : null;
  const failed = hunt.endedBy ?? (hunt.phase === "done" ? run.endedBy : null);
  const failure = searchEnded ?? (hunt.phase === "done" ? lookEnded : null);
  const searching = hunt.keywords.find((outcome) => outcome.status === "searching");
  const searched = hunt.keywords.filter(
    (outcome) => outcome.status === "done" || outcome.status === "failed",
  ).length;

  const excludeAll = async () => {
    // One at a time. Each answer is the whole list, and the next one is sent
    // only once the last has been stored.
    for (const candidate of piles.specialists) {
      if (!(await listSeller(candidate.sellerId, "excluded", ""))) {
        break;
      }
    }
  };

  return (
    <section aria-label="出品者を探す">
      <h2 className={styles.heading}>出品者を探す</h2>
      <p className={styles.about}>
        キーワードごとに検索し、出てきた出品者を順に調べて、TCG以外も出品している人を集めます。
      </p>

      <form className={styles.form} onSubmit={submit} noValidate>
        <fieldset className={styles.keywords}>
          <legend className={styles.label}>キーワード</legend>
          {fields.map((value, index) => (
            // Keyed by position: the fields have no identity but their order.
            <div key={index} className={styles.keywordRow}>
              <input
                className={styles.keyword}
                aria-label={`キーワード ${index + 1}`}
                value={value}
                placeholder={EXAMPLES[index]}
                aria-invalid={errors.keywords ? true : undefined}
                aria-describedby={`${id}-keywords-how`}
                onChange={(event) =>
                  setFields(
                    fields.map((kept, at) => (at === index ? event.target.value : kept)),
                  )
                }
              />
              {fields.length > 1 && (
                <button
                  type="button"
                  className={styles.quiet}
                  aria-label={`キーワード ${index + 1}を外す`}
                  onClick={() => setFields(fields.filter((_, at) => at !== index))}
                >
                  外す
                </button>
              )}
            </div>
          ))}
          {/* What the fields mean, where they are typed. One field is one
              search; a second field is a second search, added to the first. */}
          <p id={`${id}-keywords-how`} className={styles.how}>
            {typed.length > 1
              ? `${typed.length}つのキーワードを別々に検索し、見つかった出品を合わせます。`
              : "1つの欄が1回の検索です。空白で区切った語は、検索画面と同じく、まとめて1回で検索します。"}
          </p>
          {errors.keywords && (
            <p className={styles.error} role="alert">
              {errors.keywords}
            </p>
          )}
          {fields.length < MAX_KEYWORDS && (
            <p className={styles.more}>
              <button
                type="button"
                className={styles.quiet}
                onClick={() => setFields([...fields, ""])}
              >
                別のキーワードでも探す
              </button>
            </p>
          )}
        </fieldset>

        <TitleTermsField />

        <div className={styles.row}>
          {/* The unit sits outside the label, as on the search form, so the
              field is named 最低価格 and not 最低価格円. */}
          <div className={styles.inline}>
            <label htmlFor={`${id}-min`} className={styles.label}>
              最低価格
            </label>
            <input
              id={`${id}-min`}
              className={styles.number}
              inputMode="numeric"
              value={minPriceYen}
              aria-invalid={errors.minPriceYen ? true : undefined}
              onChange={(event) => setMinPriceYen(event.target.value)}
            />
            <span className={styles.unit}>円</span>
          </div>
          <div className={styles.inline}>
            <label htmlFor={`${id}-max`} className={styles.label}>
              最高価格
            </label>
            <input
              id={`${id}-max`}
              className={styles.number}
              inputMode="numeric"
              value={maxPriceYen}
              aria-invalid={errors.maxPriceYen ? true : undefined}
              onChange={(event) => setMaxPriceYen(event.target.value)}
            />
            <span className={styles.unit}>円</span>
          </div>
          <div className={styles.inline}>
            <label htmlFor={`${id}-budget`} className={styles.label}>
              調べる出品者
            </label>
            <select
              id={`${id}-budget`}
              value={budget}
              onChange={(event) => setBudget(Number(event.target.value))}
            >
              {SELLER_BUDGETS.map((size) => (
                <option key={size} value={size}>
                  {people(size)}まで
                </option>
              ))}
            </select>
          </div>
        </div>
        {(errors.minPriceYen || errors.maxPriceYen) && (
          <p className={styles.error} role="alert">
            {errors.minPriceYen ?? errors.maxPriceYen}
          </p>
        )}

        <div className={styles.go}>
          <button type="submit" disabled={blocked}>
            探す
          </button>
          <p className={styles.cost}>
            Mercariへ最大{ceiling.requests.toLocaleString("ja-JP")}
            回問い合わせます（検索1回につき最大{SEARCH_PAGE_LIMIT}回、出品者1人につき
            {REQUESTS_PER_EVALUATION}回。上限まで使うと{durationHint(ceiling.seconds)}以上）
          </p>
        </div>
        {run.active && !busy && (
          <p className={styles.cost}>
            検索画面で出品者を調べている最中です。終わってから探せます。
          </p>
        )}
      </form>

      {hunt.phase !== "idle" && (
        <section className={styles.record} aria-label="探した範囲">
          {busy && (
            <div className={styles.progress}>
              <p role="status">
                {hunt.phase === "searching"
                  ? `検索しています ${searched.toLocaleString("ja-JP")} / ${hunt.keywords.length.toLocaleString("ja-JP")}${
                      searching ? `（${searching.keyword}）` : ""
                    }`
                  : `出品者を調べています ${run.finished.toLocaleString("ja-JP")} / ${people(run.total)}`}
              </p>
              <button type="button" className={styles.quiet} onClick={hunt.stop}>
                止める
              </button>
            </div>
          )}

          <ul className={styles.keywordList}>
            {hunt.keywords.map((outcome) => (
              <KeywordRecord key={outcome.keyword} outcome={outcome} />
            ))}
          </ul>

          {hunt.phase === "done" && (
            <p className={styles.tally}>
              <b>{count(hunt.items.length)}</b>の出品から{" "}
              <b>{people(candidates.length)}</b>の出品者
            </p>
          )}

          {/* What this run did not look at, and why. Each line is a limit of
              the run and not of Mercari, which is why they are said here and
              not left to be noticed. */}
          <div className={styles.limits}>
            <p>一致した出品が少ない出品者から順に調べています。</p>
            {hunt.beyondBudget > 0 && (
              <p>
                上限に達したため、{people(hunt.beyondBudget)}
                はまだ調べていません。もう一度「探す」を押すと、続きから調べます。
              </p>
            )}
            {held.heldBack.length > 0 && (
              <p>
                除外リストの出品者 {people(held.heldBackSellerCount)}・
                {count(held.heldBack.length)}は対象から外しています。
              </p>
            )}
            {titled.heldBack.length > 0 && (
              <p>
                タイトルに{quoteTerms(titleTerms)}
                {titleTerms.length > 1 ? "のどれも" : "を"}含まない出品{" "}
                {count(titled.heldBack.length)}は対象から外しています
                {titled.goneSellerCount > 0 &&
                  `（出品者 ${people(titled.goneSellerCount)}は、ほかに残る出品がありません）`}
                。
              </p>
            )}
            {hunt.stoppedByReader && <p>途中で止めました。</p>}
          </div>
        </section>
      )}

      {failure && failed && (
        <FailureNotice
          message={failure.message}
          retryLabel="もう一度探す"
          retryable={failure.retryable}
          reachedMarketplace={failed.reachedMarketplace}
          retryAllowedAt={failed.retryAllowedAt}
          onRetry={() => hunt.request && hunt.start(hunt.request)}
        />
      )}

      {hunt.phase !== "idle" && candidates.length > 0 && (
        <Tabs<HuntPile>
          label="見つかった出品者"
          tabs={HUNT_PILES.map((key) => ({
            key,
            label: PILES[key].label,
            count: piles[key].length,
          }))}
          active={pile}
          onChange={setPile}
        >
          <p className={styles.pileAbout}>{PILES[pile].about}</p>

          {pile === "specialists" && piles.specialists.length > 0 && (
            <p className={styles.bulk}>
              <button
                type="button"
                className={styles.quiet}
                disabled={listBusy || listsStatus !== "ready"}
                onClick={() => void excludeAll()}
              >
                この{people(piles.specialists.length)}を除外リストへ入れる
              </button>
            </p>
          )}

          <SellerListError />

          {piles[pile].length === 0 ? (
            <p className={styles.empty}>{PILES[pile].empty}</p>
          ) : (
            <SellerCandidateList
              candidates={piles[pile]}
              evaluations={evaluations}
            />
          )}

          <SellerCandidateLimits />
        </Tabs>
      )}

      {hunt.phase === "done" &&
        hunt.items.length > 0 &&
        candidates.length === 0 &&
        titled.heldBack.length > 0 && (
          // Found, and all of it kept back by the reader's own words. Saying
          // nothing here would read as the search having found nothing.
          <p className={styles.empty}>
            見つかった出品は、すべて「タイトルに含む語」で外れています。語を変えるか、空欄にすると表示されます
          </p>
        )}

      {hunt.phase === "done" && hunt.items.length === 0 && !failure && (
        <p className={styles.empty}>
          一致する出品がありませんでした。キーワードを変えてお試しください
        </p>
      )}
    </section>
  );
}
