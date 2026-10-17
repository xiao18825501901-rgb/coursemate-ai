// Content-free UI preview only. The server verifies points, scope and provenance.
export const isPointSetup = setup => setup?.schema_version === 'assessment-setup.points.v1'
    && setup.policy_version === 'cj.assessment.points.v1';
export const secondPurposes = {
    APPLICATION: 'application', CONDITION_CHANGE: 'conditionChange',
    DISCRIMINATION: 'discrimination', ERROR_DIAGNOSIS: 'errorDiagnosis',
};
export const pointConfigurationSlots = slots => slots.map(slot => ({
    slot_id: slot.slot_id, primary_point_id: slot.primary_point_id,
    question_type: slot.question_type, task_form: slot.task_form,
    variation_purpose: slot.variation_purpose, independently_scored_parts: slot.independently_scored_parts,
}));

export function pointMarksBasisPoints(setup, slots) {
    const points = setup?.points || [];
    const refuse = () => { throw new Error('ASSESSMENT_POINT_SELECTION_INVALID'); };
    if (!isPointSetup(setup) || setup.status !== 'READY' || !points.length
        || slots.length > 10000 || new Set(slots.map(s => s.slot_id)).size !== slots.length
        || new Set(points.map(p => p.point_id)).size !== points.length) refuse();
    const groups = new Map(points.map(point => [point.point_id, []]));
    slots.forEach((slot, index) => {
        const point = points.find(p => p.point_id === slot.primary_point_id);
        if (!point || !point.allowed_forms.includes(slot.question_type)
            || slot.independently_scored_parts !== 1 || !slot.slot_id) refuse();
        groups.get(point.point_id).push({ slot, index });
    });
    const marks = Array(slots.length);
    const share = Math.floor(10000 / points.length), remainder = 10000 % points.length;
    points.forEach((point, index) => {
        const items = groups.get(point.point_id);
        if (!items.length || items.length > 2 || items[0].slot.variation_purpose !== null
            || (items.length === 2 && !Object.hasOwn(secondPurposes, items[1].slot.variation_purpose))) refuse();
        const total = share + Number(index < remainder);
        const itemShare = Math.floor(total / items.length);
        if (!itemShare) refuse();
        items.forEach((item, ordinal) => {
            marks[item.index] = itemShare + Number(ordinal < total % items.length);
        });
    });
    return marks;
}

