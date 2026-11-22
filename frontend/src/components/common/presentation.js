import {outcomeLabel, runLabel, vehicleRunLabel} from '../../constants/labels.js';
import {route} from '../../router/location.js';
import {esc, number, version} from '../../utils/format.js';

export const formError = '<p class="form-error" role="alert"></p>';
export const mark = '<span class="brand-mark" aria-hidden="true"><i></i><i></i><i></i></span>';

export function pageTitle(kicker, title, description, side = '') {
    return `<header class="page-heading"><div><p class="eyebrow">${kicker}</p><h1>${title}</h1><p class="page-summary">${description}</p></div>${side}</header>`;
}

export function lotStrip(lot, samples) {
    return `<aside class="lot-strip"><div><span class="eyebrow">供货批号</span><strong>${esc(lot.code)}</strong></div>
        <div><span class="eyebrow">来料</span><b>${esc(lot.material)}</b><small>${esc(lot.supplier)}</small></div>
        <div><span class="eyebrow">到货重量</span><b>${number(lot.shipment_kg)} kg</b>${lot.vehicle_code ? `<small>已挂车辆 ${esc(lot.vehicle_code)}</small>` : ''}</div>
        <div><span class="eyebrow">现有干样</span><b>${samples.length} 份</b></div></aside>`;
}

export function vehicleStrip(workspace) {
    const {vehicle, members} = workspace;
    const total = members.reduce((sum, member) => sum + member.shipment_kg, 0);
    const ready = members.filter(member => member.sample_count >= 3).length;
    return `<aside class="lot-strip vehicle-strip"><div><span class="eyebrow">同车合算单</span><strong>${esc(vehicle.code)}</strong>
        ${vehicle.note ? `<small>${esc(vehicle.note)}</small>` : ''}</div>
        <div><span class="eyebrow">成员批次</span><b>${members.length} 批 · 齐套 ${ready} 批</b><small>缺样批按极端包络处理</small></div>
        <div><span class="eyebrow">整车到货</span><b>${number(total)} kg</b><small>配重按各批吨位折算</small></div>
        <div><span class="eyebrow">干样合计</span><b>${members.reduce((sum, member) => sum + Number(member.sample_count), 0)} 份</b></div></aside>`;
}

export function provisionalTag(run) {
    return run.provisional ? '<span class="badge tone-provisional">暂定</span>' : '';
}

export function empty(title, explanation, link = '', label = '') {
    return `<section class="empty"><h2>${title}</h2><p>${explanation}</p>${link ? `<a class="button secondary" href="${link}">${label}</a>` : ''}</section>`;
}

export function history(page, workspace, selected) {
    const runs = workspace.inspections;
    if (!runs.length) return '<p class="quiet inset">当前批号没有可查看的验收单。</p>';
    return `<ol class="run-history">${runs.map(run => `<li><a href="${route(page, workspace.lot.id, run.id)}"
        ${selected === run.id ? 'aria-current="true"' : ''}><strong>${version(run.version)}</strong>
        <span>${esc(run.parameters.threshold_pct)}% 超标线 · 尾部 ${esc(run.parameters.tail_pct)}%</span>
        ${badge(run.outcome, run.status)}</a></li>`).join('')}</ol>`;
}

export function vehicleHistory(workspace, selected) {
    const runs = workspace.inspections;
    if (!runs.length) return '<p class="quiet inset">这辆车还没有合算单，提交后在此留痕。</p>';
    return `<ol class="run-history">${runs.map(run => `<li><a href="${route('vehicles', workspace.vehicle.id, run.id)}"
        ${selected === run.id ? 'aria-current="true"' : ''}><strong>${version(run.version)}</strong>
        <span>${esc(run.parameters.threshold_pct)}% 超标线 · 尾部 ${esc(run.parameters.tail_pct)}%
        ${run.provisional ? ' · 暂定' : ''}</span>
        ${badge(run.outcome, run.status, true)}</a></li>`).join('')}</ol>`;
}

export function badge(outcome, status, vehicle = false) {
    if (outcome) return `<span class="badge tone-${outcome}">${outcomeLabel[outcome]}</span>`;
    if (status) return `<span class="badge tone-${status}">${(vehicle ? vehicleRunLabel : runLabel)[status]}</span>`;
    return '<span class="badge tone-pending">待验收</span>';
}
