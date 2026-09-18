import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "./App";

const overview = {
  bot_connected: true,
  active_subscriptions: 2,
  expired_subscriptions: 1,
  poll_errors: 0,
  pending_notifications: 1,
  sent_notifications: 8,
  failed_notifications: 0,
};
function response(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(status === 204 ? null : JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

describe("dashboard", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string) => {
        if (input.endsWith("/auth/session")) return response({}, 401);
        if (input.endsWith("/auth/login"))
          return response({ csrf_token: "test-token" });
        if (input.endsWith("/overview")) return response(overview);
        if (input.endsWith("/subscriptions"))
          return response({ items: [], total: 0, page: 1, page_size: 25 });
        if (input.endsWith("/notifications"))
          return response({ items: [], total: 0, page: 1, page_size: 25 });
        return response({}, 204);
      }),
    );
  });
  it("requires the password before showing dashboard data", async () => {
    render(<App />);
    expect(
      await screen.findByRole("heading", { name: "관리 대시보드" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("구독과 발송 현황을 한눈에."),
    ).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("비밀번호"), {
      target: { value: "secret" },
    });
    fireEvent.click(screen.getByRole("button", { name: "로그인" }));
    expect(
      await screen.findByText("구독과 발송 현황을 한눈에."),
    ).toBeInTheDocument();
    expect(screen.getByText("활성 구독")).toBeInTheDocument();
  });
  it("shows a failed notification retry confirmation", async () => {
    const notification = {
      id: "n-1",
      subscription_id: "s-1",
      status: "failed",
      attempts: 1,
      last_error: "timeout",
      created_at: "2024-01-01T00:00:00Z",
      sent_at: null,
      next_retry_at: null,
      movie_titles: ["듄"],
      user_id: "u-1",
      user_name: "민수",
      guild_id: "g-1",
      guild_name: "서버",
      channel_id: "c-1",
      channel_name: "알림",
      theater_name: "강남",
      show_date: "2024-01-01",
      keyword: null,
    };
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string) => {
        if (input.endsWith("/auth/session")) return response({}, 401);
        if (input.endsWith("/auth/login"))
          return response({ csrf_token: "test-token" });
        if (input.endsWith("/overview")) return response(overview);
        if (input.includes("/notifications?"))
          return response({
            items: [notification],
            total: 1,
            page: 1,
            page_size: 25,
          });
        if (input.endsWith("/notifications/n-1")) return response(notification);
        return response({}, 204);
      }),
    );
    render(<App />);
    fireEvent.change(await screen.findByLabelText("비밀번호"), {
      target: { value: "secret" },
    });
    fireEvent.click(screen.getByRole("button", { name: "로그인" }));
    fireEvent.click(await screen.findByRole("button", { name: "알림 내역" }));
    expect(await screen.findByText("듄")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "재시도" }));
    await waitFor(() =>
      expect(screen.getByText("알림을 다시 시도할까요?")).toBeInTheDocument(),
    );
    expect(screen.getByText(/발견 시각과 기존 시도 횟수/)).toBeInTheDocument();
  });

  it("explains when the login server cannot be reached", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string) => {
        if (input.endsWith("/auth/session")) return response({}, 401);
        if (input.endsWith("/auth/login"))
          return Promise.reject(new TypeError("Failed to fetch"));
        return response({}, 204);
      }),
    );
    render(<App />);
    fireEvent.change(await screen.findByLabelText("비밀번호"), {
      target: { value: "secret" },
    });
    fireEvent.click(screen.getByRole("button", { name: "로그인" }));
    expect(
      await screen.findByText(
        "서버에 연결할 수 없습니다. 잠시 후 다시 시도하세요.",
      ),
    ).toBeInTheDocument();
  });

  it("keeps the dashboard open when logout cannot reach the server", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string) => {
        if (input.endsWith("/auth/session")) return response({}, 401);
        if (input.endsWith("/auth/login"))
          return response({ csrf_token: "test-token" });
        if (input.endsWith("/overview")) return response(overview);
        if (input.endsWith("/auth/logout"))
          return Promise.reject(new TypeError("Failed to fetch"));
        return response({ items: [], total: 0, page: 1, page_size: 25 });
      }),
    );
    render(<App />);
    fireEvent.change(await screen.findByLabelText("비밀번호"), {
      target: { value: "secret" },
    });
    fireEvent.click(screen.getByRole("button", { name: "로그인" }));
    expect(
      await screen.findByText("구독과 발송 현황을 한눈에."),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "로그아웃" }));
    expect(
      await screen.findByText(
        "로그아웃하지 못했습니다. 네트워크 상태를 확인하세요.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "로그아웃" }),
    ).toBeInTheDocument();
  });

  it("returns to the login form after a successful logout", async () => {
    let logoutCalls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string) => {
        if (input.endsWith("/auth/session")) return response({}, 401);
        if (input.endsWith("/auth/login"))
          return response({ csrf_token: "test-token" });
        if (input.endsWith("/auth/logout")) {
          logoutCalls += 1;
          return response({}, 204);
        }
        if (input.endsWith("/overview")) return response(overview);
        return response({ items: [], total: 0, page: 1, page_size: 25 });
      }),
    );
    render(<App />);
    fireEvent.change(await screen.findByLabelText("비밀번호"), {
      target: { value: "secret" },
    });
    fireEvent.click(screen.getByRole("button", { name: "로그인" }));
    expect(
      await screen.findByText("구독과 발송 현황을 한눈에."),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "로그아웃" }));

    expect(await screen.findByLabelText("비밀번호")).toBeInTheDocument();
    expect(logoutCalls).toBe(1);
  });

  it("returns to login when an authenticated request expires", async () => {
    let loggedIn = false;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string) => {
        if (input.endsWith("/auth/session")) return response({}, 401);
        if (input.endsWith("/auth/login")) {
          loggedIn = true;
          return response({ csrf_token: "test-token" });
        }
        if (loggedIn && input.endsWith("/overview")) return response({}, 401);
        return response({ items: [], total: 0, page: 1, page_size: 25 });
      }),
    );
    render(<App />);
    fireEvent.change(await screen.findByLabelText("비밀번호"), {
      target: { value: "secret" },
    });
    fireEvent.click(screen.getByRole("button", { name: "로그인" }));
    await waitFor(() =>
      expect(screen.getByLabelText("비밀번호")).toBeInTheDocument(),
    );
  });
});
