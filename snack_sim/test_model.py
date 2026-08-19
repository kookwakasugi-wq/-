"""モデルの整合性チェック: python3 -m unittest snack_sim.test_model"""

import unittest
from dataclasses import replace

from .model import (
    CostAssumptions,
    PriceAssumptions,
    Scenario,
    StaffAssumptions,
    break_even_guests,
    guests_for_revenue,
    simulate,
)


class TestModel(unittest.TestCase):
    def test_base_charge_matches_memo(self):
        # 男女比50:50 なら基本料金の平均は3,000円
        self.assertAlmostEqual(PriceAssumptions().base_charge(), 3_000)

    def test_spend_per_guest_near_3500(self):
        self.assertAlmostEqual(PriceAssumptions().revenue_per_guest(), 3_502.5)

    def test_daily_revenue_matches_memo_ballpark(self):
        # メモ: 1日25人 → 月商約262.5万円
        r = simulate(Scenario(guests_per_day=25))
        self.assertLess(abs(r.revenue - 2_625_000), 5_000)

    def test_pl_adds_up(self):
        r = simulate(Scenario(guests_per_day=30))
        total = r.cogs + r.labor_total + r.rent + r.karaoke + r.other_fixed + r.operating_profit
        self.assertAlmostEqual(total, r.revenue, places=4)

    def test_labor_components_add_up(self):
        r = simulate(Scenario(guests_per_day=30))
        self.assertAlmostEqual(
            r.wage_base + r.incentive_acquisition + r.incentive_staff_drink + r.incentive_bottle,
            r.labor_total,
        )

    def test_fixed_shift_wage_base(self):
        # (5h + 3h) × 2名 × 1,250円 × 30日
        r = simulate(Scenario(guests_per_day=25))
        self.assertEqual(r.wage_base, 8 * 2 * 1_250 * 30)

    def test_variable_shift_is_cheaper_at_low_volume(self):
        fixed = simulate(Scenario(guests_per_day=15))
        var = simulate(Scenario(guests_per_day=15, variable_shift=True))
        self.assertLess(var.labor_total, fixed.labor_total)
        self.assertGreater(var.operating_profit, fixed.operating_profit)

    def test_break_even_profit_is_zero(self):
        sc = Scenario(guests_per_day=25)
        be = break_even_guests(sc)
        self.assertIsNotNone(be)
        self.assertLess(abs(simulate(replace(sc, guests_per_day=be)).operating_profit), 100)

    def test_break_even_between_18_and_19(self):
        self.assertTrue(18 < break_even_guests(Scenario(guests_per_day=25)) < 19)

    def test_guests_for_revenue_roundtrip(self):
        sc = Scenario(guests_per_day=25)
        g = guests_for_revenue(sc, 3_000_000)
        self.assertLess(abs(simulate(replace(sc, guests_per_day=g)).revenue - 3_000_000), 1)

    def test_with_target_spend(self):
        p = PriceAssumptions().with_target_spend(4_000)
        self.assertAlmostEqual(p.revenue_per_guest(), 4_000, places=6)

    def test_labor_ratio_under_50_at_success_line(self):
        # 「成功ライン」25人/日で人件費率50%以内に収まるか
        self.assertLess(simulate(Scenario(guests_per_day=25)).labor_ratio, 0.50)

    def test_higher_bottle_mix_raises_margin(self):
        low = simulate(Scenario(guests_per_day=25, prices=PriceAssumptions(bottles_per_guest=0.05)))
        high = simulate(Scenario(guests_per_day=25, prices=PriceAssumptions(bottles_per_guest=0.30)))
        self.assertGreater(high.profit_ratio, low.profit_ratio)

    def test_more_acquisition_bonus_costs_more(self):
        a = simulate(Scenario(guests_per_day=25, staff=StaffAssumptions(acquisition_bonus=800)))
        b = simulate(Scenario(guests_per_day=25, staff=StaffAssumptions(acquisition_bonus=1_200)))
        self.assertGreater(b.labor_total, a.labor_total)

    def test_monthly_fixed(self):
        self.assertEqual(CostAssumptions().monthly_fixed(), 500_000)


if __name__ == "__main__":
    unittest.main()
