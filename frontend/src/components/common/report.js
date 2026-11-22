import {distribution} from './chart.js';
import {badge, empty, formError, history, vehicleHistory} from './presentation.js';
import {actions, envelopeLabel, outcomeLabel, parameterFields} from '../../constants/labels.js';
import {route} from '../../router/location.js';
import {isObserver, isReviewer, state} from '../../stores/workbench.js';
import {esc, number, pct, signed, stamp, version} from '../../utils/format.js';

export function comparisonBlock(report) {
    const delta = report.result.comparison;
    if (!delta?.previous_version || !delta.previous_parameters) return '';
    const sameKey = report.vehicle_id ? 'same_snapshot' : 'same_samples';
    const sameLabel = report.vehicle_id
        ? (delta.same_snapshot ? '合算快照相同' : '合算快照有变（含样本或复磅配重影响）')
        : (delta.same_samples ? '干样快照相同' : '干样快照有变，差额含样本影响');
    const changes = parameterFields.filter(([key]) => Number(delta.previous_parameters[key]) !== Number(report.parameters[key]))
        .map(([key, label]) => `${label} ${pct(delta.previous_parameters[key])} → ${pct(report.parameters[key])}`);
    return `<div class="comparison"><b>对比 ${version(delta.previous_version)}</b>
        <p>${sameLabel}${changes.length ? ` · ${changes.join('，')}` : ' · 参数相同'}</p>
        <span>超标份额 <strong>${signed(delta.exceed_delta_pp)}</strong> · 尾部均值 <strong>${signed(delta.tail_delta_pp)}</strong></span></div>`;
}

export function decisionBlock(workspace, report) {
    if (report.outcome) return `<section class="decision-panel"><div><p class="eyebrow">已发布收料决定</p>
        <h2>${outcomeLabel[report.outcome]}</h2><p>${esc(report.rationale)}</p></div>
        <p class="quiet">${esc(report.reviewer)} · ${stamp(report.published_at)}</p></section>`;
    if (!isReviewer()) return '<section class="decision-panel"><div><p class="eyebrow">收料决定</p><h2>等待复核</h2><p>收料复核岗可根据尾部数据填写理由并发布决定。</p></div></section>';
    if (workspace.inspections[0]?.id !== report.id) return '<section class="decision-panel"><p>该版本可追溯，请切换到最新版本进行复核。</p></section>';
    const suggested = report.result.provisional_recommendation ?? report.result.recommendation;
    return `<section class="decision-panel"><div><p class="eyebrow">收料复核</p><h2>发布验收决定</h2><p>根据现场处理情况选择决定，并保留交接理由。</p></div>
        <form id="decision-form" class="form-stack"><label>收料决定<select name="outcome" required>
        ${Object.entries(outcomeLabel).map(([value, label]) => `<option value="${value}" ${value === suggested ? 'selected' : ''}>${label}</option>`).join('')}
        </select></label><label>复核理由<textarea name="rationale" minlength="4" maxlength="400" rows="3" required></textarea></label>
        ${formError}<button class="button primary" type="submit">发布收料决定</button></form></section>`;
}

export function envelopeBlock(report) {
    const result = report.result;
    if (!result?.provisional || !result.envelope) return '';
    return `<section class="block envelope-block"><header class="block-head"><div><h2>缺样极端包络</h2>
    <p>缺样批 ${number(result.unknown_shipment_kg)} kg 的干样未到，分别按最干净与最脏补齐</p></div>
    <span class="badge tone-provisional">暂定结论</span></header>
    <div class="table-scroll"><table><thead><tr><th>补齐假设</th><th>超标份额</th><th>尾部均值</th><th>建议</th></tr></thead><tbody>
    ${['cleanest', 'dirtiest'].map(key => `<tr><td class="record-code">${envelopeLabel[key]}</td>
        <td class="mono">${pct(result.envelope[key].exceed_share_pct)}</td>
        <td class="mono">${pct(result.envelope[key].tail_mean_pct)}</td>
        <td><span class="badge tone-${result.envelope[key].recommendation}">${outcomeLabel[result.envelope[key].recommendation]}</span></td></tr>`).join('')}
    </tbody></table></div>
    <p class="inset quiet">两种极端建议一致，暂定结论为 <strong>${outcomeLabel[result.provisional_recommendation]}</strong>；
    缺样批补齐后须重新合算，正式结论以新版本为准。</p></section>`;
}

export function reportBody(workspace, report) {
    const {result, parameters} = report;
    const isVehicle = report.vehicle_id !== null;
    const scopeName = isVehicle ? esc(report.vehicle_code) : esc(report.lot_code);
    const memberNote = isVehicle
        ? `<p>${result.sample_count} 份齐套干样 · 折算后有效权重 ${number(result.effective_weight_kg, 4)} kg · 全样加权均值 ${pct(result.weighted_mean_pct)}</p>`
        : `<p>${result.sample_count} 份快照 · ${number(result.total_dry_g)} g · 全样加权均值 ${pct(result.weighted_mean_pct)}</p>`;
    return `<section class="report-summary" id="report-summary" data-run="${report.id}">
        <div class="report-title"><span class="eyebrow">${scopeName} · ${version(report.version)}${result.provisional ? ' · 暂定' : ''}</span>
        <h2>重量加权尾部诊断</h2>${memberNote}</div>
        <div class="report-metric"><span>超标重量份额</span><strong id="exceed-value">${pct(result.exceed_share_pct)}</strong>
        <small>${number(result.exceed_g, 4)} 严格高于 ${pct(parameters.threshold_pct)} · 份额上限 ${pct(parameters.exceed_cap_pct)}</small></div>
        <div class="report-metric"><span>尾部平均杂质率</span><strong id="tail-value">${pct(result.tail_mean_pct)}</strong>
        <small>最高 ${pct(parameters.tail_pct)} 权重 · 上限 ${pct(parameters.tail_cap_pct)}</small></div>
        <div class="report-outcome"><span>${report.outcome ? '发布结论' : '规则建议'}</span>${badge(report.outcome ?? result.recommendation)}</div></section>
        ${comparisonBlock(report)}
        ${envelopeBlock(report)}
        <div class="work-columns report-columns"><section class="block"><header class="block-head"><div><h2>加权经验分布</h2><p>每一级阶梯由同一杂质率的有效重量叠加</p></div></header>
        <div class="inset chart-wrap">${distribution(result.ecdf, Number(parameters.threshold_pct))}</div></section>
        <section class="block"><header class="block-head"><div><h2>尾部截取明细</h2><p>从高杂质样向下取满 ${number(result.tail_g, 4)} 权重</p></div></header>
        <div class="table-scroll"><table id="tail-table"><thead><tr><th>样号</th>${isVehicle ? '<th>来源批</th>' : ''}<th>杂质率</th><th>取入 / 原重</th></tr></thead><tbody>
        ${result.tail_contributions.map(row => `<tr><td class="record-code">${esc(row.code)}</td>
        ${isVehicle ? `<td>${esc(row.lot_code ?? '缺样未知')}</td>` : ''}
        <td>${pct(row.concentration_pct)}</td>
        <td class="mono">${number(row.used_g, 4)} / ${number(row.dry_g, 4)}${row.used_g < row.dry_g ? '<small class="cut-note">边界截取</small>' : ''}</td></tr>`).join('')}
        </tbody></table></div>
        <p class="inset quiet">${result.triggers.length ? `触发规则：${result.triggers.map(trigger => trigger === 'tail_mean' ? '尾部均值超限' : '超标重量份额超限').join('、')}` : '两项指标均在参数上限内。'}</p></section></div>
        ${decisionBlock(workspace, report)}
        <div class="work-columns trace-columns"><section class="block"><header class="block-head"><div><h2>验收单版本</h2>
        <p>当前快照校验值 <code title="${esc(report.checksum)}">${esc(report.checksum.slice(0, 12))}</code></p></div></header>
        ${isVehicle ? vehicleHistory(workspace, report.id) : history('decisions', workspace, report.id)}</section>
        ${isObserver() ? '' : `<section class="block"><header class="block-head"><h2>交接记录</h2></header><ol class="audit-trail">
        ${state.audit.slice(0, 6).map(event => `<li><time>${stamp(event.occurred_at)}</time><b>${actions[event.action] ?? event.action}</b>
        <span>${esc(event.reference)} · ${esc(event.actor ?? '后台计算')}</span></li>`).join('')}</ol></section>`}</div>`;
}

export function reportScaffold(header, strip, workspace, report, fallbackLink) {
    if (!report?.result) {
        const isVehicle = report?.vehicle_id != null || workspace.vehicle !== undefined;
        return `${header}${strip}<div class="work-columns">${empty('当前版本暂无诊断结果', esc(report?.error ?? '验收单将在计算完成后出现。'),
            fallbackLink, '返回诊断')}<section class="block"><header class="block-head"><h2>验收单版本</h2></header>
        ${isVehicle ? vehicleHistory(workspace, report?.id) : history('decisions', workspace, report?.id)}</section></div>`;
    }
    return `${header}${strip}${reportBody(workspace, report)}`;
}
