/**
 * The wait after a safety stop (MVP specification section 9).
 *
 * The assertion that matters is the button: it is absent while the backend is
 * still refusing and present once the wait it named has passed. A test that
 * only read the text would pass while offering a button that could not work.
 *
 * Time is moved by the test rather than waited for. Sixty seconds of real
 * waiting per case is exactly the reason the backend takes a clock as an
 * argument, and the same reasoning applies on this side.
 */

import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act } from "react";

import { FailureNotice } from "../src/components/FailureNotice";

const STOPPED = "続けて拒否されたため取得を止めました";

function notice(
  waitSeconds: number | null,
  { retryable = false, reachedMarketplace = null as boolean | null } = {},
) {
  return render(
    <FailureNotice
      message={STOPPED}
      retryLabel="検索をやり直す"
      retryable={retryable}
      reachedMarketplace={reachedMarketplace}
      retryAllowedAt={waitSeconds === null ? null : Date.now() + waitSeconds * 1000}
      onRetry={() => {}}
    />,
  );
}

function pass(seconds: number) {
  act(() => {
    vi.advanceTimersByTime(seconds * 1000);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("a failure with a wait attached", () => {
  it("says how long is left", () => {
    notice(60);

    expect(screen.getByText(/あと約60秒で再試行できます/)).toBeInTheDocument();
  });

  it("offers nothing to press while the backend is still refusing", () => {
    notice(60);

    expect(screen.queryByRole("button")).toBeNull();
  });

  it("counts down as the time passes", () => {
    notice(60);

    pass(20);

    expect(screen.getByText(/あと約40秒で再試行できます/)).toBeInTheDocument();
  });

  it("offers the button once the wait is over", () => {
    notice(60);

    pass(60);

    expect(screen.queryByText(/あと約/)).toBeNull();
    expect(screen.getByRole("button", { name: "検索をやり直す" })).toBeInTheDocument();
  });

  it("keeps saying what happened while it waits", () => {
    notice(60);

    expect(screen.getByRole("alert")).toHaveTextContent(STOPPED);
  });

  it("does not re-announce the failure every second", () => {
    // The countdown sits inside a `role="alert"`, so without this a screen
    // reader would read the whole sentence sixty times over.
    notice(60);

    expect(screen.getByText(/あと約60秒で再試行できます/)).toHaveAttribute(
      "aria-live",
      "off",
    );
  });
});

describe("a later response about the same stop", () => {
  it("takes the new moment rather than keeping the old one", () => {
    // Pressing during the wait produces a fresh failure carrying what is
    // left. Keeping the first moment would show the countdown the reader
    // started with, however long they had actually waited.
    const shown = (allowedAt: number) => (
      <FailureNotice
        message={STOPPED}
        retryLabel="検索をやり直す"
        retryable={false}
        reachedMarketplace={false}
        retryAllowedAt={allowedAt}
        onRetry={() => {}}
      />
    );

    const { rerender } = render(shown(Date.now() + 60_000));
    expect(screen.getByText(/あと約60秒/)).toBeInTheDocument();

    rerender(shown(Date.now() + 10_000));

    expect(screen.getByText(/あと約10秒/)).toBeInTheDocument();
  });
});

describe("leaving the screen and coming back", () => {
  it("does not start the wait over", () => {
    // The reader may open a seller, or go back and forward. The component
    // mounts again; the moment the backend named has not moved.
    const allowedAt = Date.now() + 60_000;
    const shown = () =>
      render(
        <FailureNotice
          message={STOPPED}
          retryLabel="検索をやり直す"
          retryable={false}
          reachedMarketplace={false}
          retryAllowedAt={allowedAt}
          onRetry={() => {}}
        />,
      );

    const first = shown();
    pass(40);
    first.unmount();
    shown();

    expect(screen.getByText(/あと約20秒で再試行できます/)).toBeInTheDocument();
  });

  it("comes back to a button when the wait went by while away", () => {
    const allowedAt = Date.now() + 60_000;
    const shown = () =>
      render(
        <FailureNotice
          message={STOPPED}
          retryLabel="検索をやり直す"
          retryable={false}
          reachedMarketplace={false}
          retryAllowedAt={allowedAt}
          onRetry={() => {}}
        />,
      );

    const first = shown();
    pass(90);
    first.unmount();
    shown();

    expect(screen.queryByText(/あと約/)).toBeNull();
    expect(screen.getByRole("button", { name: "検索をやり直す" })).toBeInTheDocument();
  });
});

describe("whether Mercari was reached", () => {
  it("says so when the backend answered without asking", () => {
    // The point of saying it: while the stop holds, pressing the button does
    // not put a request on Mercari, and the reader cannot see that otherwise.
    notice(60, { reachedMarketplace: false });

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Mercariへは問い合わせていません",
    );
  });

  it("stays quiet when the request did reach Mercari", () => {
    // The refusal that started the stop did go out. Saying otherwise would be
    // a claim about Mercari that is simply false.
    notice(60, { reachedMarketplace: true });

    expect(screen.getByRole("alert")).not.toHaveTextContent("問い合わせていません");
  });

  it("stays quiet when the body did not say", () => {
    notice(60, { reachedMarketplace: null });

    expect(screen.getByRole("alert")).not.toHaveTextContent("問い合わせていません");
  });
});

describe("a failure with no wait attached", () => {
  it("offers the button when trying again is the next move", () => {
    notice(null, { retryable: true });

    expect(screen.getByRole("button", { name: "検索をやり直す" })).toBeInTheDocument();
  });

  it("offers nothing when it is not", () => {
    // A safety stop whose header did not arrive lands here. Asking for time
    // without a number is still true; a button that would be refused is not.
    notice(null, { retryable: false });

    expect(screen.queryByRole("button")).toBeNull();
  });
});
