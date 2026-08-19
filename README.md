# スナック事業 収益シミュレーション

昭和レトロ・エンドレス飲み放題・歌い放題スナック（10坪／カラオケあり／2セット営業）の
収益モデルを計算するための小さなツールです。外部ライブラリは不要（Python 3.9+）。

## 使い方

```bash
# レポート再生成（docs/simulation-report.md）
python3 -m snack_sim.scenarios

# 標準出力に表示
python3 -m snack_sim.scenarios --stdout

# テスト
python3 -m unittest snack_sim.test_model
```

## 結果

- **[docs/simulation-report.md](docs/simulation-report.md)** — 全検証結果（客数別損益、スタッフ給与実額、
  シフト比較、男女比・客単価・インセンティブ感応度、席数と滞在時間、時間帯別損益、人件費率の検証）

## 主な結論

| 論点 | 結果 |
|---|---|
| 損益分岐（1日客数） | 2名固定 **18.4人** ／ 客数連動シフト **13.4人** |
| 人件費率（25人/日） | **41.0%** — 「50%」は上限であって着地点ではない |
| 営業利益（月商300万円） | 約 **61万円**（メモの簡易試算25万円より大きい） |
| 席数（10坪） | 実質12席。**ボトルネックは席数ではなく滞在時間** |
| 最大の設計リスク | 女性2,500円 × 集客バック1,000円（粗利1,875円に対しバック1,000円） |

## 単発の試算をする

```python
from snack_sim.model import Scenario, PriceAssumptions, StaffAssumptions, simulate, break_even_guests

sc = Scenario(
    guests_per_day=25,
    prices=PriceAssumptions(male_ratio=0.4, bottles_per_guest=0.15),
    staff=StaffAssumptions(acquisition_bonus=1_200),
    variable_shift=True,
)
r = simulate(sc)
print(r.revenue, r.labor_ratio, r.operating_profit)
print(break_even_guests(sc))
```

主なパラメータ:

- `PriceAssumptions` — 男女料金・男性比率・追加ドリンク杯数・スタッフドリンク・ボトル本数
- `StaffAssumptions` — 時給・集客バック・ドリンクバック・ボトルバック率・スタッフ集客比率
- `CostAssumptions` — 原価率・家賃・カラオケリース・その他経費・営業日数
- `ShiftSlot` — 時間帯ごとの営業時間・客数配分・スタッフ人数
- `variable_shift` — True で客数連動シフト、False で2名固定

## 前提の出どころ

料金・固定費・原価率・客数レンジはすべて事業計画メモの数字をそのまま使っています。
メモに無い値（追加ドリンク杯数、スタッフ集客比率、ボトル本数、席数、滞在時間）は
「平均客単価3,500円」に整合する形で置いたもので、レポート冒頭の前提表に明記しています。
