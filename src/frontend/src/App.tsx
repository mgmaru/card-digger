import { BrowserRouter, NavLink, Route, Routes } from "react-router";

import styles from "./App.module.css";
import { SearchPage } from "./pages/SearchPage";
import { SellerListsPage } from "./pages/SellerListsPage";
import { SellerPage } from "./pages/SellerPage";
import { SearchProvider } from "./searchState";
import {
  SellerDiscoveryProvider,
  useSellerDiscovery,
} from "./sellerDiscoveryState";

/**
 * The application shell.
 *
 * Both providers sit **above** the router. That placement is the whole point:
 * the search result, its sort and filter, the reader's seller lists and the
 * sellers already looked at all outlive a navigation, so coming back from a
 * seller shows what was already collected instead of collecting again
 * (MVP specification section 5.2).
 */
export function App() {
  return (
    <SearchProvider>
      <SellerDiscoveryProvider>
        <BrowserRouter>
          <AppRoutes />
        </BrowserRouter>
      </SellerDiscoveryProvider>
    </SearchProvider>
  );
}

/**
 * The two places to start from.
 *
 * A seller is reached from one of these and is not a third: nobody arrives
 * wanting "a seller", they arrive from a listing or from a list.
 */
function Navigation() {
  const { entries } = useSellerDiscovery();
  const link = ({ isActive }: { isActive: boolean }) =>
    `${styles.link} ${isActive ? styles.current : ""}`;

  return (
    <nav className={styles.nav} aria-label="画面">
      <NavLink to="/" end className={link}>
        検索
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
        <Route path="/seller-lists" element={<SellerListsPage />} />
      </Routes>
    </main>
  );
}
