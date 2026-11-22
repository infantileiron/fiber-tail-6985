from fractions import Fraction
from itertools import groupby

from src.constants.domain import (
    ALGORITHM_VERSION,
    CLEANEST_RATIO,
    DIRTIEST_RATIO,
    MIN_SAMPLES,
    Outcome,
)


class InsufficientSamples(ValueError):
    pass


class InconclusiveProvisional(ValueError):
    """缺样补成两个极端后建议仍不一致，暂定结论不成立。"""


def percent(value):
    return float(value * 100)


def number(value):
    """整数权重保持整数输出，折算产生的分数权重才显示为小数。"""
    return int(value) if value.denominator == 1 else float(value)


def _ratio(sample):
    if "ratio" in sample:
        value = sample["ratio"]
        return value if isinstance(value, Fraction) else Fraction(str(value))
    return Fraction(sample["impurity_g"], sample["dry_g"])


def _weight(sample):
    if "effective_g" in sample:
        value = sample["effective_g"]
        return value if isinstance(value, Fraction) else Fraction(str(value))
    return Fraction(sample["dry_g"])


def _recommendation(exceed_share, tail_mean, exceed_cap, tail_cap):
    triggers = []
    if exceed_share > exceed_cap:
        triggers.append("exceed_share")
    if tail_mean > tail_cap:
        triggers.append("tail_mean")
    return triggers, Outcome.REJECT if triggers else Outcome.ACCEPT


def _tail_integral(pairs_desc, tail_g, leading_block=None):
    """按杂质率从高到低累计到 tail_g；leading_block 是已知排在最前的整块缺样。"""
    remaining = tail_g
    integrated = Fraction(0)
    contributions = []
    if leading_block is not None:
        block_mass, block_ratio, block_code = leading_block
        used = min(remaining, block_mass)
        integrated += used * block_ratio
        remaining -= used
        contributions.append({
            "code": block_code, "concentration_pct": percent(block_ratio),
            "dry_g": number(block_mass), "used_g": number(used),
            "impurity_equivalent_g": number(used * block_ratio), "provisional_block": True,
        })
    for ratio, code, weight, lot_code in pairs_desc:
        if remaining == 0:
            break
        used = min(remaining, weight)
        integrated += used * ratio
        remaining -= used
        entry = {
            "code": code, "concentration_pct": percent(ratio), "dry_g": number(weight),
            "used_g": number(used), "impurity_equivalent_g": number(used * ratio),
        }
        if lot_code:
            entry["lot_code"] = lot_code
        contributions.append(entry)
    return integrated, contributions


def weighted_tail(samples, parameters):
    """以每份样的有效重量为权重的 ECDF、超标份额与截尾积分（全程有理数）。"""
    threshold = Fraction(parameters["threshold_pct"]) / 100
    tail_share = Fraction(parameters["tail_pct"]) / 100
    exceed_cap = Fraction(parameters["exceed_cap_pct"]) / 100
    tail_cap = Fraction(parameters["tail_cap_pct"]) / 100
    pairs = sorted((_ratio(sample), sample["code"], _weight(sample), sample.get("lot_code")) for sample in samples)
    total_g = sum(weight for _, _, weight, _ in pairs)
    impurity_g = sum(ratio * weight for ratio, _, weight, _ in pairs)
    exceed_g = sum(weight for ratio, _, weight, _ in pairs if ratio > threshold)

    cumulative_g = Fraction(0)
    ecdf = []
    for ratio, group in groupby(pairs, key=lambda item: item[0]):
        entries = list(group)
        group_g = sum(weight for _, _, weight, _ in entries)
        cumulative_g += group_g
        point = {
            "concentration_pct": percent(ratio), "group_g": number(group_g),
            "cumulative_g": number(cumulative_g), "cumulative_pct": percent(Fraction(cumulative_g, total_g)),
            "sample_codes": [code for _, code, _, _ in entries],
        }
        lot_codes = sorted({lot_code for _, _, _, lot_code in entries if lot_code})
        if lot_codes:
            point["lot_codes"] = lot_codes
        ecdf.append(point)

    tail_g = total_g * tail_share
    pairs_desc = sorted(pairs, key=lambda item: (-item[0], item[1]))
    integrated, contributions = _tail_integral(pairs_desc, tail_g)
    exceed_share = Fraction(exceed_g, total_g)
    tail_mean = integrated / tail_g
    triggers, recommendation = _recommendation(exceed_share, tail_mean, exceed_cap, tail_cap)

    return {
        "algorithm": ALGORITHM_VERSION,
        "total_weight": number(total_g), "impurity_equivalent_g": number(impurity_g),
        "weighted_mean_pct": percent(Fraction(impurity_g, total_g)),
        "exceed_g": number(exceed_g), "exceed_share_pct": percent(exceed_share),
        "tail_g": float(tail_g), "tail_mean_pct": percent(tail_mean),
        "ecdf": ecdf, "tail_contributions": contributions,
        "triggers": triggers, "recommendation": recommendation,
    }


def analyze(samples, parameters):
    """单批诊断：单位干样克数作为权重，保持原有验收单字段口径。"""
    if len(samples) < MIN_SAMPLES:
        raise InsufficientSamples(f"有效干样至少需要 {MIN_SAMPLES} 份，本次仅锁定 {len(samples)} 份。")
    result = weighted_tail(samples, parameters)
    result["sample_count"] = len(samples)
    result["total_dry_g"] = result.pop("total_weight")
    result["impurity_g"] = result.pop("impurity_equivalent_g")
    return result


def _envelope_scenario(pairs, unknown_mass, unknown_ratio, unknown_label, parameters):
    threshold = Fraction(parameters["threshold_pct"]) / 100
    tail_share = Fraction(parameters["tail_pct"]) / 100
    exceed_cap = Fraction(parameters["exceed_cap_pct"]) / 100
    tail_cap = Fraction(parameters["tail_cap_pct"]) / 100
    measured_total = sum(weight for _, _, weight, _ in pairs)
    measured_impurity = sum(ratio * weight for ratio, _, weight, _ in pairs)
    total_g = measured_total + unknown_mass
    exceed_g = sum(weight for ratio, _, weight, _ in pairs if ratio > threshold)
    if unknown_ratio > threshold:
        exceed_g += unknown_mass
    tail_g = total_g * tail_share
    pairs_desc = sorted(pairs, key=lambda item: (-item[0], item[1]))
    leading = (unknown_mass, unknown_ratio, unknown_label) if unknown_ratio >= max(ratio for ratio, _, _, _ in pairs_desc) else None
    integrated, _ = _tail_integral(pairs_desc, tail_g, leading)
    exceed_share = Fraction(exceed_g, total_g)
    tail_mean = integrated / tail_g
    triggers, recommendation = _recommendation(exceed_share, tail_mean, exceed_cap, tail_cap)
    return {
        "assumption": "dirtiest" if unknown_ratio == DIRTIEST_RATIO else "cleanest",
        "unknown_concentration_pct": percent(unknown_ratio),
        "total_weight": number(total_g),
        "weighted_mean_pct": percent(Fraction(measured_impurity + unknown_ratio * unknown_mass, total_g)),
        "exceed_g": number(exceed_g), "exceed_share_pct": percent(exceed_share),
        "tail_g": float(tail_g), "tail_mean_pct": percent(tail_mean),
        "triggers": triggers, "recommendation": recommendation,
    }


def analyze_vehicle(snapshot, parameters):
    """整车合算：每批总权重等于其到货吨位，批内按各干样克重比例分配，缺样批用极端做包络。"""
    measured = []
    measured_count = 0
    unknown_mass = Fraction(0)
    incomplete = []
    for member in snapshot["lots"]:
        if member["complete"]:
            lot_dry_total = sum(sample["dry_g"] for sample in member["samples"])
            # 批内归一化后乘以本批吨位：该批所有样的有效权重之和恰为 shipment_kg，单位与缺样吨位一致。
            for sample in member["samples"]:
                measured_count += 1
                measured.append({
                    "code": f"{member['lot_code']}/{sample['code']}",
                    "lot_code": member["lot_code"],
                    "ratio": Fraction(sample["impurity_g"], sample["dry_g"]),
                    "effective_g": Fraction(sample["dry_g"]) * Fraction(member["shipment_kg"], lot_dry_total),
                })
        else:
            incomplete.append(member)
            unknown_mass += Fraction(member["shipment_kg"])
    if measured_count < MIN_SAMPLES:
        raise InsufficientSamples(
            f"齐套批有效干样至少需要 {MIN_SAMPLES} 份，当前仅锁定 {measured_count} 份，整车诊断保留失败记录。"
        )

    result = weighted_tail(measured, parameters)
    result["scope"] = "vehicle"
    result["sample_count"] = measured_count
    # 有效权重以到货吨位为单位：齐套批的有效权重之和等于其到货吨位合计。
    result["effective_weight_kg"] = result.pop("total_weight")
    result["effective_impurity_kg"] = result.pop("impurity_equivalent_g")
    result["provisional"] = bool(incomplete)
    result["incomplete_lots"] = [
        {"lot_code": member["lot_code"], "shipment_kg": member["shipment_kg"], "sample_count": member["sample_count"]}
        for member in incomplete
    ]
    if not incomplete:
        return result

    pairs = sorted((_ratio(sample), sample["code"], _weight(sample), sample.get("lot_code")) for sample in measured)
    unknown_label = "缺样批未知干样"
    worst = _envelope_scenario(pairs, unknown_mass, Fraction(DIRTIEST_RATIO), unknown_label, parameters)
    best = _envelope_scenario(pairs, unknown_mass, Fraction(CLEANEST_RATIO), unknown_label, parameters)
    result["unknown_shipment_kg"] = number(unknown_mass)
    result["envelope"] = {"cleanest": best, "dirtiest": worst}
    if best["recommendation"] != worst["recommendation"]:
        raise InconclusiveProvisional(
            "缺样批补成最干净（杂质率 0%）与最脏（杂质率 100%）时收料建议不一致，"
            "暂定结论不成立，请补齐缺样批干样后重新合算。"
        )
    result["provisional_recommendation"] = best["recommendation"]
    return result
