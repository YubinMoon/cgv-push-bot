import { expect, test } from "@playwright/test";

test("login, review dashboard, and logout", async ({ page }) => {
  let subscriptionPresent = true;
  const subscription = {
    id: "1",
    user_id: "100",
    guild_id: "200",
    channel_id: "300",
    user_name: "민수",
    guild_name: "테스트 서버",
    channel_name: "알림",
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
  const notification = {
    id: "1",
    subscription_id: "1",
    status: "failed",
    attempts: 1,
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
    channel_name: "알림",
    theater_name: "강남",
    show_date: "2026-09-18",
    keyword: null,
  };
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    if (request.url().endsWith("/auth/session"))
      return route.fulfill({ status: 401, body: "{}" });
    if (request.url().endsWith("/auth/login"))
      return route.fulfill({ json: { csrf_token: "e2e-token" } });
    if (request.url().endsWith("/overview"))
      return route.fulfill({
        json: {
          bot_connected: true,
          active_subscriptions: 1,
          expired_subscriptions: 0,
          poll_errors: 0,
          pending_notifications: 0,
          sent_notifications: 1,
          failed_notifications: 0,
        },
      });
    if (
      request.method() === "DELETE" &&
      request.url().endsWith("/subscriptions/1")
    ) {
      subscriptionPresent = false;
      return route.fulfill({ status: 204 });
    }
    if (
      request.method() === "POST" &&
      request.url().endsWith("/notifications/1/retry")
    )
      return route.fulfill({ status: 204 });
    if (request.url().endsWith("/subscriptions/1"))
      return route.fulfill({
        json: { ...subscription, movies: ["듄"], notifications: [] },
      });
    if (request.url().includes("/subscriptions"))
      return route.fulfill({
        json: {
          items: subscriptionPresent ? [subscription] : [],
          total: subscriptionPresent ? 1 : 0,
          page: 1,
          page_size: 25,
        },
      });
    if (request.url().endsWith("/notifications/1"))
      return route.fulfill({ json: notification });
    if (request.url().includes("/notifications"))
      return route.fulfill({
        json: { items: [notification], total: 1, page: 1, page_size: 25 },
      });
    return route.fulfill({ status: 204 });
  });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "관리 대시보드" }),
  ).toBeVisible();
  await page.getByLabel("비밀번호").fill("secret");
  await page.getByRole("button", { name: "로그인" }).click();
  await expect(page.getByText("구독과 발송 현황을 한눈에.")).toBeVisible();
  await page.getByRole("button", { name: "구독", exact: true }).click();
  await page.getByText("강남").click();
  const subscriptionDialog = page.getByRole("dialog", { name: "구독 상세" });
  await subscriptionDialog.getByRole("button", { name: "삭제" }).click();
  const deleteDialog = page.getByRole("dialog", { name: "구독을 삭제할까요?" });
  await deleteDialog.getByRole("button", { name: "삭제하기" }).click();
  await page
    .getByRole("button", { name: "알림 내역", exact: true })
    .click();
  await page.getByText("듄").click();
  const notificationDialog = page.getByRole("dialog", { name: "알림 상세" });
  await notificationDialog.getByRole("button", { name: "재시도" }).click();
  const retryDialog = page.getByRole("dialog", {
    name: "알림을 다시 시도할까요?",
  });
  await retryDialog.getByRole("button", { name: "재시도 접수" }).click();
  await page.getByRole("button", { name: "로그아웃" }).click();
  await expect(
    page.getByRole("heading", { name: "관리 대시보드" }),
  ).toBeVisible();
});
