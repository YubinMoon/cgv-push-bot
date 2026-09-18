import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import * as api from "./api";
import { OverviewPage } from "./OverviewPage";

const overview = {
  bot_connected: true,
  active_subscriptions: 3,
  expired_subscriptions: 1,
  poll_errors: 0,
  pending_notifications: 1,
  sent_notifications: 5,
  failed_notifications: 0,
};

describe("OverviewPage", () => {
  afterEach(() => vi.restoreAllMocks());

  it("recovers after retrying a failed load", async () => {
    const getOverview = vi
      .spyOn(api, "getOverview")
      .mockRejectedValueOnce(new Error("temporarily unavailable"))
      .mockResolvedValue(overview);

    render(<OverviewPage onNavigate={vi.fn()} />);

    expect(await screen.findByText("temporarily unavailable")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "다시 시도" }));

    await waitFor(() =>
      expect(screen.getByText("구독과 발송 현황을 한눈에.")).toBeInTheDocument(),
    );
    expect(screen.getByText("활성 구독")).toBeInTheDocument();
    expect(getOverview).toHaveBeenCalledTimes(2);
  });
});
