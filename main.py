import base64
import csv
import datetime
import json
import os
import re
import subprocess
import sys
from time import sleep
import tomllib

from packaging.version import Version
import requests
from tabulate import tabulate
import tomli_w
import wget

try:
    from Crypto.Cipher import AES
except ImportError:
    AES = None


current_version = "2.0.1"
base_url = "https://lxl.sdyu.edu.cn"
default_start_time = "08:30"
default_end_time = "22:30"
reservation_start_time = "12:00"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0",
    "Referer": "https://lxl.sdyu.edu.cn",
}
api_headers = {
    **headers,
    "Content-Type": "application/json",
    "X-Requested-With": "XMLHttpRequest",
}


def default_config():
    return {
        "seat": {"seat_area": None, "seat_id": None},
        "account": {"username": None, "password": None},
        "data": {
            "date": None,
            "segment": None,
            "token": None,
            "auto_user_check_url": None,
            "access_token": None,
            "expire": None,
            "user_name": None,
            "userid": None,
        },
        "init": True,
    }


def normalize_config(config):
    schema = default_config()
    for section, value in schema.items():
        if isinstance(value, dict):
            config.setdefault(section, {})
            for key, default_value in value.items():
                config[section].setdefault(key, default_value)
        else:
            config.setdefault(section, value)
    return config


def require_aes():
    if AES is None:
        raise RuntimeError("缺少 pycryptodome，请先运行 pip install -r requirements.txt")


def crypto_key():
    date_key = datetime.datetime.now().strftime("%Y%m%d")
    return f"{date_key}{date_key[::-1]}".encode("utf-8")


def pkcs7_pad(data):
    pad_len = AES.block_size - len(data) % AES.block_size
    return data + bytes([pad_len]) * pad_len


def pkcs7_unpad(data):
    pad_len = data[-1]
    return data[:-pad_len]


def encrypt_payload(data):
    require_aes()
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    cipher = AES.new(crypto_key(), AES.MODE_CBC, b"ZZWBKJ_ZHIHUAWEI")
    return base64.b64encode(cipher.encrypt(pkcs7_pad(raw))).decode("utf-8")


def decrypt_payload(data):
    require_aes()
    cipher = AES.new(crypto_key(), AES.MODE_CBC, b"ZZWBKJ_ZHIHUAWEI")
    return pkcs7_unpad(cipher.decrypt(base64.b64decode(data))).decode("utf-8")


def api_post(path, data=None, auth=False, crypto=False, crypto_pas=False, retry_login=True):
    global conf
    payload = data or {}
    request_headers = api_headers.copy()
    if auth:
        token = conf["data"].get("token")
        if not token and retry_login:
            conf = get_cookies(force=True)
            token = conf["data"].get("token")
        if token:
            request_headers["authorization"] = f"bearer{token}"
    if crypto:
        payload = {"aesjson": encrypt_payload(payload)}

    while True:
        try:
            response = requests.post(
                url=f"{base_url}{path}",
                json=payload,
                headers=request_headers,
                timeout=30,
            )
            response.raise_for_status()
            result = response.json()
            if crypto_pas and isinstance(result.get("data"), str):
                result["data"] = json.loads(decrypt_payload(result["data"]))
            if auth and result.get("code") == 10001 and retry_login:
                print("\n登录已过期，正在自动登录", end="……", flush=True)
                conf = get_cookies(force=True)
                return api_post(path, data, auth, crypto, crypto_pas, retry_login=False)
            return result
        except Exception:
            sleep(1)


def time_sync():
    script_file = f"{os.path.realpath(os.path.dirname(__file__))}\\timeSync.ps1"
    script_contents = '''$service = Get-Service w32time
    if ($service.Status -eq 'Stopped') {
        Start-Process powershell -Verb RunAs -ArgumentList "-Command ""Set-Service -Name w32time -StartupType Automatic; Start-Service w32time; w32tm /resync""";
    }
    '''

    with open(script_file, "w") as file:
        file.write(script_contents)

    subprocess.Popen(
        [
            "powershell",
            "-Command",
            f"Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process -Force; & '{script_file}'",
        ],
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def do_upgrade():
    if sys.argv[1] != "--upgrade":
        return

    script_file = "upgrade.ps1"
    script_contents = f"""$oldFileName = "{sys.argv[2]}"
$newFileName = "{os.path.basename(sys.argv[0])}"
$programName = "sdyu_seat.exe"
while ((Get-WmiObject Win32_Process | Where-Object {{ $_.Name -match $oldFileName }}) -or ((& tasklist) -match $oldFileName) -or (Get-Process -Name $oldFileName -ErrorAction SilentlyContinue)) {{ }}
while ((Get-WmiObject Win32_Process | Where-Object {{ $_.Name -match $newFileName }}) -or ((& tasklist) -match $newFileName) -or (Get-Process -Name $newFileName -ErrorAction SilentlyContinue)) {{ }}
Remove-Item $oldFileName
Rename-Item -Path $newFileName -NewName $programName
Start-Process -FilePath $programName
Remove-Item -Path $MyInvocation.MyCommand.Path -Force
"""

    with open(script_file, "w") as file:
        file.write(script_contents)

    subprocess.Popen(
        [
            "powershell",
            "-Command",
            f"Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process -Force; & './{script_file}'",
        ],
        shell=True,
    )
    sys.exit()


def check_network():
    url = "https://baidu.com"
    fail_count = 0
    while True:
        try:
            response = requests.head(url=url, timeout=5)
            response.raise_for_status()
            break
        except Exception:
            if fail_count == 0:
                fail_count += 1
            elif fail_count == 1:
                print(
                    "\n连不上啊，登校园网了吗？http://123.123.123.123/",
                    end=" ",
                    flush=True,
                )
                fail_count += 1
            else:
                print(".", end="", flush=True)
            sleep(1)
    if fail_count > 0:
        print("\n")


def check_release(current_version):
    url = "https://api.github.com/repos/dunxuan/sdyu_seat/releases/latest"
    try:
        latest_version = requests.get(url=url, timeout=10).json()["name"]
    except Exception:
        return False

    if Version(latest_version) > Version(current_version):
        print(f"有新版本({latest_version})了，更新后会自动重启程序")
        url = f"https://gitee.com/dunxuan/sdyu_seat/releases/download/{latest_version}/sdyu_seat.exe"
        wget.download(url, f"sdyu_seat_{latest_version}.exe")

        subprocess.Popen(
            [
                "start",
                f"./sdyu_seat_{latest_version}.exe",
                "--upgrade",
                f"{os.path.basename(sys.argv[0])}",
            ],
            shell=True,
        )
        sys.exit()
    return True


def get_config():
    global conf
    if not os.path.exists("conf.toml"):
        conf = default_config()
        return conf
    with open("conf.toml", "rb") as file:
        return normalize_config(tomllib.load(file))


def tomorrow():
    return (datetime.date.today() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")


def time_to_minutes(value):
    value = normalize_time(value, "00:00")
    hour, minute = value.split(":")[:2]
    return int(hour) * 60 + int(minute)


def normalize_time(value, fallback=""):
    if not value:
        return fallback
    match = re.search(r"(\d{1,2}):(\d{2})", str(value))
    if not match:
        return fallback
    return f"{int(match.group(1)):02d}:{match.group(2)}"


def first_time_value(time_item, *keys, fallback=""):
    if isinstance(time_item, dict):
        for key in keys:
            value = normalize_time(time_item.get(key))
            if value:
                return value
        return fallback
    return normalize_time(time_item, fallback)


def clock_time_today(value):
    value = normalize_time(value)
    hour, minute = [int(part) for part in value.split(":")[:2]]
    return datetime.datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0)


def wait_until_clock_time(value, prompt="没到点呢"):
    target_time = clock_time_today(value)
    while True:
        now = datetime.datetime.now()
        if now >= target_time:
            print()
            return
        print(f"\r{prompt}:{now}", end="", flush=True)
        sleep(min(1, max(0.1, (target_time - now).total_seconds())))


def choose_time(times):
    if not times:
        return {}
    start_limit = time_to_minutes(default_start_time)
    end_limit = time_to_minutes(default_end_time)
    candidates = [time_item for time_item in times if isinstance(time_item, dict)]
    for time_item in candidates:
        start = time_item.get("start") or time_item.get("start_time")
        end = time_item.get("end") or time_item.get("end_time")
        if start and end and time_to_minutes(start) <= start_limit and time_to_minutes(end) >= end_limit:
            return time_item
    if candidates:
        return max(
            candidates,
            key=lambda time_item: time_to_minutes(time_item.get("end") or time_item.get("end_time") or "00:00")
            - time_to_minutes(time_item.get("start") or time_item.get("start_time") or "00:00"),
        )
    return times[0]


def get_space_detail(seat_area):
    result = api_post("/v4/space/detail", {"id": seat_area}, auth=True)
    if result.get("code") != 0:
        print(f"\n读取区域详情失败：{result.get('message') or result.get('msg')}")
        return {}
    return result.get("data") or {}


def get_space_map(seat_area, day=None):
    """从 /v4/Space/map 获取区域地图及日期配置"""
    payload = {"id": seat_area}
    if day:
        payload["day"] = day
    result = api_post("/v4/Space/map", payload, auth=True)
    if result.get("code") != 0:
        return {}
    return result.get("data") or {}


# booking_option 缓存，避免同一 area+day 重复请求 /v4/Space/map
_booking_option_cache = {}


def get_booking_option(seat_area):
    day = tomorrow()
    cache_key = (seat_area, day)
    if cache_key in _booking_option_cache:
        return _booking_option_cache[cache_key]
    option = {
        "day": day,
        "reserve_type": 0,
        "segment": "",
        "start_time": default_start_time,
        "end_time": default_end_time,
        "seat_start_time": default_start_time,
        "seat_end_time": default_end_time,
        "confirm_start_time": default_start_time,
        "confirm_end_time": default_end_time,
    }
    # 优先从 /v4/Space/map 获取日期配置（前端实际使用的接口）
    map_data = get_space_map(seat_area, day)
    date_info = map_data.get("date") if isinstance(map_data, dict) else None
    if not isinstance(date_info, dict):
        # 回退到 /v4/space/detail
        detail = get_space_detail(seat_area)
        date_info = detail.get("date") if isinstance(detail, dict) else None
    if not isinstance(date_info, dict):
        return option

    rows = date_info.get("list") or []
    row = next((date_row for date_row in rows if date_row.get("day") == day), None)
    if row is None and rows:
        row = rows[0]
        option["day"] = row.get("day") or day
    if not row:
        return option

    reserve_type = int(date_info.get("reserveType") or 0)
    option["reserve_type"] = reserve_type
    if reserve_type == 1:
        time_item = choose_time(row.get("times") or [])
        if isinstance(time_item, dict):
            option["segment"] = time_item.get("id") or ""
            option["start_time"] = first_time_value(time_item, "start", "start_time", fallback=default_start_time)
            option["end_time"] = first_time_value(time_item, "end", "end_time", fallback=default_end_time)
            option["seat_start_time"] = option["start_time"]
            option["seat_end_time"] = option["end_time"]
            option["confirm_start_time"] = ""
            option["confirm_end_time"] = ""
    elif reserve_type == 2:
        time_item = choose_time(row.get("times") or [])
        selected_time = first_time_value(time_item, "id", "end", "end_time", fallback=default_end_time)
        option["start_time"] = selected_time
        option["end_time"] = selected_time
        option["seat_start_time"] = selected_time
        option["seat_end_time"] = selected_time
        option["confirm_start_time"] = ""
        option["confirm_end_time"] = selected_time
    elif reserve_type == 3:
        option["start_time"] = normalize_time(
            row.get("def_start_time") or row.get("start_time"), default_start_time
        )
        option["end_time"] = normalize_time(row.get("def_end_time") or row.get("end_time"), default_end_time)
        option["seat_start_time"] = option["start_time"]
        option["seat_end_time"] = option["end_time"]
        option["confirm_start_time"] = option["start_time"]
        option["confirm_end_time"] = option["end_time"]
    _booking_option_cache[cache_key] = option
    return option


def get_seat(seat_area):
    booking_option = get_booking_option(seat_area)
    payload = {
        "id": seat_area,
        "day": booking_option["day"],
        "label_id": [],
        "start_time": booking_option["seat_start_time"],
        "end_time": booking_option["seat_end_time"],
        "begdate": "",
        "enddate": "",
    }
    result = api_post("/v4/Space/seat", payload, auth=True)
    if result.get("code") != 0:
        print(f"\n读取座位失败：{result.get('message') or result.get('msg')}")
        return []
    data = result.get("data") or {}
    if isinstance(data, dict):
        return data.get("list") or []
    return data if isinstance(data, list) else []


def _sanitize_for_toml(obj):
    """Recursively replace None with '' so tomli_w can serialize."""
    if isinstance(obj, dict):
        return {k: _sanitize_for_toml(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_toml(v) for v in obj]
    return obj if obj is not None else ""


def save_config(config):
    with open("conf.toml", "wb") as file:
        tomli_w.dump(_sanitize_for_toml(config), file)


def init_config():
    global conf
    data = []
    with open(
        f"{os.path.realpath(os.path.dirname(__file__))}\\area.csv",
        "r",
        newline="",
        encoding="utf-8",
    ) as csvfile:
        reader = csv.reader(csvfile)
        for row in reader:
            data.append(row)
    print(tabulate(data, headers="firstrow", tablefmt="github"))
    while True:
        seat_area = int(input("输入区域 id: "))
        area_ids = [int(item[0]) for item in data[1:]]
        if seat_area in area_ids:
            conf["seat"]["seat_area"] = seat_area
            break
        print("号不对啊")

    conf["account"]["username"] = input("请输入用户名:")
    conf["account"]["password"] = input("请输入密码:")
    conf = get_cookies(force=True)

    seat_list = get_seat(conf["seat"]["seat_area"])
    if not seat_list:
        print("没读到座位列表，请检查区域或账号状态")
        os.system("pause")
        sys.exit()
    seat_numbers = [int(item["no"]) for item in seat_list if str(item.get("no", "")).isdigit()]
    while True:
        seat_no = int(input(f"输入座位号 ({min(seat_numbers)}~{max(seat_numbers)}):"))
        for seat in seat_list:
            if int(seat.get("no", -1)) == seat_no:
                conf["seat"]["seat_id"] = seat["id"]
                break
        if conf["seat"].get("seat_id"):
            break
        print("号不对啊")

    conf["init"] = False
    save_config(conf)
    return conf


def get_segment(seat_area):
    return get_booking_option(seat_area).get("segment")


def save_captcha_image(base64_image):
    captcha_file = os.path.join(os.path.realpath(os.path.dirname(__file__)), "captcha.png")
    if base64_image:
        image_data = base64_image.split(",", 1)[-1]
        with open(captcha_file, "wb") as file:
            file.write(base64.b64decode(image_data))
        try:
            os.startfile(captcha_file)
        except Exception:
            pass
    return captcha_file


def update_login_data(login_data):
    member = login_data.get("member") if isinstance(login_data.get("member"), dict) else login_data
    token = login_data.get("token") or member.get("token")
    if not token:
        raise RuntimeError("登录成功响应里没有 token")
    conf["data"]["token"] = token
    conf["data"]["date"] = datetime.date.today()
    conf["data"]["user_name"] = member.get("name") or member.get("username") or conf["account"]["username"]
    conf["data"]["userid"] = str(member.get("id") or member.get("userid") or "")
    if conf["seat"].get("seat_area"):
        conf["data"]["segment"] = get_segment(conf["seat"]["seat_area"])


def login_with_cas():
    """通过 CAS REST API 登录（无需验证码）"""
    sso_base = "https://sso.sdyu.edu.cn"
    service_url = f"{base_url}/v4/login/cas"

    session = requests.Session()
    session.headers.update(headers)

    # 获取 TGT
    r = session.post(f"{sso_base}/cas/v1/tickets", data={
        "username": conf["account"]["username"],
        "password": conf["account"]["password"],
    }, timeout=30)
    tgt_url = r.headers.get("Location", "")
    if not tgt_url:
        return None

    # 获取 ST
    r = session.post(tgt_url, data={"service": service_url}, timeout=30)
    st = r.text.strip()
    if not st or st.startswith("<"):
        return None

    # 跟随重定向获取 cas token
    url = f"{base_url}/v4/login/cas?ticket={st}"
    cas_token = ""
    for _ in range(5):
        r = session.get(url, timeout=30, allow_redirects=False)
        location = r.headers.get("Location", "")
        match = re.search(r"cas=([a-f0-9]+)", location or "")
        if match:
            cas_token = match.group(1)
            break
        if not location:
            break
        url = location if location.startswith("http") else f"{base_url}{location}"

    if not cas_token:
        return None

    # 用 cas token 换取 API token
    r = session.post(f"{base_url}/v4/login/user", json={"cas": cas_token}, headers=api_headers, timeout=30)
    result = r.json()
    if result.get("code") != 0:
        return None

    return result.get("data") or {}


def login_with_password():
    # 先尝试 CAS REST API 免验证码登录
    try:
        login_data = login_with_cas()
        if login_data:
            return login_data
    except Exception:
        pass

    # CAS 失败时走传统验证码登录
    while True:
        verify = api_post("/v4/login/verify")
        if verify.get("code") != 0:
            print(f"获取验证码失败：{verify.get('message') or verify.get('msg')}")
            sleep(1)
            continue

        verify_info = verify.get("data") or {}
        captcha_file = save_captcha_image(verify_info.get("base64", ""))
        code = input(f"请输入验证码（已打开 {captcha_file}）:")
        data = {
            "key": verify_info.get("key"),
            "open_id": "",
            "username": conf["account"]["username"],
            "password": conf["account"]["password"],
            "code": code,
        }
        result = api_post("/v4/login/login", data, crypto=True)
        if result.get("code") == 0:
            return result.get("data") or {}

        print(result.get("message") or result.get("msg") or "登录失败")
        change_account = input("账号密码不变直接回车，重新输入账号请输入 n:").strip().lower()
        if change_account == "n":
            conf["account"]["username"] = input("请输入用户名:")
            conf["account"]["password"] = input("请输入密码:")


def get_cookies(force=False):
    global conf
    if conf["data"].get("date") == datetime.date.today() and conf["data"].get("token") and not force:
        return conf

    if not conf["account"].get("username"):
        conf["account"]["username"] = input("请输入用户名:")
    if not conf["account"].get("password"):
        conf["account"]["password"] = input("请输入密码:")

    login_data = login_with_password()
    update_login_data(login_data)
    save_config(conf)
    return conf


def wait_reservation_start():
    global conf
    target_time = clock_time_today(reservation_start_time)
    last_keepalive_minute = None
    while True:
        now = datetime.datetime.now()
        if now >= target_time:
            print()
            return
        print(f"\r没到点呢:{now}", end="", flush=True)
        keepalive_minute = now.strftime("%Y-%m-%d %H:%M")
        # 每 5 分钟做一次心跳，避免触发访问频率限制
        if now.second == 5 and now.minute % 5 == 0 and keepalive_minute != last_keepalive_minute:
            last_keepalive_minute = keepalive_minute
            check_network()
            while True:
                try:
                    result = api_post("/v4/index/subscribe", auth=True)
                    if result.get("code") == 0:
                        break
                    # 遇到限频则等待较长时间再重试
                    msg = result.get("message") or result.get("msg") or ""
                    if "访问频繁" in msg:
                        sleep(30)
                    else:
                        sleep(5)
                except Exception:
                    sleep(1)
        sleep(0.2)


def grab_seat():
    global conf
    # 确保缓存已清除，获取最新 booking option
    _booking_option_cache.pop((conf["seat"]["seat_area"], tomorrow()), None)
    booking_option = get_booking_option(conf["seat"]["seat_area"])
    data = {
        "seat_id": conf["seat"]["seat_id"],
        "segment": booking_option.get("segment") or "",
        "day": booking_option.get("day") or tomorrow(),
        "start_time": booking_option.get("confirm_start_time") or "",
        "end_time": booking_option.get("confirm_end_time") or "",
    }

    retry_times = 5
    attempt = 0
    while attempt < retry_times:
        result = api_post("/v4/space/confirm", data, auth=True, crypto=True)
        print(".", end="", flush=True)
        message = result.get("message") or result.get("msg") or ""
        code = result.get("code")

        if code == 0:
            print(f"\n{message or '预约成功'}", end="", flush=True)
            break
        if "已存在预约" in message or "重复预约" in message:
            print(f"\n你约过别的位了（{message}）")
            break
        if "登录" in message or code == 10001:
            attempt -= 1
            print("\n已在其他设备登录，正在自动登录", end="……", flush=True)
            conf = get_cookies(force=True)
            print("重试", end="", flush=True)
        elif "访问频繁" in message:
            # 解析限频时间戳并等待
            wait_match = re.search(r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})", message)
            if wait_match:
                try:
                    wait_until = datetime.datetime.strptime(wait_match.group(1), "%Y-%m-%d %H:%M:%S")
                    wait_sec = max(5, (wait_until - datetime.datetime.now()).total_seconds() + 3)
                    print(f"\n访问频繁，等待 {int(wait_sec)} 秒后重试……", end="", flush=True)
                    sleep(min(wait_sec, 180))
                    attempt -= 1
                    print("重试", end="", flush=True)
                except Exception:
                    sleep(30)
                    attempt -= 1
            else:
                sleep(30)
                attempt -= 1
        elif "开始预约时间" in message or "未开始" in message:
            attempt -= 1
            start_time = normalize_time(message)
            if start_time and clock_time_today(start_time) > datetime.datetime.now():
                wait_until_clock_time(start_time, f"未到预约开始时间（{start_time}）")
            else:
                sleep(5)
        elif "开放预约时间" in message or "座位开放预约时间" in message or code == 615 or code == 616:
            # 不在预约时间段内，提取时间范围并等待
            # 兼容两种格式: "开放预约时间:12:00:00" 或 "HH:MM:SS~HH:MM:SS"
            time_match = re.search(r"(\d{2}:\d{2}:\d{2})[~～](\d{2}:\d{2}:\d{2})", message)
            if not time_match:
                time_match = re.search(r"(\d{2}:\d{2}:\d{2})", message)
            if time_match:
                open_time = time_match.group(1)
                target = clock_time_today(open_time)
                now = datetime.datetime.now()
                if now < target:
                    print(f"\n未到开放时间（{open_time}），等待中……", end="", flush=True)
                    wait_until_clock_time(open_time, f"等待开放")
                    attempt -= 1
                else:
                    # 已过开放时间，可能是闭馆，等 60 秒再试
                    sleep(60)
                    attempt -= 1
            else:
                sleep(60)
                attempt -= 1
        else:
            print(f"\n预约失败（{message or result}），重试", end="", flush=True)
            sleep(5)  # 失败后等待 5 秒再重试

        attempt += 1


def extract_day(item):
    for key in ("day", "date", "beginTime", "begin_time", "showTime"):
        value = item.get(key)
        if isinstance(value, dict):
            value = value.get("date") or value.get("time")
        if not value:
            continue
        match = re.search(r"\d{4}-\d{2}-\d{2}", str(value))
        if match:
            return match.group(0)
    return ""


def format_reserved(item):
    status = item.get("statusname") or item.get("statusName") or item.get("status_name") or "已预约"
    area = item.get("areaName") or item.get("nameMerge") or item.get("name_merge") or ""
    seat_no = item.get("no") or item.get("spaceName") or item.get("space_name") or ""
    show_time = item.get("showTime") or item.get("bookTimeSegment") or ""
    if not show_time:
        begin_time = item.get("beginTime") or item.get("begin_time") or ""
        end_time = item.get("endTime") or item.get("end_time") or ""
        show_time = f"{begin_time}~{end_time}".strip("~")
    return f"{status}\t{area} {seat_no}\t预约时间:{show_time}"


def get_reserved():
    day = tomorrow()
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            result = api_post("/v4/index/subscribe", auth=True)
            if result.get("code") != 0:
                msg = result.get("message") or result.get("msg") or "未知错误"
                if attempt < max_retries:
                    print(f"\r查询失败（{msg}），{3 - attempt}秒后重试...", end="", flush=True)
                    sleep(3)
                    continue
                print(f"\n查询预约状态失败：{msg}")
                break
            data = result.get("data") or []
            reserved = [
                item
                for item in data
                if int(item.get("type") or 0) in (1, 3, 4)
                and item.get("statusname") != "使用中"
                and extract_day(item) == day
            ]
            if not reserved:
                reserved = [
                    item
                    for item in data
                    if int(item.get("type") or 0) in (1, 3, 4)
                    and item.get("statusname") != "使用中"
                    and not extract_day(item)
                ]
            if reserved:
                for item in reserved:
                    print(format_reserved(item))
            else:
                print("未查询到明天的预约记录，抢座可能失败")
            break
        except Exception:
            if attempt < max_retries:
                print(f"\r查询异常，{3 - attempt}秒后重试...", end="", flush=True)
                sleep(3)
            else:
                print("\n查询预约状态失败：网络异常")


def main():
    if len(sys.argv) > 1:
        do_upgrade()

    print("开始初始化")

    time_sync()
    check_network()
    check_release(current_version)

    global conf
    conf = get_config()
    if conf["init"]:
        conf = init_config()
        print()

    print("初始化完成")

    conf = get_cookies()
    wait_reservation_start()

    # 清除缓存，确保 grab_seat 拿到最新数据
    _booking_option_cache.clear()
    sleep(2)  # 避免和最后一次心跳产生请求突发

    print("开始抢座", end="", flush=True)
    grab_seat()

    print("\n查询预约状态……")
    get_reserved()


if __name__ == "__main__":
    main()
    os.system("pause")
