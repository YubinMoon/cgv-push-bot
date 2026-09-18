import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import * as api from "./api";
import { SubscriptionsPage } from "./SubscriptionsPage";
import type { Paginated, Subscription } from "./types";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function subscription(id: string): Subscription {
  return {
    id,
    user_id: "100",
    guild_id: "200",
    channel_id: "300",
    user_name: `사용자 ${id}`,
    guild_name: "테스트 서버",
    channel_name: "알림 채널",
    theater_id: "400",
    theater_name: "강남",
    show_date: "2026-09-18",
    keyword: null,
    status: "active",
    created_at: "2026-09-18T00:00:00Z",
    expires_at: null,
    last_success_at: null,
    last_error: null,
    pending_count: 0,
    failed_count: 0,
  };
}

function page(items: Subscription[]): Paginated<Subscription> {
  return { items, total: items.length, page: 1, page_size: 25 };
}

describe("SubscriptionsPage", () => {
  afterEach(() => vi.restoreAllMocks());

  it("keeps the newest filter response when requests finish out of order", async () => {
    const first = deferred<Paginated<Subscription>>();
    const second = deferred<Paginated<Subscription>>();
    const getSubscriptions = vi
      .spyOn(api, "getSubscriptions")
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);

    render(<SubscriptionsPage setNotice={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("상태 필터"), {
      target: { value: "active" },
    });
    await waitFor(() => expect(getSubscriptions).toHaveBeenCalledTimes(2));

    second.resolve(page([subscription("new")]));
    expect(await screen.findByText("사용자 new")).toBeInTheDocument();
    first.resolve(page([subscription("old")]));

    await waitFor(() =>
      expect(screen.queryByText("사용자 old")).not.toBeInTheDocument(),
    );
    expect(screen.getByText("사용자 new")).toBeInTheDocument();
  });
});
