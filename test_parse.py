import json
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.bili_api import BiliClient, BiliError, parse_input


def main():
    client = BiliClient()
    print("== nav:", client.nav() and client.nav().get("isLogin"))

    test_inputs = sys.argv[1:]
    if not test_inputs:
        test_inputs = ["https://www.bilibili.com/video/BV1HpuR6EE7V",
                       "https://www.bilibili.com/video/BV1BMgj6MEz4",
                       "https://www.bilibili.com/video/BV1ucb96VEXk?p=1"]
        print("== 使用内置测试视频")

    for inp in test_inputs:
        print("\n===== 输入:", inp)
        try:
            print("parse_input ->", parse_input(inp))
            tasks = client.resolve(inp, include_parts=True)
            fi = tasks[0].formats if tasks else None
            print("任务数:", len(tasks))
            for t in tasks[:10]:
                print("  P{} {} [{}] {}s {}".format(
                    t.page, t.part_title[:40], t.bvid, t.duration, t.url))
            if fi:
                print("画质列表:", [(q, d) for q, d in fi.qns])
                print("编码:", sorted(fi.codecs))
        except BiliError as e:
            print("解析失败:", e)


if __name__ == "__main__":
    main()