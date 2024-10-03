import csv
import datetime
import os
import subprocess
import sys
from time import sleep
import tomllib
from bs4 import BeautifulSoup
from tabulate import tabulate
import wget
from packaging.version import Version
import tomli_w
import requests

current_version = "1.5.6"


def time_sync():
    script_file = f"{os.path.realpath(os.path.dirname(__file__))}\\timeSync.ps1"
    script_contents = '''$service = Get-Service w32time
    if ($service.Status -eq 'Stopped') {
        Start-Process powershell -Verb RunAs -ArgumentList "-Command ""Set-Service -Name w32time -StartupType Automatic; Start-Service w32time; w32tm /resync""";
    }
    '''

    with open(script_file, "w") as f:
        f.write(script_contents)

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

    with open(script_file, "w") as f:
        f.write(script_contents)

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
    f = 0
    while True:
        try:
            r = requests.head(url=url, timeout=5)
            r.raise_for_status()
            break
        except Exception:
            if f == 0:
                f += 1
            elif f == 1:
                print(
                    "\n连不上啊，登校园网了吗？http://123.123.123.123/",
                    end=" ",
                    flush=True,
                )
                f += 1
            else:
                print(".", end="", flush=True)
            sleep(1)
    if not f:
        print("\r")


def check_release(current_version):
    url = "https://api.github.com/repos/dunxuan/sdyu_seat/releases/latest"
    try:
        latest_version = requests.get(url=url).json()["name"]
    except Exception:
        return False

    if Version(latest_version) > Version(current_version):
        print(f"有新版本({latest_version})了，更新后会自动重启程序")
        url = f"https://gh-proxy.com/https://github.com/dunxuan/sdyu_seat/releases/download/{latest_version}/sdyu_seat.exe"
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
    else:
        return True


def get_config():
    global conf
    if not os.path.exists("conf.toml"):
        conf = {
            "seat": {"seat_area": None, "seat_id": None},
            "account": {"username": None, "password": None},
            "data": {
                "date": None,
                "segment": None,
                "auto_user_check_url": None,
                "access_token": None,
                "expire": None,
                "user_name": None,
                "userid": None,
            },
            "init": True,
        }
        return conf
    else:
        with open("conf.toml", "rb") as f:
            return tomllib.load(f)


def get_seat(seat_area):
    day = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    url = "https://lxl.sdyu.edu.cn/api.php/spaces_old"
    params = {
        "area": f"{seat_area}",
        "day": day,
        "startTime": "08:30",
        "endTime": "22:30",
    }
    while True:
        try:
            r = requests.get(url=url, params=params)
            break
        except Exception:
            sleep(1)
    return r.json()["data"]["list"]


def save_config(conf):
    with open("conf.toml", "wb") as f:
        tomli_w.dump(conf, f)


def init_config():
    global conf
    # 区域
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
        ids = [int(item[0]) for item in data[1:]]
        if seat_area in ids:
            conf["seat"]["seat_area"] = seat_area
            break
        else:
            print("号不对啊")

    # 座位
    data = get_seat(conf["seat"]["seat_area"])
    min_seat = data[0]["no"]
    max_seat = data[-1]["no"]
    while True:
        seat_no = int(input(f"输入座位号 ({min_seat}~{max_seat}):"))
        if seat_no >= int(min_seat) and seat_no <= int(max_seat):
            for item in data:
                if int(item["no"]) == seat_no:
                    conf["seat"]["seat_id"] = item["id"]
                    break
            break
        else:
            print("号不对啊")

    # 账号
    conf["account"]["username"] = input("请输入用户名:")
    conf["account"]["password"] = input("请输入密码:")

    conf = get_cookies(conf)

    conf["init"] = False
    save_config(conf)
    return conf


def get_segment(seat_area):
    url = f"https://lxl.sdyu.edu.cn/api.php/v3areadays/{seat_area}"
    while True:
        try:
            r = requests.get(url=url).json()
            break
        except Exception:
            sleep(1)
    return r["data"]["list"][1]["id"]


def get_cookies(force=False):
    global conf
    if conf["data"]["date"] == datetime.date.today() and not force:
        return conf

    # url = "https://lxl.sdyu.edu.cn/api.php/logout"
    # data = {
    #     "access_token": conf["data"]["access_token"],
    #     "userid": conf["data"]["userid"],
    # }
    # cookies = dict(
    #     access_token=conf["data"]["access_token"],
    #     expire=conf["data"]["expire"],
    #     user_name=conf["data"]["user_name"],
    #     userid=conf["data"]["userid"],
    # )
    # while True:
    #     try:
    #         r = requests.post(url=url, data=data, cookies=cookies)
    #         r.raise_for_status()
    #         break
    #     except Exception:
    #         pass

    if conf["data"]["date"] != datetime.date.today():
        url = "https://iids.sdyu.edu.cn/sso/apis/v2/open/captcha"
        while True:
            try:
                r = requests.get(url=url)
                r.raise_for_status()
                token = r.json()["token"]
                break
            except Exception:
                pass

        s = requests.Session()
        url = "https://iids.sdyu.edu.cn/cas/login"
        params = {
            "service": "https://lxl.sdyu.edu.cn/cas/index.php?callback=https://lxl.sdyu.edu.cn/home/web/f_second",
        }
        while True:
            try:
                r = s.get(url=url, params=params)
                r.raise_for_status()
                soup = BeautifulSoup(r.text, "html.parser")
                lt = soup.find("input", {"name": "lt"}).get("value")
                execution = soup.find("input", {"name": "execution"}).get("value")
                break
            except Exception:
                pass

        data = {
            "username": conf["account"]["username"],
            "password": conf["account"]["password"],
            "captcha": "123456",
            "token": token,
            "_eventId": "submit",
            "lt": lt,
            "source": "cas",
            "execution": execution,
        }
        while True:
            while True:
                try:
                    r = s.post(url=url, data=data)
                    r.raise_for_status()
                    break
                except Exception:
                    pass

            if r.history:
                break

            soup = BeautifulSoup(r.text, "html.parser")
            print(soup.find("span", {"id": "errormes"}).get("value"))
            conf["account"]["username"] = input("请输入用户名:")
            conf["account"]["password"] = input("请输入密码:")
            data.update(
                {
                    "username": conf["account"]["username"],
                    "password": conf["account"]["password"],
                }
            )

        conf["data"]["auto_user_check_url"] = r.url
        conf["data"]["date"] = datetime.date.today()
        conf["data"]["segment"] = get_segment(conf["seat"]["seat_area"])

    else:
        url = conf["data"]["auto_user_check_url"]
        while True:
            try:
                r = requests.head(url=url)
                r.raise_for_status()
                break
            except Exception:
                pass

    cookies = r.cookies.get_dict()
    conf["data"]["access_token"] = cookies["access_token"]
    conf["data"]["expire"] = cookies["expire"]
    conf["data"]["user_name"] = cookies["user_name"]
    conf["data"]["userid"] = cookies["userid"]

    save_config(conf)
    return conf


def wait_12():
    global conf
    target_time = datetime.datetime.now().replace(hour=12, minute=0, second=0)
    url = "https://lxl.sdyu.edu.cn/api.php/profile"
    while True:
        now = datetime.datetime.now()
        if now >= target_time:
            print()
            return
        print(f"\r没到点呢:{now}", end="", flush=True)
        if now.second == 5:
            check_network()
            while True:
                cookies = dict(
                    access_token=conf["data"]["access_token"],
                    expire=conf["data"]["expire"],
                    user_name=conf["data"]["user_name"],
                    userid=conf["data"]["userid"],
                )
                try:
                    r = requests.get(url=url, cookies=cookies).json()
                    if r["status"] == 0:
                        print("\n已在其他设备登录，正在自动登录")
                        conf = get_cookies(force=True)
                except Exception:
                    sleep(1)
                if r["status"] == 1:
                    break


def grab_seat():
    global conf
    url = f"https://lxl.sdyu.edu.cn/api.php/spaces/{conf['seat']['seat_id']}/book"
    data = {
        "access_token": conf["data"]["access_token"],
        "userid": conf["data"]["userid"],
        "segment": conf["data"]["segment"],
        "type": "1",
        "operateChannel": "2",
    }
    day = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    headers = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Host": "lxl.sdyu.edu.cn",
        "Origin": "https://lxl.sdyu.edu.cn",
        "Referer": f"https://lxl.sdyu.edu.cn/web/seat3?area={conf['seat']['seat_area']}&segment={conf['data']['segment']}&day={day}&startTime=18:00&endTime=22:30",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0",
        "X-Requested-With": "XMLHttpRequest",
        "sec-ch-ua": '"Microsoft Edge";v="129", "Not=A?Brand";v="8", "Chromium";v="129"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    }
    cookies = dict(
        access_token=conf["data"]["access_token"],
        expire=conf["data"]["expire"],
        user_name=conf["data"]["user_name"],
        userid=conf["data"]["userid"],
    )

    retry_times = 3
    for _ in range(retry_times):
        while True:
            try:
                response = requests.post(
                    url=url,
                    data=data,
                    headers=headers,
                    cookies=cookies,
                    timeout=30,
                )
                response.raise_for_status()
                r = response.json()
                break
            except Exception:
                # sleep(1)
                pass
            finally:
                print(".", end="", flush=True)

        print()
        try:
            if r["status"] == 0:
                if (
                    r["msg"] == "参数错误"
                    or r["msg"] == "该空间当前状态不可预约"
                    or r["msg"] == "预约超时，请重新预约"
                ):
                    print(f"可能成功（{r['msg']}），重试", end="", flush=True)

                elif r["msg"] == "当前用户在该时段已存在预约，不可重复预约":
                    print(f"你约过别的位了（{r['msg']}）")
                    break

                elif r["msg"] == "由于您长时间未操作，正在重新登录":
                    print("已在其他设备登录，正在自动登录", end="……", flush=True)
                    conf = get_cookies(force=True)
                    data.update(
                        {
                            "access_token": conf["data"]["access_token"],
                        }
                    )
                    cookies.update(
                        {
                            "access_token": conf["data"]["access_token"],
                            "expire": conf["data"]["expire"],
                        }
                    )
                    print("重试", end="", flush=True)

                elif r["msg"].startswith("访问频繁！"):
                    print(r["msg"], end="", flush=True)
                    break

                else:
                    print(r)

            elif r["status"] == 1:
                print(r["msg"], end="", flush=True)
                break

        except Exception:
            sleep(1)


def get_reserved():
    global conf
    day = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    url = "https://lxl.sdyu.edu.cn/api.php/profile/books"
    while True:
        cookies = dict(
            access_token=conf["data"]["access_token"],
            expire=conf["data"]["expire"],
            user_name=conf["data"]["user_name"],
            userid=conf["data"]["userid"],
        )
        try:
            r = requests.get(url=url, cookies=cookies).json()
            if r["status"] == 1:
                data = r["data"]["list"][0]
                if data["beginTime"]["date"][:10] == day:
                    print(
                        f"{data['statusName']}\t{data['spaceDetailInfo']['areaInfo']['nameMerge']} {data['spaceDetailInfo']['no']}\t预约时间:{data['bookTimeSegment']}"
                    )
                else:
                    print("抢座失败")
                break
            elif r["status"] == 0 and r["msg"] == "由于您长时间未操作，正在重新登录":
                print("已在其他设备登录，正在自动登录")
                conf = get_cookies(force=True)
            else:
                print(f"{r['status']}\t{r['msg']}")
        except Exception:
            sleep(1)


def main():
    # 进行更新
    if len(sys.argv) > 1:
        do_upgrade()

    print("开始初始化")

    # 校时
    time_sync()

    # 检查网络情况
    check_network()

    # 检查更新
    check_release(current_version)

    # 读取配置
    global conf
    conf = get_config()
    if conf["init"]:
        conf = init_config()

    print("\n初始化完成")

    # Cookies
    conf = get_cookies()

    # 计时
    wait_12()

    print("开始抢座", end="", flush=True)

    # 抢座
    grab_seat()

    print("\n\n查询预约状态……")

    # 查看预约状态
    get_reserved()

    print("\n如果没有明天的座位信息，说明抢座失败了")


if __name__ == "__main__":
    main()

    os.system("pause")
