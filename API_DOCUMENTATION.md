# مستندات API نمایندگان BananaBot

این سند نحوه‌ی استفاده از API اختصاصی نمایندگان (Reseller API) پنل تحت وب BananaBot را توضیح می‌دهد. با این API هر نماینده می‌تواند بدون ورود به پنل تحت وب، به‌صورت برنامه‌نویسی‌شده (مثلاً از داخل ربات تلگرامی خودش) کانفیگ بسازد، لیست کند، تمدید/ویرایش کند، فعال/غیرفعال کند یا حذف کند.

> نسخه: v1
> Base URL: `https://<دامنه‌ی-شما><WEB_PATH>/api/v1`
> مثال: اگر `WEB_PATH=/panel` باشد → `https://example.com/panel/api/v1`

---

## ۱. فهرست مطالب

- [۲. دریافت کلید API](#۲-دریافت-کلید-api)
- [۳. احراز هویت](#۳-احراز-هویت)
- [۴. هدرهای الزامی](#۴-هدرهای-الزامی)
- [۵. قوانین امنیتی سمت سرور](#۵-قوانین-امنیتی-سمت-سرور)
- [۶. کدهای خطا](#۶-کدهای-خطا)
- [۷. Rate Limiting](#۷-rate-limiting)
- [۸. Endpoint ها](#۸-endpoint-ها)
  - [GET /account/](#get-account)
  - [GET /configs/](#get-configs)
  - [GET /configs/{id}/](#get-configsid)
  - [POST /configs/create/](#post-configscreate)
  - [PATCH /configs/{id}/update/](#patch-configsidupdate)
  - [POST /configs/{id}/toggle/](#post-configsidtoggle)
  - [DELETE /configs/{id}/delete/](#delete-configsiddelete)
- [۹. مثال کامل: چرخه‌ی کامل با requests](#۹-مثال-کامل-چرخهی-کامل-با-requests)
- [۱۰. نکات امنیتی برای نگهداری کلید](#۱۰-نکات-امنیتی-برای-نگهداری-کلید)

---

## ۲. دریافت کلید API

1. وارد پنل تحت وب شوید → **پنل نمایندگی** → **مدیریت کلیدهای API**.
2. یک برچسب دلخواه (مثلاً «ربات تلگرام من») وارد کرده و روی «ساخت کلید» بزنید.
3. کلید تولیدشده (با فرمت `bb_xxxxxxxx_xxxxxxxxxxxx...`) **فقط همان یک‌بار** نمایش داده می‌شود. آن را فوراً در جای امنی (مثلاً env variable سرور ربات‌تان) ذخیره کنید.
4. سرور فقط هش این کلید را نگه می‌دارد؛ اگر آن را گم کنید، راهی برای بازیابی‌اش نیست و باید کلید جدید بسازید.
5. هر نماینده می‌تواند تا **۱۰ کلید فعال** هم‌زمان داشته باشد و هرکدام را مستقل از بقیه باطل (Revoke) کند — باطل‌کردن یک کلید تأثیری روی بقیه‌ی کلیدها یا کانفیگ‌های قبلاً ساخته‌شده ندارد.

---

## ۳. احراز هویت

هر درخواست باید هدر زیر را داشته باشد:

```
Authorization: Bearer bb_xxxxxxxx_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

کلید از دو بخش تشکیل شده: یک شناسه‌ی عمومی (`key_id`) برای پیدا کردن سریع رکورد در دیتابیس، و یک رشته‌ی راز با آنتروپی بالا. **راز واقعی هرگز در سرور ذخیره نمی‌شود** — فقط هش SHA-256 آن نگه داشته می‌شود؛ حتی در صورت دسترسی به دیتابیس، کلید خام قابل استخراج نیست.

---

## ۴. هدرهای الزامی

| هدر | الزامی برای | توضیح |
|---|---|---|
| `Authorization` | همه‌ی درخواست‌ها | `Bearer <کلید API>` |
| `Content-Type` | POST / PATCH | باید `application/json` باشد |
| `X-Timestamp` | POST / PATCH / DELETE | زمان فعلی به‌صورت Unix timestamp (ثانیه) |
| `X-Nonce` | POST / PATCH / DELETE | یک رشته‌ی تصادفی و **یکتا** برای هر درخواست (پیشنهاد: UUIDv4)، بین ۸ تا ۱۲۸ کاراکتر |

برای درخواست‌های فقط-خواندنی (`GET`) نیازی به `X-Timestamp`/`X-Nonce` نیست؛ چون این درخواست‌ها اثر جانبی ندارند و replay شدن‌شان بی‌ضرر است. اما هر درخواستی که چیزی می‌سازد/تغییر می‌دهد/حذف می‌کند (`POST`, `PATCH`, `DELETE`) این دو هدر را الزامی می‌شمارد.

**مثال تولید nonce (پایتون):**
```python
import uuid, time
headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
    "X-Timestamp": str(int(time.time())),
    "X-Nonce": uuid.uuid4().hex,
}
```

> ⚠️ هر `X-Nonce` فقط یک‌بار برای هر کلید API پذیرفته می‌شود. اگر همان درخواست (با همان nonce) دوباره ارسال شود — مثلاً به‌خاطر retry خودکار یا یک مهاجم که درخواست را capture کرده — سرور با خطای `409 REPLAY_DETECTED` آن را رد می‌کند. برای هر تلاش/retry جدید، nonce تازه بسازید.
>
> ⚠️ `X-Timestamp` باید حداکثر ۱۲۰ ثانیه با ساعت سرور اختلاف داشته باشد؛ در غیر این صورت `400 STALE_TIMESTAMP` برمی‌گردد. ساعت سیستمی سرور خود را با NTP هماهنگ نگه دارید.

---

## ۵. قوانین امنیتی سمت سرور

قبل از پردازش **هر** درخواست، سرور به ترتیب زیر بررسی می‌کند و در اولین شرطِ ناموفق، درخواست را رد می‌کند:

1. کلید API معتبر است (فرمت درست + هش منطبق) → در غیر این صورت `401 INVALID_API_KEY`
2. کلید API باطل (Revoke) نشده → در غیر این صورت `401 API_KEY_REVOKED`
3. حساب نمایندگی `active` است (توسط ادمین غیرفعال نشده) → در غیر این صورت `403 RESELLER_DISABLED`
4. **مهلت پلن نمایندگی هنوز تمام نشده** → در غیر این صورت `403 RESELLER_EXPIRED`
5. پنل X-UI مرتبط با این نمایندگی فعال است → در غیر این صورت `403 PANEL_DISABLED`
6. تعداد درخواست‌های اخیر از سقف Rate Limit عبور نکرده → در غیر این صورت `429 RATE_LIMITED`
7. (فقط POST/PATCH/DELETE) هدرهای `X-Timestamp`/`X-Nonce` معتبر و nonce تکراری نیست → در غیر این صورت `400`/`409`
8. (فقط ساخت/ویرایش کانفیگ) حجم درخواستی از حجم باقیمانده‌ی سهمیه بیشتر نیست → در غیر این صورت `403 QUOTA_EXCEEDED`

نکته‌ی کلیدی طبق درخواست شما: **حتی اگر کلید API کاملاً معتبر و فعال باشد، اگر پنل نمایندگی منقضی شده یا حساب غیرفعال شده باشد، سرور در همان لحظه (نه فقط زمان صدور کلید) این را تشخیص می‌دهد و درخواست را با `403` رد می‌کند.** این چک روی هر درخواست، بدون استثنا، دوباره انجام می‌شود — نه فقط یک‌بار موقع ساخت کلید.

همچنین این چک‌ها **دقیقاً همان تابع‌هایی** هستند که پنل تحت وب (بخش «پنل نمایندگی») هم استفاده می‌کند؛ یعنی از مسیر API نمی‌توان قانونی را دور زد که از مسیر پنل تحت وب اعمال می‌شود.

تمام درخواست‌ها — موفق یا ناموفق — در جدول لاگ ثبت می‌شوند (شامل IP، User-Agent، endpoint، کد وضعیت، کد خطا و زمان پاسخ) و آخرین ۳۰ مورد از این لاگ در همان صفحه‌ی «مدیریت کلیدهای API» قابل مشاهده است.

---

## ۶. کدهای خطا

همه‌ی خطاها با این ساختار برمی‌گردند:

```json
{ "ok": false, "error_code": "RESELLER_EXPIRED", "message": "مهلت پلن نمایندگی شما به پایان رسیده است." }
```

| HTTP | error_code | معنی |
|---|---|---|
| 400 | `MISSING_NONCE` | هدرهای `X-Timestamp`/`X-Nonce` ارسال نشده‌اند |
| 400 | `INVALID_TIMESTAMP` | `X-Timestamp` عدد معتبر نیست |
| 400 | `STALE_TIMESTAMP` | اختلاف زمانی بیش از حد مجاز |
| 400 | `INVALID_NONCE` | طول nonce نامعتبر است |
| 400 | `INVALID_JSON` | بدنه‌ی درخواست JSON معتبر نیست |
| 400 | `INVALID_INPUT` | فیلدهای ورودی ناقص/نامعتبرند (مثلاً `volume_gb`/`duration_days`) |
| 401 | `MISSING_API_KEY` | هدر `Authorization` ارسال نشده |
| 401 | `INVALID_API_KEY` | کلید نامعتبر است یا وجود ندارد |
| 401 | `API_KEY_REVOKED` | این کلید باطل شده است |
| 403 | `RESELLER_DISABLED` | حساب نمایندگی توسط ادمین غیرفعال شده |
| 403 | `RESELLER_EXPIRED` | **مهلت پلن نمایندگی تمام شده** |
| 403 | `PANEL_DISABLED` | پنل X-UI مرتبط غیرفعال است |
| 403 | `QUOTA_EXCEEDED` | حجم درخواستی از سهمیه‌ی باقیمانده بیشتر است |
| 403 | `DURATION_EXCEEDS_RESELLER_EXPIRY` | مدت درخواستی از تاریخ انقضای خودِ پلن نمایندگی فراتر می‌رود |
| 404 | `CONFIG_NOT_FOUND` | کانفیگ پیدا نشد یا متعلق به شما نیست |
| 409 | `REPLAY_DETECTED` | این nonce قبلاً استفاده شده (تلاش برای Replay) |
| 409 | `NO_INBOUNDS` | برای پنل شما Inbound تنظیم نشده (با ادمین تماس بگیرید) |
| 429 | `RATE_LIMITED` | تعداد درخواست‌ها از سقف مجاز عبور کرده |
| 502 | `PANEL_ERROR` | خطا در ارتباط با پنل X-UI هنگام ساخت/ویرایش |
| 502 | `PANEL_DELETE_FAILED` | حذف از روی پنل ناموفق بود (برای جلوگیری از مغایرت، چیزی در سیستم حذف نشد) |
| 500 | `INTERNAL_ERROR` | خطای داخلی سرور |

---

## ۷. Rate Limiting

| محدوده | سقف پیش‌فرض |
|---|---|
| کل درخواست‌های یک کلید (همه‌ی endpoint ها) | ۱۲۰ درخواست در دقیقه |
| ساخت کانفیگ (`POST /configs/create/`) | ۱۰ درخواست در دقیقه |
| ویرایش/فعال‌سازی/حذف کانفیگ (مجموع) | ۳۰ درخواست در دقیقه |

هنگام برخورد با `429 RATE_LIMITED`، کمی صبر کرده و دوباره تلاش کنید (Exponential backoff پیشنهاد می‌شود).

---

## ۸. Endpoint ها

در نمونه‌های Python زیر، ابتدا یک ماژول کمکی کوچک (`bananabot_client.py`) می‌سازیم که احراز هویت، ساخت `X-Timestamp`/`X-Nonce` و مدیریت خطا را یک‌بار پیاده می‌کند؛ در ادامه هر endpoint را با همین ماژول صدا می‌زنیم.

```python
# bananabot_client.py
import os
import time
import uuid
import requests

BASE_URL = "https://example.com/panel/api/v1"   # با آدرس واقعی خودتان جایگزین کنید
API_KEY = os.environ["BANANABOT_RESELLER_API_KEY"]  # هرگز کلید را مستقیم در کد ننویسید


class BananaBotAPIError(Exception):
    def __init__(self, status_code: int, error_code: str, message: str):
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        super().__init__(f"[{status_code}] {error_code}: {message}")


def _headers(with_nonce: bool = False) -> dict:
    headers = {"Authorization": f"Bearer {API_KEY}"}
    if with_nonce:
        headers["Content-Type"] = "application/json"
        headers["X-Timestamp"] = str(int(time.time()))
        headers["X-Nonce"] = uuid.uuid4().hex
    return headers


def _handle(resp: requests.Response) -> dict:
    data = resp.json()
    if not data.get("ok"):
        raise BananaBotAPIError(resp.status_code, data.get("error_code", ""), data.get("message", ""))
    return data


def api_get(path: str, params: dict | None = None) -> dict:
    resp = requests.get(f"{BASE_URL}{path}", headers=_headers(), params=params, timeout=20)
    return _handle(resp)


def api_post(path: str, json_body: dict | None = None) -> dict:
    resp = requests.post(f"{BASE_URL}{path}", headers=_headers(with_nonce=True), json=json_body or {}, timeout=20)
    return _handle(resp)


def api_patch(path: str, json_body: dict) -> dict:
    resp = requests.patch(f"{BASE_URL}{path}", headers=_headers(with_nonce=True), json=json_body, timeout=20)
    return _handle(resp)


def api_delete(path: str) -> dict:
    resp = requests.delete(f"{BASE_URL}{path}", headers=_headers(with_nonce=True), timeout=20)
    return _handle(resp)
```

> `BananaBotAPIError` را می‌توانید `except` کنید و بر اساس `e.error_code` (یکی از کدهای بخش ۶) رفتار متفاوتی نشان دهید — مثلاً اگر `RESELLER_EXPIRED` بود، به کاربر ربات بگویید «نمایندگی منقضی شده»، و اگر `QUOTA_EXCEEDED` بود، حجم باقیمانده را نشان دهید.

### GET /account/

وضعیت فعلی حساب نمایندگی و سهمیه را برمی‌گرداند. هدرهای nonce لازم نیست.

```bash
curl -s "$BASE/account/" \
  -H "Authorization: Bearer $API_KEY"
```

```python
from bananabot_client import api_get

account = api_get("/account/")["reseller"]
print(f"سهمیه باقیمانده: {account['remaining_gb']} GB — انقضا: {account['expires_at_display']}")
```

```json
{
  "ok": true,
  "reseller": {
    "id": 12,
    "status": "active",
    "quota_gb": 100.0,
    "used_gb": 23.5,
    "remaining_gb": 76.5,
    "expires_at": 1787356500,
    "expires_at_display": "2026-08-22 03:25"
  }
}
```

---

### GET /configs/

لیست کانفیگ‌های شما (اعم از ساخته‌شده از داخل پنل یا از طریق API).

پارامتر اختیاری: `?include_deleted=1` برای نمایش کانفیگ‌های حذف‌شده هم.

```bash
curl -s "$BASE/configs/" -H "Authorization: Bearer $API_KEY"
```

```python
from bananabot_client import api_get

configs = api_get("/configs/")["configs"]
for c in configs:
    print(c["id"], c["label"], c["status"], f"{c['volume_gb']} GB", c["source"])

# شامل حذف‌شده‌ها هم:
all_configs = api_get("/configs/", params={"include_deleted": 1})["configs"]
```

```json
{
  "ok": true,
  "configs": [
    {
      "id": 55,
      "label": "مشتری ۱",
      "email": "rs111222333_ab12cd",
      "sub_id": "z0mwseq1ua5wlva2",
      "volume_gb": 10.0,
      "consumed_gb": 0.0,
      "expiry_time_ms": 1787356500000,
      "expiry_display": "2026-08-22 03:25",
      "config_link": "vless://...",
      "config_links": ["vless://..."],
      "sub_link": "https://sub.example.com/z0mwseq1ua5wlva2",
      "status": "active",
      "source": "api",
      "created_at": "2026-07-22 23:55:00"
    }
  ]
}
```

> فیلد `source` نشان می‌دهد کانفیگ از کجا ساخته شده: `"panel"` (از داخل پنل تحت وب) یا `"api"`. کانفیگ‌های ساخته‌شده از طریق API **بلافاصله** در صفحه‌ی «پنل نمایندگی» با نشان کوچک «API» هم نمایش داده می‌شوند — نیازی به هیچ تنظیم اضافه نیست.

---

### GET /configs/{id}/

جزئیات یک کانفیگ خاص (فقط اگر متعلق به همین نماینده باشد).

```bash
curl -s "$BASE/configs/55/" -H "Authorization: Bearer $API_KEY"
```

```python
from bananabot_client import api_get, BananaBotAPIError

try:
    config = api_get("/configs/55/")["config"]
    print(config["sub_link"])
except BananaBotAPIError as e:
    if e.error_code == "CONFIG_NOT_FOUND":
        print("این کانفیگ پیدا نشد یا متعلق به شما نیست.")
    else:
        raise
```

---

### POST /configs/create/

ساخت کانفیگ جدید با حجم و مدت دلخواه.

**بدنه‌ی درخواست:**

| فیلد | نوع | الزامی | توضیح |
|---|---|---|---|
| `volume_gb` | number | بله | حجم به گیگابایت (باید > 0 و ≤ سهمیه‌ی باقیمانده) |
| `duration_days` | integer | بله | مدت به روز (باید > 0 و از تاریخ انقضای پلن نمایندگی شما فراتر نرود) |
| `label` | string | خیر | برچسب دلخواه برای شناسایی در پنل (حداکثر ۱۰۰ کاراکتر) |

```bash
curl -s -X POST "$BASE/configs/create/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -H "X-Timestamp: $(date +%s)" \
  -H "X-Nonce: $(python3 -c 'import uuid;print(uuid.uuid4().hex)')" \
  -d '{"label": "مشتری جدید", "volume_gb": 10, "duration_days": 30}'
```

```python
from bananabot_client import api_post, BananaBotAPIError

try:
    config = api_post("/configs/create/", {
        "label": "مشتری جدید",
        "volume_gb": 10,
        "duration_days": 30,
    })["config"]
    print("کانفیگ ساخته شد:", config["sub_link"])
except BananaBotAPIError as e:
    if e.error_code == "QUOTA_EXCEEDED":
        print("حجم باقیمانده کافی نیست:", e.message)
    elif e.error_code == "RESELLER_EXPIRED":
        print("مهلت نمایندگی شما تمام شده است.")
    else:
        raise
```

پاسخ موفق: `201 Created` + همان ساختار شیء `config` که در بخش قبل دیدید (شامل `config_link` و `sub_link` آماده برای تحویل به کاربر نهایی).

---

### PATCH /configs/{id}/update/

تمدید/ویرایش حجم و مدت **یا** فقط تغییر نام (label)، برای یک کانفیگ موجود.

- برای **تمدید/ویرایش** حجم و مدت: هر دو فیلد `volume_gb` و `duration_days` را بفرستید. حجم مصرف‌شده‌ی واقعیِ همین دوره برای همیشه در حساب نگه داشته می‌شود (نمی‌توان با تمدید مکرر، مصرف واقعی را دور زد) و شمارنده‌ی ترافیک روی پنل ریست می‌شود.
- برای **تغییر فقط نام**: تنها فیلد `label` را بفرستید (بدون `volume_gb`/`duration_days`).

```bash
curl -s -X PATCH "$BASE/configs/55/update/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -H "X-Timestamp: $(date +%s)" \
  -H "X-Nonce: $(python3 -c 'import uuid;print(uuid.uuid4().hex)')" \
  -d '{"volume_gb": 20, "duration_days": 30}'
```

```python
from bananabot_client import api_patch

# تمدید/ویرایش حجم و مدت:
config = api_patch("/configs/55/update/", {"volume_gb": 20, "duration_days": 30})["config"]

# فقط تغییر نام:
config = api_patch("/configs/55/update/", {"label": "مشتری VIP"})["config"]
```

---

### POST /configs/{id}/toggle/

فعال/غیرفعال‌کردن دستی یک کانفیگ.

**بدنه (اختیاری):** `{"enable": true}` یا `{"enable": false}`. اگر ارسال نشود، وضعیت فعلی toggle می‌شود (فعال↔غیرفعال).

```bash
curl -s -X POST "$BASE/configs/55/toggle/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -H "X-Timestamp: $(date +%s)" \
  -H "X-Nonce: $(python3 -c 'import uuid;print(uuid.uuid4().hex)')" \
  -d '{"enable": false}'
```

```python
from bananabot_client import api_post

# غیرفعال‌کردن:
config = api_post("/configs/55/toggle/", {"enable": False})["config"]

# فعال‌کردن دوباره:
config = api_post("/configs/55/toggle/", {"enable": True})["config"]

# toggle خودکار (بدون مشخص‌کردن enable):
config = api_post("/configs/55/toggle/")["config"]
```

---

### DELETE /configs/{id}/delete/

حذف قطعی یک کانفیگ (هم از روی پنل X-UI، هم از سیستم).

```bash
curl -s -X DELETE "$BASE/configs/55/delete/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "X-Timestamp: $(date +%s)" \
  -H "X-Nonce: $(python3 -c 'import uuid;print(uuid.uuid4().hex)')"
```

```python
from bananabot_client import api_delete

result = api_delete("/configs/55/delete/")
print(f"حجم آزادشده: {result['freed_gb']} GB — حجم مصرف‌شده‌ی این دوره: {result['window_used_gb']} GB")
```

پاسخ شامل `freed_gb` (حجمی که به سهمیه‌ی شما برگشت) و `window_used_gb` (حجمی که واقعاً مصرف شده و برای همیشه از سهمیه کسر ماند) است:

```json
{
  "ok": true,
  "config": { "...": "...", "status": "deleted" },
  "freed_gb": 6.0,
  "window_used_gb": 2.0
}
```

> اگر حذف از روی پنل X-UI به هر دلیلی ناموفق باشد و کلاینت همچنان روی پنل زنده باشد، سیستم **کانفیگ را حذف‌شده علامت نمی‌زند** و حجمی هم آزاد نمی‌کند — تا هیچ‌وقت مغایرتی بین سیستم و پنل واقعی پیش نیاید. در این حالت `502 PANEL_DELETE_FAILED` برمی‌گردد؛ دوباره تلاش کنید یا با پشتیبانی تماس بگیرید.

---

## ۹. مثال کامل: چرخه‌ی کامل با requests

نمونه‌ی زیر یک اسکریپت ساده و مستقل است که فقط از کتابخانه‌ی `requests` استفاده می‌کند و کل چرخه‌ی یک کانفیگ را نشان می‌دهد: دریافت سهمیه → ساخت → لیست → تمدید → غیرفعال‌کردن → حذف.

```python
import os
import time
import uuid
import requests

BASE_URL = "https://example.com/panel/api/v1"   # با آدرس واقعی خودتان جایگزین کنید
API_KEY = os.environ["BANANABOT_RESELLER_API_KEY"]  # هرگز کلید را مستقیم در کد ننویسید


def signed_headers() -> dict:
    """هدرهای لازم برای درخواست‌های POST/PATCH/DELETE (شامل nonce تازه)."""
    return {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "X-Timestamp": str(int(time.time())),
        "X-Nonce": uuid.uuid4().hex,
    }


# ۱) دریافت وضعیت حساب و سهمیه‌ی باقیمانده
resp = requests.get(
    f"{BASE_URL}/account/",
    headers={"Authorization": f"Bearer {API_KEY}"},
    timeout=20,
)
data = resp.json()
print("account:", data)
if not data["ok"]:
    raise SystemExit(f"{data['error_code']}: {data['message']}")
remaining_gb = data["reseller"]["remaining_gb"]

# ۲) ساخت کانفیگ جدید
resp = requests.post(
    f"{BASE_URL}/configs/create/",
    json={"label": "مشتری تستی", "volume_gb": 10, "duration_days": 30},
    headers=signed_headers(),
    timeout=20,
)
data = resp.json()
print("create:", resp.status_code, data)
if not data["ok"]:
    raise SystemExit(f"{data['error_code']}: {data['message']}")
config_id = data["config"]["id"]
print("لینک اشتراک:", data["config"]["sub_link"])

# ۳) لیست همه‌ی کانفیگ‌ها
resp = requests.get(
    f"{BASE_URL}/configs/",
    headers={"Authorization": f"Bearer {API_KEY}"},
    timeout=20,
)
print("list:", resp.status_code, resp.json())

# ۴) تمدید/ویرایش حجم و مدت همان کانفیگ
resp = requests.patch(
    f"{BASE_URL}/configs/{config_id}/update/",
    json={"volume_gb": 20, "duration_days": 30},
    headers=signed_headers(),
    timeout=20,
)
print("update:", resp.status_code, resp.json())

# ۵) غیرفعال‌کردن موقت کانفیگ
resp = requests.post(
    f"{BASE_URL}/configs/{config_id}/toggle/",
    json={"enable": False},
    headers=signed_headers(),
    timeout=20,
)
print("toggle:", resp.status_code, resp.json())

# ۶) حذف قطعی کانفیگ
resp = requests.delete(
    f"{BASE_URL}/configs/{config_id}/delete/",
    headers=signed_headers(),
    timeout=20,
)
print("delete:", resp.status_code, resp.json())
```

> نکته: هر بار که یک درخواست POST/PATCH/DELETE می‌فرستید، `signed_headers()` را دوباره صدا بزنید تا `X-Timestamp`/`X-Nonce` تازه ساخته شود — استفاده‌ی مجدد از هدرهای یک درخواست قبلی باعث خطای `409 REPLAY_DETECTED` می‌شود.

---

## ۱۰. نکات امنیتی برای نگهداری کلید

- کلید API را هرگز داخل کد frontend/کلاینت یا مخزن گیت عمومی قرار ندهید؛ همیشه از environment variable یا secret manager سرور خودتان استفاده کنید.
- برای هر سرویس/ربات جدا یک کلید مجزا بسازید (نه یک کلید مشترک بین چند برنامه) — این‌طوری اگر یکی لو رفت، فقط همان یکی را Revoke می‌کنید و بقیه سرویس‌ها قطع نمی‌شوند.
- در صورت مشکوک‌شدن به لو رفتن یک کلید، بلافاصله از صفحه‌ی «مدیریت کلیدهای API» آن را باطل کنید و کلید جدید بسازید.
- همیشه روی HTTPS کار کنید؛ کلید API به‌صورت متن ساده در هدر ارسال می‌شود و HTTPS تنها لایه‌ی محافظتی آن در شبکه است.
- `X-Nonce` را واقعاً تصادفی و یکتا تولید کنید (نه شمارنده‌ی ساده‌ی ۱،۲،۳...)؛ در غیر این صورت با nonce تکراری به‌اشتباه با `409 REPLAY_DETECTED` مواجه می‌شوید.
