/**
 * The image grid, and the one legend the cards below it need.
 *
 * Column count is not fixed anywhere: the grid fills with tracks no narrower
 * than `--grid-min`, because what matters is whether a bulk-lot photograph is
 * still large enough to judge, not how many fit
 * ([視覚方針 §3.7](../../../../docs/product/design-tokens.md#37-grid列数と角丸)).
 *
 * The notes here are stated once rather than on every card. Repeated forty
 * times they would stop being read, which is the opposite of what section 2.3
 * of the visual direction asks for.
 *
 * Which timestamp is which is **not** repeated here either: the collection
 * record already carries section 6.3's sentence about it, in full, above the
 * filters. Saying it twice on one screen would not make it twice as visible.
 * Each card still attaches it to the value itself.
 */

import { DORMANCY_AXIS_DAYS } from "../elapsed";
import type { Item } from "../types/api";

import { ItemCard } from "./ItemCard";
import styles from "./ItemGrid.module.css";

export function ItemGrid({
  items,
  collectedAt,
}: {
  items: readonly Item[];
  collectedAt: string;
}) {
  // Section 5.6 says the latest auction price is on Mercari, not here. Worth
  // saying only when the reader is actually looking at one.
  const hasProvisionalPrice = items.some(
    (item) => item.saleFormat !== "fixed_price",
  );

  return (
    <>
      <div className={styles.legend}>
        <p className={styles.scale}>
          <span>更新されたばかり</span>
          <span>{DORMANCY_AXIS_DAYS}日以上 触られていない</span>
        </p>
        <p className={styles.note}>
          各Cardの下の線は、最後に更新されてから経った期間です。
        </p>
        {hasProvisionalPrice && (
          <p className={styles.note}>
            オークションと形式不明の価格は取得時点のものです。確定した落札額ではありません。
            最新の価格はMercariで確認してください。
          </p>
        )}
      </div>

      <div className={styles.grid}>
        {items.map((item) => (
          <ItemCard key={item.id} item={item} collectedAt={collectedAt} />
        ))}
      </div>
    </>
  );
}
