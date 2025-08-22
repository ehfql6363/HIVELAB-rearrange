from __future__ import annotations
import re
import shutil
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Any, List, Optional, Tuple
from threading import Event
from PIL import Image, ImageDraw, ImageFont, ImageOps
from datetime import datetime
try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:
    ZoneInfo = None
from ..i18n_loader import _

ACCOUNT_NUM_RE = re.compile(r"(\d+)")
POST_NUM_RE = re.compile(r"^\s*(\d+)\.")

# Post order sequences
SEQ = {
    "월": {
        "유미": [5, 1, 4, 2, 3],
        "상근": [2, 1, 5, 4, 3],
    },
    "화": {
        "유미": [3, 2, 5, 1, 4],
        "상근": [4, 3, 2, 5, 1],
    },
}

# Slot ranges (1-based)
SLOT_RANGES = {
    "ㄱ": [1, 2, 3],      # A(1,2,3) -> slots 1..3
    "ㄴ": [4, 5, 6],      # A(4,5,6) -> slots 4..6
    "ㄷ": [7, 8, 9],      # B(1,2,3) -> slots 7..9
    "ㄹ": [10, 11, 12],   # B(4,5,6) -> slots 10..12
}

weekdays = ["월", "화", "수", "목", "금", "토", "일"]

IMAGE_EXTS = {".jpg",".jpeg",".png",".webp",".bmp",".tiff"}

def _is_image_file(p: Path) -> bool:
    return p.is_file() and p.suffix.lower() in IMAGE_EXTS

def _rgba_from_hex(hex_color: str, alpha_pct: int) -> tuple[int,int,int,int]:
    hex_color = (hex_color or "#FFFFFF").lstrip("#")
    if len(hex_color) == 3:
        hex_color = "".join(ch*2 for ch in hex_color)
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    a = max(0, min(255, int(255 * (alpha_pct/100.0))))
    return (r,g,b,a)

def _calc_position(w: int, h: int, tw: int, th: int, preset: str, dx: int, dy: int) -> tuple[int,int]:
    # preset: top-left/top-right/bottom-left/bottom-right/center
    if preset == "top-left":
        x, y = 0 + dx, 0 + dy
    elif preset == "top-right":
        x, y = w - tw - dx, 0 + dy
    elif preset == "bottom-left":
        x, y = 0 + dx, h - th - dy
    elif preset == "bottom-right":
        x, y = w - tw - dx, h - th - dy
    else:  # center
        x, y = (w - tw)//2 + dx, (h - th)//2 + dy
    return (x, y)

def _apply_text_watermark(img: Image.Image, wm: dict) -> Image.Image:
    if not wm.get("enabled"):
        return img

    text = wm.get("text") or ""
    if not text.strip():
        return img

    font_size = max(6, int(wm.get("font_size", 36)))
    font_path = (wm.get("font_path") or "").strip()
    try:
        if font_path:
            font = ImageFont.truetype(font_path, font_size)
        else:
            font = ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()

    # 작업은 RGBA에서
    if img.mode != "RGBA":
        base = img.convert("RGBA")
    else:
        base = img.copy()

    W, H = base.size
    overlay = Image.new("RGBA", (W, H), (0,0,0,0))
    draw = ImageDraw.Draw(overlay)

    # 텍스트 바운딩 계산
    try:
        bbox = draw.multiline_textbbox((0,0), text, font=font, align="left")
        tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]
    except Exception:
        tw, th = draw.multiline_textsize(text, font=font)

    x, y = _calc_position(W, H, tw, th,
                          wm.get("position","bottom-right"),
                          int(wm.get("offset_x",16)),
                          int(wm.get("offset_y",16)))

    fill = _rgba_from_hex(wm.get("color","#FFFFFF"), int(wm.get("opacity",50)))

    # 외곽선
    if wm.get("outline", True):
        ow = max(1, int(wm.get("outline_width", 2)))
        outline_fill = (0,0,0, fill[3])  # 검정, 동일 알파
        # 8방향 반복
        for r in range(1, ow+1):
            for dx, dy in ((-r,0),(r,0),(0,-r),(0,r),(-r,-r),(-r,r),(r,-r),(r,r)):
                draw.multiline_text((x+dx, y+dy), text, font=font, fill=outline_fill)

    # 본문
    draw.multiline_text((x, y), text, font=font, fill=fill)

    out = Image.alpha_composite(base, overlay).convert(img.mode)
    return out


def _today_kor_daychar(tz_name: str = "Asia/Seoul") -> str:
    try:
        if ZoneInfo:
            idx = datetime.now(ZoneInfo(tz_name)).weekday()
        else:
            idx = datetime.now().weekday()
    except Exception:
        idx = datetime.now().weekday()
    return weekdays[idx]

def _day_of_week(idx: int) -> str:
    return weekdays[idx % 7]

def _dow_of_idx(dow: str) -> int:
    return weekdays.index(dow)

def _next_of_now(now: str, nxt: int) -> str:
    return _day_of_week(_dow_of_idx(now) + nxt)


@dataclass
class TargetSlot:
    name: str
    existing_path: Optional[Path]  # if provided, use it directly

def _find_account_dirs(group_root: Path) -> Dict[int, Path]:
    """
    Detect account folders under group_root. Mapped by first integer in folder name.
    Accepts any folder naming that contains 1..6.
    """
    result: Dict[int, Path] = {}
    if not group_root.exists():
        return result
    for child in sorted([p for p in group_root.iterdir() if p.is_dir()]):
        m = ACCOUNT_NUM_RE.search(child.name)
        if not m:
            continue
        try:
            n = int(m.group(1))
        except Exception:
            continue
        if 1 <= n <= 6 and n not in result:
            result[n] = child
    return result

def _ensure_unique_dir(parent: Path, desired_name: str) -> Path:
    """Return a directory path that does not yet exist, by suffixing (2),(3),... if needed."""
    base = desired_name
    cand = parent / base
    i = 2
    while cand.exists():
        cand = parent / f"{base} ({i})"
        i += 1
    return cand

def _copy_tree(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst)

def _copy_tree_with_optional_watermark(src: Path, dst: Path, wm: dict | None):
    """
    wm.enabled 가 True면 이미지 파일들에 워터마크를 적용해서 복사,
    아니면 그냥 copytree.
    """
    if not wm or not wm.get("enabled"):
        _copy_tree(src, dst)
        return

    # 수동으로 걷기
    import os
    for root, dirs, files in os.walk(src):
        rel = Path(root).relative_to(src)
        out_dir = dst / rel
        out_dir.mkdir(parents=True, exist_ok=True)

        # 하위 폴더
        for d in dirs:
            (out_dir / d).mkdir(exist_ok=True)

        # 파일
        for fn in files:
            sp = Path(root) / fn
            dp = out_dir / fn
            try:
                if _is_image_file(sp):
                    with Image.open(sp) as im:
                        out_im = _apply_text_watermark(im, wm)
                        # 포맷 유지 시도
                        fmt = (im.format or "").upper() or None
                        if fmt in {"JPEG","JPG"}:
                            out_im.save(dp, format="JPEG", quality=95)  # 무손실 아님 주의
                        else:
                            out_im.save(dp)
                else:
                    shutil.copy2(sp, dp)
            except Exception:
                # 문제 생기면 원본 그대로 복사
                shutil.copy2(sp, dp)


# --------------------- NEW: collect & normalize posts ---------------------
def _collect_and_normalize_posts(account_dir: Optional[Path]) -> Dict[int, Optional[Path]]:
    """
    계정 폴더의 직속 자식(폴더/파일)을 '이름 사전순'으로 정렬한 뒤,
    앞에서부터 5개를 1..5로 매핑해서 반환합니다.
    - 기존 접두 숫자("N. ") 유무는 전혀 고려하지 않습니다(무시).
    - 5개 미만이면 남는 번호는 None.
    """
    mapping: Dict[int, Optional[Path]] = {i: None for i in range(1, 6)}
    if not account_dir or not account_dir.exists():
        return mapping

    # 폴더/파일 모두 후보로 인정 (직속 1뎁스만)
    children = [p for p in account_dir.iterdir() if p.is_dir() or p.is_file()]

    # 이름(대소문자 무시) 사전순 정렬
    children_sorted = sorted(children, key=lambda p: p.name.casefold())

    # 앞에서부터 5개만 1..5에 매핑
    for i, p in enumerate(children_sorted[:5], start=1):
        mapping[i] = p

    return mapping

def _hex_to_rgba(color_hex: str, opacity_pct: int) -> tuple[int, int, int, int]:
    try:
        color_hex = color_hex.strip()
        if color_hex.startswith("#"):
            color_hex = color_hex[1:]
        if len(color_hex) == 3:  # e.g. FFF
            color_hex = "".join(c*2 for c in color_hex)
        r = int(color_hex[0:2], 16)
        g = int(color_hex[2:4], 16)
        b = int(color_hex[4:6], 16)
    except Exception:
        r, g, b = 255, 255, 255
    a = max(0, min(100, int(opacity_pct)))
    a = int(255 * (a / 100.0))
    return (r, g, b, a)

def _pick_font(font_path: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        if font_path:
            return ImageFont.truetype(font_path, size)
    except Exception:
        pass
    # Windows 기본 한글 폰트 후보 (있으면 사용)
    for win_font in [r"C:\Windows\Fonts\malgun.ttf", r"C:\Windows\Fonts\malgunbd.ttf"]:
        try:
            return ImageFont.truetype(win_font, size)
        except Exception:
            continue
    return ImageFont.load_default()

def _measure_text(text: str, font, stroke_width: int) -> tuple[int, int]:
    dummy = Image.new("RGBA", (10, 10))
    d = ImageDraw.Draw(dummy)
    try:
        bbox = d.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
    except Exception:
        w, h = d.textsize(text, font=font)
    return w, h

def _place_xy(img_w: int, img_h: int, text_w: int, text_h: int,
              preset: str, off_x: int, off_y: int) -> tuple[int, int]:
    preset = (preset or "bottom-right").lower()
    if preset == "top-left":
        x, y = 0 + off_x, 0 + off_y
    elif preset == "top-right":
        x, y = img_w - text_w - off_x, 0 + off_y
    elif preset == "bottom-left":
        x, y = 0 + off_x, img_h - text_h - off_y
    elif preset == "center":
        x, y = (img_w - text_w) // 2 + off_x, (img_h - text_h) // 2 + off_y
    else:  # bottom-right
        x, y = img_w - text_w - off_x, img_h - text_h - off_y
    return x, y

def _watermark_image_inplace(path: Path, cfg: dict, plans: list[str], dry: bool) -> int:
    if path.suffix.lower() not in IMAGE_EXTS:
        return 0
    text = (cfg.get("text") or "").strip()
    if not text:
        return 0

    try:
        im = Image.open(str(path))
        im = ImageOps.exif_transpose(im)
        base_mode = "RGBA" if im.mode != "RGBA" else im.mode
        base = im.convert("RGBA")

        font = _pick_font(cfg.get("font_path", ""), int(cfg.get("font_size", 36)))
        stroke_w = int(cfg.get("outline_width", 2)) if cfg.get("outline", True) else 0
        tw, th = _measure_text(text, font, stroke_w)
        x, y = _place_xy(base.width, base.height, tw, th,
                         cfg.get("position", "bottom-right"),
                         int(cfg.get("offset_x", 16)), int(cfg.get("offset_y", 16)))

        txt_layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(txt_layer)

        fill_rgba = _hex_to_rgba(cfg.get("color", "#FFFFFF"), int(cfg.get("opacity", 50)))
        # 외곽선은 자동 대비색(검/흰)으로
        lum = 0.2126*fill_rgba[0] + 0.7152*fill_rgba[1] + 0.0722*fill_rgba[2]
        stroke_fill = (0, 0, 0, fill_rgba[3]) if lum > 128 else (255, 255, 255, fill_rgba[3])

        if dry:
            plans.append(f"[DRY][WM] {path.name}  <-  '{text}' pos={cfg.get('position')} size={cfg.get('font_size')}")
            return 1

        draw.text((x, y), text, font=font, fill=fill_rgba,
                  stroke_width=stroke_w, stroke_fill=stroke_fill)
        out = Image.alpha_composite(base, txt_layer)

        # 포맷 맞춰 저장
        fmt = (im.format or path.suffix.replace(".", "").upper())
        if fmt.upper() in ("JPG", "JPEG"):
            out = out.convert("RGB")
        out.save(str(path))
        return 1
    except Exception as e:
        plans.append(f"[WM][skip] {path} ({e})")
        return 0

def _watermark_all_images(root: Path, cfg: dict, plans: list[str], dry: bool,
                          step: Callable[[str], None]) -> int:
    count = 0
    if root.is_file():
        count += _watermark_image_inplace(root, cfg, plans, dry)
        if count:
            step("Watermarking")
        return count
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
            count += _watermark_image_inplace(p, cfg, plans, dry)
            if count % 5 == 0:
                step("Watermarking")
    return count

def _parse_size(preset: str) -> tuple[int, int]:
    try:
        w, h = preset.lower().split("x")
        return int(w), int(h)
    except Exception:
        return (1080, 1080)

def _resize_cover(img: Image.Image, tw: int, th: int) -> Image.Image:
    # EXIF 회전을 반영
    img = ImageOps.exif_transpose(img)
    sw, sh = img.size
    if sw == 0 or sh == 0:
        return img

    # 비율 유지 확대: 목표 해상도를 '덮도록' 스케일
    scale = max(tw / sw, th / sh)
    nw, nh = int(round(sw * scale)), int(round(sh * scale))
    resized = img.resize((nw, nh), resample=Image.LANCZOS)

    # 중앙 크롭
    left = max(0, (nw - tw) // 2)
    top = max(0, (nh - th) // 2)
    right = left + tw
    bottom = top + th
    cropped = resized.crop((left, top, right, bottom))
    return cropped

def _resize_image_inplace(path: Path, cfg: dict, plans: list[str], dry: bool) -> int:
    if path.suffix.lower() not in IMAGE_EXTS:
        return 0
    tw, th = _parse_size(cfg.get("preset", "1080x1080"))
    try:
        with Image.open(str(path)) as im:
            if dry:
                plans.append(f"[DRY][RSZ] {path.name} -> {tw}x{th}")
                return 1
            out = _resize_cover(im, tw, th)

            # 저장 포맷 유지
            fmt = (im.format or path.suffix.replace(".", "")).upper()
            if fmt in ("JPG", "JPEG"):
                out = out.convert("RGB")
                out.save(str(path), format="JPEG", quality=95)
            else:
                out.save(str(path))
        return 1
    except Exception as e:
        plans.append(f"[RSZ][skip] {path} ({e})")
        return 0

def _resize_all_images(root: Path, cfg: dict, plans: list[str], dry: bool,
                       step: Callable[[str], None]) -> int:
    cnt = 0
    if root.is_file():
        cnt += _resize_image_inplace(root, cfg, plans, dry)
        if cnt:
            step("Resizing")
        return cnt
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
            cnt += _resize_image_inplace(p, cfg, plans, dry)
            if cnt % 5 == 0:
                step("Resizing")
    return cnt



# -------------------------------------------------------------------------

def _parse_perm_string(s: str) -> List[int]:
    # '3-1-2' -> [3,1,2]
    return [int(x.strip()) for x in s.split("-") if x.strip()]

def _choose_perm(base: List[int], mode: str, manual_str: str, rng: Optional[random.Random]) -> List[int]:
    if mode == "random" and rng is not None:
        perms = [
            [base[0], base[1], base[2]],
            [base[0], base[2], base[1]],
            [base[1], base[0], base[2]],
            [base[1], base[2], base[0]],
            [base[2], base[0], base[1]],
            [base[2], base[1], base[0]],
        ]
        return rng.choice(perms)
    # manual
    return _parse_perm_string(manual_str)

class RearrangeJob:
    @staticmethod
    def meta():
        return {
            "name": "Rearrange Accounts & Posts",
            "description": "Copy from A/B groups into 12 targets with both (유미, 상근) sequences. Allows 6⁴ subgroup permutations.",
            "needs_params": "rearrange"
        }

    def run(self, context: Dict[str, Any],
            progress_cb: Callable[[int, str], None],
            cancel_event: Event):
        params: Dict[str, Any] = context.get("params", {})
        watermark_cfg: dict = params.get("watermark", {}) or {}
        resize_cfg: dict = params.get("resize", {}) or {}

        A_root = Path(params["A_root"])
        B_root = Path(params["B_root"])
        target_root = Path(params["target_root"])
        dry_run = bool(params.get("dry_run", True))

        # NEW: permutation params
        perm_mode = params.get("perm_mode", "manual")  # 'manual' | 'random'
        perm_k = params.get("perm_k", "3-1-2")  # ㄱ : A(1,2,3)
        perm_n = params.get("perm_n", "6-4-5")  # ㄴ : A(4,5,6)
        perm_d = params.get("perm_d", "2-3-1")  # ㄷ : B(1,2,3)
        perm_r = params.get("perm_r", "5-6-4")  # ㄹ : B(4,5,6)
        rand_seed = params.get("rand_seed", "")

        targets_raw: List[Dict[str, str]] = params["targets"]  # 12 dicts: {name, path_optional}
        targets: List[TargetSlot] = []
        for item in targets_raw:
            name = (item.get("name") or "").strip()
            p = (item.get("path") or "").strip()
            path = Path(p) if p else None
            targets.append(TargetSlot(name=name, existing_path=path))

        # Validate
        if cancel_event.is_set(): return
        if len(targets) != 12:
            raise ValueError("Exactly 12 targets required.")
        if not A_root.exists() or not B_root.exists():
            raise ValueError("A_root or B_root does not exist.")
        if not target_root.exists():
            raise ValueError("Target root does not exist.")

        plans: List[str] = []

        rng = None
        if perm_mode == "random":
            plans.append("(info) Manual subgroup selections are ignored in Randomize mode.")
            try:
                seed_val = int(rand_seed) if str(rand_seed).strip() else None
            except Exception:
                seed_val = None
            rng = random.Random(seed_val)

        # Detect accounts
        A_accounts = _find_account_dirs(A_root)  # keys: 1..6
        B_accounts = _find_account_dirs(B_root)

        # Decide permutations for each subgroup
        chosen_perms: Dict[str, List[int]] = {}
        chosen_perms["ㄱ"] = _choose_perm([1,2,3], perm_mode, perm_k, rng)     # A(1,2,3)
        chosen_perms["ㄴ"] = _choose_perm([4,5,6], perm_mode, perm_n, rng)     # A(4,5,6)
        chosen_perms["ㄷ"] = _choose_perm([1,2,3], perm_mode, perm_d, rng)     # B(1,2,3)
        chosen_perms["ㄹ"] = _choose_perm([4,5,6], perm_mode, perm_r, rng)     # B(4,5,6)

        # Build mapping of slot index (1..12) -> source account dir
        slot_to_src: Dict[int, Optional[Path]] = {}

        # ㄱ (A 1..3) -> slots 1..3
        for idx, acct in enumerate(chosen_perms["ㄱ"]):
            slot_to_src[SLOT_RANGES["ㄱ"][idx]] = A_accounts.get(acct)

        # ㄴ (A 4..6) -> slots 4..6
        for idx, acct in enumerate(chosen_perms["ㄴ"]):
            slot_to_src[SLOT_RANGES["ㄴ"][idx]] = A_accounts.get(acct)

        # ㄷ (B 1..3) -> slots 7..9
        for idx, acct in enumerate(chosen_perms["ㄷ"]):
            slot_to_src[SLOT_RANGES["ㄷ"][idx]] = B_accounts.get(acct)

        # ㄹ (B 4..6) -> slots 10..12
        for idx, acct in enumerate(chosen_perms["ㄹ"]):
            slot_to_src[SLOT_RANGES["ㄹ"][idx]] = B_accounts.get(acct)

        # Total ops (rough): (12*5*2) + overhead
        total_ops = 10 + (12 * 5 * 2)
        done = 0
        def step(msg: str):
            nonlocal done
            done += 1
            pct = min(100, int(done * 100 / total_ops))
            progress_cb(pct, msg)

        # ---------- Mapping summary (always log) ----------
        # 드라이런 헤더 (맨 위에 보이게 하고 싶으면 insert(0, ...) 써도 됩니다)
        plans.append(_("==== DRY RUN PLAN (no changes made) ====")) if dry_run else None

        # 모드/시드
        plans.append(
            _("Permutation mode = ") + perm_mode
            + (_(" (seed=") + str(rand_seed) + ")" if perm_mode == "random" else "")
        )

        # 소그룹 순열 헤더
        plans.append(_("==== SUBGROUP PERMUTATIONS (selected/random result) ===="))
        plans.append(f"ㄱ (A1-3): {'-'.join(map(str, chosen_perms['ㄱ']))}  -> slots {SLOT_RANGES['ㄱ']}")
        plans.append(f"ㄴ (A4-6): {'-'.join(map(str, chosen_perms['ㄴ']))}  -> slots {SLOT_RANGES['ㄴ']}")
        plans.append(f"ㄷ (B1-3): {'-'.join(map(str, chosen_perms['ㄷ']))}  -> slots {SLOT_RANGES['ㄷ']}")
        plans.append(f"ㄹ (B4-6): {'-'.join(map(str, chosen_perms['ㄹ']))}  -> slots {SLOT_RANGES['ㄹ']}")

        # 슬롯 매핑 헤더
        plans.append(_("==== SLOT → SOURCE ACCOUNT ===="))
        for slot in range(1, 13):
            src = slot_to_src.get(slot)
            plans.append(f"slot {slot:2d}  <-  {src if src else '(missing)'}")

        # 오늘 요일 기반 day 라벨 만들기
        today_char = _today_kor_daychar()

        if today_char == '월':
            day_label_a = '월'
            day_label_b = '화'
        elif today_char == '금':
            day_label_a = '일'
            day_label_b = '월'
        else :
            day_label_a = _next_of_now(today_char, 1)
            day_label_b = _next_of_now(today_char, 2)

        # day_label_a = f"{today_char}-A"  # 기존 '월' 자리에 사용
        # day_label_b = f"{today_char}-B"  # 기존 '화' 자리에 사용

        label_parent_map = {
            "유미": f"A그룹-{today_char}",
            "상근": f"B그룹-{today_char}",
        }

        plans.append(f"DEST DAY LABELS: {day_label_a} (slots 1–6), {day_label_b} (slots 7–12)")

        def get_dest_parent(slot_idx: int, label: str, day: str) -> Path:
            ts = targets[slot_idx - 1]
            parent_name = label_parent_map[label]

            if ts.existing_path:
                base = ts.existing_path / parent_name / day
            else:
                if not ts.name:
                    raise ValueError(f"Target slot {slot_idx} requires a name or existing path.")
                base = target_root / parent_name / day / ts.name
            return base

        # copy helper (uses NORMALIZED posts)
        def copy_account_posts(src_account_dir: Optional[Path], dest_parent: Path, order: List[int], dry: bool):
            # 1) 소스 계정에서 1..5 매핑(사전순 정렬 기반)
            posts = _collect_and_normalize_posts(src_account_dir)  # 1..5 -> Path|None

            # 2) 목적지 부모 폴더 준비
            if dry:
                final_parent = dest_parent
            else:
                final_parent = _ensure_unique_dir(dest_parent.parent, dest_parent.name)
                final_parent.mkdir(parents=True, exist_ok=True)

                # 최근 결과 폴더 추적(이미 쓰고 계신 로직 그대로 유지)
                context.setdefault("_result_dirs", [])
                fp = str(final_parent)
                if fp not in context["_result_dirs"]:
                    context["_result_dirs"].append(fp)

            # 3) 5개 게시물 순서대로 복사(+워터마크)
            for new_idx, src_num in enumerate(order, start=1):
                src_path = posts.get(src_num)

                # 목적지 폴더명 만들기
                if src_path is not None:
                    base_name = src_path.stem if src_path.is_file() else src_path.name
                    m = POST_NUM_RE.match(base_name)  # "N. " 접두 제거
                    tail = base_name[m.end():] if m else base_name
                    dst_name = f"{new_idx}. {tail.strip()}"
                else:
                    dst_name = f"{new_idx}. (missing)"

                dst_dir = final_parent / dst_name

                if dry:
                    # -------- DRY RUN: 복사 계획 + 워터마크 계획만 로그 --------
                    plans.append(f"[DRY] {src_path if src_path else '(missing)'}  ->  {dst_dir}")

                    if resize_cfg.get("enabled") and src_path and src_path.exists():
                        if src_path.is_file() and src_path.suffix.lower() in IMAGE_EXTS:
                            plans.append(f"[DRY][RSZ] {src_path.name} -> ({dst_dir}) {resize_cfg.get('preset')}")
                        elif src_path.is_dir():
                            cnt_rsz = sum(1 for p in src_path.rglob("*")
                                          if p.is_file() and p.suffix.lower() in IMAGE_EXTS)
                            plans.append(f"[DRY][RSZ] {cnt_rsz} images -> ({dst_dir}) {resize_cfg.get('preset')}")

                    if watermark_cfg.get("enabled") and src_path and src_path.exists():
                        if src_path.is_file() and src_path.suffix.lower() in IMAGE_EXTS:
                            plans.append(f"[DRY][WM] {src_path.name} -> ({dst_dir})")
                        elif src_path.is_dir():
                            cnt = sum(
                                1 for p in src_path.rglob("*")
                                if p.is_file() and p.suffix.lower() in IMAGE_EXTS
                            )
                            plans.append(f"[DRY][WM] {cnt} images -> ({dst_dir})")

                else:
                    unique_dst = _ensure_unique_dir(final_parent, dst_name)

                    if src_path and src_path.exists():
                        if src_path.is_dir():
                            _copy_tree(src_path, unique_dst)
                        else:
                            unique_dst.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(src_path, unique_dst / src_path.name)
                    else:
                        unique_dst.mkdir(parents=True, exist_ok=True)  # placeholder

                    # 1) 리사이즈(자르기) 먼저
                    if resize_cfg.get("enabled"):
                        _resize_all_images(
                            unique_dst,
                            resize_cfg,
                            plans,
                            dry=False,
                            step=lambda _m: step("Resizing"),
                        )

                    # 2) 워터마크는 리사이즈 후 적용 (텍스트 선명도 유지)
                    if watermark_cfg.get("enabled"):
                        _watermark_all_images(
                            unique_dst,
                            watermark_cfg,
                            plans,
                            dry=False,
                            step=lambda _m: step("Watermarking"),
                        )

                step(f"Copying posts to: {final_parent.name}")

        # Iterate labels and days
        for label in ["유미", "상근"]:
            # A세트(기존 '월'): slots 1..6
            day_key = "월"  # 시퀀스 룰은 그대로 사용
            day_order = SEQ[day_key][label]
            for slot in range(1, 7):
                if cancel_event.is_set(): return
                src = slot_to_src.get(slot)
                dest_parent = get_dest_parent(slot, label, day_label_a)  # ✅ 경로는 '오늘요일-A'
                copy_account_posts(src, dest_parent, day_order, dry_run)

            # B세트(기존 '화'): slots 7..12
            day_key = "화"  # 시퀀스 룰은 그대로 사용
            day_order = SEQ[day_key][label]
            for slot in range(7, 13):
                if cancel_event.is_set(): return
                src = slot_to_src.get(slot)
                dest_parent = get_dest_parent(slot, label, day_label_b)  # ✅ 경로는 '오늘요일-B'
                copy_account_posts(src, dest_parent, day_order, dry_run)

        context.setdefault("_ui_logs", []).extend(plans)

        step("Done.")

JOBS = [RearrangeJob]
