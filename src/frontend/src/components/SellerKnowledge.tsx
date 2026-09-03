/**
 * Seller Knowledge (MVP specification section 7.7).
 *
 * A hypothesis, shown with the counts it came from. The counts are not detail
 * to be tucked away: `分析対象 3件 / 専門性 高` and `分析対象 300件 / 専門性 高`
 * are the same band and very different claims, and only the count separates
 * them. Section 7.6 fixes the thresholds as working figures, so nothing here
 * presents the band as a measured accuracy.
 *
 * The raw score is deliberately absent. It is the sum of the specification's
 * own weights, and printing it would read as a measurement.
 */

import { SELLER_ITEM_LIMIT } from "../collectionRange";
import type { KnowledgeLevel, SellerItems, SellerKnowledge } from "../types/api";

import styles from "./SellerKnowledge.module.css";

const LEVELS: Record<KnowledgeLevel, string> = {
  unknown: "判定不能",
  low: "低",
  medium: "中",
  high: "高",
};

const count = (value: number) => `${value.toLocaleString("ja-JP")}件`;
const percent = (ratio: number) => `${(ratio * 100).toFixed(1)}%`;

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className={styles.fact}>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

/**
 * Which statuses stopped short of the end.
 *
 * Named individually rather than as "some". The two are collected separately
 * and stop for their own reasons, and "販売中は上限100件で打ち切っています" tells
 * the reader which half of the sample is the incomplete one.
 */
function truncatedStatuses(onSale: SellerItems, soldOut: SellerItems): string[] {
  return [
    onSale.meta.reachedEnd ? null : "販売中",
    soldOut.meta.reachedEnd ? null : "売却済み",
  ].filter((label): label is string => label !== null);
}

export function SellerKnowledgePanel({
  knowledge,
  onSale,
  soldOut,
}: {
  knowledge: SellerKnowledge;
  /** Both statuses, for the range note. The counts came from these two. */
  onSale: SellerItems;
  soldOut: SellerItems;
}) {
  const analyzed = knowledge.analyzedItemCount;
  const truncated = truncatedStatuses(onSale, soldOut);

  /**
   * A ratio of nothing is not zero.
   *
   * The backend reports `0.0` when nothing was analysed because a float has no
   * way to say "undefined", and `ポケカ関連 0件 / 0.0%` would read as a seller
   * who lists no Pokémon cards rather than as a seller nobody could analyse.
   */
  const share = (items: number, ratio: number) =>
    analyzed === 0 ? count(items) : `${count(items)} / ${percent(ratio)}`;

  return (
    <section className={styles.knowledge} aria-label="Seller Knowledge">
      <h2 className={styles.heading}>
        Seller Knowledge<span className={styles.scope}>（取得範囲内）</span>
      </h2>

      <dl className={styles.facts}>
        <Fact label="分析対象" value={count(analyzed)} />
        <Fact
          label="ポケカ関連"
          value={share(knowledge.pokemonItemCount, knowledge.pokemonRatio)}
        />
        <Fact
          label="TCG関連"
          value={share(knowledge.tcgItemCount, knowledge.tcgRatio)}
        />
        <Fact
          label="専門用語あり"
          value={share(
            knowledge.specializedItemCount,
            knowledge.specializedItemRatio,
          )}
        />
        <Fact
          label="異なる専門用語"
          value={`${knowledge.distinctSpecializedTermCount.toLocaleString(
            "ja-JP",
          )}種類`}
        />
      </dl>

      {/* Read separately from each other: 専門性 高 / 標本信頼度 低 is a valid
          result, and folding them into one word would hide which of the two a
          reader should distrust. */}
      <dl className={styles.bands}>
        <div className={styles.band}>
          <dt>専門性</dt>
          <dd>{LEVELS[knowledge.level]}</dd>
        </div>
        <div className={styles.band}>
          <dt>標本信頼度</dt>
          <dd>{LEVELS[knowledge.sampleConfidence]}</dd>
        </div>
      </dl>

      {/* 視覚方針 §3.3 puts section 7.7's notes behind the 朱 rule: this is
          Card Digger writing in its own limits beside Mercari's data. */}
      <div className={styles.limits}>
        <p>
          Seller Knowledgeは取得した{count(analyzed)}を対象に計算しています。
        </p>
        {truncated.length > 0 && (
          <p>
            {truncated.join("と")}は上限{SELLER_ITEM_LIMIT}
            件で打ち切っています。
          </p>
        )}
        <p>
          閾値はMVPの仮説であり、精度を実証した値ではありません。
          購入判断ではなく、確認順を決める補助情報です。
        </p>
      </div>
    </section>
  );
}
