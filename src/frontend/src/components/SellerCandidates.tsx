/**
 * The sellers behind a search result
 * ([出品者探索 §5](../../../../docs/product/seller-discovery-spec.md)).
 *
 * The question this answers is "whose listings are worth opening first", for
 * a reader looking for people who sell cards among clothes and household
 * things rather than for a living. Two things are shown about each seller and
 * they arrive differently:
 *
 * - **What the search already said** — how many of their listings matched and
 *   how worn they said each was. There for everyone at once, for no request.
 * - **What a brief look found** — their name, their ratings, how much of
 *   their shelf is something other than trading cards. Three Mercari requests
 *   a seller, asked for by the button and never by opening this tab.
 *
 * The two are not folded into one score. Breadth over six listings and a
 * grade the seller chose themselves are different kinds of claim, and a
 * single number would hide which of them to doubt.
 */

import { useMemo, useState } from "react";
import { Link } from "react-router";

import type { ApiFailureKind } from "../api/client";
import { toDateTimeString } from "../jst";
import {
  CANDIDATE_SORT_LABELS,
  CANDIDATE_SORT_ORDER,
  type CandidateSort,
  cardShare,
  type EvaluationRecord,
  type FineShelf,
  fineShelf,
  evaluationSeconds,
  isOwedALook,
  mercariSellerUrl,
  REQUESTS_PER_EVALUATION,
  type SellerCandidate,
  sellerCandidates,
  sortCandidates,
} from "../sellerCandidates";
import { useSellerDiscovery } from "../sellerDiscoveryState";
import type { Item, SellerEvaluationResponse } from "../types/api";

import { FailureNotice } from "./FailureNotice";
import styles from "./SellerCandidates.module.css";
import { SellerListButtons } from "./SellerListButtons";

const MISSING = "-";

const people = (value: number) => `${value.toLocaleString("ja-JP")}人`;
const count = (value: number) => `${value.toLocaleString("ja-JP")}件`;
const percent = (ratio: number) => `${(ratio * 100).toFixed(1)}%`;

/**
 * How many of one status are 美品, over how many were read.
 *
 * The total is added only when it is more than was read: 117 of 1,152 is one
 * page of a large shelf, and the count beside it is of that page. Listings
 * with no grade are named when there are any, because they are in the
 * denominator and could not be in the count.
 */
function fineText(label: string, shelf: FineShelf): string {
  const read = `${label} ${count(shelf.fineCount)} / ${count(shelf.analyzedCount)}`;
  const all =
    shelf.foundCount !== null && shelf.foundCount > shelf.analyzedCount
      ? `（全${count(shelf.foundCount)}）`
      : "";
  const ungraded =
    shelf.unknownCount > 0 ? `・状態不明 ${count(shelf.unknownCount)}` : "";
  return `${read}${all}${ungraded}`;
}

/**
 * What ended a run, in the words the other screens use for the same failure.
 *
 * Only the three that end a run can arrive here. Each is about every request
 * that would follow, which is why the run stopped instead of moving on.
 */
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

/** At least this long, in words. Rounded up: a wait is better overstated. */
function durationHint(seconds: number): string {
  return seconds < 60
    ? `約${seconds}秒`
    : `約${Math.ceil(seconds / 60).toLocaleString("ja-JP")}分`;
}

function conditionSummary(candidate: SellerCandidate): string {
  const parts = candidate.conditions.map(
    (condition) => `${condition.name} ${count(condition.count)}`,
  );
  if (candidate.unknownConditionCount > 0) {
    parts.push(`不明 ${count(candidate.unknownConditionCount)}`);
  }
  return parts.join("、");
}

/** When the later of the two statuses was collected: when the look finished. */
function lookedAt(evaluation: SellerEvaluationResponse): string {
  const { onSaleMeta, soldOutMeta } = evaluation;
  return new Date(soldOutMeta.collectedAt) > new Date(onSaleMeta.collectedAt)
    ? soldOutMeta.collectedAt
    : onSaleMeta.collectedAt;
}

const NOT_LOOKED_AT = "未調査";

const WAITING: Record<Exclude<EvaluationRecord["status"], "done">, string> = {
  queued: "順番待ち",
  running: "調べています",
  failed: "取得できませんでした",
  gone: "この出品者は見つかりませんでした",
};

/**
 * One seller: who, what is known about them, and what to do about it.
 *
 * Exported because the same row is read in two places — under a search
 * result, and on the screen that goes looking for sellers. A seller should
 * read the same wherever they turn up.
 */
export function SellerCandidateRow({
  candidate,
  record,
}: {
  candidate: SellerCandidate;
  record: EvaluationRecord | undefined;
}) {
  const evaluation = record?.status === "done" ? record.evaluation : null;
  // Until a look brings the name back there is only the identifier, and it is
  // labelled as one rather than shown where a name would be.
  const label = evaluation?.seller.name || `Seller ${candidate.sellerId}`;
  const first = candidate.hits[0];
  const ratings = evaluation?.seller.ratingBreakdown ?? null;
  const share = evaluation ? cardShare(evaluation) : null;

  return (
    <li className={styles.row}>
      <div className={styles.who}>
        {/* The name opens the seller's page on Mercari, in another tab. It
            used to open this application's own seller screen, which starts
            collecting as soon as it is opened — up to twelve requests for
            having pressed a name. Looking at somebody on Mercari costs
            nothing here, and is what a reader pressing a name expects
            (出品者探索 §5.4). The seller screen is still one press away,
            under the words that say what it does. */}
        <h3 className={styles.name}>
          <a
            href={evaluation?.seller.url ?? mercariSellerUrl(candidate.sellerId)}
            target="_blank"
            rel="noreferrer"
            title="Mercariの出品者ページを開きます"
          >
            {label}
          </a>
        </h3>
        {first && (
          <p className={styles.sample}>
            <a
              href={first.url}
              target="_blank"
              rel="noreferrer"
              title={first.title}
            >
              {first.title}
            </a>
          </p>
        )}
        <p className={styles.analyze}>
          <Link to={`/sellers/${candidate.sellerId}`}>Sellerを分析</Link>
        </p>
      </div>

      <dl className={styles.facts}>
        <div className={styles.fact}>
          <dt>一致した出品</dt>
          <dd>{count(candidate.hits.length)}</dd>
        </div>
        {/* Named after the listings it describes. 商品の状態 alone, beside
            出品の幅 and 評価, read as a third fact about the seller; it is a
            fact about the listings counted on the line above
            (出品者探索 §5.4). */}
        <div className={styles.fact}>
          <dt>一致した出品の状態</dt>
          <dd>{conditionSummary(candidate) || MISSING}</dd>
        </div>
        {/* The share of cards, in the words the tabs use. It was the share
            of everything else, under 出品の幅, and read backwards beside a tab
            called カード専門 (出品者探索 §5.4). */}
        <div className={styles.fact}>
          <dt>カードの割合</dt>
          <dd>
            {evaluation === null ? (
              <span className={styles.pending}>
                {record && record.status !== "done"
                  ? WAITING[record.status]
                  : NOT_LOOKED_AT}
              </span>
            ) : share === null ? (
              // Looked at, and nothing listed to count.
              <span className={styles.pending}>判定不能</span>
            ) : (
              <>
                <span className={styles.band}>{percent(share.ratio)}</span>
                {/* The counts are not detail. 100% over three listings and
                    over sixty are the same share and different claims. */}
                <span className={styles.basis}>
                  カード {count(share.cardCount)} / {count(share.analyzedCount)}
                </span>
              </>
            )}
          </dd>
        </div>
        {/* Of the seller's own shelf, where the two lines at the top are of
            what the search matched. For sale first: it is what can be bought,
            and what the order by 美品 goes by (出品者探索 §5.7). */}
        <div className={styles.fact}>
          <dt>美品の出品</dt>
          <dd className={evaluation === null ? undefined : styles.shelves}>
            {evaluation === null ? (
              MISSING
            ) : (
              <>
                <span>
                  {fineText("販売中", fineShelf(evaluation.onSaleConditions))}
                </span>
                <span className={styles.sold}>
                  {fineText("売却済み", fineShelf(evaluation.soldOutConditions))}
                </span>
              </>
            )}
          </dd>
        </div>
        <div className={styles.fact}>
          <dt>評価</dt>
          <dd>
            {ratings === null
              ? MISSING
              : `良い ${ratings.good.toLocaleString("ja-JP")}・普通 ${ratings.normal.toLocaleString("ja-JP")}・悪い ${ratings.bad.toLocaleString("ja-JP")}`}
          </dd>
        </div>
      </dl>

      <div className={styles.actions}>
        <SellerListButtons sellerId={candidate.sellerId} sellerLabel={label} />
        {evaluation && (
          <p className={styles.taken}>
            {toDateTimeString(lookedAt(evaluation))} 時点
          </p>
        )}
      </div>
    </li>
  );
}

export function SellerCandidates({ items }: { items: readonly Item[] }) {
  const { evaluations, run, evaluate, stopEvaluating } = useSellerDiscovery();
  const [sort, setSort] = useState<CandidateSort>("found");

  const candidates = useMemo(() => sellerCandidates(items), [items]);
  const shown = useMemo(
    () => sortCandidates(candidates, sort, evaluations),
    [candidates, sort, evaluations],
  );

  // Asked about in the order they were found, whatever the list is sorted by:
  // sorting is a way of reading, and should not change what gets fetched next.
  const owed = candidates
    .filter((candidate) => isOwedALook(evaluations.get(candidate.sellerId)))
    .map((candidate) => candidate.sellerId);

  const ended = run.endedBy ? RUN_ENDED[run.endedBy.kind] : null;

  if (candidates.length === 0) {
    return <p className={styles.empty}>この結果に出品者はいません</p>;
  }

  return (
    <section aria-label="出品者">
      <div className={styles.head}>
        <p className={styles.tally}>
          この結果に出品していたのは <b>{people(candidates.length)}</b>
        </p>

        <label className={styles.sort}>
          <span className={styles.sortLabel}>並び順</span>
          <select
            value={sort}
            onChange={(event) => setSort(event.target.value as CandidateSort)}
          >
            {CANDIDATE_SORT_ORDER.map((key) => (
              <option key={key} value={key}>
                {CANDIDATE_SORT_LABELS[key]}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className={styles.look}>
        {run.active ? (
          <>
            {/* A count against a known total, unlike a search in progress:
                the number of sellers was fixed when the button was pressed. */}
            <p className={styles.progress} role="status">
              出品者を調べています {run.finished.toLocaleString("ja-JP")} /{" "}
              {people(run.total)}
            </p>
            <button type="button" className={styles.quiet} onClick={stopEvaluating}>
              止める
            </button>
          </>
        ) : owed.length > 0 ? (
          <>
            <button type="button" onClick={() => evaluate(owed)}>
              まだ調べていない{people(owed.length)}を調べる
            </button>
            <p className={styles.cost}>
              Mercariへ
              {(owed.length * REQUESTS_PER_EVALUATION).toLocaleString("ja-JP")}
              回問い合わせます（目安 {durationHint(evaluationSeconds(owed.length))}以上）
            </p>
          </>
        ) : (
          <p className={styles.cost}>調べられる出品者は全員調べました</p>
        )}
      </div>

      {!run.active && run.endedBy && ended && (
        <FailureNotice
          message={ended.message}
          retryLabel="続きを調べる"
          retryable={ended.retryable}
          reachedMarketplace={run.endedBy.reachedMarketplace}
          retryAllowedAt={run.endedBy.retryAllowedAt}
          onRetry={() => evaluate(owed)}
        />
      )}

      <SellerCandidateList
        candidates={shown}
        evaluations={evaluations}
      />

      <SellerCandidateLimits />
    </section>
  );
}

/** The rows, as one list. */
export function SellerCandidateList({
  candidates,
  evaluations,
}: {
  candidates: readonly SellerCandidate[];
  evaluations: ReadonlyMap<string, EvaluationRecord>;
}) {
  return (
    <ul className={styles.list}>
      {candidates.map((candidate) => (
        <SellerCandidateRow
          key={candidate.sellerId}
          candidate={candidate}
          record={evaluations.get(candidate.sellerId)}
        />
      ))}
    </ul>
  );
}

/**
 * What the figures in a row do not say (出品者探索 §5.6).
 *
 * Printed once under a list rather than on each row. Written once here so the
 * two screens that show these rows cannot come to describe them differently.
 */
export function SellerCandidateLimits() {
  return (
    <div className={styles.limits}>
      <p>
        「一致した出品」と「一致した出品の状態」は、この検索で取得した出品についてのものです。
        出品者の出品全体の状態ではありません。
        商品の状態は出品者が選んだ区分であり、実物を確認したものではありません。
      </p>
      <p>
        「カードの割合」は、販売中と売却済みそれぞれ最初の1ページのTitleから数えています。
        Titleにカードの語（ポケカ、トレカ、遊戯王など）が無い出品は、カードでも数えないので、実際より低めに出ます。
      </p>
      <p>
        「美品の出品」は、状態が「目立った傷や汚れなし」以上の出品の件数です。
        販売中と売却済みそれぞれ最初の1ページ（最大120件）から数えており、カード以外の出品も含みます。
        状態が不明の出品は数えません。「全○件」は、Mercariが返したその出品者の出品の総数です。
      </p>
      <p>
        閾値は仮説であり、精度を実証した値ではありません。
        購入判断ではなく、確認順を決める補助情報です。
      </p>
    </div>
  );
}
