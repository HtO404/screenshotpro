# 校验结果（相对路径摘要）

命令（在仓库根执行，`<figure>` 取 `wikipedia` 或 `mdn`）：

```bash
python tools/render.py demo/<figure>/spec.json
python tools/verify.py demo/<figure>/spec.json
```

## wikipedia-tour — 1254x898（原图 1254x707 + 图例 191）

```
[PASS] 1 spec 内每个 target selector 在 dump.controls 中恰好命中 1 条 -- 5 个 selector 全部唯一命中
[PASS] 2 目标 control 的 image_rect 完全落在 shot 尺寸内 -- 5 个目标均在界内
[PASS] 3 render-report 记录的 image_rect 与 dump 逐字段完全相等(无二次换算) -- steps+redactions 全部一致
[PASS] 4 输出 PNG 宽度等于输入宽度(原图区域未缩放) -- 输出 1254x898 / 输入 1254x707
[PASS] 5 徽标两两不重叠(圆心距 >= 2r) -- 最小圆心距 296.01, 需求 30.00 (step 3 / step 4)
[PASS] 6a 徽标与任何 control 的 image_rect 重叠面积/徽标面积 <= 25% -- 0 个徽标压住无关控件
[PASS] 6b report 的 badge.overlap_controls 与实际遮挡一致(不得瞒报) -- 4 个徽标的遮挡记录与实际一致
[PASS] 6c 徽标不落在其它步骤的框内(自己的框不算) -- 4 个徽标均未侵入其它框
[PASS] 7 箭头终点到自己目标框边界距离 <= 1.0px -- 4 个箭头, 最大偏离 0.000px
[PASS] 8 被标注区域像素 std > 8 -- 最低 step 3 std=31.28
[PASS] 10 有 label 时输出高 == shot.h + legend.height 且宽不变; 无 label 时尺寸 == shot -- 输出 1254x898, shot 1254x707, legend.height 191
[PASS] 11 legend.rows 的 n 集合 == 带 label 的 steps 的 n 集合 -- 4 行逐一对齐 [1, 2, 3, 4]
[PASS] 12 每条图例文本非空且绘制宽度 <= 画布宽-2*pad_x -- 4 行文本均在 1206px 内
[PASS] 13 legend.height 容得下所有行(最大行底 <= shot.h + legend.height <= 输出高) -- legend.height 191, 画布 898
[PASS] 9 退出码约定(全过 0 / 任一失败 1) -- exit 0 (0 项失败)

结果: 15/15 断言通过 -> PASS (exit 0)
```

## mdn-tour — 1254x864（原图 1254x707 + 图例 157）

```
[PASS] 1 spec 内每个 target selector 在 dump.controls 中恰好命中 1 条 -- 4 个 selector 全部唯一命中
[PASS] 2 目标 control 的 image_rect 完全落在 shot 尺寸内 -- 4 个目标均在界内
[PASS] 3 render-report 记录的 image_rect 与 dump 逐字段完全相等(无二次换算) -- steps+redactions 全部一致
[PASS] 4 输出 PNG 宽度等于输入宽度(原图区域未缩放) -- 输出 1254x864 / 输入 1254x707
[PASS] 5 徽标两两不重叠(圆心距 >= 2r) -- 最小圆心距 207.42, 需求 30.00 (step 2 / step 3)
[PASS] 6a 徽标与任何 control 的 image_rect 重叠面积/徽标面积 <= 25% -- 0 个徽标压住无关控件
[PASS] 6b report 的 badge.overlap_controls 与实际遮挡一致(不得瞒报) -- 3 个徽标的遮挡记录与实际一致
[PASS] 6c 徽标不落在其它步骤的框内(自己的框不算) -- 3 个徽标均未侵入其它框
[PASS] 7 箭头终点到自己目标框边界距离 <= 1.0px -- 3 个箭头, 最大偏离 0.000px
[PASS] 8 被标注区域像素 std > 8 -- 最低 step 1 std=44.70
[PASS] 10 有 label 时输出高 == shot.h + legend.height 且宽不变; 无 label 时尺寸 == shot -- 输出 1254x864, shot 1254x707, legend.height 157
[PASS] 11 legend.rows 的 n 集合 == 带 label 的 steps 的 n 集合 -- 3 行逐一对齐 [1, 2, 3]
[PASS] 12 每条图例文本非空且绘制宽度 <= 画布宽-2*pad_x -- 3 行文本均在 1206px 内
[PASS] 13 legend.height 容得下所有行(最大行底 <= shot.h + legend.height <= 输出高) -- legend.height 157, 画布 864
[PASS] 9 退出码约定(全过 0 / 任一失败 1) -- exit 0 (0 项失败)

结果: 15/15 断言通过 -> PASS (exit 0)
```

## 可复现性

清空两个 `out/` 目录后从零重跑 render + verify：两次都 exit 0、15/15，且 PNG 字节数不变
（wikipedia-tour.png 586212 B、mdn-tour.png 375311 B）——输出是确定的，可离线重建。

## 已知取舍

徽标按“离目标框最近且不压控件”自动落位，密集文字段落旁的徽标会盖住个别单词
（Wikipedia 正文里的 "system"、MDN 的 "Documenting" 尾字母）。这不是坐标错位：
箭头终点与目标框边界的偏差是 0.000px（见上表第 7 条）。
