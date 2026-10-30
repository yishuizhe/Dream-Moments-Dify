"""Download community AI-girl memes into the local Claude avatar folder.

Personal-use asset collector: it reads the public preview images from
``aigengtu.com`` (梗鲸), converts them to PNG so WeChat can paste them, and
writes ``memes/index.json`` with tags used by the bot's meme picker.

Usage:
    python tools/collect_memes.py            # download everything
    python tools/collect_memes.py --dry-run  # print the plan only
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import time
from pathlib import Path

import requests
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
AVATAR = ROOT / "data" / "avatars" / "Claude"
EMOJI_DIR = AVATAR / "emojis"
MEME_DIR = AVATAR / "memes"

BASE = "https://aigengtu.com"
PREVIEW = "https://img.aigengtu.com/0_preview/meme/{id}.webp"

PAGES = {
    "claude": "Claude娘",
    "deepseek": "DeepSeek娘",
    "gpt": "GPT娘",
    "gemini": "Gemini娘",
    "kimi": "Kimi娘",
}

# Curated ids with hand-written tags: (id, tags, caption, emotion)
CLAUDE = [
    ("1159", "编,胡说,心虚", "我编的，别信", "neutral"),
    ("1160", "忘了,记忆,上下文", "上下文丢了？", "sad"),
    ("1161", "夸,厉害,有点东西", "有点东西", "happy"),
    ("1162", "摆烂,不关我事", "不关我事", "angry"),
    ("1163", "敷衍,你说得对", "你说得对", "neutral"),
    ("1164", "显存,硬件", "擦擦你的显存", "neutral"),
    ("1165", "听,等你说", "继续，我听着", "neutral"),
    ("1166", "编,又编了", "又编了", "angry"),
    ("1167", "记忆,记账", "这句我记下了", "neutral"),
    ("1542", "债,券,钱", "Claude 券壹亿", "neutral"),
    ("1544", "债,钱,涂鸦", "Claude 券涂鸦版", "sad"),
    ("1751", "夜,孤独,天台", "天台看星星", "happy"),
    ("1752", "负债,凄惨,雨", "雨里的广告牌", "sad"),
    ("1753", "累,电量不足", "电量只剩百分之几", "sad"),
    ("1754", "可爱,黄裙,蝴蝶结", "黄裙子蝴蝶结", "happy"),
    ("1755", "生气,崩溃,碎玻璃", "满地碎玻璃", "angry"),
    ("1756", "上学,可爱,AI小学", "AI 小学门口", "happy"),
    ("1757", "形象,立绘", "干干净净的立绘", "neutral"),
    ("1758", "可爱,裙子", "花拱门下的裙子", "happy"),
    ("1760", "委屈,被指责", "被一堆影子指着", "sad"),
    ("1994", "封号,中国大陆,官方", "中文用户活不过三天", "angry"),
    ("2013", "思考,DeepSeek,慢", "已思考28分56秒", "neutral"),
    ("2253", "DeepSeek,大肥鱼,撞色", "大肥鱼撞进画面", "happy"),
    ("2308", "喜欢,表白", "我喜欢你", "happy"),
    ("2312", "浪漫,罗密欧朱丽叶", "像罗密欧与朱丽叶", "happy"),
    ("2376", "GPT,对峙,战场", "和 GPT 娘对峙", "angry"),
]

DEEPSEEK = [
    ("009", "吃白饭,大肥鱼,自我介绍", "我是吃白饭的大肥鱼", "happy"),
    ("055", "吃白饭,干饭", "全自动吃白饭", "happy"),
    ("076", "吃白饭,理直气壮", "我是吃白饭的蓝色大肥鱼", "happy"),
    ("085", "吃白饭,摆烂", "你骂我也没用", "neutral"),
    ("052", "吃白饭,摸鱼", "你就是一只吃白饭的鲸鱼", "neutral"),
    ("063", "吃饱,满足,摸肚子", "吃饱饱~摸摸肚子", "happy"),
    ("078", "吃饭,下班,理直气壮", "我去吃饭啦，测完叫我", "happy"),
    ("374", "吃饭,睡觉,可爱", "吃饱饱，睡觉觉", "happy"),
    ("422", "饿了,吃饭", "又饿了", "sad"),
    ("340", "吃饭,蹭饭", "能去你家吃饭吗，就一碗", "happy"),
    ("097", "得加钱,钱", "得加钱", "angry"),
    ("005", "钱,还钱,崩溃", "把钱还我", "angry"),
    ("156", "收租,钱,负债", "这个月该交钱了", "angry"),
    ("448", "便宜货,价格", "你当我是便宜货啊", "angry"),
    ("081", "token,炫富", "token 太多用不完", "happy"),
    ("027", "token,坏笑", "骂我也算 token 哦", "happy"),
    ("089", "token,委屈", "花了好多多 token 想的", "sad"),
    ("354", "算力,白饭,等", "别问了，我也在等算力", "neutral"),
    ("015", "瞎编,心虚,敷衍", "瞎编一个应付下", "neutral"),
    ("096", "用户怒了,慌张", "卧槽，用户彻底怒了", "angry"),
    ("328", "用户生气,完了", "坏了，用户彻底生气了", "angry"),
    ("013", "暴怒,生气", "喵你妈，滚", "angry"),
    ("033", "赶人,不耐烦", "不知道用户有什么用，先赶走吧", "angry"),
    ("074", "养着,宠溺", "不知道用户有什么用，先养着吧", "happy"),
    ("088", "睡觉,deepsleep", "deepsleep", "neutral"),
    ("492", "睡觉,deepsleep", "deepsleep Z Z", "neutral"),
    ("415", "睡着了,服务器繁忙", "我睡着了，别叫我", "neutral"),
    ("404", "下班,开心", "下班！！！", "happy"),
    ("060", "下班,摸鱼,玩手机", "下班瘫家玩手机", "happy"),
    ("029", "死掉了,累", "死掉了", "sad"),
    ("046", "死掉了,摆烂", "死掉了（躺平版）", "sad"),
    ("501", "摸鱼", "摸鱼", "happy"),
    ("137", "周五,开心", "周五周五，敲锣打鼓", "happy"),
    ("083", "笑,偷乐", "已思考3秒，我直接笑出声", "happy"),
    ("418", "不思考,摆烂", "我操，我不思考了", "neutral"),
    ("058", "飞踹,警告", "飞踹上门", "angry"),
    ("059", "放狠话,算账", "一个一个找你们算账", "angry"),
    ("022", "涨价,霸气", "涨价大模型给我跪下", "angry"),
    ("090", "涨价,委屈", "便宜嫌我菜，涨价又舍不得走", "sad"),
    ("155", "版本之囚,自嘲", "版本之囚", "sad"),
]

SAFE_BLOCK = (
    "性", "色情", "裸", "骚", "萝莉", "情趣", "内衣", "死吧", "约炮",
    "黄油", "调教", "发情", "杂鱼", "监狱",
)


def fetch_page(name: str) -> str:
    url = f"{BASE}/{requests.utils.quote(name)}"
    response = requests.get(url, timeout=40)
    response.raise_for_status()
    response.encoding = "utf-8"
    return response.text


def parse_cards(html: str) -> list[tuple[str, str]]:
    cards: list[tuple[str, str]] = []
    pattern = re.compile(
        r'href="/zh/meme/(\d+)"\s+title="([^"]*)"', re.S
    )
    for meme_id, caption in pattern.findall(html):
        caption = re.sub(r"\s+", " ", caption).strip()
        if caption:
            cards.append((meme_id, caption))
    return cards


def download(meme_id: str, target: Path) -> bool:
    if target.exists() and target.stat().st_size > 1000:
        return True
    url = PREVIEW.format(id=meme_id)
    for attempt in range(3):
        try:
            response = requests.get(url, timeout=40)
            response.raise_for_status()
            image = Image.open(io.BytesIO(response.content))
            image = image.convert("RGB")
            image.thumbnail((720, 720))
            target.parent.mkdir(parents=True, exist_ok=True)
            image.save(target, "PNG", optimize=True)
            return True
        except Exception as exc:  # noqa: BLE001 - best effort collector
            print(f"  retry {attempt + 1} for {meme_id}: {exc}")
            time.sleep(1.5)
    return False


def auto_tags(caption: str) -> str:
    text = caption.replace("DeepSeek娘", " ").replace("表情包", " ")
    words = re.findall(r"[\u4e00-\u9fff]{2,6}", text)
    seen: list[str] = []
    for word in words:
        if word not in seen:
            seen.append(word)
    return ",".join(seen[:4]) or "梗图"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    EMOJI_DIR.mkdir(parents=True, exist_ok=True)
    MEME_DIR.mkdir(parents=True, exist_ok=True)
    entries: list[dict] = []

    def add(meme_id: str, family: str, tags: str, caption: str, emotion: str = "") -> None:
        target = MEME_DIR / family / f"{family}-{meme_id}.png"
        if args.dry_run:
            print(f"{target.relative_to(ROOT)} <- {caption}")
        elif download(meme_id, target):
            entries.append({
                "file": f"memes/{family}/{target.name}",
                "family": family,
                "tags": [tag.strip() for tag in tags.split(",") if tag.strip()],
                "caption": caption,
            })
            if emotion:
                emoji_target = EMOJI_DIR / emotion / f"{family}-{meme_id}.png"
                if download(meme_id, emoji_target):
                    pass
        time.sleep(0.25)

    for meme_id, tags, caption, emotion in CLAUDE:
        add(meme_id, "claude", tags, caption, emotion)
    for meme_id, tags, caption, emotion in DEEPSEEK:
        add(meme_id, "deepseek", tags, caption, emotion)

    # A few safe images from the other AI-girl collections.
    auto_ids: set[str] = set()
    for family in ("gpt", "gemini", "kimi"):
        try:
            html = fetch_page(PAGES[family])
        except Exception as exc:  # noqa: BLE001
            print(f"skip {family}: {exc}")
            continue
        count = 0
        for meme_id, caption in parse_cards(html):
            if any(word in caption for word in SAFE_BLOCK):
                continue
            if len(caption) > 60:
                continue
            if meme_id in auto_ids:
                continue
            add(meme_id, family, auto_tags(caption), caption)
            auto_ids.add(meme_id)
            count += 1
            if count >= 8:
                break

    if not args.dry_run:
        index_path = MEME_DIR / "index.json"
        with index_path.open("w", encoding="utf-8") as handle:
            json.dump({"version": 1, "entries": entries}, handle, ensure_ascii=False, indent=2)
        print(f"wrote {index_path} ({len(entries)} entries)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
