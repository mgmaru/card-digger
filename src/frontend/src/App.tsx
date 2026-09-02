import { BrowserRouter, Route, Routes } from "react-router";

import styles from "./App.module.css";
import { SearchPage } from "./pages/SearchPage";
import { SellerPage } from "./pages/SellerPage";
import { SearchProvider } from "./searchState";

/**
 * The application shell.
 *
 * `SearchProvider` sits **above** the router. That placement is the whole
 * point: the search result and its sort and filter outlive a navigation, so
 * coming back from a seller shows what was already collected instead of
 * collecting again (MVP specification section 5.2).
 */
export function App() {
  return (
    <SearchProvider>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </SearchProvider>
  );
}

/**
 * Everything inside the router.
 *
 * Separate from `App` so a test can mount it under `MemoryRouter` while
 * keeping the provider where it really is: outside. A test that put the
 * provider inside would pass while the shipped arrangement lost its state on
 * every navigation.
 */
export function AppRoutes() {
  return (
    <main className={styles.shell}>
      <h1>Card Digger</h1>
      <Routes>
        <Route path="/" element={<SearchPage />} />
        <Route path="/sellers/:sellerId" element={<SellerPage />} />
      </Routes>
    </main>
  );
}
