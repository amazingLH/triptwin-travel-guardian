"""Generate the privacy-safe Stage 5 golden itinerary screenshot."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "assets" / "hangzhou-golden-itinerary.png"


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        Path("C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default(size=size)


def generate(output: Path = OUTPUT) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (1500, 1180), "#F5F7FB")
    draw = ImageDraw.Draw(image)
    navy, blue, muted, white = "#17233C", "#2563EB", "#667085", "#FFFFFF"
    draw.rounded_rectangle((55, 40, 1445, 1140), 30, fill=white, outline="#D9E2F2", width=3)
    draw.text((105, 80), "TRIPTWIN · 合成行程确认单", font=_font(42, bold=True), fill=navy)
    draw.text((105, 140), "仅供比赛演示 · 演示旅客 · 无真实个人信息", font=_font(24), fill=muted)
    draw.rounded_rectangle((1110, 75, 1385, 140), 28, fill="#E8F0FF")
    draw.text((1150, 91), "杭州 2 日行程", font=_font(25, bold=True), fill=blue)

    summary = [
        "行程ID  hangzhou-golden-001        版本  1.0",
        "旅行时间  2026-10-18 08:00  →  2026-10-20 18:00",
        "同行人  成人1 · 老人1（膝关节不适，减少步行和换乘）",
        "预算  ¥1900      Plan B 增量上限  ¥500",
        "约束  最少衔接缓冲20分钟 · 每日步行≤60分钟 · 单段换乘≤1次",
        "受保护事件  train-sh-hz, hotel-west-lake",
    ]
    y = 205
    for line in summary:
        draw.text((110, y), line, font=_font(23), fill=navy)
        y += 42

    events = [
        ("10/18 08:30–10:00", "train-sh-hz · 上海至杭州高铁", "上海虹桥站 → 杭州东站 · ¥150 · 步行5分钟 · 受保护"),
        ("10/18 10:35–11:35", "west-lake-boat · 西湖游船预约", "西湖少年宫码头 · ¥80 · 距上一节点路程45分钟 · 步行20分钟 · 换乘1次"),
        ("10/18 13:00–15:00", "zhejiang-museum · 浙江省博物馆参观", "孤山馆区 · ¥0 · 步行45分钟 · 换乘1次"),
        ("10/18 15:00–10/19 11:00", "hotel-west-lake · 西湖附近酒店", "西湖附近合成酒店 · ¥900 · 1晚 · 受保护"),
        ("10/19 14:00–17:00", "longjing-hike · 龙井村户外徒步", "龙井村 · ¥300 · 步行90分钟 · 换乘2次 · 计划增量¥600"),
    ]
    y = 490
    for index, (when, title, detail) in enumerate(events, start=1):
        top = y + (index - 1) * 122
        draw.ellipse((105, top + 8, 147, top + 50), fill=blue)
        draw.text((119, top + 13), str(index), font=_font(20, bold=True), fill=white)
        if index < len(events):
            draw.line((126, top + 52, 126, top + 116), fill="#B8C7E6", width=4)
        draw.text((175, top), when, font=_font(22, bold=True), fill=blue)
        draw.text((470, top), title, font=_font(24, bold=True), fill=navy)
        draw.text((175, top + 48), detail, font=_font(20), fill=muted)

    draw.rounded_rectangle((105, 1090, 1390, 1125), 12, fill="#FFF4E5")
    draw.text((125, 1094), "提示：价格与库存具有时效性；本系统仅做风险分析和候选推荐，不代订、不支付。", font=_font(19), fill="#9A5B00")
    image.save(output, format="PNG", optimize=True)
    return output


if __name__ == "__main__":
    print(generate())
