from __future__ import annotations
import re
import shutil
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Any, List, Optional, Tuple
from threading import Event
from datetime import datetime
try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:
    ZoneInfo = None

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

def _today_kor_daychar(tz_name: str = "Asia/Seoul") -> str:
    """
    오늘의 요일을 한글 한 글자(월~일)로 반환.
    KST(Asia/Seoul) 우선, 실패 시 로컬 시간 사용.
    """
    weekdays = ["월", "화", "수", "목", "금", "토", "일"]  # Monday=0
    try:
        if ZoneInfo:
            idx = datetime.now(ZoneInfo(tz_name)).weekday()
        else:
            idx = datetime.now().weekday()
    except Exception:
        idx = datetime.now().weekday()
    return weekdays[idx]

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

        plans: List[str] = []

        # ---------- Mapping summary (always log) ----------
        plans.append(f"Permutation mode = {perm_mode}" + (f" (seed={rand_seed})" if perm_mode == "random" else ""))
        plans.append("==== SUBGROUP PERMUTATIONS (선택/랜덤 결과) ====")
        plans.append(f"ㄱ (A1-3): {'-'.join(map(str, chosen_perms['ㄱ']))}  -> slots {SLOT_RANGES['ㄱ']}")
        plans.append(f"ㄴ (A4-6): {'-'.join(map(str, chosen_perms['ㄴ']))}  -> slots {SLOT_RANGES['ㄴ']}")
        plans.append(f"ㄷ (B1-3): {'-'.join(map(str, chosen_perms['ㄷ']))}  -> slots {SLOT_RANGES['ㄷ']}")
        plans.append(f"ㄹ (B4-6): {'-'.join(map(str, chosen_perms['ㄹ']))}  -> slots {SLOT_RANGES['ㄹ']}")

        plans.append("==== SLOT → SOURCE ACCOUNT ====")
        for slot in range(1, 13):
            src = slot_to_src.get(slot)
            plans.append(f"slot {slot:2d}  <-  {src if src else '(missing)'}")

        # 오늘 요일 기반 day 라벨 만들기
        today_char = _today_kor_daychar()
        day_label_A = f"{today_char}-A"  # 기존 '월' 자리에 사용
        day_label_B = f"{today_char}-B"  # 기존 '화' 자리에 사용

        plans.append(f"DEST DAY LABELS: {day_label_A} (slots 1–6), {day_label_B} (slots 7–12)")

        def get_dest_parent(slot_idx: int, label: str, day: str) -> Path:
            ts = targets[slot_idx - 1]
            if ts.existing_path:
                # 기존 폴더 선택 시: 그대로 사용, 그 아래 라벨/요일만 붙임 (번호 X)
                base = ts.existing_path / label / day
            else:
                if not ts.name:
                    raise ValueError(f"Target slot {slot_idx} requires a name or existing path.")
                # ✅ 새 폴더 생성 시: "슬롯번호. 이름" 형식으로 만듦
                numbered_name = f"{slot_idx}. {ts.name.strip()}"
                base = target_root / label / day / numbered_name
            return base

        # copy helper (uses NORMALIZED posts)
        def copy_account_posts(src_account_dir: Optional[Path], dest_parent: Path, order: List[int], dry: bool):
            posts = _collect_and_normalize_posts(src_account_dir)  # 1..5 -> Path|None

            # Prepare dest parent
            if dry:
                final_parent = dest_parent
            else:
                final_parent = _ensure_unique_dir(dest_parent.parent, dest_parent.name)
                final_parent.mkdir(parents=True, exist_ok=True)

                context.setdefault("_result_dirs", [])
                fp = str(final_parent)
                if fp not in context["_result_dirs"]:
                    context["_result_dirs"].append(fp)

            # For each of 1..5 mapped via 'order'
            for new_idx, src_num in enumerate(order, start=1):
                src_path = posts.get(src_num)

                # Build destination folder name
                if src_path is not None:
                    # 파일이면 확장자 제거(stem), 폴더면 폴더명 그대로 사용
                    base_name = src_path.stem if src_path.is_file() else src_path.name
                    # 앞의 "N. " 패턴 제거
                    m = POST_NUM_RE.match(base_name)
                    tail = base_name[m.end():] if m else base_name
                    dst_name = f"{new_idx}. {tail.strip()}"
                else:
                    dst_name = f"{new_idx}. (missing)"

                dst_dir = final_parent / dst_name
                if dry:
                    plans.append(f"[DRY] {src_path if src_path else '(missing)'}  ->  {dst_dir}")
                else:
                    unique_dst = _ensure_unique_dir(final_parent, dst_name)
                    if src_path and src_path.exists():
                        if src_path.is_dir():
                            _copy_tree(src_path, unique_dst)  # 폴더 게시물: 통째 복사
                        else:
                            unique_dst.mkdir(parents=True, exist_ok=True)  # 파일 게시물: 폴더 만들고
                            shutil.copy2(src_path, unique_dst / src_path.name)
                    else:
                        unique_dst.mkdir(parents=True, exist_ok=True)  # placeholder

                step(f"Copying posts to: {final_parent.name}")

        # Iterate labels and days
        for label in ["유미", "상근"]:
            # A세트(기존 '월'): slots 1..6
            day_key = "월"  # 시퀀스 룰은 그대로 사용
            day_order = SEQ[day_key][label]
            for slot in range(1, 7):
                if cancel_event.is_set(): return
                src = slot_to_src.get(slot)
                dest_parent = get_dest_parent(slot, label, day_label_A)  # ✅ 경로는 '오늘요일-A'
                copy_account_posts(src, dest_parent, day_order, dry_run)

            # B세트(기존 '화'): slots 7..12
            day_key = "화"  # 시퀀스 룰은 그대로 사용
            day_order = SEQ[day_key][label]
            for slot in range(7, 13):
                if cancel_event.is_set(): return
                src = slot_to_src.get(slot)
                dest_parent = get_dest_parent(slot, label, day_label_B)  # ✅ 경로는 '오늘요일-B'
                copy_account_posts(src, dest_parent, day_order, dry_run)

        # Emit logs
        if dry_run:
            plans.insert(0, "==== DRY RUN PLAN (no changes made) ====")
        context.setdefault("_ui_logs", []).extend(plans)

        step("Done.")

JOBS = [RearrangeJob]
