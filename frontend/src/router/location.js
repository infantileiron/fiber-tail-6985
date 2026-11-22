export const sections = [
    ['lots', '批号台账'], ['samples', '称重记录'], ['vehicles', '同车合算'],
    ['diagnosis', '尾部诊断'], ['decisions', '收料决定'],
];

// 整车合算单的路由用 vehicles/<id>/<run>，与单批 #samples/<lot> 区分。
export function locationView() {
    const [segment, id, run] = window.location.hash.slice(1).split('/');
    const page = sections.some(([key]) => key === segment) ? segment : 'lots';
    return {
        page,
        lotId: page === 'vehicles' ? null : Number(id) || null,
        vehicleId: page === 'vehicles' ? Number(id) || null : null,
        runId: Number(run) || null,
    };
}

export function route(page, id, run) {
    return `#${[page, id, run].filter(Boolean).join('/')}`;
}
