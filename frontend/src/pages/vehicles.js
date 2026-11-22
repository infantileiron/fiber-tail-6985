import {empty, formError, pageTitle, vehicleHistory, vehicleStrip} from '../components/common/presentation.js';
import {reportScaffold} from '../components/common/report.js';
import {parameterFields} from '../constants/labels.js';
import {route} from '../router/location.js';
import {state, isAnalyst} from '../stores/workbench.js';
import {esc, number, version} from '../utils/format.js';

function vehicleListPage() {
    const vehicles = state.vehicles;
    const pending = vehicles.filter(vehicle => !vehicle.outcome).length;
    return `${pageTitle('同车合算 / 车辆台账', '同车合算', '把同车的多个供货批按到货吨位折算成一张整车验收单。',
        isAnalyst() ? '<button type="button" class="button primary" id="open-vehicle">＋ 建立合算单</button>' : '')}
        <section class="ledger-intro" aria-label="车辆总览"><div class="ledger-main">
            <span class="eyebrow">在管车辆</span><strong>${vehicles.length} <small>车</small></strong>
            <p>${vehicles.reduce((sum, vehicle) => sum + Number(vehicle.member_count), 0)} 个成员批 · 共
            ${number(vehicles.reduce((sum, vehicle) => sum + Number(vehicle.total_shipment_kg), 0) / 1000, 3)} 吨</p></div>
            <div class="ledger-note"><span class="eyebrow">待发布整车决定</span><strong>${pending} <small>车</small></strong>
            <p>缺样批未补齐时，仅在两个极端建议一致时给出暂定结论。</p></div>
            <div class="ledger-fabric" aria-hidden="true"><i></i><i></i><i></i></div></section>
        <section class="block"><header class="block-head"><div><h2>同车合算单</h2><p>每个成员批在同一时刻只能挂一辆车</p></div>
        <span class="mono">${vehicles.length} 车</span></header>
        ${vehicles.length ? `<div class="table-scroll"><table><thead><tr><th>车号 / 备注</th><th>成员批（齐套/总数）</th>
        <th>整车到货 kg</th><th>状态</th><th><span class="sr-only">操作</span></th></tr></thead><tbody>
        ${vehicles.map(item => `<tr><td><a class="record-code" href="${route('vehicles', item.id)}">${esc(item.code)}</a>
        <small>${esc(item.note ?? '')}</small></td>
        <td><strong>${item.ready_lots} / ${item.member_count} 批齐套</strong><small>${item.member_count - item.ready_lots} 批缺样</small></td>
        <td class="mono">${number(item.total_shipment_kg)}</td>
        <td>${item.outcome ? `<span class="badge tone-${item.outcome}">已${{accept: '接收', retest: '复检', reject: '退货'}[item.outcome]} · ${version(item.published_version)}</span>` : '<span class="badge tone-pending">待验收</span>'}</td>
        <td><a class="text-link" href="${route('vehicles', item.id)}">打开合算 ↗</a></td></tr>`).join('')}
        </tbody></table></div>` : empty('还没有同车合算单', '称重分析岗可选择同车的多个供货批建立合算单。')}</section>
        ${vehicleDialog()}`;
}

function vehicleDialog() {
    if (!isAnalyst()) return '';
    const options = state.lots.map(lot => `<option value="${lot.id}" ${lot.vehicle_id ? 'disabled' : ''}>
        ${esc(lot.code)} · ${esc(lot.supplier)}${lot.vehicle_id ? `（已挂 ${esc(lot.vehicle_code)}）` : ''}</option>`).join('');
    return `<dialog id="vehicle-dialog"><div class="dialog-head"><h2>建立同车合算单</h2>
        <button type="button" class="bare" id="close-vehicle" aria-label="关闭">×</button></div>
        <form id="vehicle-form" class="form-stack"><label>车号<input name="code" maxlength="32"
        pattern="[A-Z0-9][A-Z0-9\\-]+" placeholder="V-1123" required></label>
        <label>备注<input name="note" maxlength="120" placeholder="如 早班车 · 缺样暂定"></label>
        <label>同车成员批（按住 Ctrl 多选，至少两批）<select name="lot_ids" multiple size="6" required>${options}</select>
        <small>已挂在其他车辆上的批号不可重复选择。</small></label>
        ${formError}<button type="submit" class="button primary">建立合算单 ↗</button></form></dialog>`;
}

function memberTable(workspace) {
    const total = workspace.members.reduce((sum, member) => sum + member.shipment_kg, 0);
    return `<section class="block"><header class="block-head"><div><h2>成员批与折算配重</h2>
    <p>配重 = 本批到货吨位 ÷ 整车到货吨位，快照随每次合算冻结</p></div></header>
    <div class="table-scroll"><table><thead><tr><th>供货批号</th><th>到货 kg</th><th>折算配重</th>
    <th>干样</th><th>状态</th>${isAnalyst() ? '<th>复磅</th>' : ''}</tr></thead><tbody>
    ${workspace.members.map(member => {
        const factor = total ? member.shipment_kg / total : 0;
        return `<tr><td><strong class="record-code">${esc(member.code)}</strong><small>${esc(member.material)}</small></td>
        <td class="mono">${number(member.shipment_kg)}</td>
        <td class="mono">${(factor * 100).toFixed(2)}%</td>
        <td><strong>${member.sample_count} 份</strong>${member.sample_count < 3 ? '<small class="cut-note">缺样批</small>' : ''}</td>
        <td>${member.sample_count >= 3 ? '<span class="badge tone-succeeded">齐套</span>' : '<span class="badge tone-queued">等待补样</span>'}</td>
        ${isAnalyst() ? `<td><button type="button" class="text-link reweigh-btn" data-lot="${member.id}"
            data-code="${esc(member.code)}" data-kg="${member.shipment_kg}">同车复磅 ↗</button></td>` : ''}</tr>`;
    }).join('')}</tbody></table></div>
    ${isAnalyst() ? `<dialog class="reweigh-dialog"><div class="dialog-head"><h2>同车复磅</h2>
    <button type="button" class="bare close-reweigh" aria-label="关闭">×</button></div>
    <form id="reweigh-form" class="form-stack"><input type="hidden" name="lot_id">
    <label>供货批号<input name="lot_code" readonly></label>
    <label>复磅后到货重量 / kg<input name="shipment_kg" type="number" min="1" max="100000" required></label>
    <label>复磅理由<input name="reason" minlength="4" maxlength="200" required placeholder="如 原车皮偏重 500kg"></label>
    ${formError}<button class="button primary" type="submit">保存复磅并提示重新合算</button></form></dialog>` : ''}</section>`;
}

function runForm(workspace) {
    if (!isAnalyst()) return '';
    return `<section class="block"><header class="block-head"><div><h2>提交整车合算</h2>
    <p>按当前吨位配重与干样快照生成新版本；重试同一请求不会新增验收单。</p></div></header>
    <form id="vehicle-run-form" class="form-stack inset"><div class="parameter-grid">
    ${parameterFields.map(([key, label, hint, value, min]) => `<label>${label} <span>%</span>
    <input name="${key}" type="number" step="0.01" min="${min}" max="100" value="${value}" required>
    <small>${hint}</small></label>`).join('')}</div>
    <div class="form-foot"><p class="quiet">缺样批将自动按 0% / 100% 两个极端做包络</p>
    <button class="button primary" type="submit">合算并排队 ↗</button></div>${formError}</form></section>`;
}

export function vehiclesPage() {
    const workspace = state.vehicleWorkspace;
    if (!workspace) return vehicleListPage();
    const report = state.report;
    const header = pageTitle('同车合算 / 整车工作区', '整车合算工作区', '折算配重、缺样包络、整车验收单版本与复磅留痕都在这一张单上。',
        report?.result ? '<button class="button secondary" type="button" id="export-run">↓ 导出验收单</button>'
            : `<a class="button secondary" href="${route('vehicles')}">← 返回车辆台账</a>`);
    const strip = vehicleStrip(workspace);
    if (report) {
        return reportScaffold(header, strip, workspace, report, route('vehicles', workspace.vehicle.id));
    }
    return `${header}${strip}
    <div class="work-columns">${memberTable(workspace)}
    <section class="block aside-block"><header class="block-head"><div><h2>合算单版本</h2><p>按提交时间倒序</p></div></header>
    ${vehicleHistory(workspace, null)}</section></div>
    ${runForm(workspace)}`;
}
