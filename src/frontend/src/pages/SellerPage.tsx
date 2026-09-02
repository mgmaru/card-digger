/**
 * The seller screen.
 *
 * Scaffolding. The profile, the two status tabs and the seller knowledge are
 * Phase 1-3 and 1-4. What is here is the part 1-0 needs: a route with a URL,
 * so that a browser reload re-collects (section 6.1) and going back returns
 * to a search that is still there.
 */

import { Link, useParams } from "react-router";

export function SellerPage() {
  const { sellerId } = useParams<{ sellerId: string }>();

  return (
    <section>
      <h2>Seller {sellerId}</h2>
      <Link to="/">検索へ戻る</Link>
    </section>
  );
}
