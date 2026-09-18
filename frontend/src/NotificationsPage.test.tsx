import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import * as api from "./api";
import { NotificationsPage } from "./NotificationsPage";
import type { Notification, Paginated } from "./types";

const notification: Notification = {
  id: "1",
  subscription_id: "2",
  status: "failed",
  attempts: 8,
  last_error: "timeout",
  created_at: "2026-09-18T00:00:00Z",
  sent_at: null,
  next_retry_at: null,
  movie_titles: ["듄"],
  user_id: "100",
  user_name: "민수",
  guild_id: "200",
  guild_name: "테스트 서버",
  channel_id: "300",
  channel_name: "알림 채널",
  theater_name: "강남",
  show_date: "2026-09-18",
  keyword: null,
};

function page(items: Notification[]): Paginated<Notification> {
  return { items, total: items.length, page: 1, page_size: 25 };
}

describe("NotificationsPage", () => {
  afterEach(() => vi.restoreAllMocks());

  it("closes detail and confirmation after a successful retry and reloads", async () => {
    const getNotifications = vi
      .spyOn(api, "getNotifications")
      .mockResolvedValueOnce(page([notification]))
      .mockResolvedValue(page([]));
    const retryNotification = vi
      .spyOn(api, "retryNotification")
      .mockResolvedValue(undefined);
    const setNotice = vi.fn();

    render(<NotificationsPage setNotice={setNotice} />);
    fireEvent.click(await screen.findByText("듄"));
    const detail = screen.getByRole("dialog", { name: "알림 상세" });
    fireEvent.click(within(detail).getByRole("button", { name: "재시도" }));

    const confirmation = await screen.findByRole("dialog", {
      name: "알림을 다시 시도할까요?",
    });
    fireEvent.click(
      within(confirmation).getByRole("button", { name: "재시도 접수" }),
    );

    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(retryNotification).toHaveBeenCalledWith("1");
    expect(getNotifications).toHaveBeenCalledTimes(2);
    expect(setNotice).toHaveBeenCalledWith("재시도를 접수했습니다.");
    expect(await screen.findByText("알림 내역이 없습니다.")).toBeInTheDocument();
  });
});
