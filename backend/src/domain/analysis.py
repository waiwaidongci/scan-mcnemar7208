"""校验配对票据并运行双侧精确 McNemar 验收。"""

from collections import Counter
from decimal import Decimal, localcontext
from fractions import Fraction

from .groups import build_groups, display_order
from .spec import SPEC


def validate_rows(rows):
    if not isinstance(rows, list) or not rows:
        raise ValueError("票据配对明细至少需要一条记录。")

    documents = []
    seen = set()
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise ValueError(f"第 {index} 条票据配对格式有误。")
        document = {}
        for field in SPEC["fields"]:
            key, label, kind = field["key"], field["label"], field["type"]
            value = row.get(key)
            if kind == "bool":
                if not isinstance(value, bool):
                    raise ValueError(f"第 {index} 条的{label}须提供布尔判定。")
            else:
                if not isinstance(value, str) or not value.strip() or len(value.strip()) > 300:
                    raise ValueError(f"第 {index} 条的{label}格式有误。")
                value = value.strip()
                if kind == "select" and value not in field["options"]:
                    raise ValueError(f"第 {index} 条的{label}超出选项范围。")
            document[key] = value
        document_id = document["document_id"]
        if document_id in seen:
            raise ValueError(f"票据编号重复：{document_id}。")
        seen.add(document_id)
        documents.append(document)
    return documents


def _run_parameters(params):
    fields = SPEC["params"]
    if not isinstance(params, dict) or set(params) - {field["key"] for field in fields}:
        raise ValueError("验收参数格式有误或包含未知字段。")

    options = {}
    for field in fields:
        key = field["key"]
        value = params.get(key, field["default"])
        if (type(value) not in (int, float) or not field["min"] <= value <= field["max"]
                or (field["type"] == "int" and type(value) is not int)):
            raise ValueError(f'{field["label"]}须为 {field["min"]} 至 {field["max"]} 之间的有效数值。')
        options[key] = value
    return options


def _exact_p_value(a_only, b_only):
    discordant = a_only + b_only
    if abs(a_only - b_only) <= 1:
        return Fraction(1)

    # Sum the shorter binomial tail with integer coefficients before converting for display.
    coefficient = tail = 1
    for count in range(1, min(a_only, b_only) + 1):
        coefficient = coefficient * (discordant - count + 1) // count
        tail += coefficient
    return Fraction(2 * tail, 1 << discordant)


def _display_p_value(value):
    with localcontext() as context:
        context.prec = 12
        return str(Decimal(value.numerator) / Decimal(value.denominator))


def _table(title, columns, rows):
    return {
        "title": title,
        "columns": [{"key": key, "label": label} for key, label in columns],
        "rows": rows,
    }


def analyze(rows, normalized_params, links=None, link_version=None):
    documents = validate_rows(rows)
    options = _run_parameters(normalized_params)
    groups = build_groups(documents, links)
    counted = [group for group in groups if group['consistent']]
    pending = [group for group in groups if not group['consistent']]
    if not counted:
        raise ValueError('同票组全部判定分歧待核，没有可计入的有效配对。')
    counts = Counter((group['a_pass'], group['b_pass']) for group in counted)
    both_pass = counts[True, True]
    a_only = counts[True, False]
    b_only = counts[False, True]
    both_fail = counts[False, False]
    pair_count = len(counted)
    scan_count = len(documents)
    merged = scan_count - len(groups)
    a_pass = both_pass + a_only
    b_pass = both_pass + b_only
    gain_pp = Fraction(100 * (b_only - a_only), pair_count)
    p_value = _exact_p_value(a_only, b_only)
    p_text = _display_p_value(p_value)
    gain_text = f"{float(gain_pp):+.4f}".rstrip("0").rstrip(".")
    alpha = str(options["alpha"])
    min_gain = str(options["min_gain_pp"])
    gates = [
        ("有效配对数", pair_count, f"≥ {options['min_pairs']} 对", pair_count >= options["min_pairs"]),
        ("双侧精确 p 值", p_text, f"≤ {alpha}", p_value <= Fraction(alpha)),
        ("候选 B 净增", f"{gain_text} 个百分点", f"≥ {min_gain} 个百分点且为正",
         gain_pp > 0 and gain_pp >= Fraction(min_gain)),
    ]
    failed_gates = [label for label, _, _, passed in gates if not passed]

    disagreements = []
    discordant = [group for group in counted if group['a_pass'] != group['b_pass']]
    for group in sorted(discordant, key=lambda item: (item['b_pass'], item['members'][0])):
        improved = group['b_pass']
        rows_in_group = group['rows']
        disagreements.append({
            "document_id": "、".join(group['members']),
            "batch_id": "、".join(dict.fromkeys(row["batch_id"] for row in rows_in_group)),
            "document_type": "、".join(dict.fromkeys(row["document_type"] for row in rows_in_group)),
            "outcome": "仅 B 通过" if improved else "仅 A 通过",
            "next_step": "抽核 B 的通过判定" if improved else "优先核对 B 的未通过字段",
        })

    if failed_gates:
        headline = f"暂缓切换。{'、'.join(failed_gates)}未达验收门槛。"
    else:
        headline = "达到统计验收门槛，提交差异复核。"
    note = f"同批票据有效配对 {pair_count} 对。现用 A 通过 {a_pass} 对，候选 B 通过 {b_pass} 对。"
    if merged:
        note += f"同票关系把 {scan_count} 件扫描件归并为 {len(groups)} 组。"
    if pending:
        note += f"{len(pending)} 组同票扫描判定分歧，整组待核未计入有效配对。"
    if not disagreements:
        note += "本批两引擎逐单判定一致，差异对为 0，p 值记为 1。"

    metrics = [
        {"label": "有效配对数", "value": pair_count, "detail": f"差异对 {a_only + b_only} 对"},
        {"label": "同票分组", "value": f"{len(groups)} 组",
         "detail": f"{scan_count} 件扫描件" + (f"，合并重复 {merged} 件" if merged else "，无同票关系")},
        {"label": "待核同票组", "value": len(pending),
         "detail": "判定分歧整组未计入" if pending else "无判定分歧组"},
    ]
    if link_version is not None:
        metrics.append({"label": "同票关系版本", "value": f"v{link_version}",
                        "detail": "发起时固定，重试与导出同版"})
    metrics += [
        {"label": "现用 A 通过率", "value": f"{a_pass / pair_count:.2%}", "detail": f"{a_pass}/{pair_count} 对"},
        {"label": "候选 B 通过率", "value": f"{b_pass / pair_count:.2%}", "detail": f"{b_pass}/{pair_count} 对"},
        {"label": "候选 B 净增（百分点）", "value": gain_text, "detail": f"仅 B 通过 {b_only} 对，减仅 A 通过 {a_only} 对"},
        {"label": "双侧精确 p 值", "value": p_text, "detail": f"显著性水平 α = {alpha}"},
    ]

    group_rows = [{
        "group_key": f"G{index}",
        "members": "、".join(group["members"]),
        "size": group["size"],
        "counted": "计入 1 对" if group["consistent"] else "待核未计入",
        "reason": group["reason"],
    } for index, group in enumerate(display_order(groups), 1)]

    return {
        "state": "warning" if failed_gates else "ok",
        "headline": headline,
        "note": note,
        "metrics": metrics,
        "tables": [
            _table("配对四格表", (("a", "现用 A"), ("b_pass", "候选 B 通过"), ("b_fail", "候选 B 未通过")), [
                {"a": "通过", "b_pass": both_pass, "b_fail": a_only},
                {"a": "未通过", "b_pass": b_only, "b_fail": both_fail},
            ]),
            _table("验收门槛", (("gate", "验收项"), ("observed", "观测值"), ("limit", "门槛"), ("status", "判断")), [
                {"gate": label, "observed": observed, "limit": limit, "status": "达标" if passed else "未达标"}
                for label, observed, limit, passed in gates
            ]),
            _table("差异票据复核清单", (
                ("document_id", "票据编号"), ("batch_id", "扫描批次"), ("document_type", "票据类型"),
                ("outcome", "配对判定"), ("next_step", "复核动作"),
            ), disagreements),
            _table("同票分组明细", (
                ("group_key", "分组"), ("members", "成员扫描件"), ("size", "件数"),
                ("counted", "是否计入"), ("reason", "原因"),
            ), group_rows),
        ],
        "charts": [{
            "title": "四类配对判定",
            "kind": "bar",
            "series": [
                {"label": label, "value": count}
                for label, count in (("均通过", both_pass), ("仅 A 通过", a_only),
                                     ("仅 B 通过", b_only), ("均未通过", both_fail))
            ],
        }],
        "sections": [
            {"title": "精确检验与门槛", "text": (
                f"仅 A 通过 {a_only} 对，仅 B 通过 {b_only} 对。双侧检验只用这 {a_only + b_only} 个差异对。"
                "门槛判断使用舍入前的精确数值。未达到显著性门槛表示当前证据不足以确认差异。"
            )},
            {"title": "同票分组口径", "text": (
                f"本批 {scan_count} 件扫描件按发起时固定的同票关系归并为 {len(groups)} 组："
                f"{pair_count} 组判定一致计入有效配对，{len(pending)} 组判定分歧整组待核。"
                "登记与撤销只产生新版本，本结果仍按发起时的版本计算，新版发布后不能换回。"
            )},
            {"title": "复核与交付", "text": (
                "先核对仅 A 通过的票据，再抽核仅 B 通过的票据。按票据编号回看影像与人工底单，"
                "补录复核决定后导出配对四格表、门槛判断和差异清单。"
            )},
        ],
    }
