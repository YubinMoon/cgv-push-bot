<p align="center">
  <img src="assets/images/cgv-push-bot-logo.png" alt="필름 릴과 돋보기 모양의 CGV PUSH BOT 로고" width="180" height="180">
</p>

<h1 align="center">CGV PUSH BOT</h1>

<p align="center">CGV 상영시간표에 새로 추가된 영화를 Discord 채널이나 DM으로 알려줍니다.</p>

알림을 받을 영화관과 상영 날짜를 선택합니다. 영화 제목 키워드를 등록하면 일치하는 영화만
알려주고, 키워드를 비워두면 선택한 날짜에 새로 편성되는 모든 영화를 알려줍니다.

등록할 때 이미 편성된 영화는 알림에서 제외합니다. 같은 영화의 회차 추가나 잔여 좌석 변경은
알리지 않습니다.

## 서버에 봇 추가하기

[**봇 초대 링크**](https://discord.com/oauth2/authorize?client_id=1244606738787991643)

1. 초대 링크를 열고 봇을 사용할 Discord 서버를 선택합니다. 서버 관리 권한이 필요합니다.
2. 봇에 **채널 보기**, **메시지 보내기**, **링크 첨부** 권한을 허용합니다.
3. 알림을 받을 텍스트 채널에서 `/alert`를 실행합니다.

봇을 추가하면 바로 사용할 수 있습니다.
초대 권한은 [Discord 공식 안내](https://docs.discord.com/developers/quick-start/getting-started)에서 확인합니다.

## 개인 DM으로 사용하기

[**봇 초대 링크**](https://discord.com/oauth2/authorize?client_id=1244606738787991643)

1. 봇 초대 링크를 열고 **내 앱에 추가(Add to my apps)**를 선택합니다.
2. 봇 프로필에서 DM을 엽니다.
3. DM에서 `/alert`를 실행하고 영화관·날짜·키워드를 등록합니다.

## 알림 사용하기

- **등록:** `/alert` → `새 알림 등록` → 영화관·날짜·키워드 선택 → 내용 확인 후 등록
- **상태 확인:** 알림 상세에서 마지막 조회 성공 시각(한국 시간), 조회 오류 여부, 전송 대기·실패 건수를 확인
- **확인·삭제:** `/alert` → `내 알림 확인` → 알림 선택 → 삭제

영화관 검색 결과가 많으면 `이전`·`다음`으로 페이지를 이동합니다.
검색·영화 조회·등록에 실패하면 화면의 재시도 버튼으로 입력 내용을 유지한 채 다시 시도할 수 있습니다.

서버에서 등록한 알림은 등록한 채널로, 봇 DM에서 등록한 알림은 개인 DM으로 전송됩니다.
기본 설정에서는 5분마다 상영시간표를 확인합니다.
알림은 상영일 다음 날 오전 6시(한국 시간)에 만료됩니다.

## 직접 실행하기

봇을 직접 실행하여 사용할 수 있습니다.

### 1. Discord 봇 준비

1. [Discord Developer Portal](https://discord.com/developers/applications)에서
   새 애플리케이션을 만듭니다.
2. `Bot` 메뉴에서 토큰을 발급받습니다.
3. `Installation`에서 `Guild Install`과 `User Install`을 모두 활성화합니다.
4. `Default Install Settings`의 `Guild Install`에는 `bot`, `applications.commands` Scope와
   `View Channels`, `Send Messages`, `Embed Links` 권한을 설정합니다.
   `User Install`에는 `applications.commands` Scope를 설정합니다.
5. `Install Link`를 `Discord Provided Link`로 설정합니다. 링크를 열어
   **서버에 추가** 또는 **내 앱에 추가**를 선택합니다.

Privileged Gateway Intents는 활성화하지 않아도 됩니다.
설정 방법은 [Discord 봇 시작 안내](https://docs.discord.com/developers/quick-start/getting-started)와
[개인 설치 앱 안내](https://docs.discord.com/developers/tutorials/developing-a-user-installable-app)에 설명되어 있습니다.
기존 봇을 업데이트하는 경우에도 Portal에서 두 설치 방식을 활성화합니다.
봇을 재시작하면 `/alert` 명령의 설치·DM 지원 설정이 자동으로 동기화됩니다.

### 2. 실행 방법 선택

아래 명령은 저장소 폴더에서 실행합니다.

#### Docker Compose

Docker와 Docker Compose가 필요합니다.
`.env.example`을 `.env`로 복사하고 `DISCORD_TOKEN`을 설정합니다.

```bash
cp .env.example .env
```

[docker-compose.yaml](docker-compose.yaml)은 같은 폴더의 `.env` 값을 읽습니다.
값이 없거나 비어 있으면 `${변수:-기본값}`의 기본값을 사용합니다.
직접 지정하려면 원하는 항목을 고정값으로 바꾸면 됩니다.

```yaml
environment:
  DISCORD_TOKEN: "${DISCORD_TOKEN:-}"
  POLL_INTERVAL_SECONDS: "120"
```

이 예시에서는 토큰은 `.env`에서 읽고, 조회 간격은 `.env` 값과 관계없이 120초로 설정합니다.
모든 항목을 직접 지정하면 `.env` 없이도 실행할 수 있습니다.
변수 참조를 유지한 항목은 셸 환경변수가 `.env`보다 우선합니다.

```bash
# 이전 movie-bot 서비스가 실행 중이면 먼저 실행
# docker compose down --remove-orphans

# 빌드 및 실행
docker compose up -d --build

# 로그 확인
docker compose logs -f cgv-push-bot

# 종료
docker compose down
```

기존 배포의 데이터를 유지하기 위해 DB 파일명은 `movie-bot.sqlite3`,
Docker 볼륨명은 `movie-bot-data`를 사용합니다.

알림 데이터는 Docker 볼륨에 저장되어 컨테이너를 다시 만들어도 유지됩니다.
`docker compose down -v`를 실행하면 데이터도 삭제됩니다.

#### Python과 uv

Python 3.12 이상과 [uv](https://docs.astral.sh/uv/)가 필요합니다.

```bash
uv sync
cp .env.example .env
```

`.env`에 `DISCORD_TOKEN`을 설정한 뒤 봇을 실행합니다.

```bash
uv run python -m cgv_push_bot
```

종료하려면 `Ctrl+C`를 누릅니다. 알림 데이터는 기본적으로 `data/movie-bot.sqlite3`에 저장합니다.
데이터베이스는 처음 실행할 때 자동으로 생성됩니다.

봇이 Discord에 연결되면 `/alert`를 사용할 수 있습니다.
명령이 표시되기까지 시간이 걸릴 수 있습니다.
토큰이 포함된 `.env`나 Compose 파일은 공개 저장소에 올리지 않습니다.

### 설정

기본 설정은 `.env`에 작성합니다. Docker에서는 Compose의 `environment`에 직접 지정할 수도 있습니다.
토큰 외의 항목은 기본값으로 실행할 수 있습니다.

| 환경변수 | 기본값 | 설명 |
| --- | --- | --- |
| `DISCORD_TOKEN` | 없음 | Discord 봇 토큰(필수) |
| `POLL_INTERVAL_SECONDS` | `300` | 조회 간격(초), 최소 60초 |
| `POLL_OFFSET_SECONDS` | `1` | 한국 시간 자정부터 첫 조회까지의 시간(초), 0 이상이며 조회 간격 미만 |
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/movie-bot.sqlite3` | 알림 데이터를 저장할 DB |
| `HISTORY_RETENTION_DAYS` | `90` | 만료 후 기록 보관 일수(0은 자동 정리 끄기, 최대 36500일) |
| `LOG_LEVEL` | `INFO` | 로그 수준 |

기본 설정에서는 한국 시간 `00:00:01`, `00:05:01`, `00:10:01` 순으로 조회합니다.
매 조회 주기에는 같은 영화관·날짜를 한 번만 조회합니다.
상영 날짜가 가까운 순서로 조회하며, 요청 사이에 최소 0.5초 간격을 둡니다.
CGV 서비스나 응답 형식이 변경되면 조회가 일시적으로 실패할 수 있습니다.

### 운영 참고

동일한 DB를 사용하는 봇 프로세스는 하나만 실행합니다. 알림 발송 잠금은 프로세스 내부에서
적용되므로 여러 인스턴스를 실행하면 같은 알림이 중복 발송될 수 있습니다.
Discord 전송 성공 후 DB 기록 전에 프로세스가 종료되는 경우에도 재시작 후 중복될 수 있습니다.

발송 직전에 구독의 삭제·만료 여부를 다시 확인합니다. 이미 시작된 발송은 마친 뒤 삭제를
완료하며, 삭제 완료 후에는 해당 구독의 새 발송을 시작하지 않습니다.
만료된 구독의 대기 알림은 발송하지 않습니다.
영화 목록은 1,024자 안에서 제목 단위로 표시하고, 생략된 영화는 “외 N편”으로 안내합니다.
알림의 발견 시각은 최초 알림 생성 시각이며, 전송을 재시도해도 바뀌지 않습니다.
만료 후 기본 90일이 지난 구독과 관련 알림·영화 기록은 자동 삭제됩니다.
조회 주기마다 구독을 최대 500건씩 정리하며, 더 이상 구독이 없는 오래된 조회 대상도 정리합니다.
`HISTORY_RETENTION_DAYS=0`으로 설정하면 자동 정리를 끌 수 있습니다.
조회·발송 실패의 DB 기록에는 예외 유형만 저장하며, 원문 응답이나 오류 메시지는 저장하지
않습니다. 이 동작은 새로 기록하는 오류에 적용되며 기존 DB 기록을 소급 변경하지 않습니다.

## 개발 검증

### 코드 구조

코드를 처음 읽을 때는 아래 흐름을 따라가면 됩니다.

1. `__main__.run`: DB·CGV 클라이언트·Discord 봇을 만들고 조회 및 발송 작업을 시작합니다.
2. `MovieAlertService.register_subscription`: 현재 영화 목록을 먼저 조회한 뒤 구독과 함께
   저장합니다. 이 목록이 **기준 영화(baseline)**이며, 등록 전에 있던 영화는 알리지 않습니다.
3. `MovieAlertService.poll_once`: 같은 영화관·날짜를 한 번 조회하고 구독별로 처음 보는 영화를
   찾습니다. 키워드가 맞으면 영화 기록과 **발송 대기 알림(Notification)**을 함께 저장합니다.
4. `DeliveryService.deliver_once`: 발송 직전에 삭제·만료·재시도 시각을 확인하고,
   `DiscordNotificationSender`로 전송한 뒤 성공 또는 다음 재시도 시각을 기록합니다.

예를 들어 등록 당시 영화가 A였고 다음 조회에 A·B가 나오면 B만 알립니다.
B가 사라졌다가 다시 나타나도 이미 관찰한 기록이 있으므로 다시 알리지 않습니다.
영화 기록과 발송 대기 알림은 같은 트랜잭션으로 저장하므로, 저장 중 실패하면 둘 다 취소됩니다.

| 위치 | 역할 |
| --- | --- |
| `cgv/` | 독립적으로 사용할 수 있는 CGV 조회 클라이언트와 응답 모델 |
| `alerts/models.py`, `alerts/protocols.py` | 알림 서비스의 데이터 모델과 인터페이스 |
| `alerts/service.py`, `alerts/delivery.py` | 구독·조회·알림 발송의 업무 흐름과 트랜잭션 |
| `db/repositories.py` | DB 조회·저장 로직과 발송 가능 조건 |
| `discord_ui/notifications.py` | Discord 채널·DM으로 메시지를 보내는 구현 |
| `discord_ui/views/registration/` | 영화관·날짜·키워드·확인 단계별 등록 화면 |

`alerts`는 Discord 구현을 직접 가져오지 않습니다. `NotificationSender` 인터페이스를 통해
발송하며, 실제 구현과 삭제·발송 공통 잠금은 `__main__.py`에서 연결합니다.
Repository는 변경을 flush하고, 서비스가 트랜잭션의 commit·rollback을 담당합니다.
발송 가능 조건을 바꿀 때는 Repository의 공통 쿼리를 수정하여 배치 조회와 발송 직전 재조회에
동일하게 적용합니다. 삭제·발송 공통 잠금은 발송 직전 재조회부터 발송 결과 저장까지 유지합니다.

등록 화면은 `theaters` → `dates` → `keywords` → `confirmation` 순으로 연결됩니다.
기존 `discord_ui.protocols`와 `views.registration`의 공개 import 경로는 유지합니다.

### 검증 명령

외부 CGV 요청은 테스트에서 모의 처리합니다. 변경 후 아래 검증을 실행합니다.

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest
uv build
```

## Contribution

어떤 기여든 환영합니다. 이슈나 Pull Request로 참여해 주세요

## 라이선스

[MIT License](LICENSE)
