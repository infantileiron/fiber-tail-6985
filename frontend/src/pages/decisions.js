import {empty, lotStrip, pageTitle} from '../components/common/presentation.js';
import {reportScaffold} from '../components/common/report.js';
import {route} from '../router/location.js';
import {state} from '../stores/workbench.js';

export function decisionsPage() {
    const work = state.workspace;
    const report = state.report;
    if (!work) return empty('没有验收单', '至少需要一批来料和已完成的诊断。', '#lots', '返回批号台账');
    const header = pageTitle('来料验收 / 收料决定', '收料决定', '复核截尾明细、对比口径版本，并向仓务移交。',
        report?.result ? '<button class="button secondary" type="button" id="export-run">↓ 导出验收单</button>' : '');
    const strip = lotStrip(work.lot, work.samples);
    return reportScaffold(header, strip, work, report, route('diagnosis', work.lot.id));
}
