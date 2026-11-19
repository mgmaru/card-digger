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
  REQUESTS_PER_EVALUATION,
  evaluationSeconds,
  isOwedALook,
  sellerCandidates,
  sortCandidates,
  type CandidateSort,
  type EvaluationRecord,
  type SellerCandidate,
} from "../sellerCandidates";
import { useSellerDiscovery } from "../sellerDiscoveryState";
import type { BreadthLevel, Item, SellerEvaluationResponse } from "../types/api";

import { FailureNotice } from "./FailureNotice";
import styles from "./SellerCandidates.module.css";
import { SellerListButtons } from "./SellerListButtons";

const BREADTH_LABELS: Record<BreadthLevel, string> = {
  unknown: "判定不能",
  narrow: "狭い",
  mixed: "中",
  wide: "広い",
};

const MISSING = "-";

const people = (value: number) => `${value.toLocaleString("ja-JP")}人`;
const count = (value: number) => `${value.toLocaleString("ja-JP")}件`;
const percent = (ratio: number) => `${(ratio * 100).toFixed(1)}%`;

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

function Row({
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
  const breadth = evaluation?.breadth ?? null;

  return (
    <li className={styles.row}>
      <div className={styles.who}>
        <h3 className={styles.name}>
          <Link to={`/sellers/${candidate.sellerId}`}>{label}</Link>
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
      </div>

      <dl className={styles.facts}>
        <div className={styles.fact}>
          <dt>一致した出品</dt>
          <dd>{count(candidate.hits.length)}</dd>
        </div>
        <div className={styles.fact}>
          <dt>商品の状態</dt>
          <dd>{conditionSummary(candidate) || MISSING}</dd>
        </div>
        <div className={styles.fact}>
          <dt>出品の幅</dt>
          <dd>
            {breadth === null ? (
              <span className={styles.pending}>
                {record && record.status !== "done"
                  ? WAITING[record.status]
                  : NOT_LOOKED_AT}
              </span>
            ) : (
              <>
                <span className={styles.band}>{BREADTH_LABELS[breadth.level]}</span>
                {/* The counts are not detail. 広い over three listings and
                    over sixty are the same band and different claims. */}
                {breadth.analyzedItemCount > 0 && (
                  <span className={styles.basis}>
                    TCG以外 {count(breadth.otherItemCount)} /{" "}
                    {count(breadth.analyzedItemCount)}（
                    {percent(breadth.otherRatio)}）
                  </span>
                )}
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

      <ul className={styles.list}>
        {shown.map((candidate) => (
          <Row
            key={candidate.sellerId}
            candidate={candidate}
            record={evaluations.get(candidate.sellerId)}
          />
        ))}
      </ul>

      <div className={styles.limits}>
        <p>
          「一致した出品」と「商品の状態」は、この検索で取得した範囲の出品だけを数えています。
          商品の状態は出品者が選んだ区分であり、実物を確認したものではありません。
        </p>
        <p>
          「出品の幅」は、販売中と売却済みそれぞれ最初の1ページのTitleから計算しています。
          TCG以外の出品が多いほど広いと表示します。
        </p>
        <p>
          閾値は仮説であり、精度を実証した値ではありません。
          購入判断ではなく、確認順を決める補助情報です。
        </p>
      </div>
    </section>
  );
}
