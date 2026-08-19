"""スナック事業の収益シミュレーションモデル.

メモ（事業計画メモ）の前提を数式化したもの。
外部ライブラリ不要 / Python 3.9+ を想定。

金額の単位はすべて「円」。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# 前提パラメータ
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PriceAssumptions:
    """料金まわりの前提."""

    male_charge: int = 3_500          # 男性フリードリンク料金
    female_charge: int = 2_500        # 女性フリードリンク料金
    drink_price: int = 350            # ビール/カクテル/ソフトドリンク等
    bottle_price: int = 2_000         # ボトルキープ基本料金

    male_ratio: float = 0.50          # 男性比率（0.0〜1.0）

    # 1人あたりの追加注文
    extra_drinks_per_guest: float = 1.00   # お客様自身の追加ドリンク杯数
    staff_drinks_per_guest: float = 0.15   # スタッフにおごるドリンク杯数
    bottles_per_guest: float = 0.05        # 1人あたりのボトル本数

    def base_charge(self) -> float:
        """男女比を加味した基本料金の平均."""
        return self.male_ratio * self.male_charge + (1 - self.male_ratio) * self.female_charge

    def revenue_per_guest(self) -> float:
        """平均客単価（基本料金＋追加ドリンク＋スタッフドリンク＋ボトル）."""
        return (
            self.base_charge()
            + self.extra_drinks_per_guest * self.drink_price
            + self.staff_drinks_per_guest * self.drink_price
            + self.bottles_per_guest * self.bottle_price
        )

    def with_target_spend(self, target: float) -> "PriceAssumptions":
        """平均客単価を target に合わせて追加ドリンク杯数だけを調整した前提を返す."""
        fixed = (
            self.base_charge()
            + self.staff_drinks_per_guest * self.drink_price
            + self.bottles_per_guest * self.bottle_price
        )
        extra = max(0.0, (target - fixed) / self.drink_price)
        return replace(self, extra_drinks_per_guest=extra)


@dataclass(frozen=True)
class StaffAssumptions:
    """スタッフ給与・インセンティブの前提."""

    hourly_wage: int = 1_250          # 基本時給
    acquisition_bonus: int = 1_000    # スタッフ集客1人あたりのバック
    staff_drink_bonus: int = 100      # スタッフドリンク1杯あたりのバック
    bottle_bonus_rate: float = 0.20   # ボトル売上に対するバック率

    staff_acquired_ratio: float = 0.60  # 全来客のうちスタッフ集客の割合


@dataclass(frozen=True)
class ShiftSlot:
    """時間帯（セット）ごとのシフト設定."""

    name: str
    hours: float                 # 営業時間
    guest_share: float           # その時間帯に来る客数の割合
    staff_fixed: int = 2         # 固定シフトでの人数
    staff_min: int = 1           # 変動シフトでの下限人数
    staff_max: int = 2           # 変動シフトでの上限人数
    guests_per_staff: float = 8.0  # 変動シフトで1名増やす客数の閾値


DEFAULT_SLOTS: List[ShiftSlot] = [
    ShiftSlot(name="1st (19:00-24:00)", hours=5.0, guest_share=0.50),
    ShiftSlot(name="2nd (00:00-03:00)", hours=3.0, guest_share=0.50),
]


@dataclass(frozen=True)
class CostAssumptions:
    """原価・固定費の前提."""

    cogs_rate: float = 0.25       # 原価率（飲み放題込みの平均）
    rent: int = 250_000           # 家賃（10坪 × 25,000円）
    karaoke_lease: int = 50_000   # カラオケリース
    other_fixed: int = 200_000    # その他経費（水光熱・通販・販促・手数料など）
    business_days: int = 30       # 月間営業日数

    def monthly_fixed(self) -> int:
        return self.rent + self.karaoke_lease + self.other_fixed


@dataclass(frozen=True)
class Scenario:
    """1シナリオ分の全前提."""

    guests_per_day: float
    prices: PriceAssumptions = field(default_factory=PriceAssumptions)
    staff: StaffAssumptions = field(default_factory=StaffAssumptions)
    costs: CostAssumptions = field(default_factory=CostAssumptions)
    slots: List[ShiftSlot] = field(default_factory=lambda: list(DEFAULT_SLOTS))
    variable_shift: bool = False   # True なら客数連動シフト、False なら固定シフト
    label: str = ""


# ---------------------------------------------------------------------------
# 計算
# ---------------------------------------------------------------------------


def staff_count_for_slot(slot: ShiftSlot, slot_guests: float, variable: bool) -> int:
    """時間帯ごとのスタッフ人数."""
    if not variable:
        return slot.staff_fixed
    needed = 1
    while needed < slot.staff_max and slot_guests > slot.guests_per_staff * needed:
        needed += 1
    return max(slot.staff_min, needed)


@dataclass
class Result:
    """月次の損益結果."""

    label: str
    guests_per_day: float
    guests_per_month: float
    spend_per_guest: float
    revenue: float

    revenue_charge: float
    revenue_drink: float
    revenue_staff_drink: float
    revenue_bottle: float

    cogs: float
    wage_base: float
    incentive_acquisition: float
    incentive_staff_drink: float
    incentive_bottle: float
    labor_total: float
    rent: float
    karaoke: float
    other_fixed: float
    operating_profit: float

    labor_ratio: float
    cogs_ratio: float
    profit_ratio: float
    flr_ratio: float                    # 原価＋人件費＋家賃 の対売上比

    staff_shift: Dict[str, int]
    slot_guests: Dict[str, float]
    labor_hours_per_day: float
    pay_per_staff_hour: float           # スタッフの実質時給（インセンティブ込み）
    monthly_pay_per_staff: float        # 1名あたり月収の目安


def simulate(sc: Scenario) -> Result:
    days = sc.costs.business_days
    guests_m = sc.guests_per_day * days
    p = sc.prices

    rev_charge = guests_m * p.base_charge()
    rev_drink = guests_m * p.extra_drinks_per_guest * p.drink_price
    rev_staff_drink = guests_m * p.staff_drinks_per_guest * p.drink_price
    rev_bottle = guests_m * p.bottles_per_guest * p.bottle_price
    revenue = rev_charge + rev_drink + rev_staff_drink + rev_bottle

    cogs = revenue * sc.costs.cogs_rate

    # シフト
    shift: Dict[str, int] = {}
    slot_guests: Dict[str, float] = {}
    staff_hours_day = 0.0
    for slot in sc.slots:
        g = sc.guests_per_day * slot.guest_share
        n = staff_count_for_slot(slot, g, sc.variable_shift)
        shift[slot.name] = n
        slot_guests[slot.name] = g
        staff_hours_day += n * slot.hours

    wage_base = staff_hours_day * sc.staff.hourly_wage * days
    inc_acq = guests_m * sc.staff.staff_acquired_ratio * sc.staff.acquisition_bonus
    inc_drink = guests_m * p.staff_drinks_per_guest * sc.staff.staff_drink_bonus
    inc_bottle = rev_bottle * sc.staff.bottle_bonus_rate
    labor = wage_base + inc_acq + inc_drink + inc_bottle

    profit = (
        revenue
        - cogs
        - labor
        - sc.costs.rent
        - sc.costs.karaoke_lease
        - sc.costs.other_fixed
    )

    staff_hours_month = staff_hours_day * days
    # 1名あたり月収 = 総人件費 / （延べ人時 / 1名あたり月間労働時間）
    avg_headcount = staff_hours_month / (8.0 * days) if days else 0.0  # 8h/日 相当の常勤換算

    return Result(
        label=sc.label or f"{sc.guests_per_day:.0f}人/日",
        guests_per_day=sc.guests_per_day,
        guests_per_month=guests_m,
        spend_per_guest=p.revenue_per_guest(),
        revenue=revenue,
        revenue_charge=rev_charge,
        revenue_drink=rev_drink,
        revenue_staff_drink=rev_staff_drink,
        revenue_bottle=rev_bottle,
        cogs=cogs,
        wage_base=wage_base,
        incentive_acquisition=inc_acq,
        incentive_staff_drink=inc_drink,
        incentive_bottle=inc_bottle,
        labor_total=labor,
        rent=sc.costs.rent,
        karaoke=sc.costs.karaoke_lease,
        other_fixed=sc.costs.other_fixed,
        operating_profit=profit,
        labor_ratio=labor / revenue if revenue else 0.0,
        cogs_ratio=cogs / revenue if revenue else 0.0,
        profit_ratio=profit / revenue if revenue else 0.0,
        flr_ratio=(cogs + labor + sc.costs.rent) / revenue if revenue else 0.0,
        staff_shift=shift,
        slot_guests=slot_guests,
        labor_hours_per_day=staff_hours_day,
        pay_per_staff_hour=labor / staff_hours_month if staff_hours_month else 0.0,
        monthly_pay_per_staff=labor / avg_headcount if avg_headcount else 0.0,
    )


def break_even_guests(sc: Scenario, lo: float = 0.0, hi: float = 200.0,
                      tol: float = 1e-4) -> Optional[float]:
    """営業利益が 0 になる 1日客数を二分探索で求める."""

    def profit(n: float) -> float:
        return simulate(replace(sc, guests_per_day=n)).operating_profit

    if profit(hi) < 0:
        return None
    while hi - lo > tol:
        mid = (lo + hi) / 2
        if profit(mid) < 0:
            lo = mid
        else:
            hi = mid
    return hi


def guests_for_revenue(sc: Scenario, target_revenue: float) -> float:
    """目標月商に必要な1日客数."""
    per_guest = sc.prices.revenue_per_guest()
    return target_revenue / per_guest / sc.costs.business_days
