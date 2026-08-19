"""検証シナリオを一括計算して Markdown レポートを出力する.

    python3 -m snack_sim.scenarios            # docs/simulation-report.md を生成
    python3 -m snack_sim.scenarios --stdout   # 標準出力に表示
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path
from typing import List

from .model import (
    DEFAULT_SLOTS,
    CostAssumptions,
    PriceAssumptions,
    Scenario,
    ShiftSlot,
    StaffAssumptions,
    break_even_guests,
    guests_for_revenue,
    simulate,
)

GUEST_LEVELS = [15, 20, 25, 30, 35, 40]
SEATS = 12          # 10坪のカウンター＋小上がりで現実的な席数
TSUBO = 10


def yen(v: float) -> str:
    return f"{round(v):,}"


def pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def h(title: str, level: int = 2) -> str:
    return f"\n{'#' * level} {title}\n"


# ---------------------------------------------------------------------------
# 各検証
# ---------------------------------------------------------------------------


def section_assumptions() -> str:
    p, s, c = PriceAssumptions(), StaffAssumptions(), CostAssumptions()
    out = [h("0. 計算前提", 2)]
    out.append(
        "| 項目 | 値 |\n|---|---|\n"
        f"| 男性 / 女性 料金 | {yen(p.male_charge)}円 / {yen(p.female_charge)}円（男性比率 {pct(p.male_ratio)}） |\n"
        f"| 基本料金の平均 | {yen(p.base_charge())}円 |\n"
        f"| 追加ドリンク | {p.extra_drinks_per_guest:.2f}杯/人 × {p.drink_price}円 |\n"
        f"| スタッフドリンク | {p.staff_drinks_per_guest:.2f}杯/人 × {p.drink_price}円 |\n"
        f"| ボトル | {p.bottles_per_guest:.2f}本/人 × {yen(p.bottle_price)}円 |\n"
        f"| **平均客単価** | **{yen(p.revenue_per_guest())}円** |\n"
        f"| 時給 / 集客バック / ドリンクバック / ボトルバック | {yen(s.hourly_wage)}円 / "
        f"{yen(s.acquisition_bonus)}円 / {yen(s.staff_drink_bonus)}円 / {pct(s.bottle_bonus_rate)} |\n"
        f"| スタッフ集客比率 | {pct(s.staff_acquired_ratio)}（残りはフリー客＝バック無し） |\n"
        f"| 原価率 | {pct(c.cogs_rate)} |\n"
        f"| 固定費 | 家賃 {yen(c.rent)} ＋ カラオケ {yen(c.karaoke_lease)} ＋ その他 {yen(c.other_fixed)} "
        f"＝ {yen(c.monthly_fixed())}円/月 |\n"
        f"| 営業日 | {c.business_days}日/月 |\n"
    )
    out.append(
        "\nメモの「平均客単価3,500円」に合うよう、追加ドリンク1.00杯・スタッフドリンク0.15杯・"
        "ボトル0.05本/人を置いています（合計 3,502.5円）。\n"
    )
    return "".join(out)


def section_pl_by_guests() -> str:
    out = [h("1. 客数別の詳細損益（スタッフ2名固定）")]
    rows = [simulate(Scenario(guests_per_day=g)) for g in GUEST_LEVELS]
    out.append("| 1日客数 | 月商 | 原価25% | 人件費 | 家賃 | カラオケ | その他 | 営業利益 | 人件費率 | 利益率 |\n")
    out.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n")
    for r in rows:
        out.append(
            f"| {r.guests_per_day:.0f}人 | {yen(r.revenue)} | ▲{yen(r.cogs)} | ▲{yen(r.labor_total)} | "
            f"▲{yen(r.rent)} | ▲{yen(r.karaoke)} | ▲{yen(r.other_fixed)} | "
            f"{'▲' if r.operating_profit < 0 else ''}{yen(abs(r.operating_profit))} | "
            f"{pct(r.labor_ratio)} | {pct(r.profit_ratio)} |\n"
        )
    out.append(h("1-2. 売上の内訳", 3))
    out.append("| 1日客数 | 基本料金 | 追加ドリンク | スタッフドリンク | ボトル | 合計 |\n|---:|---:|---:|---:|---:|---:|\n")
    for r in rows:
        out.append(
            f"| {r.guests_per_day:.0f}人 | {yen(r.revenue_charge)} | {yen(r.revenue_drink)} | "
            f"{yen(r.revenue_staff_drink)} | {yen(r.revenue_bottle)} | {yen(r.revenue)} |\n"
        )
    return "".join(out)


def section_staff_pay() -> str:
    out = [h("2. スタッフ給与の実額（時給1,250＋集客1,000＋ドリンク100＋ボトル20%）")]
    out.append(
        "| 1日客数 | 基本給 | 集客バック | ドリンクバック | ボトルバック | 人件費合計 | 実質時給 | 1名あたり月収※ |\n"
        "|---:|---:|---:|---:|---:|---:|---:|---:|\n"
    )
    for g in GUEST_LEVELS:
        r = simulate(Scenario(guests_per_day=g))
        out.append(
            f"| {g}人 | {yen(r.wage_base)} | {yen(r.incentive_acquisition)} | "
            f"{yen(r.incentive_staff_drink)} | {yen(r.incentive_bottle)} | {yen(r.labor_total)} | "
            f"{yen(r.pay_per_staff_hour)}円 | {yen(r.monthly_pay_per_staff)} |\n"
        )
    out.append(
        "\n※ 8時間×30日をフルタイム1名として常勤換算した金額。実際は2名で分け合う想定なので、"
        "「2名で毎日フル勤務した場合の1名分」と読んでください。\n"
        "\n1日25人なら実質時給は約2,200円。時給1,250円のバイトとしては十分に高く、"
        "「売れば稼げる」体感を作れる水準です。\n"
    )
    return "".join(out)


def section_shift_compare() -> str:
    out = [h("3. スタッフ2名固定 vs 売上連動シフト")]
    out.append(
        "変動シフトのルール：各セットの客数が8人以下なら1名、9人以上なら2名。\n\n"
        "| 1日客数 | 1st人数 | 2nd人数 | 人件費(固定) | 人件費(変動) | 差額 | 営業利益(固定) | 営業利益(変動) |\n"
        "|---:|---:|---:|---:|---:|---:|---:|---:|\n"
    )
    for g in GUEST_LEVELS:
        fixed = simulate(Scenario(guests_per_day=g))
        var = simulate(Scenario(guests_per_day=g, variable_shift=True, label="variable"))
        n1, n2 = list(var.staff_shift.values())
        out.append(
            f"| {g}人 | {n1}名 | {n2}名 | {yen(fixed.labor_total)} | {yen(var.labor_total)} | "
            f"{yen(fixed.labor_total - var.labor_total)} | "
            f"{'▲' if fixed.operating_profit < 0 else ''}{yen(abs(fixed.operating_profit))} | "
            f"{'▲' if var.operating_profit < 0 else ''}{yen(abs(var.operating_profit))} |\n"
        )
    out.append(
        "\n効果は低客数帯に集中します。1日15人（各セット7〜8人）なら両セット1名運用が成立し、"
        "人件費が月30万円減って **▲20万円の赤字が+10万円の黒字に反転**します。"
        "一方1日20人以上では両セットとも2名になるので差はゼロ。\n"
        "\nつまり変動シフトは「儲かっている時の節約」ではなく **「立ち上がり期・不調月を生き残るための保険」** です。"
        "この閾値（1名で捌ける客数）を8人と置いていますが、カウンター越し営業＋カラオケなら"
        "実際に何人まで1名で回せるかがそのまま生存ラインを決めます。\n"
    )
    return "".join(out)


def section_gender_mix() -> str:
    out = [h("4. 男女比を変えた場合")]
    out.append("| 男性比率 | 平均客単価 | 月商(25人/日) | 営業利益 | 損益分岐客数 |\n|---:|---:|---:|---:|---:|\n")
    for ratio in [0.3, 0.4, 0.5, 0.6, 0.7]:
        sc = Scenario(guests_per_day=25, prices=PriceAssumptions(male_ratio=ratio))
        r = simulate(sc)
        be = break_even_guests(sc)
        out.append(
            f"| {pct(ratio)} | {yen(r.spend_per_guest)}円 | {yen(r.revenue)} | "
            f"{'▲' if r.operating_profit < 0 else ''}{yen(abs(r.operating_profit))} | "
            f"{be:.1f}人 |\n"
        )
    out.append(
        "\n男性比率が10ポイント動くと客単価は100円動きます。女性中心（男性30%）だと"
        "損益分岐が約1.3人分上がるので、女性2,500円は「集客の投資」と割り切って"
        "追加ドリンク/ボトルで回収する設計が必要です。\n"
    )
    return "".join(out)


def section_spend_levels() -> str:
    out = [h("5. 平均客単価 3,000 / 3,500 / 4,000円の比較")]
    out.append("| 客単価 | 追加ドリンク杯数 | 月商(25人/日) | 営業利益 | 人件費率 | 損益分岐客数 |\n|---:|---:|---:|---:|---:|---:|\n")
    for target in [3_000, 3_500, 4_000]:
        prices = PriceAssumptions().with_target_spend(target)
        sc = Scenario(guests_per_day=25, prices=prices)
        r = simulate(sc)
        out.append(
            f"| {yen(target)}円 | {prices.extra_drinks_per_guest:.2f}杯 | {yen(r.revenue)} | "
            f"{'▲' if r.operating_profit < 0 else ''}{yen(abs(r.operating_profit))} | "
            f"{pct(r.labor_ratio)} | {break_even_guests(sc):.1f}人 |\n"
        )
    out.append(
        "\n客単価3,000円（＝追加注文がほぼ出ない状態）だと損益分岐は21〜22人まで上がります。"
        "エンドレス飲み放題の店では「追加で1杯頼む理由（ビール・カクテル・フード）」が利益の生命線です。\n"
    )
    return "".join(out)


def section_acquisition_bonus() -> str:
    out = [h("6. 集客バック 800 / 1,000 / 1,200円の比較")]
    out.append("| バック額 | 人件費(25人/日) | 人件費率 | 営業利益 | 損益分岐客数 |\n|---:|---:|---:|---:|---:|\n")
    for bonus in [800, 1_000, 1_200]:
        sc = Scenario(guests_per_day=25, staff=StaffAssumptions(acquisition_bonus=bonus))
        r = simulate(sc)
        out.append(
            f"| {yen(bonus)}円 | {yen(r.labor_total)} | {pct(r.labor_ratio)} | "
            f"{'▲' if r.operating_profit < 0 else ''}{yen(abs(r.operating_profit))} | "
            f"{break_even_guests(sc):.1f}人 |\n"
        )
    out.append(h("6-2. スタッフ集客比率を変えた場合（バック1,000円）", 3))
    out.append("| スタッフ集客比率 | 人件費 | 人件費率 | 営業利益(25人/日) |\n|---:|---:|---:|---:|\n")
    for share in [0.3, 0.5, 0.6, 0.8, 1.0]:
        sc = Scenario(guests_per_day=25, staff=StaffAssumptions(staff_acquired_ratio=share))
        r = simulate(sc)
        out.append(
            f"| {pct(share)} | {yen(r.labor_total)} | {pct(r.labor_ratio)} | "
            f"{'▲' if r.operating_profit < 0 else ''}{yen(abs(r.operating_profit))} |\n"
        )
    out.append(
        "\n集客バックは1人200円の差＝25人/日で月15万円の差。**効くのはバック額より「集客比率」**で、"
        "全員がスタッフ集客（100%）になると人件費が月19万円増えます。\n"
        "女性2,500円の客にも1,000円バックすると、その客の粗利（2,500×0.75＝1,875円）から"
        "1,000円が消え、時給分が乗ると赤字客になります。**女性はバック800円、"
        "またはボトル/追加注文が出た客のみ満額**といった条件付けを推奨します。\n"
    )
    return "".join(out)


def section_bottle() -> str:
    out = [h("7. ボトル売上が増えた場合の利益率")]
    out.append("| ボトル本数/人 | 月ボトル売上 | 客単価 | 月商(25人/日) | ボトルバック | 営業利益 | 利益率 |\n|---:|---:|---:|---:|---:|---:|---:|\n")
    for b in [0.05, 0.10, 0.15, 0.20, 0.30]:
        sc = Scenario(guests_per_day=25, prices=PriceAssumptions(bottles_per_guest=b))
        r = simulate(sc)
        out.append(
            f"| {b:.2f}本 | {yen(r.revenue_bottle)} | {yen(r.spend_per_guest)}円 | {yen(r.revenue)} | "
            f"{yen(r.incentive_bottle)} | {yen(r.operating_profit)} | {pct(r.profit_ratio)} |\n"
        )
    out.append(
        "\nボトル2,000円の内訳は 原価25%(500円) ＋ バック20%(400円) ＝ 900円で、"
        "**残る粗利は1,100円/本（55%）**。フリードリンク客1人（3,500円で滞在時間長い）より"
        "効率が良いので、ボトルキープ比率を上げるほど利益率は素直に伸びます。\n"
    )
    return "".join(out)


def section_revenue_targets() -> str:
    out = [h("8. 月商250 / 300 / 350 / 400万円の利益比較")]
    out.append("| 月商 | 必要1日客数 | 原価 | 人件費 | 人件費率 | 固定費 | 営業利益 | 利益率 |\n|---:|---:|---:|---:|---:|---:|---:|---:|\n")
    base = Scenario(guests_per_day=25)
    for target in [2_500_000, 3_000_000, 3_500_000, 4_000_000]:
        g = guests_for_revenue(base, target)
        r = simulate(replace(base, guests_per_day=g))
        out.append(
            f"| {yen(target)} | {g:.1f}人 | ▲{yen(r.cogs)} | ▲{yen(r.labor_total)} | {pct(r.labor_ratio)} | "
            f"▲{yen(r.rent + r.karaoke + r.other_fixed)} | {yen(r.operating_profit)} | {pct(r.profit_ratio)} |\n"
        )
    out.append(
        "\nメモの簡易損益（人件費を売上の50%と置いたもの）と比べると、"
        "**実際のインセンティブ計算では人件費率が40%前後にとどまり、利益はメモの想定より大きく出ます**。\n"
        "月商300万円：メモ25万円 → 本シミュレーション約61万円。差額はほぼ人件費率の差（50% vs 約38%）です。\n"
        "\nなお必要客数もメモ（月商300万＝29人/日）とほぼ一致します。\n"
    )
    return "".join(out)


def section_break_even() -> str:
    base = Scenario(guests_per_day=25)
    be_fixed = break_even_guests(base)
    be_var = break_even_guests(replace(base, variable_shift=True))
    out = [h("9. 損益分岐点となる「1日最低客数」")]
    out.append(
        f"- スタッフ2名固定：**{be_fixed:.1f}人/日**（月商 約{yen(be_fixed * 30 * 3502.5)}円）\n"
        f"- 客数連動シフト：**{be_var:.1f}人/日**（月商 約{yen(be_var * 30 * 3502.5)}円）\n\n"
        "| 条件 | 損益分岐客数(2名固定) |\n|---|---:|\n"
    )
    variants = [
        ("標準", base),
        ("客単価3,000円", replace(base, prices=PriceAssumptions().with_target_spend(3_000))),
        ("客単価4,000円", replace(base, prices=PriceAssumptions().with_target_spend(4_000))),
        ("男性比率30%", replace(base, prices=PriceAssumptions(male_ratio=0.3))),
        ("スタッフ集客100%", replace(base, staff=StaffAssumptions(staff_acquired_ratio=1.0))),
        ("集客バック1,200円", replace(base, staff=StaffAssumptions(acquisition_bonus=1_200))),
        ("原価率30%", replace(base, costs=CostAssumptions(cogs_rate=0.30))),
        ("その他経費30万円", replace(base, costs=CostAssumptions(other_fixed=300_000))),
    ]
    for name, sc in variants:
        be = break_even_guests(sc)
        out.append(f"| {name} | {be:.1f}人 |\n" if be else f"| {name} | 到達不能 |\n")
    out.append(
        "\nメモの「1日20人＝ほぼ損益分岐」は概ね正しく、実際は **2名固定で18.4人、深夜1名運用なら13.4人**が分岐点。"
        "ただし客単価が3,000円に落ちる／原価率が30%に膨らむと21〜23人まで上がります。"
        "**最低ラインは「20人/日を切らない」ではなく「客単価3,500円を守りながら20人」**と考えるべきです。\n"
    )
    return "".join(out)


def section_seats() -> str:
    out = [h("10. 10坪の席数・滞在時間・回転率")]
    out.append(
        f"10坪（約33㎡）のうちバックバー・トイレ・通路を除くと客席に使えるのは約6坪。"
        f"カウンター主体なら **実質{SEATS}席前後**（カウンター8〜9＋小上がり/立ち3〜4）が上限です。\n\n"
        "### セット別の必要回転数\n\n"
        "| 1日客数 | 1st(19-24) | 2nd(0-3) | 1stの回転 | 2ndの回転 |\n|---:|---:|---:|---:|---:|\n"
    )
    for g in GUEST_LEVELS:
        g1 = g * 0.5
        g2 = g * 0.5
        out.append(f"| {g}人 | {g1:.0f}人 | {g2:.0f}人 | {g1 / SEATS:.2f}回転 | {g2 / SEATS:.2f}回転 |\n")
    out.append(
        "\n### 滞在時間別の理論最大客数（12席）\n\n"
        "| 平均滞在 | 1st(5h)最大 | 2nd(3h)最大 | 1日最大 | 席稼働80%時の現実値 |\n|---:|---:|---:|---:|---:|\n"
    )
    for dwell in [1.5, 2.0, 2.5, 3.0, 4.0]:
        m1 = SEATS * (5.0 / dwell)
        m2 = SEATS * (3.0 / dwell)
        out.append(
            f"| {dwell:.1f}時間 | {m1:.0f}人 | {m2:.0f}人 | {m1 + m2:.0f}人 | {(m1 + m2) * 0.8:.0f}人 |\n"
        )
    out.append(
        "\n**席数はボトルネックではありません。** 平均滞在3時間でも1日最大32人（稼働80%で26人）、"
        "2時間なら48人（同38人）が入ります。つまり「成功ライン25人/日」は席的には十分達成可能ですが、"
        "**滞在3時間超が常態化すると30人/日で頭打ち**になり、35人・40人の上位目標は物理的に届きません。\n"
        "\n### 滞在時間と時間あたり売上（1席1時間あたり）\n\n"
        "| 平均滞在 | 客単価3,500円時の席時間単価 |\n|---:|---:|\n"
    )
    for dwell in [1.5, 2.0, 2.5, 3.0, 4.0, 5.0]:
        out.append(f"| {dwell:.1f}時間 | {yen(3_502.5 / dwell)}円 |\n")
    out.append(
        "\nエンドレス飲み放題の最大リスクはここです。滞在2時間なら席時間単価1,751円、"
        "5時間なら700円まで落ちます。**「延長料金なし」を貫くなら、"
        "混雑時のみ2時間制＋延長1,000円などの逃げ道を用意しておくべき**です。\n"
    )
    return "".join(out)


def section_time_slots() -> str:
    out = [h("11. 時間帯別（1st / 2nd）の売上シミュレーション")]
    out.append(
        "1st＝19:00〜24:00（5時間・仕事帰り/女性/常連）、2nd＝0:00〜3:00（3時間・BAR帰り/深夜客）。\n\n"
        "| 客数配分(1st:2nd) | 1st売上/月 | 2nd売上/月 | 2ndシフト | 人件費 | 営業利益(25人/日) |\n|---|---:|---:|---:|---:|---:|\n"
    )
    for s1 in [0.7, 0.6, 0.5, 0.4]:
        slots = [
            replace(DEFAULT_SLOTS[0], guest_share=s1),
            replace(DEFAULT_SLOTS[1], guest_share=1 - s1),
        ]
        sc = Scenario(guests_per_day=25, slots=slots, variable_shift=True)
        r = simulate(sc)
        rev1 = r.revenue * s1
        rev2 = r.revenue * (1 - s1)
        n2 = list(r.staff_shift.values())[1]
        out.append(
            f"| {s1 * 100:.0f} : {(1 - s1) * 100:.0f} | {yen(rev1)} | {yen(rev2)} | {n2}名 | "
            f"{yen(r.labor_total)} | {yen(r.operating_profit)} |\n"
        )
    out.append(
        "\n2ndセットは3時間しかないので、**深夜帯は「人数を増やす」より「1名運用で回せる客数（〜8人）に収める」ほうが利益に効きます**。"
        "深夜が10人を超えるなら2名にして、その分カラオケ・ボトルで単価を取りに行く判断になります。\n"
        "\n2ndセット単体の損益（家賃を営業時間按分：3/8）：\n\n"
        "| 2nd客数/日 | 売上/月 | 原価 | 人件費 | 家賃按分 | 貢献利益 |\n|---:|---:|---:|---:|---:|---:|\n"
    )
    for g2 in [5, 8, 10, 15]:
        rev = g2 * 3_502.5 * 30
        cogs = rev * 0.25
        staff_n = 1 if g2 <= 8 else 2
        wage = staff_n * 3.0 * 1_250 * 30
        inc = g2 * 30 * (0.6 * 1_000 + 0.15 * 100) + g2 * 30 * 0.05 * 2_000 * 0.2
        rent = 300_000 * 3 / 8
        out.append(
            f"| {g2}人 | {yen(rev)} | ▲{yen(cogs)} | ▲{yen(wage + inc)}（{staff_n}名） | ▲{yen(rent)} | "
            f"{'▲' if rev - cogs - wage - inc - rent < 0 else ''}{yen(abs(rev - cogs - wage - inc - rent))} |\n"
        )
    out.append("\n深夜帯は1名運用なら5人/日でも貢献利益がプラス。**2セット制は合理的**です。\n")
    return "".join(out)


def section_labor_check() -> str:
    out = [h("12. この料金体系で人件費50%に収まるか（結論）")]
    out.append("| 1日客数 | 人件費率(2名固定) | 人件費率(変動シフト) |\n|---:|---:|---:|\n")
    for g in GUEST_LEVELS:
        rf = simulate(Scenario(guests_per_day=g))
        rv = simulate(Scenario(guests_per_day=g, variable_shift=True))
        out.append(f"| {g}人 | {pct(rf.labor_ratio)} | {pct(rv.labor_ratio)} |\n")
    out.append(
        "\n**収まります。むしろ余裕があります。**\n\n"
        "現行ルール（時給1,250円＋集客1,000円＋ドリンク100円＋ボトル20%、スタッフ集客60%）では、"
        "2名固定でも人件費率は25人/日で41%、40人/日で32%。客数が増えるほど基本給が薄まって下がります。"
        "**50%を超えるのは2名固定かつ1日18人未満**の低客数帯だけで、その帯は同時に赤字帯でもあるので、"
        "変動シフトで対処すべき領域です（変動シフトなら9人/日から50%以下）。\n\n"
        "逆に言えば、黒字帯では **50%まで原資が余っている**ということです。"
        "差分（25人/日で月約24万円）は次のどれかに使えます：\n\n"
        "1. 集客バックの増額（1,000円→1,500円）または2回目以降の来店にも継続バック\n"
        "2. 月間売上トップへのボーナス\n"
        "3. 時給の底上げ（1,250円→1,400円）で採用力を上げる\n"
        "4. 利益として残す（＝メモの想定より月20〜30万円多い利益）\n\n"
        "### 人件費率が50%に達する条件\n\n"
        "| シナリオ(25人/日) | 人件費率 |\n|---|---:|\n"
    )
    checks = [
        ("標準", Scenario(guests_per_day=25)),
        ("スタッフ集客100%", Scenario(guests_per_day=25, staff=StaffAssumptions(staff_acquired_ratio=1.0))),
        ("集客100%＋バック1,200円", Scenario(guests_per_day=25, staff=StaffAssumptions(staff_acquired_ratio=1.0, acquisition_bonus=1_200))),
        ("集客100%＋時給1,500円", Scenario(guests_per_day=25, staff=StaffAssumptions(staff_acquired_ratio=1.0, hourly_wage=1_500))),
        ("3名体制(1st)", Scenario(guests_per_day=25, slots=[replace(DEFAULT_SLOTS[0], staff_fixed=3), DEFAULT_SLOTS[1]])),
    ]
    for name, sc in checks:
        out.append(f"| {name} | {pct(simulate(sc).labor_ratio)} |\n")
    return "".join(out)


def section_findings() -> str:
    return (
        h("13. まとめ：数字から見えた論点")
        + """
1. **損益分岐は1日18.4人**（2名固定）／**13.4人**（深夜も含めた1名運用）。メモの「20人＝生存ライン」は安全側で妥当。
2. **人件費50%は上限であって着地点ではない**。現行ルールでは25人/日で41%に着地するので、残り9ポイント分（月約24万円）をインセンティブ強化に回すか利益として残すかの判断が必要。
3. **利益はメモの試算より大きい**。月商300万円でメモ25万円 → 本試算約61万円。人件費率の置き方（50% vs 実際38%）の差。
4. **本当のボトルネックは席数ではなく滞在時間**。12席あれば25人/日は余裕だが、平均滞在3時間超だと1日30人で頭打ち。35人・40人の上位目標には「滞在2〜2.5時間」か「席数15」が前提。
5. **女性2,500円＋集客バック1,000円の組み合わせが最も危険**。粗利1,875円に対しバック1,000円で、時給を乗せると赤字客になる。バック額を性別・追加注文で条件分けすべき。
6. **ボトルが最も効率の良い商品**（1本あたり粗利1,100円／55%）。エンドレス飲み放題の滞在リスクを、ボトルキープで相殺する設計が有効。
7. **深夜セットは1名運用なら5人/日でも黒字貢献**。2セット制は合理的だが、深夜2名固定にすると10人/日を超えないと割に合わない。

### 運用ルールとして先に決めておくべきこと

- 集客バックの帰属判定（初回のみ／継続何回まで／同伴した客が複数スタッフと関係する場合）
- ボトルの担当者計上ルール（キープした時のスタッフ／飲んだ時のスタッフ）
- 混雑時の滞在時間ルール（無制限を謳いつつ、満席時の運用をどうするか）
- 女性料金・バック額の条件分け
"""
    )


def build_report() -> str:
    parts = [
        "# スナック事業 収益シミュレーション\n",
        "\n昭和レトロ・エンドレス飲み放題・歌い放題スナック（10坪）の収益モデル検証。\n",
        "すべての数字は `snack_sim/model.py` の計算結果で、`python3 -m snack_sim.scenarios` で再生成できます。\n",
        section_assumptions(),
        section_pl_by_guests(),
        section_staff_pay(),
        section_shift_compare(),
        section_gender_mix(),
        section_spend_levels(),
        section_acquisition_bonus(),
        section_bottle(),
        section_revenue_targets(),
        section_break_even(),
        section_seats(),
        section_time_slots(),
        section_labor_check(),
        section_findings(),
    ]
    return "".join(parts)


def main(argv: List[str]) -> int:
    report = build_report()
    if "--stdout" in argv:
        print(report)
        return 0
    out = Path(__file__).resolve().parent.parent / "docs" / "simulation-report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
