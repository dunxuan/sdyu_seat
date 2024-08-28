import datetime
import os
import re
import sys
from time import sleep
import tomllib
import webbrowser
from bs4 import BeautifulSoup
import tomli_w
import requests
import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By


def get_config():
    global conf
    if not os.path.exists("conf.toml"):
        conf = {
            "seat": {"seat_area": None, "seat_id": None},
            "account": {"username": None, "password": None},
            "data": {
                "date": None,
                "segment": None,
                "PHPSESSID": None,
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
    r = requests.get(url=url, params=params)
    return r.json()["data"]["list"]


def save_config(conf):
    with open("conf.toml", "wb") as f:
        tomli_w.dump(conf, f)


def init_config():
    global conf
    # 区域
    df = pd.read_csv(os.path.realpath(os.path.dirname(__file__)) + os.sep + "area.csv")
    print(df.to_string(index=False))
    while True:
        conf["seat"]["seat_area"] = int(input("输入区域id:"))
        if conf["seat"]["seat_area"] in df["id"].values:
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
    r = requests.get(url=url)
    return r.json()["data"]["list"][1]["id"]


def get_cookies(force=False):
    global conf
    if conf["data"]["date"] == datetime.date.today() and force is False:
        return conf

    options = webdriver.EdgeOptions()
    options.add_argument("--start-maximized")
    options.add_experimental_option("detach", True)
    driver = webdriver.Edge(options=options)
    driver.get(
        "https://iids.sdyu.edu.cn/cas/login?service=https://lxl.sdyu.edu.cn/cas/index.php?callback=https://lxl.sdyu.edu.cn/home/web/f_second"
    )

    driver.find_element(
        By.XPATH, "/html/body/div/div[2]/div/div/div/div[2]/label/span[2]"
    ).click()
    driver.find_element(By.NAME, "username").send_keys(conf["account"]["username"])
    driver.find_element(By.NAME, "password").send_keys(conf["account"]["password"])
    driver.find_element(By.NAME, "captcha").click()

    while True:
        sleep(1)
        if driver.current_url == "https://lxl.sdyu.edu.cn/home/web/f_second":
            break

    conf["data"]["PHPSESSID"] = driver.get_cookie("PHPSESSID")["value"]
    conf["data"]["access_token"] = driver.get_cookie("access_token")["value"]
    conf["data"]["expire"] = driver.get_cookie("expire")["value"]
    conf["data"]["user_name"] = driver.get_cookie("user_name")["value"]
    conf["data"]["userid"] = driver.get_cookie("userid")["value"]

    driver.quit()

    conf["data"]["date"] = datetime.date.today()
    conf["data"]["segment"] = get_segment(conf["seat"]["seat_area"])

    save_config(conf)
    return conf


def wait_12():
    global conf
    target_time = datetime.datetime.now().replace(hour=12, minute=0, second=0)
    i = 0
    url = "https://lxl.sdyu.edu.cn/user/index/book"
    cookies = dict(
        PHPSESSID=conf["data"]["PHPSESSID"],
        access_token=conf["data"]["access_token"],
        expire=conf["data"]["expire"],
        user_name=conf["data"]["user_name"],
        userid=conf["data"]["userid"],
    )
    while True:
        if i % 1000000 == 0:
            r = requests.get(url=url, cookies=cookies)
            if len(r.history) == 2:
                print("已在其他设备登录，正在重新登录")
                conf = get_cookies(force=True)
                cookies = dict(
                    PHPSESSID=conf["data"]["PHPSESSID"],
                    access_token=conf["data"]["access_token"],
                    expire=conf["data"]["expire"],
                    user_name=conf["data"]["user_name"],
                    userid=conf["data"]["userid"],
                )
        i += 1
        if datetime.datetime.now() >= target_time:
            print()
            return
        print(f"\r没到点呢:{datetime.datetime.now()}", end="")


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
    headers = {
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 Edg/128.0.0.0",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }
    cookies = dict(
        PHPSESSID=conf["data"]["PHPSESSID"],
        access_token=conf["data"]["access_token"],
        expire=conf["data"]["expire"],
        user_name=conf["data"]["user_name"],
        userid=conf["data"]["userid"],
    )
    retry_times = 10
    for _ in range(retry_times):
        r = requests.post(
            url=url,
            data=data,
            headers=headers,
            cookies=cookies,
        )
        print(r.json()["msg"])

        if r.json()["status"] == 0:
            if (
                r.json()["msg"] == "参数错误"
                or r.json()["msg"] == "该空间当前状态不可预约"
            ):
                print("来晚了，被约了")
                break
            if r.json()["msg"] == "预约超时，请重新预约":
                print("可能约成功了，重试……")
                sleep(1)
            if r.json()["msg"] == "当前用户在该时段已存在预约，不可重复预约":
                print("你约过别的位了")
                break
            if r.json()["msg"] == "由于您长时间未操作，正在重新登录":
                conf = get_cookies(force=True)
                cookies = dict(
                    PHPSESSID=conf["data"]["PHPSESSID"],
                    access_token=conf["data"]["access_token"],
                    expire=conf["data"]["expire"],
                    user_name=conf["data"]["user_name"],
                    userid=conf["data"]["userid"],
                )
        elif r.json()["status"] == 1:
            break


def get_reserved():
    global conf
    cookies = dict(
        PHPSESSID=conf["data"]["PHPSESSID"],
        access_token=conf["data"]["access_token"],
        expire=conf["data"]["expire"],
        user_name=conf["data"]["user_name"],
        userid=conf["data"]["userid"],
    )
    r = requests.get("https://lxl.sdyu.edu.cn/user/index/book", cookies=cookies)
    for tr in (
        BeautifulSoup(r.text, "html.parser")
        .find("table", id="menu_table")
        .select("tbody tr")
    ):
        tds = tr.find_all("td")
        if "预约成功" in tds[4].text:
            print(re.sub(r"\s|\t|\n", "", tds[1].text), end="\t\t")
            print(re.sub(r"\s|\t|\n", "", tds[2].text[0:10]))


def main():
    # 读取配置
    global conf
    conf = get_config()
    if conf["init"]:
        conf = init_config()
    print("初始化完成")

    # Cookies
    conf = get_cookies()
    print("开始抢座")

    # 计时
    wait_12()

    # 抢座
    grab_seat()
    print()

    # 查看预约状态
    get_reserved()
    print("如果没有明天的座位信息，说明抢座失败了")


def check_release(current_version):
    url = "https://api.github.com/repos/dunxuan/sdyu_seat/tags"
    latest_tag = requests.get(url=url).json()[0]["name"]
    if latest_tag != current_version:
        print(
            f"自动下载中，下完了解压并覆盖:https://mirror.ghproxy.com/?q=https://github.com/dunxuan/sdyu_seat/releases/download/{latest_tag}/sdyu_seat.exe"
        )
        webbrowser.open(
            f"https://mirror.ghproxy.com/?q=https://github.com/dunxuan/sdyu_seat/releases/download/{latest_tag}/sdyu_seat.exe"
        )
        os.system("pause")
        sys.exit(0)


if __name__ == "__main__":
    # 检查更新
    current_version = "1.2.4"
    check_release(current_version)

    main()

    os.system("pause")
