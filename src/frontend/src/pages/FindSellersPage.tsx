/**
 * Going looking for sellers
 * ([出品者探索 §12](../../../../docs/product/seller-discovery-spec.md)).
 *
 * The search screen starts from listings. This starts from the question the
 * reader actually has — who sells cards, and among what — and does the
 * collecting for them.
 *
 * **Three things, in the order they happen, and each in its own block**
 * (出品者探索 §15):
 *
 * 1. 取得する条件 — the keywords and the price band, put to Mercari's search
 *    by 検索.
 * 2. 調べる出品者 — out of what came back, whom to look at: the words a title
 *    has to contain, and how many sellers. 調べる looks at them.
 * 3. The result, sorted into four piles behind tabs.
 *
 * The first two send requests, and each says how many before it is pressed —
 * the second exactly, because by then the sellers are known. The third sends
 * nothing. Opening this screen, typing in it and changing tabs send nothing
 * either.
 *
 * **The list is what the last 調べる was asked for.** Editing the words
 * afterwards prepares the next press and leaves the list as it is.
 */

import { useId, useMemo, useState, type FormEvent } from "react";

import type { ApiFailureKind } from "../api/client";
import { SEARCH_PAGE_LIMIT, rangeNote } from "../collectionRange";
import { FailureNotice } from "../components/FailureNotice";
import { EXAMPLES, KEYWORD_SCOPE } from "../components/SearchForm";
import {
  SellerCandidateLimits,
  SellerCandidateList,
} from "../components/SellerCandidates";
import { SellerListError } from "../components/SellerListNote";
import { Tabs } from "../components/Tabs";
import {
  DISPLAY_AND_SORT_STAGE_TITLE,
  FETCH_STAGE_TITLE,
  SELECT_STAGE_TITLE,
  Stage,
} from "../components/Stage";
import { TitleTermsField } from "../components/TitleTermsField";
import {
  CANDIDATE_SORT_LABELS,
  type CandidateSort,
  excludedSellerIds,
  isOwedALook,
  REQUESTS_PER_EVALUATION,
  type SellerCandidate,
  sellerCandidates,
  sortCandidates,
  withGoodRatings,
  withoutExcluded,
} from "../sellerCandidates";
import { useSellerDiscovery } from "../sellerDiscoveryState";
import {
  chooseTargets,
  DEFAULT_LOOK_ORDER,
  DEFAULT_SELLER_BUDGET,
  HUNT_PILES,
  HUNT_SORT_ORDER,
  type HuntPile,
  keywordsFrom,
  LOOK_ORDER_LABELS,
  LOOK_ORDERS,
  lookCost,
  type LookOrder,
  MAX_KEYWORDS,
  pileOf,
  searchCeiling,
  SELLER_BUDGETS,
  SPECIALIST_FROM_CARD_PERCENT,
} from "../sellerHunt";
import { parseTitleTerms, quoteTerms, sameTerms, withTitleTerms } from "../titleTerms";
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
  varied: {
    label: "混ざっている",
    about:
      `出品のうち、カード（TCG）が${SPECIALIST_FROM_CARD_PERCENT}%に満たない出品者です。カード以外の物も出品しています。`,
    empty: "ここに入る出品者は、まだ見つかっていません",
  },
  few: {
    label: "出品が少ない",
    about:
      `出品の${SPECIALIST_FROM_CARD_PERCENT}%以上がカード（TCG）ですが、調べた出品が30件に満たない出品者です。引退や整理で数点だけ出している人がここに入ります。カード専門かどうかは、この件数では判断できません。`,
    empty: "ここに入る出品者は、まだ見つかっていません",
  },
  specialists: {
    label: "カード専門",
    about:
      `調べた出品が30件以上あり、その${SPECIALIST_FROM_CARD_PERCENT}%以上がカード（TCG）の出品者です。ポケモンカードに限らず、カード全般で数えています。`,
    empty: "ここに入る出品者は、まだ見つかっていません",
  },
  others: {
    label: "未調査・不明",
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
    () => hunt.applied?.sellerBudget ?? DEFAULT_SELLER_BUDGET,
  );
  const [order, setOrder] = useState<LookOrder>(
    () => hunt.applied?.order ?? DEFAULT_LOOK_ORDER,
  );
  const [errors, setErrors] = useState<FormErrors>({});
  const [pile, setPile] = useState<HuntPile>("varied");
  // What is typed in the ratings field. The number it stands for lives with
  // the list; this is only so that a half-typed value is not thrown away.
  const [minGoodText, setMinGoodText] = useState(
    () => hunt.view.minGoodRatings?.toString() ?? "",
  );
  const id = useId();

  const typed = keywordsFrom(fields);
  // The ceiling follows what is typed, so the cost is on screen before the
  // press and changes as a keyword is added.
  const ceiling = searchCeiling(Math.max(typed.length, 1));
  const searchingNow = hunt.searchPhase === "searching";
  const busy = searchingNow || hunt.looking;
  // Nothing here starts while sellers are being looked at from a search
  // result either: both would be drawing on the same queue.
  const blocked = busy || run.active;

  const submitSearch = (event: FormEvent) => {
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
    hunt.search({ keywords: typed, band });
  };

  // The excluded list is applied live, to the next press and to the list
  // alike: somebody excluded from the カード専門 tab leaves it at once.
  const held = useMemo(
    () => withoutExcluded(hunt.items, excludedSellerIds(entries)),
    [hunt.items, entries],
  );
  const foundSellerCount = useMemo(
    () => new Set(hunt.items.map((item) => item.sellerId)).size,
    [hunt.items],
  );

  // What the next 調べる would do, worked out from the fields as they stand.
  // Nothing is sent to find this out: the listings are already in hand.
  const draftTerms = useMemo(() => parseTitleTerms(titleTermsText), [titleTermsText]);
  const draft = useMemo(
    () => withTitleTerms(held.kept, draftTerms),
    [held.kept, draftTerms],
  );
  const draftCandidates = useMemo(() => sellerCandidates(draft.kept), [draft.kept]);
  const draftTargets = useMemo(
    () => chooseTargets(draftCandidates, evaluations, budget, order),
    [draftCandidates, evaluations, budget, order],
  );
  const toLook = draftTargets.sellerIds.length;
  const cost = lookCost(toLook);
  const termsChanged =
    hunt.applied !== null && !sameTerms(draftTerms, hunt.applied.titleTerms);
  // With nobody left to look at, a press still has something to do when the
  // words differ from the ones the list was made with: it changes the list,
  // and sends nothing.
  const lookHasWork = toLook > 0 || hunt.applied === null || termsChanged;

  const submitLook = () => {
    setPile("varied");
    hunt.look({ titleTerms: draftTerms, sellerBudget: budget, order });
  };

  // What is on screen: the collection as the last 調べる narrowed it. Not the
  // fields — those are for the next press.
  const appliedTerms = hunt.applied?.titleTerms ?? null;
  const shown = useMemo(
    () => (appliedTerms === null ? null : withTitleTerms(held.kept, appliedTerms)),
    [held.kept, appliedTerms],
  );
  const lookedOver = useMemo(
    () => (shown === null ? [] : sellerCandidates(shown.kept)),
    [shown],
  );
  const notLookedAt = lookedOver.filter((candidate) =>
    isOwedALook(evaluations.get(candidate.sellerId)),
  ).length;

  // How the list is read. Applied last, over what the looks brought back, and
  // sends nothing: undoing it brings back whoever it kept off (出品者探索 §16.2).
  const rated = useMemo(
    () => withGoodRatings(lookedOver, evaluations, hunt.view.minGoodRatings),
    [lookedOver, evaluations, hunt.view.minGoodRatings],
  );
  const candidates = rated.kept;
  const minGoodInvalid = minGoodText.trim() !== "" && !/^\d+$/.test(minGoodText.trim());
  const changeMinGood = (text: string) => {
    setMinGoodText(text);
    const typedNumber = text.trim();
    if (typedNumber === "") {
      hunt.setView({ ...hunt.view, minGoodRatings: null });
    } else if (/^\d+$/.test(typedNumber)) {
      hunt.setView({ ...hunt.view, minGoodRatings: Number(typedNumber) });
    }
    // Anything else is left as it was: a letter typed by mistake does not
    // change what is on the list.
  };
  const piles = useMemo(() => {
    const sorted: Record<HuntPile, SellerCandidate[]> = {
      varied: [],
      few: [],
      specialists: [],
      others: [],
    };
    // In the order the reader chose, within each pile.
    for (const candidate of sortCandidates(candidates, hunt.view.sort, evaluations)) {
      sorted[pileOf(evaluations.get(candidate.sellerId))].push(candidate);
    }
    return sorted;
  }, [candidates, evaluations, hunt.view.sort]);

  const searchFailure = hunt.searchEndedBy ? RUN_ENDED[hunt.searchEndedBy.kind] : null;
  // The looks report what ended them through the shared run, which may also
  // have been started from a search result. Only said here once this screen
  // has asked for some.
  const lookEndedBy =
    hunt.applied !== null && !run.active && !hunt.looking ? run.endedBy : null;
  const lookFailure = lookEndedBy ? RUN_ENDED[lookEndedBy.kind] : null;
  const searchingKeyword = hunt.keywords.find(
    (outcome) => outcome.status === "searching",
  );
  const searchedCount = hunt.keywords.filter(
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
    <section aria-label="出品者検索">
      <h2 className={styles.heading}>出品者検索</h2>
      <p className={styles.about}>
        キーワードで商品を検索し、出てきた出品者を調べて、出品にカードがどれだけあるかで分けます。
      </p>

      <Stage
        title={FETCH_STAGE_TITLE}
        note="Mercariの商品検索へ送ります。変えたときは「検索」を押して取得し直します。"
      >
      <form className={styles.form} onSubmit={submitSearch} noValidate>
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
          {/* Where a keyword is looked for, in the search screen's own words.
              With a second field, also that the two are searched apart and
              added together — the one thing about several fields that the
              result alone would not show. */}
          <p id={`${id}-keywords-how`} className={styles.how}>
            {KEYWORD_SCOPE}
            {typed.length > 1 &&
              ` ${typed.length}つのキーワードは別々に検索し、見つかった出品を合わせます。`}
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
        </div>
        {(errors.minPriceYen || errors.maxPriceYen) && (
          <p className={styles.error} role="alert">
            {errors.minPriceYen ?? errors.maxPriceYen}
          </p>
        )}

        <div className={styles.go}>
          <button type="submit" disabled={blocked}>
            検索
          </button>
          <p className={styles.cost}>
            Mercariへ最大{ceiling.requests.toLocaleString("ja-JP")}
            回問い合わせます（検索1回につき最大{SEARCH_PAGE_LIMIT}回。上限まで使うと
            {durationHint(ceiling.seconds)}以上）
          </p>
        </div>
        {run.active && !busy && (
          <p className={styles.cost}>
            商品検索の画面で出品者を調べている最中です。終わってから検索できます。
          </p>
        )}
      </form>
      </Stage>

      {hunt.searchPhase !== "idle" && (
        <section className={styles.record} aria-label="探した範囲">
          {searchingNow && (
            <div className={styles.progress}>
              <p role="status">
                {`検索しています ${searchedCount.toLocaleString("ja-JP")} / ${hunt.keywords.length.toLocaleString("ja-JP")}${
                  searchingKeyword ? `（${searchingKeyword.keyword}）` : ""
                }`}
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

          {hunt.searchPhase === "done" && (
            <p className={styles.tally}>
              <b>{count(hunt.items.length)}</b>の出品から{" "}
              <b>{people(foundSellerCount)}</b>の出品者
            </p>
          )}
          {hunt.searchStopped && (
            <div className={styles.limits}>
              <p>検索を途中で止めました。</p>
            </div>
          )}
        </section>
      )}

      {searchFailure && hunt.searchEndedBy && (
        <FailureNotice
          message={searchFailure.message}
          retryLabel="もう一度検索する"
          retryable={searchFailure.retryable}
          reachedMarketplace={hunt.searchEndedBy.reachedMarketplace}
          retryAllowedAt={hunt.searchEndedBy.retryAllowedAt}
          onRetry={() => hunt.request && hunt.search(hunt.request)}
        />
      )}

      {hunt.searchPhase === "done" && hunt.items.length === 0 && !searchFailure && (
        <p className={styles.empty}>
          一致する出品がありませんでした。キーワードを変えてお試しください
        </p>
      )}

      {/* Whom to look at, out of what was collected. Its own block and its
          own press: neither a question put to Mercari's search nor a way of
          reading a finished result, but the step between them. */}
      {hunt.searchPhase === "done" && hunt.items.length > 0 && (
        <Stage
          title={SELECT_STAGE_TITLE}
          note={`取得した結果の中から、誰を調べるかを決めます。「調べる」を押すと、1人につき${REQUESTS_PER_EVALUATION}回Mercariへ問い合わせます。検索はやり直しません。`}
        >
          <div className={styles.select}>
            <TitleTermsField disabled={blocked} />

            <div className={styles.row}>
              <div className={styles.inline}>
                <label htmlFor={`${id}-budget`} className={styles.label}>
                  一度に調べる人数
                </label>
                <select
                  id={`${id}-budget`}
                  value={budget}
                  disabled={blocked}
                  onChange={(event) => setBudget(Number(event.target.value))}
                >
                  {SELLER_BUDGETS.map((size) => (
                    <option key={size} value={size}>
                      {people(size)}まで
                    </option>
                  ))}
                </select>
              </div>
              <div className={styles.inline}>
                <label htmlFor={`${id}-order`} className={styles.label}>
                  調べる順番
                </label>
                <select
                  id={`${id}-order`}
                  value={order}
                  disabled={blocked}
                  aria-describedby={`${id}-order-how`}
                  onChange={(event) => setOrder(event.target.value as LookOrder)}
                >
                  {LOOK_ORDERS.map((key) => (
                    <option key={key} value={key}>
                      {LOOK_ORDER_LABELS[key]}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            {/* What the order is and is not. It is read off a count the
                search already gave; what a shelf holds is only known once
                somebody has been looked at. */}
            <p id={`${id}-order-how`} className={styles.how}>
              少ない人からは出品が混ざっている人に、多い人からはカード専門の人に当たりやすい、という見立てです。
              どちらも確かめた値ではなく、調べるまで分かりません。対象が人数の上限に収まるときは、順番に関わらず全員を調べます。
            </p>

            {/* Who that leaves, said before the press and from what is
                already in hand. */}
            <div className={styles.selected}>
              <p>
                対象の出品者 {people(draftCandidates.length)}
                （まだ調べていない人 {people(toLook + draftTargets.beyondBudget)}）
              </p>
              {held.heldBack.length > 0 && (
                <p>
                  除外リストの出品者 {people(held.heldBackSellerCount)}・
                  {count(held.heldBack.length)}は対象から外しています。
                </p>
              )}
              {draft.heldBack.length > 0 && (
                <p>
                  タイトルに{quoteTerms(draftTerms)}
                  {draftTerms.length > 1 ? "のどれも" : "を"}含まない出品{" "}
                  {count(draft.heldBack.length)}は対象から外しています
                  {draft.goneSellerCount > 0 &&
                    `（出品者 ${people(draft.goneSellerCount)}は、ほかに残る出品がありません）`}
                  。
                </p>
              )}
            </div>

            <div className={styles.go}>
              <button type="button" disabled={blocked || !lookHasWork} onClick={submitLook}>
                調べる
              </button>
              <p className={styles.cost}>
                {toLook > 0
                  ? `Mercariへ${cost.requests.toLocaleString("ja-JP")}回問い合わせます（${people(toLook)} × ${REQUESTS_PER_EVALUATION}回。${durationHint(cost.seconds)}以上）`
                  : lookHasWork
                    ? "問い合わせは発生しません。対象の出品者は全員調べ済みで、一覧だけを切り替えます。"
                    : "対象の出品者は全員調べました。"}
              </p>
            </div>
            {toLook > 0 && draftTargets.beyondBudget > 0 && (
              <p className={styles.cost}>
                人数の上限のため、今回調べるのは{people(toLook)}です。残り
                {people(draftTargets.beyondBudget)}
                は、もう一度「調べる」を押すと続きから調べます。
              </p>
            )}
            {termsChanged && !busy && (
              <p className={styles.cost}>
                語を変えました。「調べる」を押すと、下の一覧もこの語に切り替わります。
              </p>
            )}

            {hunt.looking && (
              <div className={styles.progress}>
                <p role="status">
                  {`出品者を調べています ${run.finished.toLocaleString("ja-JP")} / ${people(run.total)}`}
                </p>
                <button type="button" className={styles.quiet} onClick={hunt.stop}>
                  止める
                </button>
              </div>
            )}
            {hunt.lookStopped && !hunt.looking && (
              <p className={styles.cost}>調べるのを途中で止めました。</p>
            )}
          </div>
        </Stage>
      )}

      {lookFailure && lookEndedBy && (
        <FailureNotice
          message={lookFailure.message}
          retryLabel="もう一度調べる"
          retryable={lookFailure.retryable}
          reachedMarketplace={lookEndedBy.reachedMarketplace}
          retryAllowedAt={lookEndedBy.retryAllowedAt}
          onRetry={() => hunt.applied && hunt.look(hunt.applied)}
        />
      )}

      {hunt.applied !== null && lookedOver.length > 0 && (
        <>
          {/* What the list is a list of. It was made by the last press, and
              the fields above may have moved on since. */}
          <div className={styles.shown}>
            {hunt.applied.titleTerms.length > 0 && (
              <p>
                タイトルに{quoteTerms(hunt.applied.titleTerms)}
                {hunt.applied.titleTerms.length > 1 ? "のどれか" : ""}
                を含む出品の出品者を表示しています。
              </p>
            )}
            {notLookedAt > 0 && !hunt.looking && (
              <p>
                {people(notLookedAt)}
                はまだ調べていません。もう一度「調べる」を押すと、続きから調べます。
              </p>
            )}
          </div>

          {/* The third kind of thing on this screen, and the only one that
              sends nothing: how to read what the looks brought back. */}
          <Stage
            title={DISPLAY_AND_SORT_STAGE_TITLE}
            note="調べ終えた結果の見え方だけを変えます。Mercariへは何も送らず、戻せば元に戻ります。"
          >
            <div className={styles.view}>
              <div className={styles.row}>
                <div className={styles.inline}>
                  <label htmlFor={`${id}-good`} className={styles.label}>
                    良い評価
                  </label>
                  <input
                    id={`${id}-good`}
                    className={styles.number}
                    inputMode="numeric"
                    value={minGoodText}
                    disabled={blocked}
                    aria-invalid={minGoodInvalid ? true : undefined}
                    onChange={(event) => changeMinGood(event.target.value)}
                  />
                  <span className={styles.unit}>件以上</span>
                </div>
                <div className={styles.inline}>
                  <label htmlFor={`${id}-sort`} className={styles.label}>
                    並び順
                  </label>
                  <select
                    id={`${id}-sort`}
                    value={hunt.view.sort}
                    disabled={blocked}
                    onChange={(event) =>
                      hunt.setView({
                        ...hunt.view,
                        sort: event.target.value as CandidateSort,
                      })
                    }
                  >
                    {HUNT_SORT_ORDER.map((key) => (
                      <option key={key} value={key}>
                        {CANDIDATE_SORT_LABELS[key]}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
              {minGoodInvalid && (
                <p className={styles.error} role="alert">
                  良い評価の件数は、0以上の整数で入力してください
                </p>
              )}
              {blocked && <p className={styles.how}>処理中は変えられません。</p>}
              {rated.heldBack.length > 0 && hunt.view.minGoodRatings !== null && (
                <p className={styles.how}>
                  良い評価が{hunt.view.minGoodRatings.toLocaleString("ja-JP")}
                  件に満たない出品者 {people(rated.heldBack.length)}
                  を表示していません。評価の件数が分からない出品者は外していません。
                </p>
              )}
            </div>
          </Stage>

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
                {/* What the button does, and nothing about whether to. A card
                    specialist is somebody to exclude on a day spent looking
                    for bargains and somebody to read on a day spent looking
                    for cards in good condition. */}
                <span className={styles.bulkNote}>
                  除外リストへ入れた出品者は、次から調べる対象に入らず、検索結果にも出なくなります。
                </span>
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
        </>
      )}

      {hunt.applied !== null &&
        candidates.length === 0 &&
        shown !== null &&
        shown.heldBack.length > 0 && (
          // Found, and all of it kept back by the reader's own words. Saying
          // nothing here would read as the search having found nothing.
          <p className={styles.empty}>
            見つかった出品は、すべて「タイトルに含む語」で外れています。語を変えて、もう一度「調べる」を押してください
          </p>
        )}
    </section>
  );
}
