import { BrowserRouter, NavLink, Route, Routes } from "react-router";

import styles from "./App.module.css";
import { FindSellersPage } from "./pages/FindSellersPage";
import { SearchPage } from "./pages/SearchPage";
import { SellerListsPage } from "./pages/SellerListsPage";
import { SellerPage } from "./pages/SellerPage";
import { SellerShelfPage } from "./pages/SellerShelfPage";
import { SearchProvider } from "./searchState";
import {
  SellerDiscoveryProvider,
  useSellerDiscovery,
} from "./sellerDiscoveryState";
import { SellerHuntProvider } from "./sellerHuntState";

/**
 * The application shell.
 *
 * The providers sit **above** the router. That placement is the whole point:
 * the search result, its sort and filter, the reader's seller lists, the
 * sellers already looked at and the last run of looking for them all outlive
 * a navigation, so coming back from a
 * seller shows what was already collected instead of collecting again
 * (MVP specification section 5.2).
 */
export function App() {
  return (
    <SearchProvider>
      <SellerDiscoveryProvider>
        <SellerHuntProvider>
          <BrowserRouter>
            <AppRoutes />
          </BrowserRouter>
        </SellerHuntProvider>
      </SellerDiscoveryProvider>
    </SearchProvider>
  );
}

/**
 * The three places to start from: listings, sellers, and the sellers already
 * decided about.
 *
 * One seller is reached from one of these and is not a fourth: nobody arrives
 * wanting "a seller", they arrive from a listing, a run or a list.
 */
function Navigation() {
  const { entries } = useSellerDiscovery();
  const link = ({ isActive }: { isActive: boolean }) =>
    `${styles.link} ${isActive ? styles.current : ""}`;

  return (
    <nav className={styles.nav} aria-label="画面">
      {/* 商品検索, not 検索: the screen beside it looks for sellers, and 検索
          alone no longer says which of the two it is. */}
      <NavLink to="/" end className={link}>
        商品検索
      </NavLink>
      <NavLink to="/find-sellers" className={link}>
        出品者検索
      </NavLink>
      <NavLink to="/seller-lists" className={link}>
        出品者リスト
        {entries.length > 0 && (
          <span className={styles.count}>
            {entries.length.toLocaleString("ja-JP")}
          </span>
        )}
      </NavLink>
    </nav>
  );
}

/**
 * Everything inside the router.
 *
 * Separate from `App` so a test can mount it under `MemoryRouter` while
 * keeping the providers where they really are: outside. A test that put a
 * provider inside would pass while the shipped arrangement lost its state on
 * every navigation.
 */
export function AppRoutes() {
  return (
    <main className={styles.shell}>
      <header className={styles.masthead}>
        <h1 className={styles.wordmark}>Card Digger</h1>
        <Navigation />
      </header>
      <Routes>
        <Route path="/" element={<SearchPage />} />
        <Route path="/sellers/:sellerId" element={<SellerPage />} />
        <Route path="/sellers/:sellerId/shelf" element={<SellerShelfPage />} />
        <Route path="/find-sellers" element={<FindSellersPage />} />
        <Route path="/seller-lists" element={<SellerListsPage />} />
      </Routes>
    </main>
  );
}
